from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Sequence

from accounting_converter.adapters.output.jdl.models import (
    JDL_OUTPUT_METADATA_KEY,
    JdlEvidenceProfile,
    JdlTargetContext,
)
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.mapping import (
    MappingKey,
    MappingStatus,
    MappingType,
    SubaccountPolicy,
)
from accounting_converter.domain.validation import Severity, ValidationResult

from .company_settings import CompanySettingStatus
from .jdl_migration_tax_evidence import evidence_occurrence_mismatches
from .jdl_migration_review import jdl_description_replacement_key
from .journal_route import JournalRouteResult


@dataclass(frozen=True)
class JdlMigrationPreflightResult:
    validation_results: tuple[ValidationResult, ...]
    journal_count: int
    physical_row_count: int

    @property
    def output_allowed(self) -> bool:
        return not any(
            item.severity in {Severity.ERROR, Severity.FATAL}
            for item in self.validation_results
        )


class JdlMigrationPreflight:
    """Migration-specific gate; it never promotes Evidence or mappings."""

    def evaluate(
        self,
        entries: Sequence[JournalEntry],
        profile: ConversionProfile,
        context: JdlTargetContext,
        *,
        company_status: CompanySettingStatus = CompanySettingStatus.AVAILABLE,
        verified_tax_keys: frozenset[str] = frozenset(),
        source_sha256: str | None = None,
    ) -> JdlMigrationPreflightResult:
        errors: list[ValidationResult] = []
        if company_status is not CompanySettingStatus.AVAILABLE:
            errors.append(self._error("JDL-MIGRATION-CONTEXT-STALE", "JDL科目一覧と対応内容の再確認が必要です。", "target_context"))
        if not entries:
            errors.append(self._error("JDL-MIGRATION-EMPTY", "仕訳がありません。", "entries"))

        for entry in entries:
            self._validate_entry(
                entry, profile, context, verified_tax_keys, errors, source_sha256
            )
        return JdlMigrationPreflightResult(
            validation_results=tuple(errors),
            journal_count=len(entries),
            physical_row_count=sum(
                len(entry.metadata.get("physical_rows", ())) for entry in entries
            ),
        )

    def _validate_entry(
        self,
        entry: JournalEntry,
        profile: ConversionProfile,
        context: JdlTargetContext,
        verified_tax_keys: frozenset[str],
        errors: list[ValidationResult],
        source_sha256: str | None,
    ) -> None:
        if not entry.is_balanced():
            errors.append(self._entry_error("JDL-MIGRATION-BALANCE", "貸借が一致しません。", "amount", entry))
        rows = tuple(entry.metadata.get("physical_rows", ()))
        flags = tuple(entry.metadata.get("identifier_flags", ()))
        if len(rows) != len(flags) or not self._valid_flags(flags):
            errors.append(self._entry_error("JDL-MIGRATION-FLAGS", "仕訳のflag sequenceを安全に保持できません。", "identifier_flag", entry))
        for row_index, row in enumerate(rows, 1):
            description = str(row.get("description", ""))
            if len(description) > 32 and not self._description_replacement_valid(
                profile,
                entry.id,
                row_index,
                description,
                source_sha256,
            ):
                errors.append(self._entry_error("JDL-MIGRATION-DESCRIPTION-LENGTH", "摘要が32文字を超えています。", "description", entry))
            try:
                description.encode("cp932", errors="strict")
            except UnicodeEncodeError:
                errors.append(self._entry_error("JDL-MIGRATION-CP932", "CP932で損失なく表現できない摘要があります。", "description", entry))

        for line in entry.lines:
            account_mapping = profile.account_mappings.get(line.account or "")
            target_parent = ""
            source_code = str(line.metadata.get("jdl_source_account_code", ""))
            source_name = str(
                line.metadata.get("jdl_source_account_formal_name", "")
                or line.metadata.get("jdl_source_account_name", "")
            )
            exact_target = next(
                (
                    item
                    for item in context.account_master
                    if item.target_master_code == source_code
                    and item.target_formal_name == source_name
                ),
                None,
            )
            if exact_target is not None:
                target_parent = exact_target.mapping_value
            elif (
                account_mapping is None
                or account_mapping.status is not MappingStatus.USER_CONFIRMED
                or not account_mapping.target_value
                or account_mapping.target_value not in context.accounts
            ):
                errors.append(self._entry_error("JDL-MIGRATION-ACCOUNT-UNRESOLVED", "科目対応のHuman確認が必要です。", "account", entry))
            else:
                target_parent = account_mapping.target_value
            self._validate_subaccount(line, target_parent, profile, context, entry, errors)
            if line.tax_info is not None and line.tax_info.category:
                tax_key = line.tax_info.category
                tax_mapping = profile.tax_mappings.get(tax_key)
                if (
                    tax_key not in verified_tax_keys
                    or tax_mapping is None
                    or tax_mapping.status is not MappingStatus.USER_CONFIRMED
                    or tax_mapping.target_value is None
                ):
                    errors.append(self._entry_error("JDL-MIGRATION-TAX-UNVERIFIED", "税表現のHuman確認と実機Evidenceが必要です。", "tax", entry))
                else:
                    mismatches = evidence_occurrence_mismatches(
                        tax_key, entry, line, context
                    )
                    for mismatch in mismatches:
                        errors.append(self._entry_error(
                            f"JDL-MIGRATION-TAX-EVIDENCE-{mismatch}",
                            self._tax_evidence_mismatch_message(mismatch),
                            "tax",
                            entry,
                        ))

    @staticmethod
    def _description_replacement_valid(
        profile: ConversionProfile,
        entry_id: str,
        row_index: int,
        original: str,
        source_sha256: str | None,
    ) -> bool:
        if source_sha256 is None:
            return False
        mapping = profile.loss_policy_mappings.get(
            jdl_description_replacement_key(entry_id, row_index)
        )
        if (
            mapping is None
            or mapping.status is not MappingStatus.USER_CONFIRMED
            or mapping.metadata.get("policy")
            != "HUMAN_CONFIRMED_DESCRIPTION_REPLACEMENT"
            or mapping.metadata.get("source_sha256") != source_sha256
            or mapping.metadata.get("original_description_sha256")
            != hashlib.sha256(original.encode("utf-8")).hexdigest()
            or not mapping.target_value
            or not 1 <= len(mapping.target_value) <= 32
        ):
            return False
        try:
            mapping.target_value.encode("cp932", errors="strict")
        except UnicodeEncodeError:
            return False
        return True

    @staticmethod
    def _tax_evidence_mismatch_message(reason: str) -> str:
        messages = {
            "ROUTE_MISMATCH": "税表現の入力経路が実機確認済み条件と一致しません。",
            "SHAPE_MISMATCH": "税表現の仕訳構成が実機確認済み条件と一致しません。",
            "SIDE_MISMATCH": "税表現の借貸位置が実機確認済み条件と一致しません。",
            "ACCOUNT_SCOPE_MISMATCH": "税表現に使用する科目条件が実機確認済み範囲外です。",
            "SUBACCOUNT_SCOPE_MISMATCH": "税表現と補助科目の組合せが実機確認されていません。",
            "OPTIONAL_FIELD_MISMATCH": "税表現と追加項目の組合せが実機確認されていません。",
            "OPPOSITE_TAX_MISMATCH": "反対側の税表現が実機確認済み条件と一致しません。",
            "TAX_SEMANTICS_MISMATCH": "税区分・税率・入力区分が実機確認済み条件と一致しません。",
            "CONTEXT_MISMATCH": "JDL税設定が実機確認済み条件と一致しません。",
        }
        return messages.get(reason, "税表現が実機確認済み条件と一致しません。")

    def _validate_subaccount(
        self,
        line,
        target_parent: str,
        profile: ConversionProfile,
        context: JdlTargetContext,
        entry: JournalEntry,
        errors: list[ValidationResult],
    ) -> None:
        if not line.sub_account:
            return
        key = MappingKey(MappingType.SUBACCOUNT, line.sub_account, line.account)
        mapping = profile.subaccount_context_mappings.get(key)
        if mapping is None or mapping.status is not MappingStatus.USER_CONFIRMED:
            errors.append(self._entry_error("JDL-MIGRATION-SUBACCOUNT-UNRESOLVED", "補助科目の扱いをHumanが確認する必要があります。", "sub_account", entry))
            return
        policy = mapping.metadata.get("subaccount_policy")
        if policy == SubaccountPolicy.PARENT_ONLY_CONFIRMED.value:
            if mapping.target_value != "" or any(
                item.parent_account == target_parent for item in context.subaccounts
            ):
                errors.append(self._entry_error("JDL-MIGRATION-PARENT-ONLY-INVALID", "親科目のみの確認内容がtarget masterと一致しません。", "sub_account", entry))
            return
        if policy != SubaccountPolicy.PRESERVE_SUBACCOUNT.value:
            errors.append(self._entry_error("JDL-MIGRATION-SUBACCOUNT-POLICY", "補助科目の保持policyが確認されていません。", "sub_account", entry))
            return
        if not any(
            item.parent_account == target_parent
            and item.mapping_value == mapping.target_value
            for item in context.subaccounts
        ):
            errors.append(self._entry_error("JDL-MIGRATION-SUBACCOUNT-TARGET", "target masterに親科目付き補助科目を確認できません。", "sub_account", entry))

    @staticmethod
    def _valid_flags(flags: tuple[object, ...]) -> bool:
        if len(flags) == 1:
            return flags[0] in {"1000", "1111"}
        return (
            len(flags) >= 2
            and flags[0] == "1110"
            and flags[-1] == "1101"
            and all(flag == "1100" for flag in flags[1:-1])
        )

    @staticmethod
    def _error(rule_id: str, message: str, field: str) -> ValidationResult:
        return ValidationResult(Severity.ERROR, rule_id, message, field=field)

    @staticmethod
    def _entry_error(rule_id: str, message: str, field: str, entry: JournalEntry) -> ValidationResult:
        return ValidationResult(
            Severity.ERROR,
            rule_id,
            message,
            journal_id=entry.id,
            source_reference=entry.source_reference,
            field=field,
        )


class JdlMigrationSyntheticRoutePolicy:
    """Narrow synthetic-only bridge to the existing verified JDL serializer."""

    def apply(self, entries: Sequence[JournalEntry]) -> JournalRouteResult:
        routed: list[JournalEntry] = []
        errors: list[ValidationResult] = []
        for entry in entries:
            flags = tuple(entry.metadata.get("identifier_flags", ()))
            has_optional = any(
                line.sub_account or line.department or line.tax_info is not None
                for line in entry.lines
            )
            if len(entry.lines) != 2 or has_optional or flags not in {("1000",), ("1111",)}:
                errors.append(self._entry_error(
                    "JDL-MIGRATION-ROUTE-NOT-EVIDENCED",
                    "synthetic routeは検証済みの単一1D1Cだけ対応します。",
                    "journal_structure",
                    entry,
                ))
                continue
            evidence = (
                JdlEvidenceProfile.BASIC_1000
                if flags == ("1000",)
                else JdlEvidenceProfile.BASIC_1111
            )
            routed.append(replace(entry, metadata={**entry.metadata, JDL_OUTPUT_METADATA_KEY: evidence.value}))
        return JournalRouteResult(tuple(routed), tuple(errors))

    @staticmethod
    def _entry_error(rule_id: str, message: str, field: str, entry: JournalEntry) -> ValidationResult:
        return ValidationResult(
            Severity.ERROR,
            rule_id,
            message,
            journal_id=entry.id,
            source_reference=entry.source_reference,
            field=field,
        )
