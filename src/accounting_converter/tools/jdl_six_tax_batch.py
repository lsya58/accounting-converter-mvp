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


SIX_TAX_CASE_IDENTITIES = (
    "SIX-TAX-P10",
    "SIX-TAX-S10",
    "SIX-TAX-PR8",
    "SIX-TAX-SR8",
    "SIX-TAX-NTP",
    "SIX-TAX-OOS",
)
SIX_TAX_BATCH_ROUNDTRIP_EVIDENCE_ID = (
    "EVID-JDL-MF-SIX-TAX-BATCH-ROUNDTRIP-001"
)
SIX_TAX_EVIDENCE_PROFILES = (
    "SUPPORTED_1111_TAX_PURCHASE_10_SUBACCOUNT_INCLUDED",
    "SUPPORTED_1111_TAX_SALES_10_SUBACCOUNT_INCLUDED",
    "SUPPORTED_1111_TAX_PURCHASE_REDUCED_8_INCLUDED",
    "SUPPORTED_1111_TAX_SALES_REDUCED_8_SUBACCOUNT_INCLUDED",
    "SUPPORTED_1111_TAX_NON_TAXABLE_PURCHASE_SUBACCOUNT_INCLUDED",
    "SUPPORTED_1111_TAX_OUT_OF_SCOPE_SUBACCOUNT_INCLUDED",
)


@dataclass(frozen=True)
class JdlSixTaxBatchComparison:
    status: str
    expected_count: int
    actual_count: int
    matched_count: int
    missing_count: int
    duplicate_count: int
    extra_count: int
    ambiguous_count: int
    mismatched_count: int

    @property
    def passed(self) -> bool:
        return self.status == "MATCH"

    def privacy_safe_result(self) -> dict[str, int | str | bool]:
        return {
            "status": self.status,
            "comparison_pass": self.passed,
            "expected_count": self.expected_count,
            "actual_count": self.actual_count,
            "matched_count": self.matched_count,
            "missing_count": self.missing_count,
            "duplicate_count": self.duplicate_count,
            "extra_count": self.extra_count,
            "ambiguous_count": self.ambiguous_count,
            "mismatched_count": self.mismatched_count,
        }


def compare_jdl_six_tax_batch(
    candidate_path: Path,
    reexport_path: Path,
    *,
    manifest_case_identities: tuple[str, ...],
) -> JdlSixTaxBatchComparison:
    if manifest_case_identities != SIX_TAX_CASE_IDENTITIES:
        return JdlSixTaxBatchComparison("MANIFEST_MISMATCH", 6, 0, 0, 6, 0, 0, 0, 0)

    candidate = _read_rows(candidate_path)
    actual = _read_rows(reexport_path)
    description_index = 23
    candidate_by_id = _index(candidate, description_index)
    actual_by_id = _index(actual, description_index)
    duplicates = sum(max(0, len(rows) - 1) for rows in actual_by_id.values())
    extras = sum(
        len(rows) for identity, rows in actual_by_id.items()
        if identity not in SIX_TAX_CASE_IDENTITIES
    )
    ambiguous = sum(
        1 for identity in SIX_TAX_CASE_IDENTITIES
        if len(actual_by_id.get(identity, ())) > 1
    )
    missing = 0
    mismatched = 0
    matched = 0
    # JDL supplies master codes/formal names and zero representations on
    # re-export. Those fields are validated against the exact profile by the
    # artifact comparator; semantic fields remain strict here.
    compared_indexes = (
        0, 2, 4, 7, 8, 9, 10, 11, 14, 17, 18, 19, 20, 21, 23, 27, 29,
    )
    for identity in SIX_TAX_CASE_IDENTITIES:
        expected_rows = candidate_by_id.get(identity, ())
        actual_rows = actual_by_id.get(identity, ())
        if len(expected_rows) != 1 or len(actual_rows) != 1:
            if not actual_rows:
                missing += 1
            continue
        expected = expected_rows[0]
        observed = actual_rows[0]
        normalized_fields_valid = (
            expected[1] == "" and observed[1] in ("", "0")
            and expected[12] == "" and observed[12] in ("", "0")
            and expected[22] == "" and observed[22] in ("", "0")
            and expected[26] == "" and observed[26] in ("", "0")
            and expected[28] == "" and observed[28] in ("", "0")
        )
        balanced = observed[11] == observed[21]
        if (
            all(expected[index] == observed[index] for index in compared_indexes)
            and normalized_fields_valid
            and balanced
        ):
            matched += 1
        else:
            mismatched += 1
    status = (
        "MATCH"
        if matched == 6 and not missing and not duplicates and not extras
        and not ambiguous and not mismatched and len(actual) == 6
        else "MISMATCH"
    )
    return JdlSixTaxBatchComparison(
        status, 6, len(actual), matched, missing, duplicates, extras, ambiguous,
        mismatched
    )


def compare_jdl_six_tax_batch_artifact(
    candidate_path: Path,
    reexport_path: Path,
    manifest_path: Path,
    profile_path: Path,
    context_path: Path | None = None,
) -> JdlSixTaxBatchComparison:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        profile_raw = profile_path.read_bytes()
        profile = json.loads(profile_raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return JdlSixTaxBatchComparison("MANIFEST_MISMATCH", 6, 0, 0, 6, 0, 0, 0, 0)
    if (
        manifest.get("batch_semantic_identity") != "MF_SIX_TAX_CASES_BATCH_V0"
        or tuple(manifest.get("case_identities", ())) != SIX_TAX_CASE_IDENTITIES
        or tuple(manifest.get("evidence_scope", ())) != SIX_TAX_EVIDENCE_PROFILES
        or manifest.get("expected_journal_count") != 6
        or manifest.get("expected_row_count") != 6
        or manifest.get("NOT_FOR_PRODUCTION") is not True
        or manifest.get("production_allowed") is not False
        or manifest.get("output_sha256")
        != hashlib.sha256(candidate_path.read_bytes()).hexdigest()
        or manifest.get("conversion_profile_sha256")
        != hashlib.sha256(profile_raw).hexdigest()
        or (
            context_path is not None
            and manifest.get("jdl_context_sha256")
            != hashlib.sha256(context_path.read_bytes()).hexdigest()
        )
    ):
        return JdlSixTaxBatchComparison("MANIFEST_MISMATCH", 6, 0, 0, 6, 0, 0, 0, 0)
    mappings = profile.get("tax_mappings")
    if not isinstance(mappings, list) or not any(
        isinstance(item, dict)
        and item.get("source_value") == "対象外"
        and item.get("target_value") == ""
        and item.get("status") == "USER_CONFIRMED"
        and isinstance(item.get("metadata"), dict)
        and item["metadata"].get("jdl_tax_scope") == ""
        and item["metadata"].get("jdl_evidence_id")
        == "EVID-JDL-MF-TAX-OUT-OF-SCOPE-SUBACCOUNT-ROUNDTRIP-001"
        for item in mappings
    ):
        return JdlSixTaxBatchComparison("PROFILE_MISMATCH", 6, 0, 0, 6, 0, 0, 0, 0)
    if not _master_fields_match(candidate_path, reexport_path, profile):
        return JdlSixTaxBatchComparison("PROFILE_MISMATCH", 6, 6, 0, 0, 0, 0, 0, 6)
    return compare_jdl_six_tax_batch(
        candidate_path,
        reexport_path,
        manifest_case_identities=SIX_TAX_CASE_IDENTITIES,
    )


def _master_fields_match(
    candidate_path: Path, reexport_path: Path, profile: dict[str, object]
) -> bool:
    accounts = {
        item.get("target_value"): item.get("metadata")
        for item in profile.get("account_mappings", [])
        if isinstance(item, dict) and item.get("status") == "USER_CONFIRMED"
    }
    subaccounts = {
        (item.get("parent_account"), item.get("target_value")): item.get("metadata")
        for item in profile.get("subaccount_context_mappings", [])
        if isinstance(item, dict) and item.get("status") == "USER_CONFIRMED"
    }
    candidate = _index(_read_rows(candidate_path), 23)
    actual = _index(_read_rows(reexport_path), 23)
    for identity in SIX_TAX_CASE_IDENTITIES:
        if len(candidate.get(identity, ())) != 1 or len(actual.get(identity, ())) != 1:
            return False
        expected = candidate[identity][0]
        observed = actual[identity][0]
        for name_index, code_index, formal_index in ((4, 3, 5), (14, 13, 15)):
            metadata = accounts.get(expected[name_index])
            if not isinstance(metadata, dict) or (
                observed[code_index] != metadata.get("target_code")
                or observed[formal_index] != metadata.get("target_formal_name")
            ):
                return False
        for parent_index, name_index, code_index in ((4, 7, 6), (14, 17, 16)):
            if not expected[name_index]:
                if observed[name_index] or observed[code_index]:
                    return False
                continue
            metadata = subaccounts.get((expected[parent_index], expected[name_index]))
            if not isinstance(metadata, dict) or (
                observed[name_index] != metadata.get("output_name")
                or observed[code_index] != metadata.get("output_code")
            ):
                return False
    return True


def _read_rows(path: Path) -> tuple[tuple[str, ...], ...]:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r\n" not in raw:
        raise ValueError("JDL batch evidence must be CP932, BOM-less, and CRLF")
    text = raw.decode("cp932", errors="strict")
    rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    header = tuple(jdl_ibex_cashbook_official_journal_import_spec().column_names)
    indexes = [index for index, row in enumerate(rows) if tuple(row) == header]
    if len(indexes) != 1:
        raise ValueError("exact JDL header must occur once")
    data = tuple(tuple(row) for row in rows[indexes[0] + 1 :] if any(row))
    if any(len(row) != 30 for row in data):
        raise ValueError("JDL batch rows must contain exactly 30 columns")
    return data


def _index(
    rows: tuple[tuple[str, ...], ...], description_index: int
) -> dict[str, tuple[tuple[str, ...], ...]]:
    result: dict[str, list[tuple[str, ...]]] = {}
    for row in rows:
        result.setdefault(row[description_index], []).append(row)
    return {key: tuple(value) for key, value in result.items()}
