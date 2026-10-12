from __future__ import annotations

import csv
import hashlib
import io
import json
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
EVIDENCE_ID_JDL_PURCHASE_10_SUBACCOUNT_HAND = (
    "EVID-JDL-TAX-PURCHASE-10-SUBACCOUNT-HAND-001"
)
EVIDENCE_ID_MF_JDL_PURCHASE_10_SUBACCOUNT_ROUNDTRIP = (
    "EVID-JDL-MF-TAX-PURCHASE-10-SUBACCOUNT-ROUNDTRIP-001"
)
EVIDENCE_ID_MF_JDL_SALES_10_SUBACCOUNT_ROUNDTRIP = (
    "EVID-JDL-MF-TAX-SALES-10-SUBACCOUNT-ROUNDTRIP-001"
)
EVIDENCE_ID_JDL_PURCHASE_REDUCED_8_INCLUSIVE_HAND = (
    "EVID-JDL-TAX-PURCHASE-REDUCED-8-INCLUSIVE-HAND-001"
)
EVIDENCE_ID_MF_JDL_PURCHASE_REDUCED_8_SUBACCOUNT_ROUNDTRIP = (
    "EVID-JDL-MF-TAX-PURCHASE-REDUCED-8-SUBACCOUNT-ROUNDTRIP-001"
)
EVIDENCE_ID_MF_JDL_SALES_REDUCED_8_SUBACCOUNT_ROUNDTRIP = (
    "EVID-JDL-MF-TAX-SALES-REDUCED-8-SUBACCOUNT-ROUNDTRIP-001"
)
EVIDENCE_ID_MF_JDL_NON_TAXABLE_PURCHASE_SUBACCOUNT_ROUNDTRIP = (
    "EVID-JDL-MF-TAX-NONTAXABLE-PURCHASE-SUBACCOUNT-ROUNDTRIP-001"
)
EVIDENCE_ID_MF_JDL_OUT_OF_SCOPE_SUBACCOUNT_ROUNDTRIP = (
    "EVID-JDL-MF-TAX-OUT-OF-SCOPE-SUBACCOUNT-ROUNDTRIP-001"
)

HUMAN_TAX_CASES = {
    "tax_sales_10": ("CREDIT", "売一種", "10%", "EVID-JDL-TAX-SALES-10-INCLUSIVE-HAND-001"),
    "tax_purchase_reduced_8": ("DEBIT", "仕　入", "軽減8%", "EVID-JDL-TAX-PURCHASE-REDUCED-8-INCLUSIVE-HAND-001"),
    "tax_sales_reduced_8": ("CREDIT", "売一種", "軽減8%", "EVID-JDL-TAX-SALES-REDUCED-8-INCLUSIVE-HAND-001"),
    "tax_non_taxable_purchase": ("DEBIT", "非仕入", "", "EVID-JDL-TAX-NONTAXABLE-PURCHASE-HAND-001"),
    "tax_out_of_scope": ("DEBIT", "", "", "EVID-JDL-TAX-OUT-OF-SCOPE-HAND-001"),
}


class JdlTaxEvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class JdlScopedTaxHumanObservation:
    case_name: str
    evidence_id: str
    sha256: str
    byte_size: int
    side: str
    tax_scope_present: bool
    tax_category_present: bool
    balanced: bool

    def privacy_safe_manifest(self) -> dict[str, object]:
        return {
            "case_name": self.case_name,
            "evidence_id": self.evidence_id,
            "sha256": self.sha256,
            "byte_size": self.byte_size,
            "evidence_level": "HUMAN_OBSERVED",
            "candidate_readiness": "BLOCKED_UNTIL_CASE_SPECIFIC_PREFLIGHT",
            "side": self.side,
            "tax_scope_present": self.tax_scope_present,
            "tax_category_present": self.tax_category_present,
            "balanced": self.balanced,
            "mapping_promotion_allowed": False,
            "NOT_FOR_PRODUCTION": True,
        }


@dataclass(frozen=True)
class JdlReduced8SubaccountHumanObservation:
    sha256: str
    byte_size: int
    debit_case_valid: bool
    credit_case_valid: bool
    debit_description_comparison_allowed: bool = True
    credit_description_comparison_allowed: bool = False

    def privacy_safe_manifest(self) -> dict[str, object]:
        return {
            "evidence_id": "EVID-JDL-SUBACCOUNT-TAX-REDUCED-8-HAND-001",
            "sha256": self.sha256,
            "byte_size": self.byte_size,
            "evidence_level": "HUMAN_OBSERVED",
            "data_row_count": 2,
            "debit_parent_subaccount_reduced_8_valid": self.debit_case_valid,
            "credit_parent_subaccount_reduced_8_valid": self.credit_case_valid,
            "debit_description_comparison_allowed": (
                self.debit_description_comparison_allowed
            ),
            "credit_description_comparison_allowed": (
                self.credit_description_comparison_allowed
            ),
            "mapping_promotion_allowed": False,
            "production_allowed": False,
            "NOT_FOR_PRODUCTION": True,
        }


def analyze_reduced_8_subaccount_human_evidence(
    path: Path,
) -> JdlReduced8SubaccountHumanObservation:
    raw, rows = _read_official_rows(path)
    if len(rows) != 2:
        raise JdlTaxEvidenceError("reduced 8 subaccount evidence must contain two rows")
    header = jdl_ibex_cashbook_official_journal_import_spec().column_names
    positions = {name: index for index, name in enumerate(header)}

    def matching(prefix: str, other: str, scope: str) -> list[list[str]]:
        return [
            row
            for row in rows
            if row[positions["//識別フラグ"]] == "1111"
            and row[positions[f"{prefix}補助"]]
            and row[positions[f"{prefix}補助名称"]]
            and row[positions[f"{prefix}課区"]] == scope
            and row[positions[f"{prefix}税区"]] == "軽減8%"
            and row[positions[f"{prefix}税入力方法"]] == ""
            and row[positions[f"{prefix}消費税"]] == "0"
            and all(
                row[positions[f"{other}{name}"]] in {"", "0"}
                for name in ("課区", "税区", "税入力方法", "消費税")
            )
            and row[positions["借方金額"]].isdigit()
            and row[positions["借方金額"]] == row[positions["貸方金額"]]
        ]

    debit = matching("借方", "貸方", "仕　入")
    credit = matching("貸方", "借方", "売一種")
    if len(debit) != 1 or len(credit) != 1:
        raise JdlTaxEvidenceError(
            "expected one debit and one credit reduced 8 subaccount observation"
        )
    return JdlReduced8SubaccountHumanObservation(
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_size=len(raw),
        debit_case_valid=True,
        credit_case_valid=True,
    )


def analyze_scoped_tax_human_evidence(
    path: Path, case_name: str
) -> JdlScopedTaxHumanObservation:
    try:
        side, expected_scope, expected_category, evidence_id = HUMAN_TAX_CASES[
            case_name
        ]
    except KeyError as exc:
        raise JdlTaxEvidenceError("unknown scoped tax evidence case") from exc
    raw, rows = _read_official_rows(path)
    if len(rows) != 1:
        raise JdlTaxEvidenceError("human tax evidence must contain exactly one row")
    header = jdl_ibex_cashbook_official_journal_import_spec().column_names
    positions = {name: index for index, name in enumerate(header)}
    row = rows[0]
    prefix = "借方" if side == "DEBIT" else "貸方"
    other = "貸方" if side == "DEBIT" else "借方"
    if row[positions["//識別フラグ"]] != "1111":
        raise JdlTaxEvidenceError("scoped tax evidence must use observed flag 1111")
    if (
        row[positions[f"{prefix}課区"]] != expected_scope
        or row[positions[f"{prefix}税区"]] != expected_category
        or row[positions[f"{prefix}税入力方法"]] != ""
        or row[positions[f"{prefix}消費税"]] != "0"
    ):
        raise JdlTaxEvidenceError("tax fields do not match the scoped human evidence")
    if any(
        row[positions[f"{other}{name}"]] not in {"", "0"}
        for name in ("課区", "税区", "税入力方法", "消費税")
    ):
        raise JdlTaxEvidenceError("unexpected tax fields exist on the opposite side")
    debit = row[positions["借方金額"]]
    credit = row[positions["貸方金額"]]
    if not debit.isdigit() or debit != credit:
        raise JdlTaxEvidenceError("human tax evidence must be balanced integer yen")
    return JdlScopedTaxHumanObservation(
        case_name=case_name,
        evidence_id=evidence_id,
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_size=len(raw),
        side=side,
        tax_scope_present=bool(expected_scope),
        tax_category_present=bool(expected_category),
        balanced=True,
    )


def analyze_purchase_10_subaccount_human_evidence(
    path: Path,
) -> JdlScopedTaxHumanObservation:
    raw, rows = _read_official_rows(path)
    if len(rows) != 1:
        raise JdlTaxEvidenceError("purchase 10 subaccount evidence must contain one row")
    header = jdl_ibex_cashbook_official_journal_import_spec().column_names
    pos = {name: index for index, name in enumerate(header)}
    row = rows[0]
    if (
        row[pos["//識別フラグ"]] != "1111"
        or not row[pos["借方科目"]]
        or not row[pos["借方科目名称"]]
        or not row[pos["貸方科目"]]
        or not row[pos["貸方科目名称"]]
        or not row[pos["借方補助"]]
        or not row[pos["借方補助名称"]]
        or row[pos["借方課区"]] != "仕　入"
        or row[pos["借方税区"]] != "10%"
        or row[pos["借方税入力方法"]] != ""
        or row[pos["借方消費税"]] != "0"
        or any(row[pos[f"貸方{name}"]] not in {"", "0"} for name in ("課区", "税区", "税入力方法", "消費税"))
        or row[pos["摘要"]] != "SUBACCOUNT-TAX-P10-PROBE"
        or any(row[pos[name]] for name in ("借方部門名称", "貸方部門名称"))
        or any(row[pos[name]] not in {"", "0"} for name in ("借方部門コード", "貸方部門コード"))
        or not row[pos["借方金額"]].isdigit()
        or row[pos["借方金額"]] != row[pos["貸方金額"]]
    ):
        raise JdlTaxEvidenceError("purchase 10 subaccount evidence is outside strict scope")
    return JdlScopedTaxHumanObservation(
        case_name="tax_purchase_10_with_subaccount",
        evidence_id=EVIDENCE_ID_JDL_PURCHASE_10_SUBACCOUNT_HAND,
        sha256=_sha256(raw),
        byte_size=len(raw),
        side="DEBIT",
        tax_scope_present=True,
        tax_category_present=True,
        balanced=True,
    )


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
    date_preserved: bool
    identifier_flag_preserved: bool
    parent_scoped_subaccount_match: bool
    candidate_blank_fields_normalized_by_jdl: tuple[str, ...]
    probe_case: str = "tax_purchase_10"
    evidence_id: str = EVIDENCE_ID_MF_JDL_PURCHASE_10_ROUNDTRIP

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
                self.date_preserved,
                self.identifier_flag_preserved,
                self.parent_scoped_subaccount_match,
            )
        )

    def privacy_safe_result(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "probe_case": self.probe_case,
            "result_status": "PASS" if self.passed else "MISMATCH",
            "imported": True,
            "reexport_present": True,
            "comparison_pass": self.passed,
            "evidence_id": self.evidence_id,
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
                "date": self.date_preserved,
                "identifier_flag": self.identifier_flag_preserved,
                "parent_scoped_subaccount": self.parent_scoped_subaccount_match,
            },
            "jdl_normalized_field_categories": list(
                self.candidate_blank_fields_normalized_by_jdl
            ),
            "mapping_promotion_allowed": False,
            "production_ready": False,
            "NOT_FOR_PRODUCTION_GENERALIZATION": True,
        }


def compare_purchase_10_roundtrip(
    human_evidence: Path, candidate: Path, reexport: Path
) -> JdlTaxRoundTripComparison:
    analyze_purchase_10_inclusive_evidence(human_evidence)
    return _compare_tax_roundtrip(
        human_evidence, candidate, reexport,
        probe_case="tax_purchase_10",
        evidence_id=EVIDENCE_ID_MF_JDL_PURCHASE_10_ROUNDTRIP,
        tax_prefix="借方", expected_scope="仕　入",
    )


def compare_purchase_10_subaccount_roundtrip(
    human_evidence: Path, candidate: Path, reexport: Path
) -> JdlTaxRoundTripComparison:
    analyze_purchase_10_subaccount_human_evidence(human_evidence)
    return _compare_tax_roundtrip(
        human_evidence,
        candidate,
        reexport,
        probe_case="tax_purchase_10_with_subaccount",
        evidence_id=EVIDENCE_ID_MF_JDL_PURCHASE_10_SUBACCOUNT_ROUNDTRIP,
        tax_prefix="借方",
        expected_scope="仕　入",
        require_tax_side_subaccount=True,
    )


def compare_sales_10_roundtrip(
    human_evidence: Path, candidate: Path, reexport: Path
) -> JdlTaxRoundTripComparison:
    analyze_scoped_tax_human_evidence(human_evidence, "tax_sales_10")
    return _compare_tax_roundtrip(
        human_evidence, candidate, reexport,
        probe_case="tax_sales_10",
        evidence_id="EVID-JDL-MF-TAX-SALES-10-ROUNDTRIP-001",
        tax_prefix="貸方", expected_scope="売一種",
    )


def compare_sales_10_subaccount_roundtrip(
    human_evidence: Path, candidate: Path, reexport: Path
) -> JdlTaxRoundTripComparison:
    analyze_scoped_tax_human_evidence(human_evidence, "tax_sales_10")
    return _compare_tax_roundtrip(
        human_evidence,
        candidate,
        reexport,
        probe_case="tax_sales_10_with_subaccount",
        evidence_id=EVIDENCE_ID_MF_JDL_SALES_10_SUBACCOUNT_ROUNDTRIP,
        tax_prefix="貸方",
        expected_scope="売一種",
        require_tax_side_subaccount=True,
    )


def compare_purchase_reduced_8_roundtrip(
    human_evidence: Path, candidate: Path, reexport: Path
) -> JdlTaxRoundTripComparison:
    analyze_scoped_tax_human_evidence(
        human_evidence, "tax_purchase_reduced_8"
    )
    return _compare_tax_roundtrip(
        human_evidence,
        candidate,
        reexport,
        probe_case="tax_purchase_reduced_8",
        evidence_id="EVID-JDL-MF-TAX-PURCHASE-REDUCED-8-ROUNDTRIP-001",
        tax_prefix="借方",
        expected_scope="仕　入",
        expected_category="軽減8%",
    )


def compare_purchase_reduced_8_subaccount_roundtrip(
    human_evidence: Path, candidate: Path, reexport: Path
) -> JdlTaxRoundTripComparison:
    analyze_reduced_8_subaccount_human_evidence(human_evidence)
    return _compare_tax_roundtrip(
        human_evidence,
        candidate,
        reexport,
        probe_case="tax_purchase_reduced_8_with_subaccount",
        evidence_id=EVIDENCE_ID_MF_JDL_PURCHASE_REDUCED_8_SUBACCOUNT_ROUNDTRIP,
        tax_prefix="借方",
        expected_scope="仕　入",
        expected_category="軽減8%",
        require_tax_side_subaccount=True,
    )


def compare_sales_reduced_8_subaccount_roundtrip(
    human_evidence: Path, candidate: Path, reexport: Path
) -> JdlTaxRoundTripComparison:
    analyze_reduced_8_subaccount_human_evidence(human_evidence)
    return _compare_tax_roundtrip(
        human_evidence,
        candidate,
        reexport,
        probe_case="tax_sales_reduced_8_with_subaccount",
        evidence_id=EVIDENCE_ID_MF_JDL_SALES_REDUCED_8_SUBACCOUNT_ROUNDTRIP,
        tax_prefix="貸方",
        expected_scope="売一種",
        expected_category="軽減8%",
        require_tax_side_subaccount=True,
    )


def compare_non_taxable_purchase_subaccount_roundtrip(
    human_evidence: Path, candidate: Path, reexport: Path
) -> JdlTaxRoundTripComparison:
    analyze_scoped_tax_human_evidence(
        human_evidence, "tax_non_taxable_purchase"
    )
    return _compare_tax_roundtrip(
        human_evidence,
        candidate,
        reexport,
        probe_case="tax_non_taxable_purchase_with_subaccount",
        evidence_id=EVIDENCE_ID_MF_JDL_NON_TAXABLE_PURCHASE_SUBACCOUNT_ROUNDTRIP,
        tax_prefix="借方",
        expected_scope="非仕入",
        expected_category="",
        require_tax_side_subaccount=True,
        subaccount_reference_candidate=True,
    )


def compare_out_of_scope_subaccount_roundtrip(
    human_evidence: Path,
    candidate: Path,
    candidate_manifest: Path,
    candidate_profile: Path,
    reexport: Path,
) -> JdlTaxRoundTripComparison:
    analyze_scoped_tax_human_evidence(human_evidence, "tax_out_of_scope")
    try:
        manifest = json.loads(candidate_manifest.read_text(encoding="utf-8"))
        profile_raw = candidate_profile.read_bytes()
        profile = json.loads(profile_raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise JdlTaxEvidenceError("out-of-scope candidate manifest is invalid") from exc
    expected_profile = (
        "SUPPORTED_1111_TAX_OUT_OF_SCOPE_SUBACCOUNT_INCLUDED"
    )
    if (
        manifest.get("probe_case") != "tax_out_of_scope_with_subaccount"
        or manifest.get("evidence_scope") != [expected_profile]
        or manifest.get("NOT_FOR_PRODUCTION") is not True
        or manifest.get("conversion_profile_sha256")
        != hashlib.sha256(profile_raw).hexdigest()
    ):
        raise JdlTaxEvidenceError(
            "blank tax fields require dedicated OUT_OF_SCOPE semantic identity"
        )
    mappings = profile.get("tax_mappings")
    if not isinstance(mappings, list) or not any(
        isinstance(item, dict)
        and item.get("source_value") == "対象外"
        and item.get("target_value") == ""
        and item.get("status") == "USER_CONFIRMED"
        and isinstance(item.get("metadata"), dict)
        and item["metadata"].get("jdl_tax_scope") == ""
        and item["metadata"].get("jdl_evidence_id")
        == "EVID-JDL-TAX-OUT-OF-SCOPE-HAND-001"
        for item in mappings
    ):
        raise JdlTaxEvidenceError(
            "MF out-of-scope source semantic mapping is not explicitly confirmed"
        )
    return _compare_tax_roundtrip(
        human_evidence,
        candidate,
        reexport,
        probe_case="tax_out_of_scope_with_subaccount",
        evidence_id=EVIDENCE_ID_MF_JDL_OUT_OF_SCOPE_SUBACCOUNT_ROUNDTRIP,
        tax_prefix="借方",
        expected_scope="",
        expected_category="",
        require_tax_side_subaccount=True,
        subaccount_reference_candidate=True,
    )


def _compare_tax_roundtrip(
    human_evidence: Path, candidate: Path, reexport: Path, *,
    probe_case: str, evidence_id: str, tax_prefix: str, expected_scope: str,
    expected_category: str = "10%",
    require_tax_side_subaccount: bool = False,
    subaccount_reference_candidate: bool = False,
) -> JdlTaxRoundTripComparison:
    human_raw, human_rows = _read_official_rows(human_evidence)
    candidate_raw, candidate_rows = _read_official_rows(candidate)
    reexport_raw, reexport_rows = _read_official_rows(reexport)
    if len(candidate_rows) != 1:
        raise JdlTaxEvidenceError("candidate must contain one row")
    header = jdl_ibex_cashbook_official_journal_import_spec().column_names
    pos = {name: index for index, name in enumerate(header)}
    expected = candidate_rows[0]
    other = "貸方" if tax_prefix == "借方" else "借方"
    human_matches = [
        row
        for row in human_rows
        if row[pos[f"{tax_prefix}課区"]] == expected_scope
        and row[pos[f"{tax_prefix}税区"]] == expected_category
    ]
    if len(human_matches) != 1:
        raise JdlTaxEvidenceError("human evidence tax row must be unique")
    human = human_matches[0]
    if (
        expected[pos["//識別フラグ"]] != "1111"
        or expected[pos[f"{tax_prefix}課区"]] != expected_scope
        or expected[pos[f"{tax_prefix}税区"]] != expected_category
        or expected[pos[f"{tax_prefix}税入力方法"]] != ""
        or expected[pos[f"{tax_prefix}消費税"]] != ""
        or any(expected[pos[f"{other}{name}"]] for name in ("課区", "税区", "税入力方法", "消費税"))
        or any(expected[pos[name]] for name in ("借方部門名称", "貸方部門名称"))
    ):
        raise JdlTaxEvidenceError("candidate is outside the scoped tax evidence")
    tax_sub_fields = (f"{tax_prefix}補助", f"{tax_prefix}補助名称")
    other_sub_fields = (f"{other}補助", f"{other}補助名称")
    if require_tax_side_subaccount:
        if not all(expected[pos[name]] for name in tax_sub_fields):
            raise JdlTaxEvidenceError("parent-scoped tax-side subaccount is required")
        if any(expected[pos[name]] for name in other_sub_fields):
            raise JdlTaxEvidenceError("opposite-side subaccount is outside the scope")
    elif any(
        expected[pos[name]]
        for name in (*tax_sub_fields, *other_sub_fields)
    ):
        raise JdlTaxEvidenceError("subaccount is outside the scoped tax evidence")
    identity = ("日付", "借方科目名称", "貸方科目名称", "借方金額", "貸方金額", "摘要")
    matches = [row for row in reexport_rows if all(row[pos[name]] == expected[pos[name]] for name in identity)]
    actual = matches[0] if len(matches) == 1 else None
    account_fields = ("借方科目", "借方科目名称", "借方科目正式名称", "貸方科目", "貸方科目名称", "貸方科目正式名称")
    normalized = () if actual is None else tuple(
        category
        for category, fields in (
            ("account_master_identity", account_fields),
            ("tax_amount_reexport_representation", ("借方消費税", "貸方消費税")),
        )
        if any(expected[pos[name]] == "" and actual[pos[name]] != "" for name in fields)
    )
    common = dict(
        human_sha256=_sha256(human_raw), candidate_sha256=_sha256(candidate_raw),
        reexport_sha256=_sha256(reexport_raw), reexport_journal_count=len(reexport_rows),
        candidate_match_count=len(matches), candidate_blank_fields_normalized_by_jdl=normalized,
        probe_case=probe_case, evidence_id=evidence_id,
    )
    if actual is None:
        return JdlTaxRoundTripComparison(account_identity_match=False, amount_match=False, debit_tax_fields_match=False, credit_tax_fields_match=False, description_preserved=False, balance_preserved=False, date_preserved=False, identifier_flag_preserved=False, parent_scoped_subaccount_match=False, **common)
    debit_tax = ("借方課区", "借方税区", "借方税入力方法", "借方消費税")
    credit_tax = ("貸方課区", "貸方税区", "貸方税入力方法", "貸方消費税")
    return JdlTaxRoundTripComparison(
        account_identity_match=_fields_equal(human, actual, pos, account_fields),
        amount_match=_fields_equal(expected, actual, pos, ("借方金額", "貸方金額")),
        debit_tax_fields_match=_fields_equal(human, actual, pos, debit_tax),
        credit_tax_fields_match=_fields_equal(human, actual, pos, credit_tax),
        description_preserved=expected[pos["摘要"]] == actual[pos["摘要"]],
        balance_preserved=actual[pos["借方金額"]] == actual[pos["貸方金額"]],
        date_preserved=expected[pos["日付"]] == actual[pos["日付"]],
        identifier_flag_preserved=(
            expected[pos["//識別フラグ"]]
            == actual[pos["//識別フラグ"]]
            == "1111"
        ),
        parent_scoped_subaccount_match=(
            _fields_equal(
                expected if subaccount_reference_candidate else human,
                actual,
                pos,
                tax_sub_fields,
            )
            if require_tax_side_subaccount
            else not any(actual[pos[name]] for name in (*tax_sub_fields, *other_sub_fields))
        ),
        **common,
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
