from __future__ import annotations

import csv
import io
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from accounting_converter.domain.format_metadata import EvidenceLevel
from accounting_converter.profiles.jdl_official import (
    jdl_ibex_cashbook_official_journal_import_spec,
)


EVIDENCE_ID_1111 = "EVID-JDL-GENERATOR-1111-001"
EVIDENCE_ID_1000 = "EVID-JDL-GENERATOR-1000-001"
EVIDENCE_ID_1000_SUBACCOUNT = "EVID-JDL-GENERATOR-1000-SUBACCOUNT-001"
EVIDENCE_ID_DEPARTMENT_HAND_1111 = "EVID-JDL-DEPARTMENT-HAND-1111-001"
EVIDENCE_ID_1111_DEPARTMENT = "EVID-JDL-GENERATOR-1111-DEPARTMENT-001"
EVIDENCE_ID_TAX_INCLUSIVE_HAND_1111 = "EVID-JDL-TAX-INCLUSIVE-HAND-1111-001"
EVIDENCE_ID_1111_TAX_INCLUSIVE = "EVID-JDL-GENERATOR-1111-TAX-INCLUSIVE-001"
EVIDENCE_ID_TAX_EXCLUSIVE_HAND_1111 = "EVID-JDL-TAX-EXCLUSIVE-HAND-1111-001"
EVIDENCE_ID_1111_TAX_EXCLUSIVE = "EVID-JDL-GENERATOR-1111-TAX-EXCLUSIVE-001"
EVIDENCE_ID_COMPOUND_HAND_1110_1100_1101 = (
    "EVID-JDL-COMPOUND-HAND-1110-1100-1101-001"
)
EVIDENCE_ID_GENERATOR_COMPOUND_1110_1100_1101 = (
    "EVID-JDL-GENERATOR-COMPOUND-1110-1100-1101-001"
)
EVIDENCE_ID_GENERATOR_MULTIGROUP_SIMPLE_COMPOUND = (
    "EVID-JDL-GENERATOR-MULTIGROUP-SIMPLE-COMPOUND-001"
)
EVIDENCE_ID_CONVERSION_SERVICE_E2E = "EVID-JDL-CONVERSION-SERVICE-E2E-001"
EVIDENCE_ID_YAYOI_TO_JDL_E2E = "EVID-JDL-YAYOI-TO-JDL-E2E-001"
EVIDENCE_ID_CONTEXT_AWARE_RUNTIME_E2E = (
    "EVID-JDL-CONTEXT-AWARE-RUNTIME-E2E-001"
)
EVIDENCE_ID_SIMPLE_PLUS_SIMPLE_RUNTIME = (
    "EVID-JDL-SIMPLE-PLUS-SIMPLE-RUNTIME-001"
)
EVIDENCE_ID = EVIDENCE_ID_1111
VERIFIED_ARTIFACT_STATUS = "GENERATOR_AUTHORED_1111_VERIFIED_BY_REAL_IMPORT_SCOPED"
VERIFIED_ARTIFACT_STATUS_1000 = "GENERATOR_AUTHORED_1000_VERIFIED_BY_REAL_IMPORT_SCOPED"
VERIFIED_ARTIFACT_STATUS_1000_SUBACCOUNT = (
    "GENERATOR_AUTHORED_1000_SUBACCOUNT_VERIFIED_BY_REAL_IMPORT_SCOPED"
)
VERIFIED_ARTIFACT_STATUS_1111_DEPARTMENT = (
    "GENERATOR_AUTHORED_1111_DEPARTMENT_VERIFIED_BY_REAL_IMPORT_SCOPED"
)
DEPARTMENT_1000_EXPERIMENT_STATUS = "INCONCLUSIVE_NOT_VERIFIED"
VERIFIED_ARTIFACT_STATUS_1111_TAX_INCLUSIVE = (
    "GENERATOR_AUTHORED_1111_TAX_INCLUSIVE_VERIFIED_BY_REAL_IMPORT_SCOPED"
)
VERIFIED_ARTIFACT_STATUS_1111_TAX_EXCLUSIVE = (
    "GENERATOR_AUTHORED_1111_TAX_EXCLUSIVE_VERIFIED_BY_REAL_IMPORT_SCOPED"
)
VERIFIED_ARTIFACT_STATUS_CONVERSION_SERVICE_E2E = (
    "CONVERSION_SERVICE_E2E_VERIFIED_BY_REAL_IMPORT_SCOPED"
)
VERIFIED_ARTIFACT_STATUS_YAYOI_TO_JDL_E2E = (
    "YAYOI_TO_JDL_E2E_VERIFIED_BY_REAL_IMPORT_SCOPED"
)
VERIFIED_ARTIFACT_STATUS_CONTEXT_AWARE_RUNTIME_E2E = (
    "CONTEXT_AWARE_RUNTIME_E2E_VERIFIED_BY_REAL_IMPORT_SCOPED"
)
OFFICIAL_HEADER = jdl_ibex_cashbook_official_journal_import_spec().column_names


class RuntimeReexportFieldStatus(str, Enum):
    INPUT_PRESERVED = "INPUT_PRESERVED"
    INPUT_BLANK_REEXPORT_NONBLANK = "INPUT_BLANK_REEXPORT_NONBLANK"
    INPUT_NONBLANK_REEXPORT_BLANK = "INPUT_NONBLANK_REEXPORT_BLANK"
    DIFFERENT = "DIFFERENT"


@dataclass(frozen=True)
class RuntimeReexportFieldComparison:
    field_name: str
    status: RuntimeReexportFieldStatus


@dataclass(frozen=True)
class ScopedJdlImportEvidence:
    evidence_id: str
    evidence_level: EvidenceLevel
    product: str
    observed_version: str
    verified_scope: tuple[str, ...]
    not_verified: tuple[str, ...]
    production_output_enabled: bool = False


@dataclass(frozen=True)
class GeneratorRuntimeComparison:
    evidence_id: str
    identifier_flag: str
    candidate_fields: tuple[RuntimeReexportFieldComparison, ...]
    candidate_structure: dict[str, Any]
    reexport_structure: dict[str, Any]
    reference_preserved_count: int | None = None
    reference_difference_fields: tuple[str, ...] = ()
    reference_structure: dict[str, Any] | None = None

    @property
    def status_counts(self) -> tuple[tuple[str, int], ...]:
        counts = Counter(field.status.value for field in self.candidate_fields)
        return tuple(sorted(counts.items()))

    def to_privacy_safe_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "evidence_id": self.evidence_id,
            "identifier_flag": self.identifier_flag,
            "candidate_to_reexport_status_counts": dict(self.status_counts),
            "candidate_to_reexport_fields": [
                {"field": item.field_name, "status": item.status.value}
                for item in self.candidate_fields
            ],
            "structures": {
                "candidate": self.candidate_structure,
                "runtime_reexport": self.reexport_structure,
            },
            "interpretation": (
                "Nonblank re-export fields show re-export representation only; "
                "they are not generator defaults or proof of internal storage values."
            ),
            "privacy_note": (
                "Field values, account names, descriptions, dates, amounts, "
                "voucher values, and raw rows are omitted."
            ),
        }
        if self.reference_structure is not None:
            payload["structures"]["reference_export"] = self.reference_structure
            payload["reference_to_reexport_preserved_count"] = (
                self.reference_preserved_count
            )
            payload["reference_to_reexport_difference_fields"] = list(
                self.reference_difference_fields
            )
            payload["human_29_of_30_claim_confirmed"] = (
                self.reference_preserved_count == 29
                and self.reference_difference_fields == ("伝番",)
            )
        return payload


Generator1111RuntimeComparison = GeneratorRuntimeComparison


@dataclass(frozen=True)
class CompoundRuntimeFieldComparison:
    record_index: int
    field_name: str
    status: RuntimeReexportFieldStatus


@dataclass(frozen=True)
class CompoundRuntimeComparison:
    evidence_id: str
    candidate_fields: tuple[CompoundRuntimeFieldComparison, ...]
    candidate_structure: dict[str, Any]
    reexport_structure: dict[str, Any]
    sequence_preserved: bool
    row_order_preserved: bool
    date_preserved: bool
    amounts_and_positions_preserved: bool
    descriptions_and_positions_preserved: bool
    candidate_vouchers_blank: bool
    reexport_vouchers_zero: bool

    @property
    def status_counts(self) -> tuple[tuple[str, int], ...]:
        counts = Counter(field.status.value for field in self.candidate_fields)
        return tuple(sorted(counts.items()))

    def to_privacy_safe_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "candidate_to_reexport_status_counts": dict(self.status_counts),
            "candidate_to_reexport_fields": [
                {
                    "record_index": item.record_index,
                    "field": item.field_name,
                    "status": item.status.value,
                }
                for item in self.candidate_fields
            ],
            "structures": {
                "candidate": self.candidate_structure,
                "runtime_reexport": self.reexport_structure,
            },
            "sequence_preserved": self.sequence_preserved,
            "row_order_preserved": self.row_order_preserved,
            "date_preserved": self.date_preserved,
            "amounts_and_positions_preserved": self.amounts_and_positions_preserved,
            "descriptions_and_positions_preserved": (
                self.descriptions_and_positions_preserved
            ),
            "candidate_vouchers_blank": self.candidate_vouchers_blank,
            "reexport_vouchers_zero": self.reexport_vouchers_zero,
            "interpretation": (
                "Blank candidate vouchers grouped successfully for this one runtime "
                "artifact; re-export zero is an observed representation, not a "
                "generator default or a general grouping rule."
            ),
            "privacy_note": (
                "Field values, account names, descriptions, dates, amounts, "
                "voucher values, and raw rows are omitted."
            ),
        }


@dataclass(frozen=True)
class MultiGroupRuntimeComparison:
    evidence_id: str
    candidate_fields: tuple[CompoundRuntimeFieldComparison, ...]
    candidate_structure: dict[str, Any]
    reexport_structure: dict[str, Any]
    flag_order_preserved: bool
    row_order_preserved: bool
    date_preserved: bool
    account_placement_preserved: bool
    amounts_and_positions_preserved: bool
    descriptions_and_positions_preserved: bool
    candidate_vouchers_blank: bool
    runtime_ui_vouchers_blank: bool
    reexport_vouchers_zero: bool
    runtime_logical_voucher_count: int
    simple_balanced: bool
    compound_balanced: bool

    @property
    def status_counts(self) -> tuple[tuple[str, int], ...]:
        counts = Counter(field.status.value for field in self.candidate_fields)
        return tuple(sorted(counts.items()))

    def to_privacy_safe_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "candidate_to_reexport_status_counts": dict(self.status_counts),
            "structures": {
                "candidate": self.candidate_structure,
                "runtime_reexport": self.reexport_structure,
            },
            "flag_order_preserved": self.flag_order_preserved,
            "row_order_preserved": self.row_order_preserved,
            "date_preserved": self.date_preserved,
            "account_placement_preserved": self.account_placement_preserved,
            "amounts_and_positions_preserved": self.amounts_and_positions_preserved,
            "descriptions_and_positions_preserved": (
                self.descriptions_and_positions_preserved
            ),
            "voucher_evidence": {
                "candidate_raw_fields_blank": self.candidate_vouchers_blank,
                "runtime_ui_fields_blank_operator_observed": (
                    self.runtime_ui_vouchers_blank
                ),
                "reexport_raw_fields_zero": self.reexport_vouchers_zero,
            },
            "runtime_logical_voucher_count_operator_observed": (
                self.runtime_logical_voucher_count
            ),
            "simple_balanced": self.simple_balanced,
            "compound_balanced": self.compound_balanced,
            "interpretation": (
                "For this artifact, same-date records with blank candidate voucher "
                "fields imported as two logical vouchers and re-exported with zero "
                "voucher fields. Zero is not a generator default or proof of an "
                "internally assigned voucher number."
            ),
            "privacy_note": (
                "Field values, account names, descriptions, dates, amounts, "
                "voucher values, and raw rows are omitted."
            ),
        }


@dataclass(frozen=True)
class SimplePairRuntimeComparison:
    evidence_id: str
    candidate_fields: tuple[CompoundRuntimeFieldComparison, ...]
    candidate_structure: dict[str, Any]
    reexport_structure: dict[str, Any]
    flag_order_preserved: bool
    row_order_preserved: bool
    date_preserved: bool
    account_placement_preserved: bool
    amounts_and_positions_preserved: bool
    descriptions_and_positions_preserved: bool
    candidate_vouchers_blank: bool
    runtime_ui_vouchers_blank: bool
    reexport_vouchers_zero: bool
    runtime_logical_voucher_count: int
    independently_balanced: bool

    @property
    def status_counts(self) -> tuple[tuple[str, int], ...]:
        counts = Counter(field.status.value for field in self.candidate_fields)
        return tuple(sorted(counts.items()))

    def to_privacy_safe_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "candidate_to_reexport_status_counts": dict(self.status_counts),
            "structures": {
                "candidate": self.candidate_structure,
                "runtime_reexport": self.reexport_structure,
            },
            "flag_order_preserved": self.flag_order_preserved,
            "row_order_preserved": self.row_order_preserved,
            "date_preserved": self.date_preserved,
            "account_placement_preserved": self.account_placement_preserved,
            "amounts_and_positions_preserved": self.amounts_and_positions_preserved,
            "descriptions_and_positions_preserved": (
                self.descriptions_and_positions_preserved
            ),
            "voucher_evidence": {
                "candidate_raw_fields_blank": self.candidate_vouchers_blank,
                "runtime_ui_fields_blank_operator_observed": (
                    self.runtime_ui_vouchers_blank
                ),
                "reexport_raw_fields_zero": self.reexport_vouchers_zero,
            },
            "runtime_logical_voucher_count_operator_observed": (
                self.runtime_logical_voucher_count
            ),
            "independently_balanced": self.independently_balanced,
            "interpretation": (
                "For this exact two-journal artifact, same-date 1111 records with "
                "blank candidate voucher fields imported as two separate vouchers. "
                "Re-export zero is not a generator default or a general numbering rule."
            ),
            "privacy_note": (
                "Field values, account names, descriptions, dates, amounts, "
                "voucher values, and raw rows are omitted."
            ),
        }


def generator_authored_1111_real_import_evidence() -> ScopedJdlImportEvidence:
    return ScopedJdlImportEvidence(
        evidence_id=EVIDENCE_ID,
        evidence_level=EvidenceLevel.VERIFIED_BY_REAL_IMPORT,
        product="JDL IBEX 出納帳",
        observed_version="35.5",
        verified_scope=(
            "generator-authored explicit-config CSV",
            "official 30-column first-row header",
            "CP932-compatible CRLF BOM-less serialization",
            "one 1111 single-line voucher record",
            "exempt company",
            "account-name-only identifiers",
            "no subaccount, department, tax fields, or transaction account",
            "balanced amounts and description",
            "runtime import completed and journal visually verified",
            "post-import JDL re-export obtained",
        ),
        not_verified=(
            "identifier flag 1000",
            "compound 1110/1100/1101",
            "subaccount",
            "department",
            "tax-inclusive and tax-exclusive processing",
            "tax abbreviations and transaction account",
            "multiple records and large data sets",
            "other JDL versions or products",
            "Yayoi to JDL end-to-end",
            "production JDLOutputAdapter",
        ),
        production_output_enabled=False,
    )


def generator_authored_1000_real_import_evidence() -> ScopedJdlImportEvidence:
    return ScopedJdlImportEvidence(
        evidence_id=EVIDENCE_ID_1000,
        evidence_level=EvidenceLevel.VERIFIED_BY_REAL_IMPORT,
        product="JDL IBEX 出納帳",
        observed_version="35.5",
        verified_scope=(
            "generator-authored explicit-config CSV",
            "official 30-column first-row header",
            "CP932-compatible CRLF BOM-less serialization",
            "one 1000 non-voucher journal record",
            "exempt company",
            "account-name-only identifiers",
            "no subaccount, department, tax fields, or transaction account",
            "balanced amounts and description",
            "runtime import completed and journal-book entry visually verified",
            "absence from voucher screen consistent with documented flag semantics",
            "post-import JDL re-export obtained",
        ),
        not_verified=(
            "subaccount",
            "department",
            "tax-inclusive and tax-exclusive processing",
            "tax abbreviations and transaction account",
            "compound 1110/1100/1101",
            "multiple records and large data sets",
            "other JDL versions or products",
            "Yayoi to JDL end-to-end",
            "production JDLOutputAdapter",
        ),
        production_output_enabled=False,
    )


def generator_authored_1000_subaccount_real_import_evidence() -> ScopedJdlImportEvidence:
    return ScopedJdlImportEvidence(
        evidence_id=EVIDENCE_ID_1000_SUBACCOUNT,
        evidence_level=EvidenceLevel.VERIFIED_BY_REAL_IMPORT,
        product="JDL IBEX 出納帳",
        observed_version="35.5",
        verified_scope=(
            "one exact generator-authored 1000 non-voucher artifact",
            "official 30-column first-row header",
            "CP932-compatible CRLF BOM-less serialization",
            "exempt company with no department or tax fields",
            "credit subaccount displayed under the confirmed parent account",
            "candidate numeric subaccount representation 0001",
            "target master actual subaccount code 1",
            "raw post-import re-export subaccount representation 1",
            "runtime import completed for one balanced record",
            "journal-book account, subaccount, amounts, and description visually verified",
            "post-import JDL re-export raw structure and subaccount fields verified",
        ),
        not_verified=(
            "general leading-zero equivalence for numeric subaccount identifiers",
            "whether generators should emit 1 or 0001",
            "other subaccount codes, parent accounts, JDL versions, or products",
            "debit subaccount",
            "department",
            "tax-inclusive and tax-exclusive processing",
            "compound 1110/1100/1101",
            "multiple records and large data sets",
            "Yayoi to JDL end-to-end",
            "production JDLOutputAdapter",
        ),
        production_output_enabled=False,
    )


def department_hand_entry_1111_observed_evidence() -> ScopedJdlImportEvidence:
    return ScopedJdlImportEvidence(
        evidence_id=EVIDENCE_ID_DEPARTMENT_HAND_1111,
        evidence_level=EvidenceLevel.OBSERVED,
        product="JDL IBEX 出納帳",
        observed_version="35.5",
        verified_scope=(
            "real-runtime manual-entry export observation",
            "one 1111 single-line voucher record",
            "department processing enabled",
            "operator selected the department on the debit side",
            "raw re-export populated both debit and credit department fields",
            "both re-export department codes used representation 1",
            "both re-export department names used the confirmed short name",
            "CP932-compatible CRLF BOM-less export with three-row preamble",
        ),
        not_verified=(
            "generator-authored department import",
            "identifier flag 1000 department behavior",
            "department is required on both sides",
            "all JDL exports duplicate a one-sided department",
            "other department codes, accounts, JDL versions, or products",
            "production JDLOutputAdapter",
        ),
        production_output_enabled=False,
    )


def generator_authored_1111_department_real_import_evidence(
) -> ScopedJdlImportEvidence:
    return ScopedJdlImportEvidence(
        evidence_id=EVIDENCE_ID_1111_DEPARTMENT,
        evidence_level=EvidenceLevel.VERIFIED_BY_REAL_IMPORT,
        product="JDL IBEX 出納帳",
        observed_version="35.5",
        verified_scope=(
            "one exact generator-authored 1111 single-line voucher artifact",
            "official 30-column first-row header",
            "CP932-compatible CRLF BOM-less serialization",
            "exempt company with no subaccount or tax fields",
            "department processing enabled with confirmed target master",
            "both debit and credit department fields explicitly generated",
            "one balanced record with description",
            "runtime import completed and one voucher visually verified",
            "debit department displayed in the runtime UI",
            "post-import JDL re-export obtained",
            "all four department fields preserved in the raw re-export",
        ),
        not_verified=(
            "identifier flag 1000 department semantics",
            "debit-only or credit-only department input",
            "why the runtime UI appeared blank on the credit side",
            "whether department fields must always be populated on both sides",
            "other department codes, hierarchical departments, or allocation settings",
            "taxable, tax-inclusive, or tax-exclusive processing",
            "tax abbreviations and transaction account",
            "compound voucher and multiple-record or large data sets",
            "other JDL versions or products",
            "Yayoi to JDL end-to-end",
            "production JDLOutputAdapter",
        ),
        production_output_enabled=False,
    )


def tax_inclusive_hand_entry_1111_observed_evidence() -> ScopedJdlImportEvidence:
    return ScopedJdlImportEvidence(
        evidence_id=EVIDENCE_ID_TAX_INCLUSIVE_HAND_1111,
        evidence_level=EvidenceLevel.OBSERVED,
        product="JDL IBEX 出納帳",
        observed_version="35.5",
        verified_scope=(
            "real-runtime manual-entry export observation",
            "one 1111 single-line voucher record",
            "taxable company using standard taxation and individual attribution",
            "tax-included accounting with downward sales/purchase rounding",
            "separately stated consumption tax disabled",
            "department processing disabled and no subaccount",
            "debit-side tax scope/category populated by the runtime UI",
            "credit-side tax classification blank in UI and raw export",
            "CP932-compatible CRLF BOM-less export with three-row preamble",
        ),
        not_verified=(
            "generator-authored tax-inclusive import from this observation alone",
            "other tax scope/category abbreviations or tax rates",
            "tax amount zero as a generator default",
            "department code zero as a generator default",
            "tax-exclusive processing",
            "simplified taxation or other input-tax-credit methods",
            "transaction account requirements for consumption-tax journals",
            "other accounts, JDL versions, or products",
            "production JDLOutputAdapter",
        ),
        production_output_enabled=False,
    )


def generator_authored_1111_tax_inclusive_real_import_evidence(
) -> ScopedJdlImportEvidence:
    return ScopedJdlImportEvidence(
        evidence_id=EVIDENCE_ID_1111_TAX_INCLUSIVE,
        evidence_level=EvidenceLevel.VERIFIED_BY_REAL_IMPORT,
        product="JDL IBEX 出納帳",
        observed_version="35.5",
        verified_scope=(
            "one exact generator-authored 1111 single-line voucher artifact",
            "official 30-column first-row header",
            "CP932-compatible CRLF BOM-less serialization",
            "taxable company using standard taxation and individual attribution",
            "tax-included accounting with downward sales/purchase rounding",
            "separately stated consumption tax disabled",
            "one raw-confirmed debit tax scope/category combination at 10 percent",
            "tax input method, transaction accounts, and credit classification blank",
            "no subaccount or department input",
            "one balanced record with description",
            "runtime import completed and one voucher visually verified",
            "post-import JDL re-export obtained",
            "exact debit tax scope including U+3000 preserved in raw re-export",
        ),
        not_verified=(
            "other tax scopes, categories, or rates including reduced 8 percent",
            "sales-side tax classification",
            "tax-exclusive accounting",
            "tax input method variants or explicit tax amount input",
            "transaction account behavior",
            "identifier flag 1000 tax semantics",
            "compound voucher, mixed rates, or multiple taxable rows",
            "multiple-record or large data sets",
            "other JDL versions or products",
            "Yayoi to JDL end-to-end",
            "production JDLOutputAdapter",
        ),
        production_output_enabled=False,
    )


def tax_exclusive_hand_entry_1111_observed_evidence() -> ScopedJdlImportEvidence:
    return ScopedJdlImportEvidence(
        evidence_id=EVIDENCE_ID_TAX_EXCLUSIVE_HAND_1111,
        evidence_level=EvidenceLevel.OBSERVED,
        product="JDL IBEX 出納帳",
        observed_version="35.5",
        verified_scope=(
            "real-runtime manual-entry export observation",
            "one 1111 single-line voucher record",
            "taxable company using standard taxation and individual attribution",
            "company accounting method configured as tax-exclusive",
            "operator explicitly selected the tax-exclusive UI input mode",
            "UI input mode and CSV tax-input-method field kept as separate evidence",
            "one exact debit tax scope/category/input-method/amount representation",
            "credit-side tax classification and input method blank in the raw export",
            "no subaccount and department processing disabled",
            "CP932-compatible CRLF BOM-less export with three-row preamble",
        ),
        not_verified=(
            "generator-authored tax-exclusive import from this observation alone",
            "semantic equivalence of the UI input mode and CSV tax-input-method field",
            "other tax scopes, categories, rates, input methods, or tax amounts",
            "sales-side tax classification",
            "transaction account behavior",
            "identifier flag 1000 tax semantics",
            "compound voucher, mixed rates, or multiple taxable rows",
            "multiple-record or large data sets",
            "other JDL versions or products",
            "Yayoi to JDL end-to-end",
            "production JDLOutputAdapter",
        ),
        production_output_enabled=False,
    )


def compound_hand_entry_1110_1100_1101_observed_evidence(
) -> ScopedJdlImportEvidence:
    return ScopedJdlImportEvidence(
        evidence_id=EVIDENCE_ID_COMPOUND_HAND_1110_1100_1101,
        evidence_level=EvidenceLevel.OBSERVED,
        product="JDL IBEX 出納帳",
        observed_version="35.5",
        verified_scope=(
            "real-runtime manual-entry export observation",
            "one three-record voucher candidate",
            "exact 1110/1100/1101 sequence",
            "same nonblank voucher number and date across all three records",
            "one debit total balanced against three credit amounts",
            "first record contains both debit and credit accounts",
            "middle and final records contain credit accounts with blank debit accounts",
            "required missing-side debit amounts represented as numeric zero",
            "description populated on the first record only",
            "exempt company with no subaccount, department, or tax classification",
            "CP932-compatible CRLF BOM-less export with three-row preamble",
        ),
        not_verified=(
            "generator-authored compound import",
            "blank voucher-number behavior for compound import",
            "all possible 1110/1100*/1101 shapes or line counts",
            "multiple debit lines or many-to-many compound vouchers",
            "subaccount, department, or taxable compound vouchers",
            "multiple vouchers or large data sets",
            "other JDL versions or products",
            "Yayoi to JDL end-to-end",
            "production JDLOutputAdapter",
        ),
        production_output_enabled=False,
    )


def generator_authored_compound_real_import_evidence() -> ScopedJdlImportEvidence:
    return ScopedJdlImportEvidence(
        evidence_id=EVIDENCE_ID_GENERATOR_COMPOUND_1110_1100_1101,
        evidence_level=EvidenceLevel.VERIFIED_BY_REAL_IMPORT,
        product="JDL IBEX 出納帳",
        observed_version="35.5",
        verified_scope=(
            "one exact generator-authored three-record compound artifact",
            "official 30-column first-row header",
            "CP932-compatible CRLF BOM-less serialization",
            "exact 1110/1100/1101 sequence and row order",
            "same date across all three records",
            "blank voucher field on all candidate records",
            "runtime recognized three records and grouped them into one voucher",
            "one debit balanced against three credits",
            "first record description with later descriptions blank",
            "exempt company with no subaccount, department, or tax fields",
            "runtime import completed and one voucher visually verified",
            "no duplicate voucher observed",
            "post-import JDL re-export obtained",
        ),
        not_verified=(
            "multiple compound vouchers in one file",
            "nonblank supplied voucher-number behavior",
            "two-debit/one-credit or many-to-many generator import",
            "longer 1100 chains",
            "tax, subaccount, department, or mixed tax rates inside compound vouchers",
            "multiple simple and compound groups or large data sets",
            "blank-voucher behavior outside this exact single-group artifact",
            "sequence-only grouping as a general JDL rule",
            "other JDL versions or products",
            "Yayoi to JDL end-to-end",
            "production JDLOutputAdapter",
        ),
        production_output_enabled=False,
    )


def generator_authored_multi_group_real_import_evidence() -> ScopedJdlImportEvidence:
    return ScopedJdlImportEvidence(
        evidence_id=EVIDENCE_ID_GENERATOR_MULTIGROUP_SIMPLE_COMPOUND,
        evidence_level=EvidenceLevel.VERIFIED_BY_REAL_IMPORT,
        product="JDL IBEX 出納帳",
        observed_version="35.5",
        verified_scope=(
            "one exact generator-authored four-record artifact",
            "official 30-column first-row header",
            "CP932-compatible CRLF BOM-less serialization",
            "one CSV containing 1111 then 1110/1100/1101",
            "same date and blank candidate voucher field across all four records",
            "runtime recognized four records and produced exactly two vouchers",
            "simple and compound groups remained separate without split or duplicate",
            "simple and compound balances, row order, and descriptions preserved",
            "runtime UI voucher-number fields observed blank for both vouchers",
            "post-import JDL re-export obtained with voucher representation zero",
        ),
        not_verified=(
            "simple plus simple or compound plus compound boundaries",
            "three or more logical groups",
            "nonblank supplied voucher numbers",
            "arbitrary group order or repeated same-flag group boundaries",
            "longer 1100 chains, two-debit/one-credit, or many-to-many compounds",
            "tax, subaccount, or department inside compound vouchers",
            "monthly-scale or large data sets",
            "general blank-to-zero voucher conversion or internal numbering semantics",
            "other JDL versions or products",
            "Yayoi to JDL end-to-end",
            "production JDLOutputAdapter",
        ),
        production_output_enabled=False,
    )


def conversion_service_e2e_real_import_evidence() -> ScopedJdlImportEvidence:
    return ScopedJdlImportEvidence(
        evidence_id=EVIDENCE_ID_CONVERSION_SERVICE_E2E,
        evidence_level=EvidenceLevel.VERIFIED_BY_REAL_IMPORT,
        product="JDL IBEX 出納帳",
        observed_version="35.5",
        verified_scope=(
            "formal ConversionService path with confirmed ConversionProfile mappings",
            "JdlOutputPreflight, JDLOutputAdapter, JDLOutputValidator, and atomic publish",
            "official 30-column first-row header and CP932 CRLF BOM-less serialization",
            "one 1111 simple journal followed by one 1110/1100/1101 compound journal",
            "same date and blank candidate voucher fields across all four records",
            "runtime recognized four records and produced exactly two vouchers",
            "no merge, compound split, or duplicate observed",
            "balances, account placement, descriptions, and group boundaries preserved",
            "runtime UI voucher fields observed blank for both vouchers",
            "post-import JDL self re-export obtained and compared across 120 fields",
        ),
        not_verified=(
            "YayoiInputAdapter through JDLOutputAdapter formal end-to-end",
            "registry factory wiring for explicit target master and tax context",
            "simple plus simple or compound plus compound boundaries",
            "ten-to-twenty-record mixed operational batch",
            "three or more arbitrary logical groups",
            "other JDL products or versions",
            "format-wide support outside the v0 strict allow-list",
        ),
        production_output_enabled=False,
    )


def yayoi_to_jdl_e2e_real_import_evidence() -> ScopedJdlImportEvidence:
    return ScopedJdlImportEvidence(
        evidence_id=EVIDENCE_ID_YAYOI_TO_JDL_E2E,
        evidence_level=EvidenceLevel.VERIFIED_BY_REAL_IMPORT,
        product="JDL IBEX 出納帳",
        observed_version="35.5",
        verified_scope=(
            "synthetic Yayoi AE19 observed 25-field CP932 input",
            "formal YayoiInputAdapter and structural validation",
            "Common Journal Model with one simple and one compound journal",
            "confirmed four-account mapping without fuzzy or implicit mapping",
            "explicit JDL evidence-profile assignment without feature inference",
            "formal JDLOutputAdapter, validator, report, and atomic publish",
            "one 1111 record followed by one 1110/1100/1101 group",
            "same-date four-record output with blank candidate voucher fields",
            "runtime recognized four records and produced exactly two vouchers",
            "no merge, split, or duplicate observed",
            "balances, account placement, descriptions, and group boundaries preserved",
            "post-import JDL self re-export compared across 120 fields",
        ),
        not_verified=(
            "tax, subaccount, or department in the Yayoi to JDL route",
            "arbitrary compound shapes or group combinations",
            "simple plus simple or compound plus compound boundaries",
            "ten-to-twenty-record mixed operational batch",
            "arbitrary batch sizes",
            "other Yayoi or JDL products and versions",
            "registry factory wiring for explicit target master and tax context",
            "general-user GUI workflow",
            "format-wide production readiness",
        ),
        production_output_enabled=False,
    )


def context_aware_runtime_e2e_real_import_evidence() -> ScopedJdlImportEvidence:
    return ScopedJdlImportEvidence(
        evidence_id=EVIDENCE_ID_CONTEXT_AWARE_RUNTIME_E2E,
        evidence_level=EvidenceLevel.VERIFIED_BY_REAL_IMPORT,
        product="JDL IBEX 出納帳",
        observed_version="35.5",
        verified_scope=(
            "synthetic Yayoi AE19 observed 25-field CP932 input",
            "formal YayoiInputAdapter and structural validation",
            "Common Journal Model with one simple and one exact 1D3C compound journal",
            "confirmed four-account ConversionProfile mapping",
            "ConversionRequest target runtime context injection",
            "immutable validated JdlTargetContext snapshot",
            "AdapterRegistry context-required implementation resolution",
            "JdlOutputRuntimeFactory and exact mapping-context cross-check",
            "explicit JDL evidence-profile assignment without feature inference",
            "formal JDLOutputAdapter, validator, report, and atomic publish",
            "exempt company with no tax, subaccount, or department fields",
            "same-date 1111 then 1110/1100/1101 four-record output",
            "runtime recognized four records and produced exactly two vouchers",
            "no merge, compound split, or duplicate observed",
            "runtime UI voucher-number fields observed blank for both vouchers",
            "post-import JDL self re-export compared across 120 fields",
        ),
        not_verified=(
            "arbitrary customer target contexts or mappings",
            "simple plus simple or compound plus compound boundaries",
            "ten-to-twenty-record mixed operational batch",
            "arbitrary batch sizes, compound shapes, or group combinations",
            "tax, subaccount, or department in the Yayoi to JDL route",
            "other Yayoi or JDL products and versions",
            "general-user GUI context confirmation workflow",
            "format-wide production readiness",
        ),
        production_output_enabled=False,
    )


def simple_plus_simple_runtime_real_import_evidence() -> ScopedJdlImportEvidence:
    return ScopedJdlImportEvidence(
        evidence_id=EVIDENCE_ID_SIMPLE_PLUS_SIMPLE_RUNTIME,
        evidence_level=EvidenceLevel.VERIFIED_BY_REAL_IMPORT,
        product="JDL IBEX 出納帳",
        observed_version="35.5",
        verified_scope=(
            "synthetic Yayoi AE19 input through the formal context-aware route",
            "confirmed four-account mapping and validated exempt target context",
            "exactly two same-date simple journals",
            "exact 1111/1111 output order with blank candidate voucher fields",
            "no tax, subaccount, or department fields",
            "runtime recognized two records and produced exactly two vouchers",
            "no merge, split, or duplicate observed",
            "balances, account placement, descriptions, and row order preserved",
            "runtime UI voucher-number fields observed blank for both vouchers",
            "post-import JDL self re-export compared across 60 fields",
        ),
        not_verified=(
            "three or more simple journals or arbitrary batch sizes",
            "different dates, arbitrary group orders, or nonblank voucher numbers",
            "compound plus compound boundaries",
            "tax, subaccount, or department in repeated simple journals",
            "other Yayoi or JDL products and versions",
            "general-user GUI workflow",
            "format-wide production readiness",
        ),
        production_output_enabled=False,
    )


def generator_authored_1111_tax_exclusive_real_import_evidence(
) -> ScopedJdlImportEvidence:
    return ScopedJdlImportEvidence(
        evidence_id=EVIDENCE_ID_1111_TAX_EXCLUSIVE,
        evidence_level=EvidenceLevel.VERIFIED_BY_REAL_IMPORT,
        product="JDL IBEX 出納帳",
        observed_version="35.5",
        verified_scope=(
            "one exact generator-authored 1111 single-line voucher artifact",
            "official 30-column first-row header",
            "CP932-compatible CRLF BOM-less serialization",
            "taxable company using standard taxation and individual attribution",
            "company accounting method configured as tax-exclusive",
            "one raw-confirmed debit tax scope/category/input-method/amount combination",
            "UI input mode and CSV tax-input-method field kept as separate evidence",
            "credit-side tax classification, input method, and transaction accounts blank",
            "no subaccount or department input",
            "one balanced record with description",
            "runtime import completed and one voucher visually verified",
            "post-import JDL re-export obtained",
            "exact debit tax scope including U+3000 and all debit tax literals preserved",
        ),
        not_verified=(
            "other tax scopes, categories, rates, input methods, or tax amounts",
            "sales-side tax classification",
            "reduced-rate 8 percent",
            "transaction account behavior",
            "identifier flag 1000 tax semantics",
            "compound voucher, mixed rates, or multiple taxable rows",
            "multiple-record or large data sets",
            "semantic equivalence of the UI input mode and CSV tax-input-method field",
            "other JDL versions or products",
            "Yayoi to JDL end-to-end",
            "production JDLOutputAdapter",
        ),
        production_output_enabled=False,
    )


def compare_generator_runtime(
    candidate_path: Path,
    reexport_path: Path,
    *,
    evidence_id: str,
    expected_flag: str,
    reference_path: Path | None = None,
) -> GeneratorRuntimeComparison:
    candidate = _read_single_record(candidate_path)
    reexport = _read_single_record(reexport_path)
    if candidate["row"][0] != expected_flag or reexport["row"][0] != expected_flag:
        raise ValueError("candidate and re-export must use the expected identifier flag")

    comparisons = tuple(
        RuntimeReexportFieldComparison(
            field_name=name,
            status=_field_status(candidate["row"][index], reexport["row"][index]),
        )
        for index, name in enumerate(OFFICIAL_HEADER)
    )
    reference_preserved_count = None
    reference_differences: tuple[str, ...] = ()
    reference_structure = None
    if reference_path is not None:
        reference = _read_single_record(reference_path)
        reference_differences = tuple(
            name
            for index, name in enumerate(OFFICIAL_HEADER)
            if reference["row"][index] != reexport["row"][index]
        )
        reference_preserved_count = len(OFFICIAL_HEADER) - len(reference_differences)
        reference_structure = reference["structure"]
    return GeneratorRuntimeComparison(
        evidence_id=evidence_id,
        identifier_flag=expected_flag,
        candidate_fields=comparisons,
        candidate_structure=candidate["structure"],
        reexport_structure=reexport["structure"],
        reference_preserved_count=reference_preserved_count,
        reference_difference_fields=reference_differences,
        reference_structure=reference_structure,
    )


def compare_generator_1111_runtime(
    candidate_path: Path,
    reexport_path: Path,
    reference_path: Path,
) -> Generator1111RuntimeComparison:
    return compare_generator_runtime(
        candidate_path,
        reexport_path,
        evidence_id=EVIDENCE_ID_1111,
        expected_flag="1111",
        reference_path=reference_path,
    )


def compare_generator_1000_runtime(
    candidate_path: Path,
    reexport_path: Path,
) -> GeneratorRuntimeComparison:
    return compare_generator_runtime(
        candidate_path,
        reexport_path,
        evidence_id=EVIDENCE_ID_1000,
        expected_flag="1000",
    )


def compare_generator_1000_subaccount_runtime(
    candidate_path: Path,
    reexport_path: Path,
) -> GeneratorRuntimeComparison:
    return compare_generator_runtime(
        candidate_path,
        reexport_path,
        evidence_id=EVIDENCE_ID_1000_SUBACCOUNT,
        expected_flag="1000",
    )


def compare_generator_1111_department_runtime(
    candidate_path: Path,
    reexport_path: Path,
) -> GeneratorRuntimeComparison:
    return compare_generator_runtime(
        candidate_path,
        reexport_path,
        evidence_id=EVIDENCE_ID_1111_DEPARTMENT,
        expected_flag="1111",
    )


def compare_generator_1111_tax_inclusive_runtime(
    candidate_path: Path,
    reexport_path: Path,
) -> GeneratorRuntimeComparison:
    return compare_generator_runtime(
        candidate_path,
        reexport_path,
        evidence_id=EVIDENCE_ID_1111_TAX_INCLUSIVE,
        expected_flag="1111",
    )


def compare_generator_1111_tax_exclusive_runtime(
    candidate_path: Path,
    reexport_path: Path,
) -> GeneratorRuntimeComparison:
    return compare_generator_runtime(
        candidate_path,
        reexport_path,
        evidence_id=EVIDENCE_ID_1111_TAX_EXCLUSIVE,
        expected_flag="1111",
    )


def compare_generator_compound_runtime(
    candidate_path: Path,
    reexport_path: Path,
) -> CompoundRuntimeComparison:
    candidate = _read_records(candidate_path, expected_count=3)
    reexport = _read_records(reexport_path, expected_count=3)
    expected_flags = ("1110", "1100", "1101")
    candidate_flags = tuple(row[0] for row in candidate["rows"])
    reexport_flags = tuple(row[0] for row in reexport["rows"])
    if candidate_flags != expected_flags or reexport_flags != expected_flags:
        raise ValueError("candidate and re-export must preserve 1110/1100/1101")

    comparisons = tuple(
        CompoundRuntimeFieldComparison(
            record_index=record_index,
            field_name=name,
            status=_field_status(candidate_row[field_index], reexport_row[field_index]),
        )
        for record_index, (candidate_row, reexport_row) in enumerate(
            zip(candidate["rows"], reexport["rows"], strict=True), start=1
        )
        for field_index, name in enumerate(OFFICIAL_HEADER)
    )
    date_index = OFFICIAL_HEADER.index("日付")
    debit_amount_index = OFFICIAL_HEADER.index("借方金額")
    credit_amount_index = OFFICIAL_HEADER.index("貸方金額")
    description_index = OFFICIAL_HEADER.index("摘要")
    voucher_index = OFFICIAL_HEADER.index("伝番")
    return CompoundRuntimeComparison(
        evidence_id=EVIDENCE_ID_GENERATOR_COMPOUND_1110_1100_1101,
        candidate_fields=comparisons,
        candidate_structure=candidate["structure"],
        reexport_structure=reexport["structure"],
        sequence_preserved=candidate_flags == reexport_flags == expected_flags,
        row_order_preserved=all(
            candidate_row[0] == reexport_row[0]
            for candidate_row, reexport_row in zip(
                candidate["rows"], reexport["rows"], strict=True
            )
        ),
        date_preserved=all(
            candidate_row[date_index] == reexport_row[date_index]
            for candidate_row, reexport_row in zip(
                candidate["rows"], reexport["rows"], strict=True
            )
        ),
        amounts_and_positions_preserved=all(
            candidate_row[index] == reexport_row[index]
            for candidate_row, reexport_row in zip(
                candidate["rows"], reexport["rows"], strict=True
            )
            for index in (debit_amount_index, credit_amount_index)
        ),
        descriptions_and_positions_preserved=all(
            candidate_row[description_index] == reexport_row[description_index]
            for candidate_row, reexport_row in zip(
                candidate["rows"], reexport["rows"], strict=True
            )
        ),
        candidate_vouchers_blank=all(
            not row[voucher_index] for row in candidate["rows"]
        ),
        reexport_vouchers_zero=all(
            row[voucher_index] == "0" for row in reexport["rows"]
        ),
    )


def compare_generator_multi_group_runtime(
    candidate_path: Path,
    reexport_path: Path,
    *,
    runtime_ui_vouchers_blank: bool,
    runtime_logical_voucher_count: int,
    evidence_id: str = EVIDENCE_ID_GENERATOR_MULTIGROUP_SIMPLE_COMPOUND,
) -> MultiGroupRuntimeComparison:
    if runtime_logical_voucher_count < 1:
        raise ValueError("runtime logical voucher count must be positive")
    candidate = _read_records(candidate_path, expected_count=4)
    reexport = _read_records(reexport_path, expected_count=4)
    expected_flags = ("1111", "1110", "1100", "1101")
    candidate_flags = tuple(row[0] for row in candidate["rows"])
    reexport_flags = tuple(row[0] for row in reexport["rows"])
    if candidate_flags != expected_flags or reexport_flags != expected_flags:
        raise ValueError(
            "candidate and re-export must preserve 1111/1110/1100/1101"
        )

    comparisons = tuple(
        CompoundRuntimeFieldComparison(
            record_index=record_index,
            field_name=name,
            status=_field_status(candidate_row[field_index], reexport_row[field_index]),
        )
        for record_index, (candidate_row, reexport_row) in enumerate(
            zip(candidate["rows"], reexport["rows"], strict=True), start=1
        )
        for field_index, name in enumerate(OFFICIAL_HEADER)
    )
    indexes = {name: OFFICIAL_HEADER.index(name) for name in OFFICIAL_HEADER}
    def balanced(rows: tuple[tuple[str, ...], ...]) -> bool:
        debit = sum(int(row[indexes["借方金額"]] or 0) for row in rows)
        credit = sum(int(row[indexes["貸方金額"]] or 0) for row in rows)
        return debit == credit

    compared_rows = zip(candidate["rows"], reexport["rows"], strict=True)
    return MultiGroupRuntimeComparison(
        evidence_id=evidence_id,
        candidate_fields=comparisons,
        candidate_structure=candidate["structure"],
        reexport_structure=reexport["structure"],
        flag_order_preserved=candidate_flags == reexport_flags == expected_flags,
        row_order_preserved=all(
            candidate_row[0] == reexport_row[0]
            for candidate_row, reexport_row in zip(
                candidate["rows"], reexport["rows"], strict=True
            )
        ),
        date_preserved=all(
            candidate_row[indexes["日付"]] == reexport_row[indexes["日付"]]
            for candidate_row, reexport_row in zip(
                candidate["rows"], reexport["rows"], strict=True
            )
        ),
        account_placement_preserved=all(
            candidate_row[index] == reexport_row[index]
            for candidate_row, reexport_row in compared_rows
            for index in (
                indexes["借方科目名称"],
                indexes["貸方科目名称"],
            )
        ),
        amounts_and_positions_preserved=all(
            candidate_row[index] == reexport_row[index]
            for candidate_row, reexport_row in zip(
                candidate["rows"], reexport["rows"], strict=True
            )
            for index in (indexes["借方金額"], indexes["貸方金額"])
        ),
        descriptions_and_positions_preserved=all(
            candidate_row[indexes["摘要"]] == reexport_row[indexes["摘要"]]
            for candidate_row, reexport_row in zip(
                candidate["rows"], reexport["rows"], strict=True
            )
        ),
        candidate_vouchers_blank=all(
            not row[indexes["伝番"]] for row in candidate["rows"]
        ),
        runtime_ui_vouchers_blank=runtime_ui_vouchers_blank,
        reexport_vouchers_zero=all(
            row[indexes["伝番"]] == "0" for row in reexport["rows"]
        ),
        runtime_logical_voucher_count=runtime_logical_voucher_count,
        simple_balanced=balanced(candidate["rows"][:1]) and balanced(
            reexport["rows"][:1]
        ),
        compound_balanced=balanced(candidate["rows"][1:]) and balanced(
            reexport["rows"][1:]
        ),
    )


def compare_context_aware_runtime_e2e(
    candidate_path: Path,
    reexport_path: Path,
) -> MultiGroupRuntimeComparison:
    return compare_generator_multi_group_runtime(
        candidate_path,
        reexport_path,
        runtime_ui_vouchers_blank=True,
        runtime_logical_voucher_count=2,
        evidence_id=EVIDENCE_ID_CONTEXT_AWARE_RUNTIME_E2E,
    )


def compare_simple_plus_simple_runtime(
    candidate_path: Path,
    reexport_path: Path,
    *,
    runtime_ui_vouchers_blank: bool,
    runtime_logical_voucher_count: int,
) -> SimplePairRuntimeComparison:
    if runtime_logical_voucher_count != 2:
        raise ValueError("runtime logical voucher count must be exactly two")
    candidate = _read_records(candidate_path, expected_count=2)
    reexport = _read_records(reexport_path, expected_count=2)
    expected_flags = ("1111", "1111")
    candidate_flags = tuple(row[0] for row in candidate["rows"])
    reexport_flags = tuple(row[0] for row in reexport["rows"])
    if candidate_flags != expected_flags or reexport_flags != expected_flags:
        raise ValueError("candidate and re-export must preserve 1111/1111")

    comparisons = tuple(
        CompoundRuntimeFieldComparison(
            record_index=record_index,
            field_name=name,
            status=_field_status(candidate_row[field_index], reexport_row[field_index]),
        )
        for record_index, (candidate_row, reexport_row) in enumerate(
            zip(candidate["rows"], reexport["rows"], strict=True), start=1
        )
        for field_index, name in enumerate(OFFICIAL_HEADER)
    )
    indexes = {name: OFFICIAL_HEADER.index(name) for name in OFFICIAL_HEADER}
    row_identity_indexes = tuple(
        indexes[name]
        for name in (
            "//識別フラグ",
            "日付",
            "借方科目名称",
            "借方金額",
            "貸方科目名称",
            "貸方金額",
            "摘要",
        )
    )

    def balanced(row: tuple[str, ...]) -> bool:
        return int(row[indexes["借方金額"]]) == int(row[indexes["貸方金額"]])

    return SimplePairRuntimeComparison(
        evidence_id=EVIDENCE_ID_SIMPLE_PLUS_SIMPLE_RUNTIME,
        candidate_fields=comparisons,
        candidate_structure=candidate["structure"],
        reexport_structure=reexport["structure"],
        flag_order_preserved=candidate_flags == reexport_flags == expected_flags,
        row_order_preserved=all(
            all(candidate_row[index] == reexport_row[index] for index in row_identity_indexes)
            for candidate_row, reexport_row in zip(
                candidate["rows"], reexport["rows"], strict=True
            )
        ),
        date_preserved=all(
            candidate_row[indexes["日付"]] == reexport_row[indexes["日付"]]
            for candidate_row, reexport_row in zip(
                candidate["rows"], reexport["rows"], strict=True
            )
        ),
        account_placement_preserved=all(
            candidate_row[index] == reexport_row[index]
            for candidate_row, reexport_row in zip(
                candidate["rows"], reexport["rows"], strict=True
            )
            for index in (indexes["借方科目名称"], indexes["貸方科目名称"])
        ),
        amounts_and_positions_preserved=all(
            candidate_row[index] == reexport_row[index]
            for candidate_row, reexport_row in zip(
                candidate["rows"], reexport["rows"], strict=True
            )
            for index in (indexes["借方金額"], indexes["貸方金額"])
        ),
        descriptions_and_positions_preserved=all(
            candidate_row[indexes["摘要"]] == reexport_row[indexes["摘要"]]
            for candidate_row, reexport_row in zip(
                candidate["rows"], reexport["rows"], strict=True
            )
        ),
        candidate_vouchers_blank=all(
            not row[indexes["伝番"]] for row in candidate["rows"]
        ),
        runtime_ui_vouchers_blank=runtime_ui_vouchers_blank,
        reexport_vouchers_zero=all(
            row[indexes["伝番"]] == "0" for row in reexport["rows"]
        ),
        runtime_logical_voucher_count=runtime_logical_voucher_count,
        independently_balanced=all(
            balanced(row) for row in (*candidate["rows"], *reexport["rows"])
        ),
    )


def _field_status(input_value: str, reexport_value: str) -> RuntimeReexportFieldStatus:
    if input_value == reexport_value:
        return RuntimeReexportFieldStatus.INPUT_PRESERVED
    if input_value == "" and reexport_value != "":
        return RuntimeReexportFieldStatus.INPUT_BLANK_REEXPORT_NONBLANK
    if input_value != "" and reexport_value == "":
        return RuntimeReexportFieldStatus.INPUT_NONBLANK_REEXPORT_BLANK
    return RuntimeReexportFieldStatus.DIFFERENT


def _read_single_record(path: Path) -> dict[str, Any]:
    parsed = _read_records(path, expected_count=1)
    return {"row": parsed["rows"][0], "structure": parsed["structure"]}


def _read_records(path: Path, *, expected_count: int) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        text = raw.decode("cp932")
    except UnicodeDecodeError as exc:
        raise ValueError("evidence CSV must be CP932-decodable") from exc
    rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    header_indexes = [
        index for index, row in enumerate(rows) if tuple(row) == OFFICIAL_HEADER
    ]
    if len(header_indexes) != 1:
        raise ValueError("evidence CSV must contain exactly one official header")
    header_index = header_indexes[0]
    records = rows[header_index + 1:]
    if len(records) != expected_count or any(
        len(record) != len(OFFICIAL_HEADER) for record in records
    ):
        raise ValueError(
            f"evidence CSV must contain exactly {expected_count} 30-column records"
        )
    without_crlf = raw.replace(b"\r\n", b"")
    if b"\n" in without_crlf or b"\r" in without_crlf:
        line_ending = "mixed_or_non_crlf"
    else:
        line_ending = "CRLF"
    structure = {
        "encoding": "cp932",
        "has_bom": raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")),
        "line_ending": line_ending,
        "physical_row_count": len(raw.splitlines()),
        "preamble_row_count": header_index,
        "header_row_number": header_index + 1,
        "header_column_count": len(rows[header_index]),
        "data_row_count": len(records),
        "data_column_count": len(records[0]),
        "data_column_counts": dict(
            Counter(len(record) for record in records)
        ),
    }
    return {"rows": tuple(tuple(record) for record in records), "structure": structure}
