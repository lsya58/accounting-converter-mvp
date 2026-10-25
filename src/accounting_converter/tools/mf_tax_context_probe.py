from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from accounting_converter.profiles.jdl_official import (
    jdl_ibex_cashbook_official_journal_import_spec,
)


HEADER = tuple(jdl_ibex_cashbook_official_journal_import_spec().column_names)
KNOWN_BLANK_NORMALIZATIONS = frozenset(
    {"伝番", "借方消費税", "貸方消費税", "借方部門コード", "貸方部門コード"}
)


@dataclass(frozen=True)
class ProbeComparison:
    classification: str
    missing_journals: int
    extra_journals: int
    missing_rows: int
    extra_rows: int
    unexpected_changes: tuple[str, ...]
    known_normalizations: tuple[str, ...]


def generate_probe(config_path: Path, output_path: Path, manifest_path: Path) -> None:
    """Generate a private, non-production JDL batch from an explicit config."""
    if output_path.exists() or manifest_path.exists():
        raise FileExistsError("probe output already exists")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("NOT_FOR_PRODUCTION") is not True or config.get("production_allowed") is not False:
        raise ValueError("private probe safety markers are required")
    cases = tuple(config.get("cases", ()))
    if not cases:
        raise ValueError("at least one probe case is required")

    rows: list[list[str]] = []
    dates: list[str] = []
    for case in cases:
        case_rows = tuple(case.get("rows", ()))
        if not case_rows:
            raise ValueError("each case requires physical rows")
        _validate_case(case_rows)
        dates.extend(str(row.get("日付", "")) for row in case_rows)
        for values in case_rows:
            row = [str(values.get(name, "")) for name in HEADER]
            _validate_row(row)
            rows.append(row)
    if any(not value.isdigit() or len(value) != 8 for value in dates):
        raise ValueError("probe dates must be YYYYMMDD")

    start, end = min(dates), max(dates)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(["// MF TAX CONTEXT PROBE / NOT FOR PRODUCTION", *("" for _ in range(29))])
    writer.writerow([f"// 出力期間 ： {start} ～ {end}", *("" for _ in range(29))])
    writer.writerow([""] * 30)
    writer.writerow(HEADER)
    writer.writerows(rows)
    raw = stream.getvalue().encode("cp932", errors="strict")
    _validate_bytes(raw, expected_rows=len(rows))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(raw)

    manifest = {
        "schema_version": "1",
        "NOT_FOR_PRODUCTION": True,
        "production_allowed": False,
        "evidence_status": "PENDING_REAL_JDL_IMPORT_REEXPORT",
        "context": config["context"],
        "target_master_identity_sha256": config["target_master_identity_sha256"],
        "import_period": {"start": start, "end": end},
        "journal_count": len(cases),
        "physical_row_count": len(rows),
        "patterns": [
            {
                "pattern_id": case["pattern_id"],
                "occurrence_count": int(case["occurrence_count"]),
                "planned_evidence_id": case["planned_evidence_id"],
                "status": "PENDING_REAL_JDL_IMPORT_REEXPORT",
            }
            for case in cases
        ],
        "candidate_sha256": hashlib.sha256(raw).hexdigest(),
        "comparison_policy": {
            "required": [
                "journal_count", "physical_row_count", "row_order", "flags",
                "account", "subaccount", "tax_category", "tax_rate",
                "tax_amount", "tax_input_method", "description", "balance",
            ],
            "allowed": sorted(KNOWN_BLANK_NORMALIZATIONS),
            "unknown_normalization_allowed": False,
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def compare_probe(candidate: Path, reexport: Path) -> ProbeComparison:
    expected = _journal_rows(candidate)
    actual = _journal_rows(reexport)
    missing_rows = max(0, len(expected) - len(actual))
    extra_rows = max(0, len(actual) - len(expected))
    unexpected: list[str] = []
    known: list[str] = []
    positions = {name: index for index, name in enumerate(HEADER)}
    account_name_positions = {
        positions["借方科目名称"]: positions["借方科目"],
        positions["借方科目正式名称"]: positions["借方科目"],
        positions["貸方科目名称"]: positions["貸方科目"],
        positions["貸方科目正式名称"]: positions["貸方科目"],
    }
    subaccount_code_positions = {
        positions["借方補助"]: positions["借方補助名称"],
        positions["貸方補助"]: positions["貸方補助名称"],
    }
    for row_index, (left, right) in enumerate(zip(expected, actual), 1):
        for index, name in enumerate(HEADER):
            if left[index] == right[index]:
                continue
            if (
                index in account_name_positions
                and left[account_name_positions[index]]
                == right[account_name_positions[index]]
                and right[index]
            ):
                known.append(f"row-{row_index}:{name}:TARGET_MASTER_NAME_NORMALIZATION")
            elif (
                index in subaccount_code_positions
                and left[index].isdigit()
                and right[index].isdigit()
                and int(left[index]) == int(right[index])
                and left[subaccount_code_positions[index]]
                == right[subaccount_code_positions[index]]
            ):
                known.append(f"row-{row_index}:{name}:NUMERIC_CODE_ZERO_SUPPRESSION")
            elif (
                name == "伝番"
                and left[index] == ""
                and right[index].isdigit()
            ) or (
                name in KNOWN_BLANK_NORMALIZATIONS - {"伝番"}
                and left[index] == ""
                and right[index] == "0"
            ):
                known.append(f"row-{row_index}:{name}:KNOWN_JDL_CANONICAL_NORMALIZATION")
            else:
                unexpected.append(f"row-{row_index}:{name}")
    expected_journals = _journal_count(expected)
    actual_journals = _journal_count(actual)
    missing_journals = max(0, expected_journals - actual_journals)
    extra_journals = max(0, actual_journals - expected_journals)
    if missing_rows or extra_rows or missing_journals or extra_journals or unexpected:
        classification = "UNEXPECTED_CHANGE"
    elif known:
        classification = "KNOWN_JDL_CANONICAL_NORMALIZATION"
    else:
        classification = "EXACT_MATCH"
    return ProbeComparison(
        classification, missing_journals, extra_journals, missing_rows, extra_rows,
        tuple(unexpected), tuple(known),
    )


def comparison_to_dict(result: ProbeComparison) -> dict[str, object]:
    return {
        "classification": result.classification,
        "missing_journal_count": result.missing_journals,
        "extra_journal_count": result.extra_journals,
        "missing_physical_row_count": result.missing_rows,
        "extra_physical_row_count": result.extra_rows,
        "unexpected_changes": result.unexpected_changes,
        "known_normalizations": result.known_normalizations,
        "evidence_promotion_allowed": result.classification != "UNEXPECTED_CHANGE",
    }


def compare_probe_patterns(
    candidate: Path, reexport: Path, pattern_ids: Sequence[str]
) -> tuple[dict[str, object], ...]:
    expected_groups = _group_rows(_journal_rows(candidate))
    actual_groups = _group_rows(_journal_rows(reexport))
    results: list[dict[str, object]] = []
    for index, pattern_id in enumerate(pattern_ids):
        if index >= len(expected_groups) or index >= len(actual_groups):
            results.append({
                "pattern_id": pattern_id,
                "classification": "UNEXPECTED_CHANGE",
                "unexpected_changes": ("missing_or_extra_journal",),
                "known_normalizations": (),
                "evidence_eligible": False,
            })
            continue
        result = _compare_rows(expected_groups[index], actual_groups[index])
        results.append({
            "pattern_id": pattern_id,
            "classification": result.classification,
            "unexpected_changes": result.unexpected_changes,
            "known_normalizations": result.known_normalizations,
            "evidence_eligible": result.classification != "UNEXPECTED_CHANGE",
        })
    return tuple(results)


def _compare_rows(
    expected: Sequence[Sequence[str]], actual: Sequence[Sequence[str]]
) -> ProbeComparison:
    with _temporary_rows(expected) as left, _temporary_rows(actual) as right:
        return compare_probe(left, right)


class _temporary_rows:
    def __init__(self, rows: Sequence[Sequence[str]]) -> None:
        import tempfile
        self._directory = tempfile.TemporaryDirectory()
        self.path = Path(self._directory.name) / "rows.csv"
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\r\n")
        writer.writerow(HEADER)
        writer.writerows(rows)
        self.path.write_bytes(stream.getvalue().encode("cp932", errors="strict"))

    def __enter__(self) -> Path:
        return self.path

    def __exit__(self, *_args) -> None:
        self._directory.cleanup()


def _group_rows(rows: Sequence[Sequence[str]]) -> tuple[tuple[Sequence[str], ...], ...]:
    groups: list[list[Sequence[str]]] = []
    current: list[Sequence[str]] = []
    for row in rows:
        flag = row[0]
        if flag == "1111":
            if current:
                raise ValueError("invalid journal grouping")
            groups.append([row])
        elif flag == "1110":
            if current:
                raise ValueError("nested journal grouping")
            current = [row]
        elif flag == "1100":
            if not current:
                raise ValueError("orphan middle row")
            current.append(row)
        elif flag == "1101":
            if not current:
                raise ValueError("orphan final row")
            current.append(row)
            groups.append(current)
            current = []
        else:
            raise ValueError("unsupported journal flag")
    if current:
        raise ValueError("unterminated journal grouping")
    return tuple(tuple(group) for group in groups)


def _validate_row(row: Sequence[str]) -> None:
    if len(row) != 30:
        raise ValueError("official 30-column row is required")
    positions = {name: index for index, name in enumerate(HEADER)}
    if row[positions["//識別フラグ"]] not in {"1111", "1110", "1100", "1101"}:
        raise ValueError("unsupported probe flag")
    debit = int(row[positions["借方金額"]] or "0")
    credit = int(row[positions["貸方金額"]] or "0")
    if debit < 0 or credit < 0:
        raise ValueError("negative probe amount is not allowed")
    for prefix in ("借方", "貸方"):
        scope = row[positions[f"{prefix}課区"]]
        rate = row[positions[f"{prefix}税区"]]
        method = row[positions[f"{prefix}税入力方法"]]
        amount = row[positions[f"{prefix}消費税"]]
        if scope:
            if (scope, rate, method) != ("仕　入", "10%", "内税") or not amount.isdigit():
                raise ValueError("tax-excluded probe requires exact purchase/10%/internal-tax fields")
        elif rate or method or amount:
            raise ValueError("opposite-side tax fields must be blank")


def _validate_case(rows: Sequence[dict[str, object]]) -> None:
    flags = tuple(str(row.get("//識別フラグ", "")) for row in rows)
    if len(rows) == 1:
        if flags != ("1111",):
            raise ValueError("single-row probe requires flag 1111")
    elif flags[0] != "1110" or flags[-1] != "1101" or any(
        flag != "1100" for flag in flags[1:-1]
    ):
        raise ValueError("compound probe flags must be 1110/1100*/1101")
    debit_total = sum(int(str(row.get("借方金額", "0")) or "0") for row in rows)
    credit_total = sum(int(str(row.get("貸方金額", "0")) or "0") for row in rows)
    if debit_total != credit_total:
        raise ValueError("probe journal must be balanced")


def _validate_bytes(raw: bytes, *, expected_rows: int) -> None:
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise ValueError("BOM is not allowed")
    if not raw.endswith(b"\r\n") or b"\n" in raw.replace(b"\r\n", b""):
        raise ValueError("CRLF-only CSV is required")
    rows = list(csv.reader(io.StringIO(raw.decode("cp932", errors="strict"))))
    headers = [i for i, row in enumerate(rows) if tuple(row) == HEADER]
    if len(headers) != 1 or len(rows) - headers[0] - 1 != expected_rows:
        raise ValueError("probe row count or official header is invalid")
    header_index = headers[0]
    if any(
        row
        and any(row)
        and not (len(row) in {1, 30} and row[0].startswith("//"))
        for row in rows[:header_index]
    ):
        raise ValueError("unknown preamble row is not allowed")
    if any(len(row) != 30 for row in rows[header_index:]):
        raise ValueError("all official journal rows must have 30 columns")


def _journal_rows(path: Path) -> tuple[tuple[str, ...], ...]:
    raw = path.read_bytes()
    _validate_bytes(raw, expected_rows=_count_rows_after_header(raw))
    rows = list(csv.reader(io.StringIO(raw.decode("cp932", errors="strict"))))
    header_index = next(i for i, row in enumerate(rows) if tuple(row) == HEADER)
    return tuple(tuple(row) for row in rows[header_index + 1:])


def _count_rows_after_header(raw: bytes) -> int:
    rows = list(csv.reader(io.StringIO(raw.decode("cp932", errors="strict"))))
    header_index = next(i for i, row in enumerate(rows) if tuple(row) == HEADER)
    return len(rows) - header_index - 1


def _journal_count(rows: Iterable[Sequence[str]]) -> int:
    flags = [row[0] for row in rows]
    return sum(flag in {"1111", "1110"} for flag in flags)
