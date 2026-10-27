from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Sequence

from accounting_converter.domain.journal import JournalEntry, JournalLine, Side, TaxInfo
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import Severity, ValidationResult
from accounting_converter.application.moneyforward_jdl_loss import (
    moneyforward_verified_description_rows,
)
from accounting_converter.profiles.jdl_official import (
    JdlTaxProcessingMode,
    jdl_ibex_cashbook_official_journal_import_spec,
)

from .models import (
    JDL_OUTPUT_FORMAT_ID,
    JDL_OUTPUT_METADATA_KEY,
    JdlDepartmentIdentity,
    JdlEvidenceProfile,
    JdlOutputPlan,
    JdlOutputRow,
    JdlSubaccountIdentity,
    JdlTargetContext,
)


TAX_SCOPE_PURCHASE = "仕　入"
TAX_SCOPE_SALES = "売一種"
TAX_CATEGORY_TEN_PERCENT = "10%"
TAX_CATEGORY_REDUCED_EIGHT_PERCENT = "軽減8%"
TAX_SCOPE_NON_TAXABLE_PURCHASE = "非仕入"
TAX_SCOPE_NON_TAXABLE_SALES = "非売上"
TAX_INPUT_METHOD_INTERNAL = "内税"
EVIDENCE_IDS = {
    JdlEvidenceProfile.BASIC_1111: "EVID-JDL-GENERATOR-1111-001",
    JdlEvidenceProfile.BASIC_1000: "EVID-JDL-GENERATOR-1000-001",
    JdlEvidenceProfile.SUBACCOUNT_1000: (
        "EVID-JDL-GENERATOR-1000-SUBACCOUNT-001"
    ),
    JdlEvidenceProfile.DEPARTMENT_1111: (
        "EVID-JDL-GENERATOR-1111-DEPARTMENT-001"
    ),
    JdlEvidenceProfile.TAX_INCLUDED_1111: (
        "EVID-JDL-GENERATOR-1111-TAX-INCLUSIVE-001"
    ),
    JdlEvidenceProfile.TAX_PURCHASE_10_SUBACCOUNT_INCLUDED_1111: (
        "EVID-JDL-MF-TAX-PURCHASE-10-SUBACCOUNT-ROUNDTRIP-001"
    ),
    JdlEvidenceProfile.TAX_PURCHASE_REDUCED_8_INCLUDED_1111: (
        "EVID-JDL-MF-TAX-PURCHASE-REDUCED-8-SUBACCOUNT-ROUNDTRIP-001"
    ),
    JdlEvidenceProfile.TAX_SALES_10_INCLUDED_1111: (
        "EVID-JDL-TAX-SALES-10-INCLUSIVE-HAND-001"
    ),
    JdlEvidenceProfile.TAX_SALES_10_SUBACCOUNT_INCLUDED_1111: (
        "EVID-JDL-MF-TAX-SALES-10-SUBACCOUNT-ROUNDTRIP-001"
    ),
    JdlEvidenceProfile.TAX_SALES_REDUCED_8_SUBACCOUNT_INCLUDED_1111: (
        "EVID-JDL-MF-TAX-SALES-REDUCED-8-SUBACCOUNT-ROUNDTRIP-001"
    ),
    JdlEvidenceProfile.TAX_NON_TAXABLE_PURCHASE_SUBACCOUNT_INCLUDED_1111: (
        "EVID-JDL-MF-TAX-NONTAXABLE-PURCHASE-SUBACCOUNT-ROUNDTRIP-001"
    ),
    JdlEvidenceProfile.TAX_NON_TAXABLE_SALES_SUBACCOUNT_INCLUDED_1111: (
        "EVID-JDL-MF-TAX-NONTAXABLE-SALES-SUBACCOUNT-ROUNDTRIP-001"
    ),
    JdlEvidenceProfile.TAX_OUT_OF_SCOPE_SUBACCOUNT_INCLUDED_1111: (
        "EVID-JDL-MF-TAX-OUT-OF-SCOPE-SUBACCOUNT-ROUNDTRIP-001"
    ),
    JdlEvidenceProfile.TAX_EXCLUDED_1111: (
        "EVID-JDL-GENERATOR-1111-TAX-EXCLUSIVE-001"
    ),
    JdlEvidenceProfile.MF_TAX_EXCLUDED_PROPORTIONAL_1111: (
        "EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-BATCH-001"
    ),
    JdlEvidenceProfile.MF_NO_TAX_PROPORTIONAL_1111: (
        "EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-BATCH-001"
    ),
    JdlEvidenceProfile.COMPOUND_1D3C: (
        "EVID-JDL-GENERATOR-COMPOUND-1110-1100-1101-001"
    ),
    JdlEvidenceProfile.COMPOUND_1D3C_LINE_DESCRIPTIONS: (
        "EVID-JDL-COMPOUND-PER-ROW-DESCRIPTION-ROUNDTRIP-001"
    ),
    JdlEvidenceProfile.COMPOUND_2D2C_LINE_DESCRIPTIONS: (
        "EVID-JDL-COMPOUND-2D2C-PER-ROW-DESCRIPTION-001"
    ),
    JdlEvidenceProfile.COMPOUND_2D2C_PURCHASE_10_TAXABLE: (
        "EVID-JDL-COMPOUND-2D2C-PURCHASE-10-TAXABLE-ROUNDTRIP-001"
    ),
    JdlEvidenceProfile.COMPOUND_2D2C_PURCHASE_10_TAXABLE_NO_SUBACCOUNT: (
        "EVID-JDL-COMPOUND-2D2C-PURCHASE-10-TAXABLE-"
        "NO-SUBACCOUNT-ROUNDTRIP-001"
    ),
    JdlEvidenceProfile.MF_COMPOUND_2D2C_TAX_EXCLUDED_PROPORTIONAL: (
        "EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P01-2D2C-PURCHASE-10-001"
    ),
    JdlEvidenceProfile.COMPOUND_2D1C_LINE_DESCRIPTIONS: (
        "EVID-JDL-COMPOUND-2D1C-PER-ROW-DESCRIPTION-001"
    ),
    JdlEvidenceProfile.COMPOUND_2D3C_LINE_DESCRIPTIONS: (
        "EVID-JDL-COMPOUND-2D3C-PER-ROW-DESCRIPTION-001"
    ),
    JdlEvidenceProfile.COMPOUND_4D6C_LINE_DESCRIPTIONS: (
        "EVID-JDL-COMPOUND-4D6C-PER-ROW-DESCRIPTION-ROUNDTRIP-001"
    ),
    JdlEvidenceProfile.COMPOUND_5D7C_LINE_DESCRIPTIONS: (
        "EVID-JDL-COMPOUND-5D7C-PER-ROW-DESCRIPTION-ROUNDTRIP-001"
    ),
    JdlEvidenceProfile.COMPOUND_5D8C_LINE_DESCRIPTIONS: (
        "EVID-JDL-COMPOUND-5D8C-PER-ROW-DESCRIPTION-ROUNDTRIP-001"
    ),
}
MULTIGROUP_EVIDENCE_ID = "EVID-JDL-GENERATOR-MULTIGROUP-SIMPLE-COMPOUND-001"
SIMPLE_PLUS_SIMPLE_EVIDENCE_ID = "EVID-JDL-SIMPLE-PLUS-SIMPLE-RUNTIME-001"
MIXED_BATCH_EVIDENCE_ID = "EVID-JDL-MIXED-BATCH-RUNTIME-001"
SIX_TAX_BATCH_EVIDENCE_ID = "EVID-JDL-MF-SIX-TAX-BATCH-FORMAL-E2E-001"
MF_TAX_EXCLUDED_PROPORTIONAL_13_SEQUENCE = (
    JdlEvidenceProfile.MF_COMPOUND_2D2C_TAX_EXCLUDED_PROPORTIONAL,
    JdlEvidenceProfile.MF_NO_TAX_PROPORTIONAL_1111,
    JdlEvidenceProfile.MF_NO_TAX_PROPORTIONAL_1111,
    JdlEvidenceProfile.MF_TAX_EXCLUDED_PROPORTIONAL_1111,
    *(JdlEvidenceProfile.MF_TAX_EXCLUDED_PROPORTIONAL_1111 for _ in range(3)),
    JdlEvidenceProfile.MF_NO_TAX_PROPORTIONAL_1111,
    JdlEvidenceProfile.MF_NO_TAX_PROPORTIONAL_1111,
    *(JdlEvidenceProfile.MF_TAX_EXCLUDED_PROPORTIONAL_1111 for _ in range(4)),
)
MIXED_BATCH_PROFILE_SEQUENCE = (
    JdlEvidenceProfile.BASIC_1111,
    JdlEvidenceProfile.BASIC_1111,
    JdlEvidenceProfile.COMPOUND_1D3C,
    JdlEvidenceProfile.COMPOUND_1D3C,
    JdlEvidenceProfile.BASIC_1111,
    JdlEvidenceProfile.COMPOUND_1D3C,
    JdlEvidenceProfile.BASIC_1111,
    JdlEvidenceProfile.BASIC_1111,
    JdlEvidenceProfile.COMPOUND_1D3C,
    JdlEvidenceProfile.BASIC_1111,
    JdlEvidenceProfile.COMPOUND_1D3C,
    JdlEvidenceProfile.BASIC_1111,
)
SIX_TAX_BATCH_PROFILE_SEQUENCE = (
    JdlEvidenceProfile.TAX_PURCHASE_10_SUBACCOUNT_INCLUDED_1111,
    JdlEvidenceProfile.TAX_SALES_10_SUBACCOUNT_INCLUDED_1111,
    JdlEvidenceProfile.TAX_PURCHASE_REDUCED_8_INCLUDED_1111,
    JdlEvidenceProfile.TAX_SALES_REDUCED_8_SUBACCOUNT_INCLUDED_1111,
    JdlEvidenceProfile.TAX_NON_TAXABLE_PURCHASE_SUBACCOUNT_INCLUDED_1111,
    JdlEvidenceProfile.TAX_OUT_OF_SCOPE_SUBACCOUNT_INCLUDED_1111,
)


class JdlOutputBlockedError(ValueError):
    def __init__(self, results: Sequence[ValidationResult]) -> None:
        self.validation_results = tuple(results)
        super().__init__("JDL output was blocked by evidence preflight")


@dataclass(frozen=True)
class JdlPreflightResult:
    plan: JdlOutputPlan | None
    validation_results: tuple[ValidationResult, ...]

    @property
    def supported(self) -> bool:
        return self.plan is not None and not self.validation_results


class JdlOutputPreflight:
    def __init__(self, context: JdlTargetContext) -> None:
        self.context = context

    def evaluate(
        self,
        entries: Sequence[JournalEntry],
        profile: FormatProfile,
    ) -> JdlPreflightResult:
        errors: list[ValidationResult] = []
        self._validate_profile(profile, errors)
        self._validate_context(errors)
        if not entries:
            errors.append(self._error("JDL-OUT-EMPTY", "仕訳がありません。", "entries"))

        rows: list[JdlOutputRow] = []
        profiles: list[JdlEvidenceProfile] = []
        for entry in entries:
            evidence = self._profile_for_entry(entry, errors)
            if evidence is None:
                continue
            profiles.append(evidence)
            rows.extend(self._rows_for_entry(entry, evidence, errors))

        if profiles:
            self._validate_file_combination(entries, tuple(profiles), errors)
        if not errors:
            self._validate_serializable_rows(rows, errors)
        if errors:
            return JdlPreflightResult(None, tuple(errors))
        return JdlPreflightResult(
            JdlOutputPlan(tuple(rows), tuple(profiles), len(entries)),
            (),
        )

    def _validate_profile(
        self,
        profile: FormatProfile,
        errors: list[ValidationResult],
    ) -> None:
        expected = ("JDL", "JDL IBEX 出納帳", "35.5", JDL_OUTPUT_FORMAT_ID, "cp932")
        actual = (
            profile.software,
            profile.product,
            profile.version,
            profile.format_id,
            profile.encoding.lower(),
        )
        if actual != expected:
            errors.append(
                self._error(
                    "JDL-OUT-FORMAT-IDENTITY",
                    "JDL出力profileが検証済みidentityと一致しません。",
                    "output_profile",
                )
            )

    def _validate_context(self, errors: list[ValidationResult]) -> None:
        if self.context.product != "JDL IBEX 出納帳" or self.context.version != "35.5":
            errors.append(
                self._error(
                    "JDL-OUT-TARGET-IDENTITY",
                    "取込先JDL製品またはversionが検証済み対象と一致しません。",
                    "target_identity",
                )
            )
        if not self.context.no_fuzzy_matching or not self.context.no_automatic_replacement:
            errors.append(
                self._error(
                    "JDL-OUT-EXACT-MAPPING-REQUIRED",
                    "fuzzy mappingまたは自動置換は使用できません。",
                    "mapping_policy",
                )
            )
        for item in self.context.subaccounts:
            if (
                not item.target_master_code
                or not item.output_code
                or not item.output_name
                or not item.output_representation_confirmed
            ):
                errors.append(
                    self._error(
                        "JDL-OUT-SUBACCOUNT-IDENTITY",
                        "補助科目のtarget masterと出力表現を明示してください。",
                        "sub_account",
                    )
                )
        for item in self.context.departments:
            if (
                item.target_master_code != item.output_code
                or not item.output_name
            ):
                errors.append(
                    self._error(
                        "JDL-OUT-DEPARTMENT-IDENTITY",
                        "部門codeは確認済みtarget masterと完全一致する必要があります。",
                        "department",
                    )
                )

    def _profile_for_entry(
        self,
        entry: JournalEntry,
        errors: list[ValidationResult],
    ) -> JdlEvidenceProfile | None:
        raw = entry.metadata.get(JDL_OUTPUT_METADATA_KEY)
        try:
            return JdlEvidenceProfile(raw)
        except (TypeError, ValueError):
            errors.append(
                self._error(
                    "JDL-OUT-EVIDENCE-PROFILE",
                    "検証済みJDL Evidence profileが明示されていません。",
                    "evidence_profile",
                    entry,
                )
            )
            return None

    def _rows_for_entry(
        self,
        entry: JournalEntry,
        evidence: JdlEvidenceProfile,
        errors: list[ValidationResult],
    ) -> list[JdlOutputRow]:
        if evidence in {
            JdlEvidenceProfile.COMPOUND_1D3C,
            JdlEvidenceProfile.COMPOUND_1D3C_LINE_DESCRIPTIONS,
            JdlEvidenceProfile.COMPOUND_2D2C_LINE_DESCRIPTIONS,
            JdlEvidenceProfile.COMPOUND_2D2C_PURCHASE_10_TAXABLE,
            JdlEvidenceProfile.COMPOUND_2D2C_PURCHASE_10_TAXABLE_NO_SUBACCOUNT,
            JdlEvidenceProfile.MF_COMPOUND_2D2C_TAX_EXCLUDED_PROPORTIONAL,
            JdlEvidenceProfile.COMPOUND_2D1C_LINE_DESCRIPTIONS,
            JdlEvidenceProfile.COMPOUND_2D3C_LINE_DESCRIPTIONS,
            JdlEvidenceProfile.COMPOUND_4D6C_LINE_DESCRIPTIONS,
            JdlEvidenceProfile.COMPOUND_5D7C_LINE_DESCRIPTIONS,
            JdlEvidenceProfile.COMPOUND_5D8C_LINE_DESCRIPTIONS,
        }:
            return self._compound_rows(entry, evidence, errors)
        if not entry.is_balanced():
            errors.append(self._error("JDL-OUT-BALANCE", "仕訳が貸借一致しません。", "amount", entry))
            return []
        if entry.description is not None and len(entry.description) > 32:
            errors.append(self._error("JDL-OUT-DESCRIPTION-LENGTH", "摘要が32文字を超えています。", "description", entry))
            return []
        return self._simple_rows(entry, evidence, errors)

    def _simple_rows(
        self,
        entry: JournalEntry,
        evidence: JdlEvidenceProfile,
        errors: list[ValidationResult],
    ) -> list[JdlOutputRow]:
        debit = [line for line in entry.lines if line.side is Side.DEBIT]
        credit = [line for line in entry.lines if line.side is Side.CREDIT]
        if len(debit) != 1 or len(credit) != 1:
            errors.append(self._error("JDL-OUT-SIMPLE-SHAPE", "単一仕訳は借貸各1行だけ対応します。", "journal_structure", entry))
            return []

        flag = "1000" if evidence in {
            JdlEvidenceProfile.BASIC_1000,
            JdlEvidenceProfile.SUBACCOUNT_1000,
        } else "1111"
        self._validate_feature_combination(debit[0], credit[0], evidence, entry, errors)
        if errors:
            return []
        return [self._row(flag, entry, debit[0], credit[0], entry.description or "")]

    def _compound_rows(
        self,
        entry: JournalEntry,
        evidence: JdlEvidenceProfile,
        errors: list[ValidationResult],
    ) -> list[JdlOutputRow]:
        debit = [line for line in entry.lines if line.side is Side.DEBIT]
        credit = [line for line in entry.lines if line.side is Side.CREDIT]
        line_description_profiles = {
            JdlEvidenceProfile.COMPOUND_1D3C_LINE_DESCRIPTIONS,
            JdlEvidenceProfile.COMPOUND_2D2C_LINE_DESCRIPTIONS,
            JdlEvidenceProfile.COMPOUND_2D2C_PURCHASE_10_TAXABLE,
            JdlEvidenceProfile.COMPOUND_2D2C_PURCHASE_10_TAXABLE_NO_SUBACCOUNT,
            JdlEvidenceProfile.MF_COMPOUND_2D2C_TAX_EXCLUDED_PROPORTIONAL,
            JdlEvidenceProfile.COMPOUND_2D1C_LINE_DESCRIPTIONS,
            JdlEvidenceProfile.COMPOUND_2D3C_LINE_DESCRIPTIONS,
            JdlEvidenceProfile.COMPOUND_4D6C_LINE_DESCRIPTIONS,
            JdlEvidenceProfile.COMPOUND_5D7C_LINE_DESCRIPTIONS,
            JdlEvidenceProfile.COMPOUND_5D8C_LINE_DESCRIPTIONS,
        }
        expected_shapes = {
            JdlEvidenceProfile.COMPOUND_1D3C_LINE_DESCRIPTIONS: (1, 3, 3),
            JdlEvidenceProfile.COMPOUND_2D2C_LINE_DESCRIPTIONS: (2, 2, 2),
            JdlEvidenceProfile.COMPOUND_2D2C_PURCHASE_10_TAXABLE: (2, 2, 2),
            JdlEvidenceProfile.COMPOUND_2D2C_PURCHASE_10_TAXABLE_NO_SUBACCOUNT: (2, 2, 2),
            JdlEvidenceProfile.MF_COMPOUND_2D2C_TAX_EXCLUDED_PROPORTIONAL: (2, 2, 2),
            JdlEvidenceProfile.COMPOUND_2D1C_LINE_DESCRIPTIONS: (2, 1, 2),
            JdlEvidenceProfile.COMPOUND_2D3C_LINE_DESCRIPTIONS: (2, 3, 3),
            JdlEvidenceProfile.COMPOUND_4D6C_LINE_DESCRIPTIONS: (4, 6, 6),
            JdlEvidenceProfile.COMPOUND_5D7C_LINE_DESCRIPTIONS: (5, 7, 7),
            JdlEvidenceProfile.COMPOUND_5D8C_LINE_DESCRIPTIONS: (5, 8, 8),
        }
        if evidence is JdlEvidenceProfile.COMPOUND_1D3C:
            if len(debit) != 1 or len(credit) != 3 or len(entry.lines) != 4:
                errors.append(self._error("JDL-OUT-COMPOUND-SHAPE", "v0は検証済みの複合仕訳形状だけ対応します。", "journal_structure", entry))
                return []
            physical_rows = None
        else:
            physical_rows = moneyforward_verified_description_rows(entry)
            shape = (
                len(debit),
                len(credit),
                len(physical_rows) if physical_rows is not None else 0,
            )
            if physical_rows is None or shape != expected_shapes[evidence]:
                errors.append(self._error("JDL-OUT-COMPOUND-SHAPE", "Evidence profileと複合仕訳形状が一致しません。", "journal_structure", entry))
                return []
        if not entry.is_balanced():
            errors.append(self._error("JDL-OUT-BALANCE", "複合仕訳がgroup単位で貸借一致しません。", "amount", entry))
            return []
        for line in entry.lines:
            self._validate_account(line, entry, errors)
            self._validate_amount(line.amount, entry, errors)
        if evidence is JdlEvidenceProfile.MF_COMPOUND_2D2C_TAX_EXCLUDED_PROPORTIONAL:
            assert physical_rows is not None
            taxed_rows = tuple(
                row for row in physical_rows
                if row.debit is not None and self._nonempty_tax(row.debit.tax_info)
            )
            if len(taxed_rows) != 1 or taxed_rows[0].credit is None:
                errors.append(self._error("JDL-OUT-COMPOUND-TAX-ROW", "課税対象行がEvidenceと一致しません。", "tax", entry))
            else:
                self._validate_tax(
                    taxed_rows[0].debit, taxed_rows[0].credit, entry,
                    included=False, errors=errors,
                    allow_opposite_subaccount=True,
                    expected_credit_method="PROPORTIONAL",
                )
            for row in physical_rows:
                self._validate_optional_subaccount(row.debit, entry, errors)
                self._validate_optional_subaccount(row.credit, entry, errors)
        elif evidence in {
            JdlEvidenceProfile.COMPOUND_2D2C_PURCHASE_10_TAXABLE,
            JdlEvidenceProfile.COMPOUND_2D2C_PURCHASE_10_TAXABLE_NO_SUBACCOUNT,
        }:
            assert physical_rows is not None
            first = physical_rows[0]
            if first.debit is None or first.credit is None:
                errors.append(self._error("JDL-OUT-COMPOUND-TAX-ROW", "課税対象の先頭行がEvidenceと一致しません。", "tax", entry))
                return []
            self._validate_tax(
                first.debit, first.credit, entry,
                included=True,
                errors=errors,
                allow_tax_side_subaccount=(
                    evidence
                    is JdlEvidenceProfile.COMPOUND_2D2C_PURCHASE_10_TAXABLE
                ),
            )
            if any(self._has_optional_features(line) for row in physical_rows[1:] for line in (row.debit, row.credit) if line is not None):
                errors.append(self._error("JDL-OUT-COMPOUND-TAX-EXTRA-FEATURE", "2行目に未検証featureがあります。", "journal_structure", entry))
        else:
            if any(self._has_optional_features(line) for line in entry.lines):
                errors.append(self._error("JDL-OUT-COMPOUND-FEATURE", "複合仕訳内の補助・部門・税は未対応です。", "journal_structure", entry))
            if self.context.tax_processing_mode is not JdlTaxProcessingMode.EXEMPT:
                errors.append(self._error("JDL-OUT-COMPOUND-TAX-MODE", "複合仕訳は免税profileだけ対応します。", "tax_processing", entry))
        if errors:
            return []
        if evidence in line_description_profiles:
            if physical_rows is None:
                errors.append(self._error(
                    "JDL-OUT-COMPOUND-DESCRIPTION",
                    "検証済み物理行に対応する摘要を一意に保持できません。",
                    "description",
                    entry,
                ))
                return []
            descriptions = tuple(row.description for row in physical_rows)
            for description in descriptions:
                try:
                    description.encode("cp932")
                except UnicodeEncodeError:
                    errors.append(self._error(
                        "JDL-OUT-DESCRIPTION-ENCODING",
                        "摘要をCP932で表現できません。",
                        "description",
                        entry,
                    ))
                    return []
                if len(description) > 32:
                    errors.append(self._error(
                        "JDL-OUT-DESCRIPTION-LENGTH",
                        "摘要が32文字を超えています。",
                        "description",
                        entry,
                    ))
                    return []
        else:
            descriptions = (entry.description or "", "", "")
        flags = (
            ("1110", "1101")
            if len(descriptions) == 2
            else ("1110", *("1100",) * (len(descriptions) - 2), "1101")
        )
        rows: list[JdlOutputRow] = []
        if physical_rows is None:
            paired_rows = tuple(
                (debit[0] if index == 0 else None, credit_line)
                for index, credit_line in enumerate(credit)
            )
        else:
            paired_rows = tuple((row.debit, row.credit) for row in physical_rows)
        for index, (debit_line, credit_line) in enumerate(paired_rows):
            rows.append(
                self._row(
                    flags[index],
                    entry,
                    debit_line,
                    credit_line,
                    descriptions[index],
                )
            )
        return rows

    def _validate_feature_combination(
        self,
        debit: JournalLine,
        credit: JournalLine,
        evidence: JdlEvidenceProfile,
        entry: JournalEntry,
        errors: list[ValidationResult],
    ) -> None:
        for line in (debit, credit):
            self._validate_account(line, entry, errors)
            self._validate_amount(line.amount, entry, errors)

        if evidence in {JdlEvidenceProfile.BASIC_1111, JdlEvidenceProfile.BASIC_1000}:
            if any(self._has_optional_features(line) for line in (debit, credit)):
                errors.append(self._error("JDL-OUT-BASIC-FEATURE", "basic profileに補助・部門・税を追加できません。", "evidence_profile", entry))
            self._require_tax_mode(JdlTaxProcessingMode.EXEMPT, entry, errors)
        elif evidence is JdlEvidenceProfile.SUBACCOUNT_1000:
            self._validate_subaccount(debit, credit, entry, errors)
        elif evidence is JdlEvidenceProfile.DEPARTMENT_1111:
            self._validate_department(debit, credit, entry, errors)
        elif evidence is JdlEvidenceProfile.TAX_INCLUDED_1111:
            self._validate_tax(debit, credit, entry, included=True, errors=errors)
        elif evidence is JdlEvidenceProfile.MF_TAX_EXCLUDED_PROPORTIONAL_1111:
            self._validate_tax(
                debit, credit, entry, included=False, errors=errors,
                allow_opposite_subaccount=True,
                expected_credit_method="PROPORTIONAL",
            )
            self._validate_optional_subaccount(debit, entry, errors)
            self._validate_optional_subaccount(credit, entry, errors)
        elif evidence is JdlEvidenceProfile.MF_NO_TAX_PROPORTIONAL_1111:
            self._require_tax_mode(JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED, entry, errors)
            if self.context.effective_input_tax_credit_method.value != "PROPORTIONAL":
                errors.append(self._error("JDL-OUT-TAX-COMPANY-PROFILE", "一括比例配分方式の確認が必要です。", "tax_processing", entry))
            if self._nonempty_tax(debit.tax_info) or self._nonempty_tax(credit.tax_info):
                errors.append(self._error("JDL-OUT-OPPOSITE-TAX", "対象外mapping後の税fieldはblankである必要があります。", "tax", entry))
            self._validate_optional_subaccount(debit, entry, errors)
            self._validate_optional_subaccount(credit, entry, errors)
        elif evidence is JdlEvidenceProfile.TAX_PURCHASE_10_SUBACCOUNT_INCLUDED_1111:
            self._validate_tax(
                debit,
                credit,
                entry,
                included=True,
                errors=errors,
                allow_tax_side_subaccount=True,
            )
        elif evidence is JdlEvidenceProfile.TAX_PURCHASE_REDUCED_8_INCLUDED_1111:
            self._validate_tax(
                debit,
                credit,
                entry,
                included=True,
                errors=errors,
                expected_category=TAX_CATEGORY_REDUCED_EIGHT_PERCENT,
                expected_reduced_rate=True,
                allow_tax_side_subaccount=True,
            )
        elif evidence is JdlEvidenceProfile.TAX_SALES_10_INCLUDED_1111:
            self._validate_tax(
                debit,
                credit,
                entry,
                included=True,
                errors=errors,
                tax_side=Side.CREDIT,
                expected_scope=TAX_SCOPE_SALES,
            )
        elif evidence is JdlEvidenceProfile.TAX_SALES_10_SUBACCOUNT_INCLUDED_1111:
            self._validate_tax(
                debit,
                credit,
                entry,
                included=True,
                errors=errors,
                tax_side=Side.CREDIT,
                expected_scope=TAX_SCOPE_SALES,
                allow_tax_side_subaccount=True,
            )
        elif evidence is JdlEvidenceProfile.TAX_SALES_REDUCED_8_SUBACCOUNT_INCLUDED_1111:
            self._validate_tax(
                debit,
                credit,
                entry,
                included=True,
                errors=errors,
                tax_side=Side.CREDIT,
                expected_scope=TAX_SCOPE_SALES,
                expected_category=TAX_CATEGORY_REDUCED_EIGHT_PERCENT,
                expected_reduced_rate=True,
                allow_tax_side_subaccount=True,
            )
        elif evidence is JdlEvidenceProfile.TAX_NON_TAXABLE_PURCHASE_SUBACCOUNT_INCLUDED_1111:
            self._validate_tax(
                debit,
                credit,
                entry,
                included=True,
                errors=errors,
                expected_scope=TAX_SCOPE_NON_TAXABLE_PURCHASE,
                expected_category="",
                allow_tax_side_subaccount=True,
            )
        elif evidence is JdlEvidenceProfile.TAX_NON_TAXABLE_SALES_SUBACCOUNT_INCLUDED_1111:
            self._validate_tax(
                debit,
                credit,
                entry,
                included=True,
                errors=errors,
                tax_side=Side.CREDIT,
                expected_scope=TAX_SCOPE_NON_TAXABLE_SALES,
                expected_category="",
                allow_tax_side_subaccount=True,
                expected_mapping_evidence_id="EVID-JDL-MF-TAX-NONTAXABLE-SALES-SUBACCOUNT-ROUNDTRIP-001",
            )
        elif evidence is JdlEvidenceProfile.TAX_OUT_OF_SCOPE_SUBACCOUNT_INCLUDED_1111:
            self._validate_tax(
                debit,
                credit,
                entry,
                included=True,
                errors=errors,
                expected_scope="",
                expected_category="",
                allow_tax_side_subaccount=True,
                expected_mapping_evidence_id="EVID-JDL-MF-TAX-OUT-OF-SCOPE-SUBACCOUNT-ROUNDTRIP-001",
            )
        elif evidence is JdlEvidenceProfile.TAX_EXCLUDED_1111:
            self._validate_tax(debit, credit, entry, included=False, errors=errors)

    def _validate_account(
        self,
        line: JournalLine,
        entry: JournalEntry,
        errors: list[ValidationResult],
    ) -> None:
        identity = self._account_identity(line.account)
        if not line.account or (
            self.context.account_master and identity is None
        ) or (
            not self.context.account_master and line.account not in self.context.accounts
        ):
            errors.append(self._error("JDL-OUT-ACCOUNT-MASTER", "確認済み取込先科目に一致しません。", "account", entry))
        elif identity is None and len(line.account) > 4:
            errors.append(self._error("JDL-OUT-ACCOUNT-LENGTH", "v0の科目名称identifierは4文字以内です。", "account", entry))

    def _validate_amount(
        self,
        amount: Decimal,
        entry: JournalEntry,
        errors: list[ValidationResult],
    ) -> None:
        if amount < 0 or amount != amount.to_integral_value():
            errors.append(self._error("JDL-OUT-AMOUNT", "金額は0以上の整数円で指定してください。", "amount", entry))

    def _validate_subaccount(
        self,
        debit: JournalLine,
        credit: JournalLine,
        entry: JournalEntry,
        errors: list[ValidationResult],
    ) -> None:
        self._require_tax_mode(JdlTaxProcessingMode.EXEMPT, entry, errors)
        if debit.sub_account or debit.department or credit.department or debit.tax_info or credit.tax_info:
            errors.append(self._error("JDL-OUT-SUBACCOUNT-COMBINATION", "検証済み貸方補助以外のfeatureを併用できません。", "evidence_profile", entry))
        identity = self._subaccount_identity(credit)
        if not credit.sub_account or identity is None:
            errors.append(self._error("JDL-OUT-SUBACCOUNT-MASTER", "貸方補助と親科目の完全一致確認が必要です。", "sub_account", entry))

    def _validate_department(
        self,
        debit: JournalLine,
        credit: JournalLine,
        entry: JournalEntry,
        errors: list[ValidationResult],
    ) -> None:
        self._require_tax_mode(JdlTaxProcessingMode.EXEMPT, entry, errors)
        if not self.context.department_processing_enabled:
            errors.append(self._error("JDL-OUT-DEPARTMENT-DISABLED", "取込先の部門処理確認が必要です。", "department", entry))
        if debit.sub_account or credit.sub_account or debit.tax_info or credit.tax_info:
            errors.append(self._error("JDL-OUT-DEPARTMENT-COMBINATION", "部門profileに補助・税を併用できません。", "evidence_profile", entry))
        if not debit.department or not credit.department:
            errors.append(self._error("JDL-OUT-DEPARTMENT-BOTH-SIDES", "検証済みscopeでは借貸両側の部門指定が必要です。", "department", entry))
        for line in (debit, credit):
            if line.department and self._department_identity(line.department) is None:
                errors.append(self._error("JDL-OUT-DEPARTMENT-MASTER", "確認済み取込先部門に一致しません。", "department", entry))

    def _validate_tax(
        self,
        debit: JournalLine,
        credit: JournalLine,
        entry: JournalEntry,
        *,
        included: bool,
        errors: list[ValidationResult],
        tax_side: Side = Side.DEBIT,
        expected_scope: str = TAX_SCOPE_PURCHASE,
        expected_category: str = TAX_CATEGORY_TEN_PERCENT,
        expected_reduced_rate: bool = False,
        allow_tax_side_subaccount: bool = False,
        allow_opposite_subaccount: bool = False,
        expected_credit_method: str = "INDIVIDUAL",
        expected_mapping_evidence_id: str | None = None,
    ) -> None:
        expected_mode = (
            JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED
            if included
            else JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED
        )
        self._require_tax_mode(expected_mode, entry, errors)
        if (
            not self.context.standard_taxation_confirmed
            or self.context.effective_input_tax_credit_method.value != expected_credit_method
        ):
            errors.append(self._error("JDL-OUT-TAX-COMPANY-PROFILE", "原則課税の仕入税額控除方式がEvidenceと一致しません。", "tax_processing", entry))
        tax_line = debit if tax_side is Side.DEBIT else credit
        opposite_line = credit if tax_side is Side.DEBIT else debit
        if (
            debit.department
            or credit.department
            or (opposite_line.sub_account and not allow_opposite_subaccount)
            or (tax_line.sub_account and not allow_tax_side_subaccount)
        ):
            errors.append(self._error("JDL-OUT-TAX-COMBINATION", "検証済み税profileに補助・部門を併用できません。", "evidence_profile", entry))
        configured_subaccounts = tuple(
            item
            for item in self.context.subaccounts
            if item.parent_account == tax_line.account
        )
        if configured_subaccounts and not tax_line.sub_account:
            errors.append(
                self._error(
                    "JDL-OUT-TARGET-SUBACCOUNT-REQUIRED",
                    "取込先科目には補助科目が設定されているため、確認済み補助が必要です。",
                    "sub_account",
                    entry,
                )
            )
        if tax_line.sub_account and (
            not allow_tax_side_subaccount
            or self._subaccount_identity(tax_line) is None
        ):
            errors.append(
                self._error(
                    "JDL-OUT-TAX-SUBACCOUNT-MASTER",
                    "税対象sideの補助科目と親科目が確認済みmasterに一致しません。",
                    "sub_account",
                    entry,
                )
            )
        info = tax_line.tax_info
        if info is None or info.category != expected_category or info.metadata.get("jdl_tax_scope") != expected_scope:
            errors.append(self._error("JDL-OUT-TAX-LITERAL", "検証済み課区・税区のexact literalが必要です。", "tax", entry))
            return
        if (
            expected_mapping_evidence_id is not None
            and info.metadata.get("jdl_evidence_id") != expected_mapping_evidence_id
        ):
            errors.append(
                self._error(
                    "JDL-OUT-TAX-SEMANTIC-IDENTITY",
                    "対象外は専用Evidenceで明示確認されたmappingだけ使用できます。",
                    "tax",
                    entry,
                )
            )
        expected_rate = Decimal("8") if expected_reduced_rate else Decimal("10")
        reduced_rate_mismatch = (
            info.reduced_rate not in {None, True}
            if expected_reduced_rate
            else info.reduced_rate is True
        )
        if reduced_rate_mismatch or info.rate not in {None, expected_rate}:
            errors.append(self._error("JDL-OUT-TAX-RATE", "Evidence profileと一致する税率指定が必要です。", "tax", entry))
        if self._nonempty_tax(opposite_line.tax_info):
            errors.append(self._error("JDL-OUT-OPPOSITE-TAX", "Evidence対象外sideの課税値は使用できません。", "tax", entry))
        if info.metadata.get("jdl_transaction_account"):
            errors.append(self._error("JDL-OUT-TRANSACTION-ACCOUNT", "取引科目を必要とするcaseは未対応です。", "tax", entry))
        method = info.metadata.get("jdl_tax_input_method")
        if included:
            if method not in {None, ""} or info.tax_amount is not None:
                errors.append(self._error("JDL-OUT-TAX-INCLUDED-FIELDS", "税込profileでは税入力方法・消費税を出力しません。", "tax", entry))
        elif method != TAX_INPUT_METHOD_INTERNAL or info.tax_amount is None:
            errors.append(self._error("JDL-OUT-TAX-EXCLUDED-FIELDS", "税抜profileには内税と明示消費税額が必要です。", "tax", entry))
        elif info.tax_amount < 0 or info.tax_amount != info.tax_amount.to_integral_value():
            errors.append(self._error("JDL-OUT-TAX-AMOUNT", "消費税額は0以上の整数円で指定してください。", "tax", entry))
        else:
            observed_tax_amount = (tax_line.amount * Decimal("10") / Decimal("110")).quantize(
                Decimal("1"),
                rounding=ROUND_DOWN,
            )
            if info.tax_amount != observed_tax_amount:
                errors.append(
                    self._error(
                        "JDL-OUT-TAX-AMOUNT-PATTERN",
                        "明示消費税額が検証済み10%内税・端数切捨てpatternと一致しません。",
                        "tax",
                        entry,
                    )
                )

    def _validate_file_combination(
        self,
        entries: Sequence[JournalEntry],
        profiles: tuple[JdlEvidenceProfile, ...],
        errors: list[ValidationResult],
    ) -> None:
        verified_mixed_batch = (
            profiles == MIXED_BATCH_PROFILE_SEQUENCE
            and len(entries) == len(MIXED_BATCH_PROFILE_SEQUENCE)
            and len({entry.date for entry in entries}) == 1
        )
        if verified_mixed_batch:
            return
        experimental_six_tax_batch = (
            profiles == SIX_TAX_BATCH_PROFILE_SEQUENCE
            and len(entries) == len(SIX_TAX_BATCH_PROFILE_SEQUENCE)
            and len({entry.date for entry in entries}) == len(entries)
        )
        if experimental_six_tax_batch:
            return
        if profiles == MF_TAX_EXCLUDED_PROPORTIONAL_13_SEQUENCE:
            return
        if len(profiles) == 1:
            return
        allowed = (JdlEvidenceProfile.BASIC_1111, JdlEvidenceProfile.COMPOUND_1D3C)
        verified_simple_pair = (
            profiles == (JdlEvidenceProfile.BASIC_1111,) * 2
            and len(entries) == 2
            and entries[0].date == entries[1].date
        )
        if not verified_simple_pair and (
            profiles != allowed
            or len(entries) != 2
            or entries[0].date != entries[1].date
        ):
            errors.append(
                self._error(
                    "JDL-OUT-MULTIGROUP-SCOPE",
                    "複数groupは検証済みの同日1111+1111または1111+compound構成だけ対応します。",
                    "journal_groups",
                )
            )

    def _validate_serializable_rows(
        self,
        rows: Sequence[JdlOutputRow],
        errors: list[ValidationResult],
    ) -> None:
        spec = jdl_ibex_cashbook_official_journal_import_spec()
        for row in rows:
            columns = row.columns()
            if len(columns) != spec.column_count:
                errors.append(self._error("JDL-OUT-COLUMN-COUNT", "JDL出力行は30列である必要があります。", "column_count"))
                continue
            for definition, value in zip(spec.columns, columns, strict=True):
                if definition.max_length is not None and len(value) > definition.max_length:
                    errors.append(self._error("JDL-OUT-FIELD-LENGTH", "JDL項目の最大文字数を超えています。", definition.name))
                try:
                    encoded = value.encode("cp932", errors="strict")
                    if encoded.decode("cp932", errors="strict") != value:
                        raise UnicodeError("CP932 round-trip mismatch")
                except UnicodeError:
                    errors.append(self._error("JDL-OUT-CP932", "CP932へ損失なく変換できない文字を検出しました。", definition.name))
                if value and definition.data_type == "数値" and not value.isdecimal():
                    errors.append(self._error("JDL-OUT-NUMERIC-FIELD", "数値項目に数字以外が含まれています。", definition.name))
                if value and definition.data_type == "金額":
                    try:
                        amount = Decimal(value)
                    except InvalidOperation:
                        amount = Decimal("-1")
                    if amount < 0 or amount != amount.to_integral_value():
                        errors.append(self._error("JDL-OUT-AMOUNT-FIELD", "金額項目は0以上の整数円である必要があります。", definition.name))
                if value and definition.data_type == "日付":
                    try:
                        datetime.strptime(value, "%Y%m%d")
                    except ValueError:
                        errors.append(self._error("JDL-OUT-DATE-FIELD", "日付は有効なYYYYMMDDである必要があります。", definition.name))

    def _row(
        self,
        flag: str,
        entry: JournalEntry,
        debit: JournalLine | None,
        credit: JournalLine | None,
        description: str,
    ) -> JdlOutputRow:
        debit_account = self._account_identity(debit.account) if debit else None
        credit_account = self._account_identity(credit.account) if credit else None
        debit_sub = self._subaccount_identity(debit) if debit else None
        credit_sub = self._subaccount_identity(credit)
        debit_department = self._department_identity(debit.department) if debit and debit.department else None
        credit_department = self._department_identity(credit.department) if credit and credit.department else None
        debit_tax = debit.tax_info if debit else None
        credit_tax = credit.tax_info if credit else None
        return JdlOutputRow(
            identifier_flag=flag,
            voucher_number="",
            journal_date=entry.date.strftime("%Y%m%d"),
            debit_account_code=(debit_account.target_master_code if debit_account else ""),
            debit_account_name=(
                debit_account.target_name
                if debit_account else debit.account if debit and debit.account else ""
            ),
            debit_account_formal_name=(
                debit_account.target_formal_name if debit_account else ""
            ),
            debit_subaccount_code=debit_sub.output_code if debit_sub else "",
            debit_subaccount_name=debit_sub.output_name if debit_sub else "",
            debit_tax_scope=self._tax_metadata(debit_tax, "jdl_tax_scope"),
            debit_tax_category=debit_tax.category if debit_tax and debit_tax.category else "",
            debit_tax_input_method=self._tax_metadata(debit_tax, "jdl_tax_input_method"),
            debit_amount=self._amount(debit.amount) if debit else "0",
            debit_tax_amount=self._optional_amount(debit_tax.tax_amount if debit_tax else None),
            credit_account_code=(credit_account.target_master_code if credit_account else ""),
            credit_account_name=(
                credit_account.target_name
                if credit_account else credit.account if credit and credit.account else ""
            ),
            credit_account_formal_name=(
                credit_account.target_formal_name if credit_account else ""
            ),
            credit_subaccount_code=credit_sub.output_code if credit_sub else "",
            credit_subaccount_name=credit_sub.output_name if credit_sub else "",
            credit_tax_scope=self._tax_metadata(credit_tax, "jdl_tax_scope"),
            credit_tax_category=credit_tax.category if credit_tax and credit_tax.category else "",
            credit_tax_input_method=self._tax_metadata(credit_tax, "jdl_tax_input_method"),
            credit_amount=self._amount(credit.amount) if credit else "0",
            credit_tax_amount=self._optional_amount(credit_tax.tax_amount if credit_tax else None),
            description=description,
            debit_transaction_account="",
            credit_transaction_account="",
            debit_department_code=debit_department.output_code if debit_department else "",
            debit_department_name=debit_department.output_name if debit_department else "",
            credit_department_code=credit_department.output_code if credit_department else "",
            credit_department_name=credit_department.output_name if credit_department else "",
        )

    def _account_identity(self, value: str | None):
        if not value:
            return None
        matches = tuple(
            item for item in self.context.account_master
            if item.mapping_value == value
        )
        return matches[0] if len(matches) == 1 else None

    def _subaccount_identity(self, line: JournalLine | None) -> JdlSubaccountIdentity | None:
        if line is None or not line.account or not line.sub_account:
            return None
        return next(
            (
                item
                for item in self.context.subaccounts
                if item.parent_account == line.account and item.mapping_value == line.sub_account
            ),
            None,
        )

    def _validate_optional_subaccount(
        self, line: JournalLine | None, entry: JournalEntry, errors: list[ValidationResult]
    ) -> None:
        if line is not None and line.sub_account and self._subaccount_identity(line) is None:
            errors.append(self._error("JDL-OUT-SUBACCOUNT-MASTER", "補助科目が確認済みmasterと一致しません。", "sub_account", entry))

    def _department_identity(self, value: str | None) -> JdlDepartmentIdentity | None:
        if not value:
            return None
        return next((item for item in self.context.departments if item.mapping_value == value), None)

    def _require_tax_mode(
        self,
        expected: JdlTaxProcessingMode,
        entry: JournalEntry,
        errors: list[ValidationResult],
    ) -> None:
        if self.context.tax_processing_mode is not expected:
            errors.append(self._error("JDL-OUT-TAX-MODE", "会社の消費税処理がEvidence profileと一致しません。", "tax_processing", entry))

    @staticmethod
    def _has_optional_features(line: JournalLine) -> bool:
        return bool(line.sub_account or line.department or JdlOutputPreflight._nonempty_tax(line.tax_info))

    @staticmethod
    def _nonempty_tax(info: TaxInfo | None) -> bool:
        return bool(
            info
            and (
                info.category
                or info.rate is not None
                or info.tax_inclusion
                or info.reduced_rate is True
                or info.invoice_classification
                or info.tax_amount is not None
                or info.metadata.get("jdl_tax_scope")
                or info.metadata.get("jdl_tax_input_method")
                or info.metadata.get("jdl_transaction_account")
            )
        )

    @staticmethod
    def _tax_metadata(info: TaxInfo | None, key: str) -> str:
        if info is None:
            return ""
        value = info.metadata.get(key, "")
        return value if isinstance(value, str) else ""

    @staticmethod
    def _amount(value: Decimal) -> str:
        return str(value.quantize(Decimal("1")))

    @staticmethod
    def _optional_amount(value: Decimal | None) -> str:
        return "" if value is None else str(value.quantize(Decimal("1")))

    @staticmethod
    def _error(
        rule_id: str,
        message: str,
        field: str,
        entry: JournalEntry | None = None,
    ) -> ValidationResult:
        return ValidationResult(
            severity=Severity.ERROR,
            rule_id=rule_id,
            message=message,
            journal_id=entry.id if entry else None,
            source_reference=entry.source_reference if entry else None,
            field=field,
            suggested_action="検証済みEvidence scopeと取込先master設定を確認してください。",
        )


def jdl_ibex_35_5_output_profile() -> FormatProfile:
    return FormatProfile(
        software="JDL",
        product="JDL IBEX 出納帳",
        version="35.5",
        format_id=JDL_OUTPUT_FORMAT_ID,
        encoding="cp932",
        delimiter=",",
        date_format="%Y%m%d",
        journal_structure="evidence-limited-v0",
        columns=tuple(),
    )
