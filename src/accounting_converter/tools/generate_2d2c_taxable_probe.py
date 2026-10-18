from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

from accounting_converter.profiles.jdl_official import (
    jdl_ibex_cashbook_official_journal_import_spec,
)


CASE_ID = "compound_2d2c_purchase_10_taxable"
DATE = "20261126"
EVIDENCE_ID = "EVID-JDL-COMPOUND-2D2C-PURCHASE-10-TAXABLE-ROUNDTRIP-001"
COMPONENT_EVIDENCE = (
    "EVID-JDL-COMPOUND-2D2C-PER-ROW-DESCRIPTION-001",
    "EVID-JDL-MF-TAX-PURCHASE-10-SUBACCOUNT-ROUNDTRIP-001",
)


def generate(output_dir: Path, private_root: Path) -> dict[str, Path]:
    output_dir = output_dir.resolve()
    private_root = private_root.resolve()
    if output_dir != private_root and private_root not in output_dir.parents:
        raise ValueError("probe output must stay under data/private")
    paths = {
        "candidate": output_dir / "compound_2d2c_taxable.csv",
        "manifest": output_dir / "compound_2d2c_taxable.manifest.json",
        "result": output_dir / "compound_2d2c_taxable_result.json",
    }
    existing = [path.name for path in paths.values() if path.exists()]
    if existing:
        raise FileExistsError(f"probe output exists: {', '.join(existing)}")
    output_dir.mkdir(parents=True, exist_ok=True)

    header = tuple(jdl_ibex_cashbook_official_journal_import_spec().column_names)
    rows = _candidate_rows(header)
    _validate_candidate(header, rows)
    _write_csv(paths["candidate"], header, rows)
    manifest = {
        "schema_version": "1",
        "probe_case": CASE_ID,
        "component_evidence_ids": list(COMPONENT_EVIDENCE),
        "new_feature_combination": "2D2C_PLUS_PURCHASE_10_TAXABLE",
        "expected_date": DATE,
        "expected_rows": 2,
        "expected_shape": {"debit_lines": 2, "credit_lines": 2},
        "expected_flag_sequence": ["1110", "1101"],
        "candidate_sha256": _hash(paths["candidate"]),
        "strict_comparison_required": True,
        "trade_partner_present": False,
        "other_optional_fields_present": False,
        "component_preflight": "PASS",
        "formal_preflight": "BLOCKED_PENDING_2D2C_TAXABLE_EVIDENCE",
        "production_allowed": False,
        "NOT_FOR_PRODUCTION": True,
    }
    result = {
        "schema_version": "1",
        "probe_case": CASE_ID,
        "result_status": "UNTESTED",
        "comparison_pass": None,
        "mapping_promotion_allowed": False,
        "production_allowed": False,
        "NOT_FOR_PRODUCTION": True,
    }
    paths["manifest"].write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths["result"].write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return paths


def compare_reexport(candidate: Path, manifest_path: Path, reexport: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("probe_case") != CASE_ID
        or manifest.get("candidate_sha256") != _hash(candidate)
        or manifest.get("NOT_FOR_PRODUCTION") is not True
    ):
        raise ValueError("probe manifest identity mismatch")
    header, expected = _read_csv(candidate, require_header_first=True)
    actual_header, all_actual = _read_csv(reexport)
    if header != actual_header:
        raise ValueError("official header mismatch")
    pos = {name: index for index, name in enumerate(header)}
    actual = [row for row in all_actual if row[pos["日付"]] == DATE]
    mismatches = _semantic_mismatches(header, expected, actual)
    passed = len(expected) == len(actual) == 2 and not mismatches
    return {
        "schema_version": "1",
        "probe_case": CASE_ID,
        "candidate_sha256": _hash(candidate),
        "reexport_sha256": _hash(reexport),
        "expected_rows": 2,
        "actual_rows": len(actual),
        "missing_rows": max(2 - len(actual), 0),
        "extra_rows": max(len(actual) - 2, 0),
        "mismatch_field_categories": sorted(mismatches),
        "comparison_pass": passed,
        "evidence_id": EVIDENCE_ID,
        "evidence_level": "VERIFIED_BY_REAL_IMPORT" if passed else "UNTESTED",
        "mapping_promotion_allowed": False,
        "production_allowed": False,
        "NOT_FOR_PRODUCTION": True,
    }


def _candidate_rows(header: tuple[str, ...]) -> list[list[str]]:
    pos = {name: index for index, name in enumerate(header)}
    rows = [[""] * 30 for _ in range(2)]
    for row, flag, description in zip(
        rows, ("1110", "1101"), ("JDL-2D2C-TAX-ROW1", "JDL-2D2C-TAX-ROW2"), strict=True
    ):
        row[pos["//識別フラグ"]] = flag
        row[pos["日付"]] = DATE
        row[pos["摘要"]] = description

    first, second = rows
    first[pos["借方科目名称"]] = "消耗品費"
    first[pos["借方補助"]] = "0001"
    first[pos["借方補助名称"]] = "テスト消耗品"
    first[pos["借方課区"]] = "仕　入"
    first[pos["借方税区"]] = "10%"
    first[pos["借方金額"]] = "600"
    first[pos["貸方科目名称"]] = "現金"
    first[pos["貸方金額"]] = "300"

    second[pos["借方科目名称"]] = "小口現金"
    second[pos["借方金額"]] = "400"
    second[pos["貸方科目名称"]] = "小口現金"
    second[pos["貸方金額"]] = "700"
    return rows


def _validate_candidate(header: tuple[str, ...], rows: list[list[str]]) -> None:
    pos = {name: index for index, name in enumerate(header)}
    if len(rows) != 2 or any(len(row) != 30 for row in rows):
        raise ValueError("exactly two official 30-column rows are required")
    if [row[pos["//識別フラグ"]] for row in rows] != ["1110", "1101"]:
        raise ValueError("verified 2D2C flag sequence is required")
    if any(row[pos["日付"]] != DATE for row in rows):
        raise ValueError("probe date mismatch")
    debit = sum(int(row[pos["借方金額"]] or "0") for row in rows)
    credit = sum(int(row[pos["貸方金額"]] or "0") for row in rows)
    if debit != credit or debit != 1000:
        raise ValueError("probe must be balanced")
    first, second = rows
    if (
        first[pos["借方課区"]] != "仕　入"
        or first[pos["借方税区"]] != "10%"
        or first[pos["借方税入力方法"]] != ""
        or first[pos["借方補助"]] != "0001"
        or not first[pos["借方補助名称"]]
    ):
        raise ValueError("verified purchase-10 subaccount placement is required")
    tax_fields = ("課区", "税区", "税入力方法", "消費税")
    if any(first[pos[f"貸方{name}"]] for name in tax_fields) or any(
        second[pos[f"{side}{name}"]]
        for side in ("借方", "貸方") for name in tax_fields
    ):
        raise ValueError("all opposite tax fields must remain blank")
    forbidden = (
        "借方取引科目", "貸方取引科目", "借方部門コード", "借方部門名称",
        "貸方部門コード", "貸方部門名称",
    )
    if any(row[pos[name]] for row in rows for name in forbidden):
        raise ValueError("optional fields are outside this probe")
    for row in rows:
        if len(row[pos["摘要"]]) > 32:
            raise ValueError("description exceeds JDL limit")
        row[pos["摘要"]].encode("cp932", errors="strict")


def _semantic_mismatches(
    header: tuple[str, ...], expected: list[list[str]], actual: list[list[str]]
) -> set[str]:
    if len(expected) != len(actual):
        return {"row_count"}
    pos = {name: index for index, name in enumerate(header)}
    compared = (
        "//識別フラグ", "日付", "借方科目名称", "借方補助名称",
        "借方課区", "借方税区", "借方税入力方法", "借方金額",
        "貸方科目名称", "貸方補助名称", "貸方課区", "貸方税区",
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
            if not (left[pos[name]] == right[pos[name]] or (left[pos[name]] == "" and right[pos[name]] == "0")):
                mismatches.add(name)
    expected_debit = sum(int(row[pos["借方金額"]] or "0") for row in expected)
    actual_debit = sum(int(row[pos["借方金額"]] or "0") for row in actual)
    expected_credit = sum(int(row[pos["貸方金額"]] or "0") for row in expected)
    actual_credit = sum(int(row[pos["貸方金額"]] or "0") for row in actual)
    if expected_debit != expected_credit or actual_debit != actual_credit or expected_debit != actual_debit:
        mismatches.add("balance")
    return mismatches


def _write_csv(path: Path, header: tuple[str, ...], rows: list[list[str]]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    path.write_bytes(stream.getvalue().encode("cp932"))


def _read_csv(path: Path, *, require_header_first: bool = False) -> tuple[tuple[str, ...], list[list[str]]]:
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
    data = rows[indexes[0] + 1 :]
    if not data or any(len(row) != 30 for row in data):
        raise ValueError("official 30-column rows are required")
    return header, data


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a development-only 2D2C taxable probe")
    parser.add_argument("--output-dir", type=Path, default=Path("data/private/jdl_2d2c_taxable_probe"))
    parser.add_argument("--reexport", type=Path)
    args = parser.parse_args()
    if args.reexport:
        root = args.output_dir
        print(json.dumps(compare_reexport(root / "compound_2d2c_taxable.csv", root / "compound_2d2c_taxable.manifest.json", args.reexport), ensure_ascii=False, sort_keys=True))
        return 0
    print(json.dumps({key: str(value) for key, value in generate(args.output_dir, Path("data/private")).items()}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
