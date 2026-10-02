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


EVIDENCE_ID = "EVID-JDL-GENERATOR-1111-001"
VERIFIED_ARTIFACT_STATUS = "GENERATOR_AUTHORED_1111_VERIFIED_BY_REAL_IMPORT_SCOPED"
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
class Generator1111RuntimeComparison:
    candidate_fields: tuple[RuntimeReexportFieldComparison, ...]
    reference_preserved_count: int
    reference_difference_fields: tuple[str, ...]
    candidate_structure: dict[str, Any]
    reexport_structure: dict[str, Any]
    reference_structure: dict[str, Any]

    @property
    def status_counts(self) -> tuple[tuple[str, int], ...]:
        counts = Counter(field.status.value for field in self.candidate_fields)
        return tuple(sorted(counts.items()))

    def to_privacy_safe_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": EVIDENCE_ID,
            "candidate_to_reexport_status_counts": dict(self.status_counts),
            "candidate_to_reexport_fields": [
                {"field": item.field_name, "status": item.status.value}
                for item in self.candidate_fields
            ],
            "reference_to_reexport_preserved_count": self.reference_preserved_count,
            "reference_to_reexport_difference_fields": list(
                self.reference_difference_fields
            ),
            "human_29_of_30_claim_confirmed": (
                self.reference_preserved_count == 29
                and self.reference_difference_fields == ("伝番",)
            ),
            "structures": {
                "candidate": self.candidate_structure,
                "runtime_reexport": self.reexport_structure,
                "reference_export": self.reference_structure,
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


def compare_generator_1111_runtime(
    candidate_path: Path,
    reexport_path: Path,
    reference_path: Path,
) -> Generator1111RuntimeComparison:
    candidate = _read_single_record(candidate_path)
    reexport = _read_single_record(reexport_path)
    reference = _read_single_record(reference_path)

    comparisons = tuple(
        RuntimeReexportFieldComparison(
            field_name=name,
            status=_field_status(candidate["row"][index], reexport["row"][index]),
        )
        for index, name in enumerate(OFFICIAL_HEADER)
    )
    reference_differences = tuple(
        name
        for index, name in enumerate(OFFICIAL_HEADER)
        if reference["row"][index] != reexport["row"][index]
    )
    return Generator1111RuntimeComparison(
        candidate_fields=comparisons,
        reference_preserved_count=len(OFFICIAL_HEADER) - len(reference_differences),
        reference_difference_fields=reference_differences,
        candidate_structure=candidate["structure"],
        reexport_structure=reexport["structure"],
        reference_structure=reference["structure"],
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
