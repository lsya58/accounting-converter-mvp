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


def _field_status(input_value: str, reexport_value: str) -> RuntimeReexportFieldStatus:
    if input_value == reexport_value:
        return RuntimeReexportFieldStatus.INPUT_PRESERVED
    if input_value == "" and reexport_value != "":
        return RuntimeReexportFieldStatus.INPUT_BLANK_REEXPORT_NONBLANK
    if input_value != "" and reexport_value == "":
        return RuntimeReexportFieldStatus.INPUT_NONBLANK_REEXPORT_BLANK
    return RuntimeReexportFieldStatus.DIFFERENT


def _read_single_record(path: Path) -> dict[str, Any]:
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
    if len(records) != 1 or len(records[0]) != len(OFFICIAL_HEADER):
        raise ValueError("evidence CSV must contain exactly one 30-column record")
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
    }
    return {"row": tuple(records[0]), "structure": structure}
