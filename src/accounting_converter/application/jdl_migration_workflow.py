from __future__ import annotations

import csv
import hashlib
import io
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from accounting_converter.adapters.input.jdl import (
    JdlMigrationParser,
    jdl_source_account_key,
)
from accounting_converter.adapters.output.jdl import JdlTargetContext
from accounting_converter.application.conversion import ConversionResult, ConversionStatus
from accounting_converter.application.first_release_workflow import (
    FirstReleaseReadiness,
    FirstReleaseSummary,
)
from accounting_converter.application.jdl_migration import JdlMigrationPreflight
from accounting_converter.application.jdl_migration_review import (
    jdl_description_replacement_key,
)
from accounting_converter.application.jdl_migration_tax_evidence import (
    canonical_flag_normalization_evidence,
)
from accounting_converter.application.output_validation import OutputValidationResult
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.journal import JournalEntry, Side
from accounting_converter.domain.mapping import (
    MappingKey,
    MappingStatus,
    MappingType,
    SubaccountPolicy,
)
from accounting_converter.domain.validation import Severity, ValidationResult
from accounting_converter.infrastructure.local_diagnostic_log import log_local_exception
from accounting_converter.profiles.jdl_official import (
    jdl_ibex_cashbook_official_journal_import_spec,
)
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_migration_input_schema_definition,
    jdl_ibex_cashbook_official_journal_import_schema_definition,
)


@dataclass(frozen=True)
class JdlMigrationPreparedConversion:
    summary: FirstReleaseSummary
    input_path: Path | None = None
    output_path: Path | None = None
    profile: ConversionProfile | None = None
    context: JdlTargetContext | None = None
    entries: tuple[JournalEntry, ...] = ()
    source_sha256: str | None = None
    expected_rows: tuple[tuple[str, ...], ...] = ()
    normalization_evidence_ids: tuple[str, ...] = ()


class JdlMigrationFormalWorkflow:
    """Fail-closed JDL-to-JDL writer over preserved source physical rows."""

    def prepare(
        self,
        *,
        input_path: Path | None,
        output_path: Path | None,
        profile: ConversionProfile | None,
        context: JdlTargetContext | None,
        company_status,
        verified_tax_keys: frozenset[str],
    ) -> JdlMigrationPreparedConversion:
        reasons: list[str] = []
        if input_path is None:
            reasons.append("JDL仕訳CSVを選択してください。")
        if output_path is None:
            reasons.append("出力先を選択してください。")
        elif output_path.exists():
            reasons.append("出力先は既に存在するため生成できません。")
        if input_path is not None and output_path is not None and (
            input_path.resolve(strict=False) == output_path.resolve(strict=False)
        ):
            reasons.append("入力ファイルと出力先に同じパスは指定できません。")
        if profile is None or context is None:
            reasons.append("現在の会社設定を確認してください。")
        if reasons:
            return self._blocked(input_path, output_path, profile, context, reasons)
        assert input_path and output_path and profile and context

        source_identity = jdl_ibex_cashbook_migration_input_schema_definition().identity
        target_identity = jdl_ibex_cashbook_official_journal_import_schema_definition().identity
        if profile.verify_format_identity(source_identity, target_identity).value != "MATCH":
            return self._blocked(
                input_path, output_path, profile, context,
                ["選択した変換設定の形式が一致しません。"],
            )
        try:
            source_raw = input_path.read_bytes()
            source_sha256 = hashlib.sha256(source_raw).hexdigest()
            parsed = JdlMigrationParser().parse_path(input_path)
            entries = parsed.entries
        except Exception:
            return self._blocked(
                input_path, output_path, profile, context,
                ["JDL仕訳データを安全に解析できませんでした。"],
            )
        preflight = JdlMigrationPreflight().evaluate(
            entries,
            profile,
            context,
            company_status=company_status,
            verified_tax_keys=verified_tax_keys,
            source_sha256=source_sha256,
        )
        if not preflight.output_allowed:
            return self._blocked(
                input_path, output_path, profile, context,
                list(dict.fromkeys(item.message for item in preflight.validation_results)),
                entries,
            )
        try:
            rows, evidence_ids = self._mapped_rows(
                entries, profile, context, source_sha256
            )
            self._validate_expected_rows(entries, rows)
        except ValueError as exc:
            return self._blocked(
                input_path, output_path, profile, context, [str(exc)], entries
            )
        return JdlMigrationPreparedConversion(
            summary=self._summary(
                input_path, output_path, profile, context, (), entries
            ),
            input_path=input_path,
            output_path=output_path,
            profile=profile,
            context=context,
            entries=entries,
            source_sha256=source_sha256,
            expected_rows=rows,
            normalization_evidence_ids=evidence_ids,
        )

    def execute(self, prepared: JdlMigrationPreparedConversion) -> ConversionResult | None:
        if prepared.summary.readiness is not FirstReleaseReadiness.READY:
            return None
        assert prepared.input_path and prepared.output_path and prepared.source_sha256
        completed_at = datetime.now(timezone.utc)
        if hashlib.sha256(prepared.input_path.read_bytes()).hexdigest() != prepared.source_sha256:
            return self._failure(prepared, "JDL-MIGRATION-SOURCE-CHANGED", "入力ファイルが変更されています。", completed_at)
        if prepared.output_path.exists():
            return self._failure(prepared, "OUTPUT-PATH-EXISTS", "出力先は既に存在します。", completed_at, ConversionStatus.OUTPUT_PATH_ALREADY_EXISTS)

        raw = self._serialize(prepared.expected_rows)
        prepared.output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{prepared.output_path.name}.", suffix=".tmp",
                dir=prepared.output_path.parent, delete=False,
            ) as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = Path(handle.name)
            validation = self._validate_output(temp_path, prepared)
            if not validation.success:
                return self._result(
                    prepared, ConversionStatus.OUTPUT_VALIDATION_FAILED,
                    validation.validation_results, validation, None, completed_at,
                )
            try:
                os.link(temp_path, prepared.output_path)
            except FileExistsError:
                return self._failure(prepared, "OUTPUT-PATH-EXISTS", "出力先は既に存在します。", completed_at, ConversionStatus.OUTPUT_PATH_ALREADY_EXISTS)
            return self._result(
                prepared, ConversionStatus.SUCCESS, (), validation,
                prepared.output_path, completed_at,
            )
        except OSError as exc:
            log_local_exception("jdl_migration_formal_output", exc)
            return self._failure(
                prepared,
                "JDL-MIGRATION-OUTPUT-WRITE",
                "JDL用CSVを安全に保存できませんでした。保存先を確認してください。",
                completed_at,
                ConversionStatus.SYSTEM_ERROR,
            )
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def _mapped_rows(self, entries, profile, context, source_sha256):
        rows: list[tuple[str, ...]] = []
        evidence_ids: list[str] = []
        accounts_by_value = {item.mapping_value: item for item in context.account_master}
        for entry in entries:
            physical_rows = tuple(entry.metadata.get("physical_rows", ()))
            source_flags = tuple(entry.metadata.get("identifier_flags", ()))
            output_flags = source_flags
            normalization = canonical_flag_normalization_evidence(entry, ("1111",))
            if source_flags == ("1000",) and normalization is not None:
                output_flags = normalization.canonical_flag_sequence
                evidence_ids.append(normalization.evidence_id)
            for row_index, (row_meta, output_flag) in enumerate(
                zip(physical_rows, output_flags, strict=True), 1
            ):
                columns = list(row_meta["source_columns"])
                columns[0] = output_flag
                for side, base, line_key in (
                    (Side.DEBIT, 3, "debit_line_index"),
                    (Side.CREDIT, 13, "credit_line_index"),
                ):
                    line_index = row_meta.get(line_key)
                    if line_index is None:
                        continue
                    line = entry.lines[int(line_index)]
                    source_code = str(line.metadata.get("jdl_source_account_code", ""))
                    source_name = str(
                        line.metadata.get("jdl_source_account_formal_name", "")
                        or line.metadata.get("jdl_source_account_name", "")
                    )
                    exact = next((item for item in context.account_master if item.target_master_code == source_code and item.target_formal_name == source_name), None)
                    if exact is None:
                        mapping = profile.account_mappings.get(line.account or "")
                        if mapping is None or mapping.status is not MappingStatus.USER_CONFIRMED or not mapping.target_value:
                            raise ValueError("未確認の科目対応があるため出力できません。")
                        exact = accounts_by_value.get(mapping.target_value)
                    if exact is None:
                        raise ValueError("確認済み科目が現在のJDL科目一覧にありません。")
                    columns[base:base + 3] = [
                        exact.target_master_code, exact.target_name,
                        exact.target_formal_name,
                    ]
                    if line.sub_account:
                        key = MappingKey(MappingType.SUBACCOUNT, line.sub_account, line.account)
                        sub = profile.subaccount_context_mappings.get(key)
                        if sub is None or sub.status is not MappingStatus.USER_CONFIRMED:
                            raise ValueError("未確認の補助科目対応があるため出力できません。")
                        policy = sub.metadata.get("subaccount_policy")
                        if policy == SubaccountPolicy.PARENT_ONLY_CONFIRMED.value:
                            columns[base + 3:base + 5] = ["", ""]
                        elif policy == SubaccountPolicy.PRESERVE_SUBACCOUNT.value:
                            columns[base + 3:base + 5] = [
                                sub.metadata.get("output_code", sub.metadata.get("target_code", "")),
                                sub.metadata.get("output_name", sub.target_value or ""),
                            ]
                        else:
                            raise ValueError("補助科目の保持方法が確認されていません。")
                    if line.tax_info is not None and line.tax_info.category:
                        tax = profile.tax_mappings.get(line.tax_info.category)
                        if tax is None or tax.status is not MappingStatus.USER_CONFIRMED or tax.target_value != line.tax_info.category:
                            raise ValueError("税区分の確認内容が現在の入力と一致しません。")
                description = columns[23]
                if len(description) > 32:
                    replacement = profile.loss_policy_mappings.get(
                        jdl_description_replacement_key(entry.id, row_index)
                    )
                    if (
                        replacement is None
                        or replacement.status is not MappingStatus.USER_CONFIRMED
                        or replacement.metadata.get("source_sha256") != source_sha256
                        or replacement.metadata.get("original_description_sha256")
                        != hashlib.sha256(description.encode("utf-8")).hexdigest()
                        or not replacement.target_value
                    ):
                        raise ValueError("摘要のHuman確認済み置換が一致しません。")
                    columns[23] = replacement.target_value
                rows.append(tuple(columns))
        return tuple(rows), tuple(dict.fromkeys(evidence_ids))

    @staticmethod
    def _serialize(rows: tuple[tuple[str, ...], ...]) -> bytes:
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\r\n")
        writer.writerow(jdl_ibex_cashbook_official_journal_import_spec().column_names)
        writer.writerows(rows)
        return stream.getvalue().encode("cp932", errors="strict")

    @staticmethod
    def _validate_expected_rows(entries, rows) -> None:
        if len(rows) != sum(len(entry.metadata.get("physical_rows", ())) for entry in entries):
            raise ValueError("出力予定行数が入力と一致しません。")
        if any(len(row) != 30 for row in rows):
            raise ValueError("出力予定行がJDL公式30列ではありません。")
        for row in rows:
            row[23].encode("cp932", errors="strict")

    def _validate_output(self, path, prepared):
        errors: list[ValidationResult] = []
        raw = path.read_bytes()
        if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
            errors.append(self._error("JDL-MIGRATION-OUTPUT-BOM", "BOMを検出しました。"))
        remainder = raw.replace(b"\r\n", b"")
        if b"\n" in remainder or b"\r" in remainder:
            errors.append(self._error("JDL-MIGRATION-OUTPUT-LINE-END", "CRLF以外の改行を検出しました。"))
        try:
            text = raw.decode("cp932", errors="strict")
            parsed_csv = tuple(tuple(row) for row in csv.reader(io.StringIO(text, newline=""), strict=True))
            reparsed = JdlMigrationParser().parse_path(path)
        except Exception:
            return OutputValidationResult.failed((self._error("JDL-MIGRATION-OUTPUT-REPARSE", "生成CSVをstrict再解析できません。"),))
        actual_rows = parsed_csv[1:]
        if not parsed_csv or parsed_csv[0] != jdl_ibex_cashbook_official_journal_import_spec().column_names:
            errors.append(self._error("JDL-MIGRATION-OUTPUT-HEADER", "JDL公式30列headerと一致しません。"))
        if actual_rows != prepared.expected_rows:
            errors.append(self._error("JDL-MIGRATION-OUTPUT-ROWS", "生成後の行内容が変換計画と一致しません。"))
        if len(reparsed.entries) != len(prepared.entries):
            errors.append(self._error("JDL-MIGRATION-OUTPUT-JOURNALS", "生成後の仕訳数が入力と一致しません。"))
        if reparsed.journal_record_count != len(prepared.expected_rows):
            errors.append(self._error("JDL-MIGRATION-OUTPUT-RECORDS", "生成後の物理行数が入力と一致しません。"))
        debit = sum((entry.debit_total() for entry in reparsed.entries), Decimal("0"))
        credit = sum((entry.credit_total() for entry in reparsed.entries), Decimal("0"))
        expected_debit = sum((entry.debit_total() for entry in prepared.entries), Decimal("0"))
        expected_credit = sum((entry.credit_total() for entry in prepared.entries), Decimal("0"))
        if debit != credit or debit != expected_debit or credit != expected_credit:
            errors.append(self._error("JDL-MIGRATION-OUTPUT-BALANCE", "生成後の貸借合計が入力と一致しません。"))
        return OutputValidationResult(
            success=not errors,
            record_count=len(actual_rows), journal_count=len(reparsed.entries),
            debit_total=debit, credit_total=credit,
            validation_results=tuple(errors),
            evidence_profiles=prepared.normalization_evidence_ids,
            output_schema_identity=jdl_ibex_cashbook_official_journal_import_schema_definition().identity.stable_key,
        )

    @staticmethod
    def _error(rule_id, message):
        return ValidationResult(Severity.ERROR, rule_id, message)

    def _failure(self, prepared, rule_id, message, completed_at, status=ConversionStatus.OUTPUT_VALIDATION_FAILED):
        return self._result(prepared, status, (self._error(rule_id, message),), None, None, completed_at)

    @staticmethod
    def _result(prepared, status, validations, output_validation, output_path, completed_at):
        debit = sum((entry.debit_total() for entry in prepared.entries), Decimal("0"))
        credit = sum((entry.credit_total() for entry in prepared.entries), Decimal("0"))
        return ConversionResult(
            status=status, input_record_count=len(prepared.expected_rows),
            input_journal_count=len(prepared.entries),
            output_record_count=(output_validation.record_count if output_validation else 0),
            output_journal_count=(output_validation.journal_count if output_validation else 0),
            debit_total=debit, credit_total=credit,
            validation_results=tuple(validations),
            error_count=sum(item.severity in {Severity.ERROR, Severity.FATAL} for item in validations),
            warning_count=sum(item.severity is Severity.WARNING for item in validations),
            unresolved_mapping_count=0,
            output_validation_result=output_validation, output_path=output_path,
            verification_report=(
                "JDL migration formal output\n"
                f"journals={len(prepared.entries)}\nrows={len(prepared.expected_rows)}\n"
                f"canonical_normalization_evidence={','.join(prepared.normalization_evidence_ids) or 'none'}"
            ), completed_at=completed_at,
        )

    def _blocked(self, input_path, output_path, profile, context, reasons, entries=()):
        return JdlMigrationPreparedConversion(
            self._summary(input_path, output_path, profile, context, tuple(reasons), entries)
        )

    @staticmethod
    def _summary(input_path, output_path, profile, context, reasons, entries):
        return FirstReleaseSummary(
            readiness=FirstReleaseReadiness.BLOCKED if reasons else FirstReleaseReadiness.READY,
            blocking_reasons=tuple(reasons), source_name=input_path.name if input_path else None,
            source_format="JDL IBEX 出納帳 仕訳CSV（30項目）",
            profile_name=profile.profile_name if profile else None,
            account_master_count=len(context.account_master) if context else 0,
            subaccount_master_count=len(context.subaccounts) if context else 0,
            department_master_count=len(context.departments) if context else 0,
            tax_setting="確認済み" if context else "未確認",
            context_validated=context is not None,
            simple_journal_count=sum(not entry.is_compound() for entry in entries),
            compound_journal_count=sum(entry.is_compound() for entry in entries),
            output_path=output_path,
        )
