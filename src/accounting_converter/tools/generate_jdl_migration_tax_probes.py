from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

from accounting_converter.adapters.input.jdl import JdlMigrationParser
from accounting_converter.profiles.jdl_official import (
    jdl_ibex_cashbook_official_journal_import_spec,
)


CASES = (
    ("sales_second_10", "20260330", "売二種", "JDL-MIG-TAX-S2-10"),
    ("sales_fifth_10", "20260331", "売五種", "JDL-MIG-TAX-S5-10"),
)


@dataclass(frozen=True)
class ProbeConfig:
    debit_account_code: str
    debit_account_name: str
    credit_account_code: str
    credit_account_name: str
    cases: tuple[tuple[str, str, str, str], ...] = CASES
    target_master_sha256: str = ""


def generate(
    output_dir: Path,
    private_root: Path,
    config: ProbeConfig = ProbeConfig("111", "現金", "612", "売上高"),
) -> tuple[Path, ...]:
    output_dir = output_dir.resolve()
    private_root = private_root.resolve()
    if output_dir != private_root and private_root not in output_dir.parents:
        raise ValueError("probe output must stay under data/private")
    planned = tuple(
        output_dir / f"{case}.{suffix}"
        for case, _date, _scope, _description in config.cases
        for suffix in ("csv", "manifest.json", "result.json")
    )
    if any(path.exists() for path in planned):
        raise FileExistsError("probe output already exists")
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for case, journal_date, scope, description in config.cases:
        candidate = output_dir / f"{case}.csv"
        candidate.write_bytes(
            _candidate_bytes(
                journal_date, scope, description,
                period_start=journal_date, period_end=journal_date,
                debit_account=(config.debit_account_code, config.debit_account_name),
                credit_account=(config.credit_account_code, config.credit_account_name),
            )
        )
        parsed = JdlMigrationParser().parse_path(candidate)
        if len(parsed.entries) != 1 or parsed.journal_record_count != 1:
            raise RuntimeError("generated probe structure is invalid")
        manifest = output_dir / f"{case}.manifest.json"
        result = output_dir / f"{case}.result.json"
        manifest.write_text(json.dumps({
            "schema_version": "1",
            "probe_case": case,
            "semantic_scope": scope,
            "tax_category": "10%",
            "journal_date": journal_date,
            "header_output_period_start": journal_date,
            "header_output_period_end": journal_date,
            "candidate_sha256": _sha256(candidate),
            "target_master_sha256": config.target_master_sha256,
            "journal_count": 1,
            "physical_rows": 1,
            "official_columns": 30,
            "encoding": "CP932",
            "bom": False,
            "line_ending": "CRLF",
            "expected_preflight_blockers": ["JDL-MIGRATION-TAX-UNVERIFIED"],
            "mapping_promotion_allowed": False,
            "production_allowed": False,
            "NOT_FOR_PRODUCTION": True,
        }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result.write_text(json.dumps({
            "schema_version": "1",
            "probe_case": case,
            "result_status": "UNTESTED",
            "comparison_pass": None,
            "mapping_promotion_allowed": False,
            "production_allowed": False,
            "NOT_FOR_PRODUCTION": True,
        }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.extend((candidate, manifest, result))
    return tuple(written)


def compare(candidate: Path, reexport: Path) -> dict[str, object]:
    header, expected_rows = _read_rows(candidate, require_header_first=False)
    actual_header, actual_rows = _read_rows(reexport, require_header_first=False)
    if actual_header != header:
        raise ValueError("official header mismatch")
    mismatches = _semantic_mismatches(header, expected_rows, actual_rows)
    return {
        "comparison_pass": not mismatches,
        "expected_journals": len(JdlMigrationParser().parse_path(candidate).entries),
        "actual_journals": len(JdlMigrationParser().parse_path(reexport).entries),
        "expected_rows": len(expected_rows),
        "actual_rows": len(actual_rows),
        "missing_or_extra": len(expected_rows) != len(actual_rows),
        "semantic_mismatch": bool(mismatches),
        "mismatched_fields": sorted(mismatches),
    }


def compare_in_reexport(candidate: Path, reexport: Path) -> dict[str, object]:
    """Strictly compare one probe selected from a possibly mixed re-export."""
    header, expected_rows = _read_rows(candidate, require_header_first=False)
    actual_header, actual_rows = _read_rows(reexport, require_header_first=False)
    if actual_header != header:
        raise ValueError("official header mismatch")
    if len(expected_rows) != 1:
        raise ValueError("single-journal probe is required")
    expected = expected_rows[0]
    positions = {name: index for index, name in enumerate(header)}
    identity_fields = (
        "日付",
        "借方科目",
        "借方科目名称",
        "貸方科目",
        "貸方科目名称",
        "摘要",
    )
    matches = [
        row
        for row in actual_rows
        if all(row[positions[name]] == expected[positions[name]] for name in identity_fields)
    ]
    if len(matches) != 1:
        raise ValueError("probe identity must match exactly one re-export row")
    mismatches = _semantic_mismatches(header, expected_rows, matches)
    return {
        "comparison_pass": not mismatches,
        "expected_journals": 1,
        "actual_journals": 1,
        "expected_rows": 1,
        "actual_rows": 1,
        "reexport_total_rows": len(actual_rows),
        "unique_probe_match": True,
        "missing_or_extra": False,
        "semantic_mismatch": bool(mismatches),
        "mismatched_fields": sorted(mismatches),
    }


def _candidate_bytes(
    journal_date: str,
    scope: str,
    description: str,
    *,
    period_start: str,
    period_end: str,
    debit_account: tuple[str, str],
    credit_account: tuple[str, str],
) -> bytes:
    _validate_period((journal_date,), period_start, period_end)
    header = jdl_ibex_cashbook_official_journal_import_spec().column_names
    row = [""] * 30
    row[0], row[2] = "1111", journal_date
    row[3], row[4], row[11] = debit_account[0], debit_account[1], "1100"
    row[13], row[14], row[18], row[19], row[21] = (
        credit_account[0], credit_account[1], scope, "10%", "1100"
    )
    row[23] = description
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(["// JDL MIGRATION TAX PROBE", *("" for _ in range(29))])
    writer.writerow([
        f"// 出力期間 ： {period_start} ～ {period_end}",
        *("" for _ in range(29)),
    ])
    writer.writerow([""] * 30)
    writer.writerow(header)
    writer.writerow(row)
    return stream.getvalue().encode("cp932", errors="strict")


def _validate_period(
    journal_dates: tuple[str, ...], period_start: str, period_end: str
) -> None:
    if not period_start.isdigit() or not period_end.isdigit():
        raise ValueError("output period must use YYYYMMDD")
    if period_start > period_end or any(
        value < period_start or value > period_end for value in journal_dates
    ):
        raise ValueError("transaction date is outside header output period")


def _read_rows(path: Path, *, require_header_first: bool):
    raw = path.read_bytes()
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise ValueError("BOM is not allowed")
    if not raw.endswith(b"\r\n") or b"\n" in raw.replace(b"\r\n", b""):
        raise ValueError("CRLF-only CSV is required")
    rows = list(csv.reader(io.StringIO(raw.decode("cp932", errors="strict"), newline=""), strict=True))
    header = tuple(jdl_ibex_cashbook_official_journal_import_spec().column_names)
    indexes = [index for index, row in enumerate(rows) if tuple(row) == header]
    if len(indexes) != 1 or (require_header_first and indexes[0] != 0):
        raise ValueError("exact official header is required")
    data = rows[indexes[0] + 1:]
    if not data or any(len(row) != 30 for row in data):
        raise ValueError("official 30-column rows are required")
    return header, data


def _semantic_mismatches(header, expected, actual) -> set[str]:
    if len(expected) != len(actual):
        return {"row_count"}
    pos = {name: index for index, name in enumerate(header)}
    compared = (
        "//識別フラグ", "日付", "借方科目", "借方科目名称",
        "借方補助", "借方補助名称", "借方課区", "借方税区",
        "借方税入力方法", "借方金額", "貸方科目", "貸方科目名称",
        "貸方補助", "貸方補助名称", "貸方課区", "貸方税区",
        "貸方税入力方法", "貸方金額", "摘要",
    )
    mismatches = {
        name
        for left, right in zip(expected, actual, strict=True)
        for name in compared
        if left[pos[name]] != right[pos[name]]
    }
    for side in ("借方", "貸方"):
        name = f"{side}消費税"
        for left, right in zip(expected, actual, strict=True):
            if not (
                left[pos[name]] == right[pos[name]]
                or (left[pos[name]] == "" and right[pos[name]] == "0")
            ):
                mismatches.add(name)
    return mismatches


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
