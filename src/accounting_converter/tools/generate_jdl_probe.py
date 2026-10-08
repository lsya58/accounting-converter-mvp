from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Sequence

from accounting_converter.adapters.input.moneyforward import (
    MONEYFORWARD_OBSERVED_HEADER,
    MoneyForwardInputAdapter,
    MoneyForwardStructuralValidator,
)
from accounting_converter.adapters.output.jdl import (
    ExplicitJdlEvidenceRoutePolicy,
    JdlEvidenceProfile,
    JdlOutputRuntimeFactory,
    JdlTargetContext,
    jdl_ibex_35_5_output_profile,
)
from accounting_converter.application.conversion import (
    ConversionRequest,
    ConversionResult,
    ConversionService,
    ConversionStatus,
)
from accounting_converter.application.mapping_engine import MappingEngine
from accounting_converter.application.moneyforward_jdl_loss import MoneyForwardToJdlLossRule
from accounting_converter.application.profile_preflight import mapping_rule_set_from_profile
from accounting_converter.application.validation_pipeline import ValidationPipeline
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.mapping import MappingKey, MappingType
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import BalanceRule
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
    moneyforward_cloud_journal_export_observed_schema,
)


SAFETY_NOTICE = (
    "DEVELOPMENT TEST ONLY / NOT FOR CUSTOMER ACCOUNTING USE / "
    "DO NOT USE FOR PRODUCTION BOOKS / 開発検証専用 / 実務データへの利用禁止"
)


class JdlProbeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProbeDefinition:
    name: str
    journal_count: int
    evidence_profile: JdlEvidenceProfile | None
    availability: str
    expected_import_goal: str


PROBE_DEFINITIONS = (
    ProbeDefinition("simple_no_tax", 1, JdlEvidenceProfile.BASIC_1111, "EVIDENCE_GATED", "基本1仕訳の受理確認"),
    ProbeDefinition("simple_two_journals", 2, JdlEvidenceProfile.BASIC_1111, "EVIDENCE_GATED", "独立2仕訳の受理確認"),
    ProbeDefinition("simple_with_tax", 1, None, "BLOCKED_MISSING_TAX_EVIDENCE", "税項目mappingの受理確認"),
    ProbeDefinition("simple_with_subaccount", 1, JdlEvidenceProfile.SUBACCOUNT_1000, "EVIDENCE_GATED", "親科目付き補助科目の受理確認"),
    ProbeDefinition("compound_1d3c", 1, JdlEvidenceProfile.COMPOUND_1D3C, "EVIDENCE_GATED", "観測済み1D3Cの受理確認"),
)


@dataclass(frozen=True)
class ProbeGenerationResult:
    output_path: Path
    manifest_path: Path
    conversion_result: ConversionResult


class JdlProbeGenerator:
    def __init__(self, private_root: Path) -> None:
        self.private_root = private_root.resolve()

    def generate(
        self,
        *,
        case_name: str,
        output_path: Path,
        profile_path: Path,
        context_path: Path,
    ) -> ProbeGenerationResult:
        definition = self._definition(case_name)
        if definition.evidence_profile is None:
            raise JdlProbeError(
                "PROBE_BLOCKED_MISSING_TAX_EVIDENCE",
                "MF税区分からJDL税項目への実機確認済みmappingがないため生成できません。",
            )
        output_path = output_path.resolve()
        manifest_path = output_path.with_suffix(".manifest.json")
        self._validate_destination(output_path, manifest_path)
        profile = self._load_profile(profile_path)
        context = JdlTargetContextLoader().load(context_path)
        self._validate_identities(profile)
        rows, assignments = self._case_rows(definition, profile, context)
        self.private_root.mkdir(parents=True, exist_ok=True)
        source_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="mf_jdl_probe_", suffix=".csv", dir=self.private_root, delete=False
            ) as source_file:
                source_path = Path(source_file.name)
                source_bytes = self._source_bytes(rows)
                source_file.write(source_bytes)
            source_hash = self._sha256(source_path)
            result = self._convert(source_path, output_path, profile, context, assignments)
            if self._sha256(source_path) != source_hash:
                raise JdlProbeError("PROBE_SOURCE_CHANGED", "一時入力ファイルが変更されました。")
            if result.status != ConversionStatus.SUCCESS:
                rule_ids = sorted({item.rule_id for item in result.validation_results})
                raise JdlProbeError(
                    "PROBE_CONVERSION_BLOCKED",
                    f"変換は安全判定により停止しました: {result.status}; rules={','.join(rule_ids)}",
                )
            manifest = self._manifest(definition, result, output_path, profile_path, context)
            self._atomic_json_write(manifest_path, manifest)
            return ProbeGenerationResult(output_path, manifest_path, result)
        except Exception:
            if output_path.exists() and not manifest_path.exists():
                output_path.unlink()
            raise
        finally:
            if source_path is not None and source_path.exists():
                source_path.unlink()

    def _validate_destination(self, output_path: Path, manifest_path: Path) -> None:
        if not output_path.is_relative_to(self.private_root):
            raise JdlProbeError("PROBE_PRIVATE_PATH_REQUIRED", "出力先は指定private root配下に限定されます。")
        if output_path.suffix.lower() != ".csv":
            raise JdlProbeError("PROBE_OUTPUT_EXTENSION", "出力ファイルは.csvを指定してください。")
        if output_path.exists() or manifest_path.exists():
            raise JdlProbeError("PROBE_OUTPUT_EXISTS", "CSVまたはmanifestが既に存在します。上書きしません。")

    @staticmethod
    def _load_profile(path: Path) -> ConversionProfile:
        return ConversionProfileStore(path.parent / ".unused").from_json_text(
            path.read_text(encoding="utf-8")
        )

    @staticmethod
    def _validate_identities(profile: ConversionProfile) -> None:
        source = moneyforward_cloud_journal_export_observed_schema().identity
        target = jdl_ibex_cashbook_official_journal_import_schema_definition().identity
        if profile.source_format_identity.stable_key != source.stable_key:
            raise JdlProbeError("PROBE_PROFILE_SOURCE_IDENTITY", "Money Forward observed identity用Profileではありません。")
        if profile.target_format_identity.stable_key != target.stable_key:
            raise JdlProbeError("PROBE_PROFILE_TARGET_IDENTITY", "対象JDL identity用Profileではありません。")

    def _case_rows(
        self,
        definition: ProbeDefinition,
        profile: ConversionProfile,
        context: JdlTargetContext,
    ) -> tuple[list[tuple[str, ...]], dict[str, JdlEvidenceProfile]]:
        if definition.name == "simple_no_tax":
            rows = [self._row("1", "現金", "普通預金", "700", "JDL-PROBE-A")]
        elif definition.name == "simple_two_journals":
            rows = [
                self._row("1", "現金", "普通預金", "700", "JDL-PROBE-A"),
                self._row("2", "当座預金", "小口現金", "900", "JDL-PROBE-B"),
            ]
        elif definition.name == "compound_1d3c":
            rows = [
                self._row("1", "現金", "普通預金", "1000", "JDL-PROBE-C", credit_amount="500"),
                self._row("1", "", "当座預金", "", "", credit_amount="300"),
                self._row("1", "", "小口現金", "", "", credit_amount="200"),
            ]
        elif definition.name == "simple_with_subaccount":
            sub_key = self._confirmed_credit_subaccount(profile, context)
            rows = [self._row("1", "現金", sub_key.parent_account or "", "700", "JDL-PROBE-S", credit_sub=sub_key.source_value)]
        else:
            raise JdlProbeError("PROBE_CASE_UNSUPPORTED", "未対応のprobe caseです。")
        transaction_numbers = tuple(dict.fromkeys(row[0] for row in rows))
        assignments = {
            number: definition.evidence_profile for number in transaction_numbers
        }
        return rows, assignments  # type: ignore[return-value]

    @staticmethod
    def _confirmed_credit_subaccount(
        profile: ConversionProfile, context: JdlTargetContext
    ) -> MappingKey:
        candidates = [
            key
            for key, value in profile.subaccount_context_mappings.items()
            if key.mapping_type is MappingType.SUBACCOUNT
            and value.is_resolved
            and key.parent_account in profile.account_mappings
            and any(
                item.parent_account
                == profile.account_mappings[key.parent_account].target_value
                and item.mapping_value == value.target_value
                for item in context.subaccounts
            )
        ]
        if len(candidates) != 1:
            raise JdlProbeError(
                "PROBE_BLOCKED_MISSING_SUBACCOUNT_EVIDENCE",
                "確認済みの親科目付き補助科目mappingが一意に選べません。",
            )
        return candidates[0]

    def _convert(self, source: Path, output: Path, profile: ConversionProfile, context: JdlTargetContext, assignments: dict[str, JdlEvidenceProfile]) -> ConversionResult:
        source_schema = moneyforward_cloud_journal_export_observed_schema()
        source_profile = FormatProfile("Money Forward", "Money Forward クラウド会計", "UNKNOWN", source_schema.identity.stable_key, "cp932")
        service = ConversionService(
            input_adapter=MoneyForwardInputAdapter(),
            structural_validator=MoneyForwardStructuralValidator(),
            mapping_engine=MappingEngine(mapping_rule_set_from_profile(profile)),
            business_validator=ValidationPipeline((BalanceRule(), MoneyForwardToJdlLossRule())),
            output_adapter=None,
            output_validator=None,
            journal_route_policy=ExplicitJdlEvidenceRoutePolicy(
                {f"moneyforward:{source.name}:{key}": value for key, value in assignments.items()},
                route_id="MF-JDL-REAL-IMPORT-PROBE-V0",
            ),
            runtime_output_factory=JdlOutputRuntimeFactory(),
        )
        return service.convert(ConversionRequest(source, output, source_profile, jdl_ibex_35_5_output_profile(), conversion_profile=profile, target_runtime_context=context))

    @staticmethod
    def _row(transaction: str, debit: str, credit: str, debit_amount: str, description: str, *, credit_amount: str | None = None, credit_sub: str = "") -> tuple[str, ...]:
        return (
            transaction, "2026/10/20", debit, "", "", "", "", "", debit_amount,
            credit, credit_sub, "", "", "", "", credit_amount if credit_amount is not None else debit_amount,
            description, "", "",
        )

    @staticmethod
    def _source_bytes(rows: Sequence[Sequence[str]]) -> bytes:
        text = io.StringIO(newline="")
        writer = csv.writer(text, lineterminator="\n", quoting=csv.QUOTE_ALL)
        writer.writerow(MONEYFORWARD_OBSERVED_HEADER)
        writer.writerows(rows)
        return text.getvalue().encode("cp932")

    def _manifest(self, definition: ProbeDefinition, result: ConversionResult, output: Path, profile_path: Path, context: JdlTargetContext) -> dict[str, object]:
        context_summary = json.dumps(context.privacy_safe_summary(), sort_keys=True, ensure_ascii=False).encode("utf-8")
        return {
            "schema_version": "1",
            "probe_case": definition.name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "output_sha256": self._sha256(output),
            "logical_journal_count": result.output_journal_count,
            "output_record_count": result.output_record_count,
            "debit_total": str(result.debit_total),
            "credit_total": str(result.credit_total),
            "totals_match": result.debit_total == result.credit_total,
            "output_validation": "PASS" if result.output_validation_result and result.output_validation_result.success else "FAIL",
            "jdl_context_hash": hashlib.sha256(context_summary).hexdigest(),
            "conversion_profile_sha256": self._sha256(profile_path),
            "expected_import_goal": definition.expected_import_goal,
            "evidence_scope": [definition.evidence_profile.value] if definition.evidence_profile else [],
            "NOT_FOR_PRODUCTION": True,
            "safety_notice": SAFETY_NOTICE,
        }

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _atomic_json_write(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.tmp")
        try:
            temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(temp, path)
        finally:
            if temp.exists():
                temp.unlink()

    @staticmethod
    def _definition(name: str) -> ProbeDefinition:
        for definition in PROBE_DEFINITIONS:
            if definition.name == name:
                return definition
        raise JdlProbeError("PROBE_CASE_UNKNOWN", "一覧にないprobe caseです。")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Development-only MF -> JDL real-import probe generator")
    parser.add_argument("--list", action="store_true", help="probe case一覧")
    parser.add_argument("--case", choices=[item.name for item in PROBE_DEFINITIONS])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--context", type=Path)
    parser.add_argument("--private-root", type=Path, default=Path("data/private"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    print(SAFETY_NOTICE)
    if args.list:
        for item in PROBE_DEFINITIONS:
            print(f"{item.name}: {item.availability}")
        return 0
    if not all((args.case, args.output, args.profile, args.context)):
        print("--case, --output, --profile, --context are required")
        return 2
    try:
        generated = JdlProbeGenerator(args.private_root).generate(
            case_name=args.case,
            output_path=args.output,
            profile_path=args.profile,
            context_path=args.context,
        )
    except (JdlProbeError, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, JdlProbeError) else "PROBE_INPUT_ERROR"
        print(f"BLOCKED: {code}: {exc}")
        return 1
    result = generated.conversion_result
    print("Probe candidate generated")
    print(f"Case: {args.case}")
    print(f"Logical journals: {result.output_journal_count}")
    print("Debit / credit totals: match")
    print("Output validation: PASS")
    print("Production use: NO - DEVELOPMENT TEST ONLY")
    print(f"Candidate: {generated.output_path}")
    print(f"Manifest: {generated.manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
