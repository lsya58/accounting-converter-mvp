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
EVIDENCE_ID_MF_JDL_PURCHASE_10_ROUNDTRIP = (
    "EVID-JDL-MF-TAX-PURCHASE-10-ROUNDTRIP-001"
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


@dataclass(frozen=True)
class JdlTaxRoundTripComparison:
    human_sha256: str
    candidate_sha256: str
    reexport_sha256: str
    reexport_journal_count: int
    candidate_match_count: int
    account_identity_match: bool
    amount_match: bool
    debit_tax_fields_match: bool
    credit_tax_fields_match: bool
    description_preserved: bool
    balance_preserved: bool
    candidate_blank_fields_normalized_by_jdl: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return all(
            (
                self.candidate_match_count == 1,
                self.account_identity_match,
                self.amount_match,
                self.debit_tax_fields_match,
                self.credit_tax_fields_match,
                self.description_preserved,
                self.balance_preserved,
            )
        )

    def privacy_safe_result(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "probe_case": "tax_purchase_10",
            "result_status": "PASS" if self.passed else "MISMATCH",
            "imported": True,
            "reexport_present": True,
            "comparison_pass": self.passed,
            "evidence_id": EVIDENCE_ID_MF_JDL_PURCHASE_10_ROUNDTRIP,
            "evidence_level": (
                "VERIFIED_BY_REAL_IMPORT" if self.passed else "OBSERVED"
            ),
            "source_hashes": {
                "human_evidence_sha256": self.human_sha256,
                "candidate_sha256": self.candidate_sha256,
                "reexport_sha256": self.reexport_sha256,
            },
            "reexport_journal_count": self.reexport_journal_count,
            "candidate_match_count": self.candidate_match_count,
            "compared_fields": {
                "account_identity": self.account_identity_match,
                "amount": self.amount_match,
                "debit_tax_fields": self.debit_tax_fields_match,
                "credit_tax_fields": self.credit_tax_fields_match,
                "description": self.description_preserved,
                "balance": self.balance_preserved,
            },
            "jdl_normalized_field_categories": list(
                self.candidate_blank_fields_normalized_by_jdl
            ),
            "mapping_promotion_allowed": False,
            "production_ready": False,
            "NOT_FOR_PRODUCTION_GENERALIZATION": True,
        }


def compare_purchase_10_roundtrip(
    human_evidence: Path,
    candidate: Path,
    reexport: Path,
) -> JdlTaxRoundTripComparison:
    analyze_purchase_10_inclusive_evidence(human_evidence)
    human_raw, human_rows = _read_official_rows(human_evidence)
    candidate_raw, candidate_rows = _read_official_rows(candidate)
    reexport_raw, reexport_rows = _read_official_rows(reexport)
    if len(human_rows) != 1 or len(candidate_rows) != 1:
        raise JdlTaxEvidenceError("human evidence and candidate must contain one row")

    header = jdl_ibex_cashbook_official_journal_import_spec().column_names
    positions = {name: index for index, name in enumerate(header)}
    human = human_rows[0]
    expected = candidate_rows[0]
    if (
        expected[positions["//識別フラグ"]] != "1111"
        or expected[positions["借方課区"]] != "仕　入"
        or expected[positions["借方税区"]] != "10%"
        or expected[positions["借方税入力方法"]] != ""
        or expected[positions["借方消費税"]] != ""
        or any(
            expected[positions[name]]
            for name in (
                "借方補助",
                "借方補助名称",
                "貸方補助",
                "貸方補助名称",
                "借方部門コード",
                "借方部門名称",
                "貸方部門コード",
                "貸方部門名称",
            )
        )
    ):
        raise JdlTaxEvidenceError("candidate is outside the verified probe scope")
    identity_fields = (
        "日付",
        "借方科目名称",
        "貸方科目名称",
        "借方金額",
        "貸方金額",
        "摘要",
    )
    matches = [
        row
        for row in reexport_rows
        if all(row[positions[name]] == expected[positions[name]] for name in identity_fields)
    ]
    actual = matches[0] if len(matches) == 1 else None
    if actual is None:
        return JdlTaxRoundTripComparison(
            _sha256(human_raw),
            _sha256(candidate_raw),
            _sha256(reexport_raw),
            len(reexport_rows),
            len(matches),
            False,
            False,
            False,
            False,
            False,
            False,
            (),
        )

    account_fields = (
        "借方科目",
        "借方科目名称",
        "借方科目正式名称",
        "貸方科目",
        "貸方科目名称",
        "貸方科目正式名称",
    )
    amount_fields = ("借方金額", "貸方金額")
    debit_tax_fields = ("借方課区", "借方税区", "借方税入力方法", "借方消費税")
    credit_tax_fields = ("貸方課区", "貸方税区", "貸方税入力方法", "貸方消費税")
    normalized = tuple(
        category
        for category, fields in (
            ("account_master_identity", account_fields),
            ("tax_amount_reexport_representation", ("借方消費税", "貸方消費税")),
        )
        if any(
            expected[positions[name]] == "" and actual[positions[name]] != ""
            for name in fields
        )
    )
    return JdlTaxRoundTripComparison(
        human_sha256=_sha256(human_raw),
        candidate_sha256=_sha256(candidate_raw),
        reexport_sha256=_sha256(reexport_raw),
        reexport_journal_count=len(reexport_rows),
        candidate_match_count=1,
        account_identity_match=_fields_equal(human, actual, positions, account_fields),
        amount_match=(
            _fields_equal(human, actual, positions, amount_fields)
            and _fields_equal(expected, actual, positions, amount_fields)
        ),
        debit_tax_fields_match=_fields_equal(
            human, actual, positions, debit_tax_fields
        ),
        credit_tax_fields_match=_fields_equal(
            human, actual, positions, credit_tax_fields
        ),
        description_preserved=(
            expected[positions["摘要"]] == actual[positions["摘要"]]
        ),
        balance_preserved=(
            actual[positions["借方金額"]] == actual[positions["貸方金額"]]
        ),
        candidate_blank_fields_normalized_by_jdl=normalized,
    )


def _read_official_rows(path: Path) -> tuple[bytes, list[list[str]]]:
    raw = path.read_bytes()
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise JdlTaxEvidenceError("BOM is outside the observed evidence identity")
    if b"\r\n" not in raw or b"\n" in raw.replace(b"\r\n", b""):
        raise JdlTaxEvidenceError("expected CRLF-only evidence")
    try:
        rows = list(
            csv.reader(io.StringIO(raw.decode("cp932", errors="strict"), newline=""), strict=True)
        )
    except (UnicodeDecodeError, csv.Error) as exc:
        raise JdlTaxEvidenceError("evidence is not strict CP932 CSV") from exc
    header = jdl_ibex_cashbook_official_journal_import_spec().column_names
    indexes = [index for index, row in enumerate(rows) if tuple(row) == header]
    if len(indexes) != 1:
        raise JdlTaxEvidenceError("exact official header must appear once")
    data_rows = rows[indexes[0] + 1 :]
    if not data_rows or any(len(row) != len(header) for row in data_rows):
        raise JdlTaxEvidenceError("official 30-column data rows are required")
    return raw, data_rows


def _fields_equal(
    left: list[str],
    right: list[str],
    positions: dict[str, int],
    fields: tuple[str, ...],
) -> bool:
    return all(left[positions[name]] == right[positions[name]] for name in fields)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


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
