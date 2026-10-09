from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

from accounting_converter.profiles.jdl_official import (
    jdl_ibex_cashbook_official_journal_import_spec,
)


EVIDENCE_ID_JDL_PURCHASE_10_INCLUSIVE_HAND = (
    "EVID-JDL-TAX-PURCHASE-10-INCLUSIVE-HAND-001"
)


class JdlTaxEvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class JdlTaxEvidenceObservation:
    path: Path
    sha256: str
    byte_size: int
    preamble_row_count: int
    identifier_flag: str
    debit_tax_scope: str
    debit_tax_category: str
    debit_tax_input_method: str
    debit_tax_amount: str
    credit_tax_fields_empty: bool
    balanced: bool

    def privacy_safe_manifest(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "evidence_id": EVIDENCE_ID_JDL_PURCHASE_10_INCLUSIVE_HAND,
            "source_sha256": self.sha256,
            "source_byte_size": self.byte_size,
            "product": "JDL IBEX 出納帳",
            "version": "35.5",
            "encoding": "cp932",
            "bom": False,
            "line_ending": "CRLF",
            "preamble_row_count": self.preamble_row_count,
            "header_column_count": 30,
            "data_row_count": 1,
            "data_column_count": 30,
            "identifier_flag": self.identifier_flag,
            "tax_processing_mode": "TAXABLE_TAX_INCLUDED",
            "accounting_mode": "TAX_INCLUDED",
            "probe_intent": "MF_TAX_PURCHASE_10_TO_JDL",
            "debit_tax_scope_present": bool(self.debit_tax_scope),
            "debit_tax_category_present": bool(self.debit_tax_category),
            "debit_tax_input_method_present": bool(self.debit_tax_input_method),
            "debit_tax_amount_reexport_zero": self.debit_tax_amount == "0",
            "credit_tax_fields_empty": self.credit_tax_fields_empty,
            "balanced": self.balanced,
            "synthetic_evidence": True,
            "human_observed": True,
            "evidence_level": "OBSERVED",
            "mapping_promotion_allowed": False,
            "NOT_FOR_PRODUCTION_GENERALIZATION": True,
        }


def analyze_purchase_10_inclusive_evidence(path: Path) -> JdlTaxEvidenceObservation:
    raw = path.read_bytes()
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise JdlTaxEvidenceError("BOM is outside the observed evidence identity")
    if b"\r\n" not in raw or b"\n" in raw.replace(b"\r\n", b""):
        raise JdlTaxEvidenceError("expected CRLF-only evidence")
    try:
        text = raw.decode("cp932", errors="strict")
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise JdlTaxEvidenceError("evidence is not strict CP932 CSV") from exc

    header = jdl_ibex_cashbook_official_journal_import_spec().column_names
    header_indexes = [index for index, row in enumerate(rows) if tuple(row) == header]
    if len(header_indexes) != 1:
        raise JdlTaxEvidenceError("exact official header must appear once")
    header_index = header_indexes[0]
    data_rows = rows[header_index + 1 :]
    if len(data_rows) != 1 or len(data_rows[0]) != 30:
        raise JdlTaxEvidenceError("evidence must contain exactly one 30-column row")

    row = data_rows[0]
    positions = {name: index for index, name in enumerate(header)}
    debit_amount = row[positions["借方金額"]]
    credit_amount = row[positions["貸方金額"]]
    if not debit_amount.isdigit() or debit_amount != credit_amount:
        raise JdlTaxEvidenceError("evidence amounts must be integer and balanced")
    if (
        row[positions["//識別フラグ"]] != "1111"
        or row[positions["借方課区"]] != "仕　入"
        or row[positions["借方税区"]] != "10%"
        or row[positions["借方税入力方法"]] != ""
        or row[positions["借方消費税"]] != "0"
    ):
        raise JdlTaxEvidenceError(
            "evidence does not match the scoped purchase-10 tax-inclusive observation"
        )
    return JdlTaxEvidenceObservation(
        path=path,
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_size=len(raw),
        preamble_row_count=header_index,
        identifier_flag=row[positions["//識別フラグ"]],
        debit_tax_scope=row[positions["借方課区"]],
        debit_tax_category=row[positions["借方税区"]],
        debit_tax_input_method=row[positions["借方税入力方法"]],
        debit_tax_amount=row[positions["借方消費税"]],
        credit_tax_fields_empty=all(
            row[positions[name]] in {"", "0"}
            for name in ("貸方課区", "貸方税区", "貸方税入力方法", "貸方消費税")
        ),
        balanced=True,
    )
