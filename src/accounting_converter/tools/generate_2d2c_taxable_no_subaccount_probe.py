from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

from accounting_converter.tools.generate_2d2c_taxable_probe import (
    _read_csv,
    _semantic_mismatches,
)
from accounting_converter.tools.generate_2d2c_trade_partner_no_subaccount_probe import (
    CASE_ID as BASE_CASE_ID,
    TARGET_ACCOUNT_CODE,
    TARGET_ACCOUNT_NAME,
    TARGET_CSV_NAME,
)


CASE_ID = "compound_2d2c_taxable_no_subaccount"
DATE = "20261129"
EXPECTED_DESCRIPTION = "TEST"
PENDING_EVIDENCE_ID = (
    "EVID-JDL-COMPOUND-2D2C-PURCHASE-10-TAXABLE-"
    "NO-SUBACCOUNT-ROUNDTRIP-001"
)
BASE_EVIDENCE_ID = (
    "EVID-MF-JDL-TRADE-PARTNER-2D2C-TAXABLE-NO-SUBACCOUNT-"
    "DESCRIPTION-ROUNDTRIP-001"
)


def generate(
    base_candidate: Path,
    base_manifest: Path,
    output_dir: Path,
    private_root: Path,
) -> dict[str, Path]:
    output_dir = output_dir.resolve()
    private_root = private_root.resolve()
    if output_dir != private_root and private_root not in output_dir.parents:
        raise ValueError("probe output must stay under data/private")

    manifest = json.loads(base_manifest.read_text(encoding="utf-8"))
    if (
        manifest.get("probe_case") != BASE_CASE_ID
        or manifest.get("candidate_sha256") != _hash(base_candidate)
        or manifest.get("NOT_FOR_PRODUCTION") is not True
    ):
        raise ValueError("verified no-subaccount trade-partner base identity mismatch")
    header, base_rows = _read_csv(base_candidate, require_header_first=True)
    if len(base_rows) != 2:
        raise ValueError("verified two-row base is required")

    paths = {
        "candidate": output_dir / "compound_2d2c_taxable_no_subaccount.csv",
        "manifest": output_dir / "compound_2d2c_taxable_no_subaccount.manifest.json",
        "result": output_dir / "compound_2d2c_taxable_no_subaccount_result.json",
    }
    if any(path.exists() for path in paths.values()):
        raise FileExistsError("2D2C taxable no-subaccount probe output already exists")
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = [list(row) for row in base_rows]
    pos = {name: index for index, name in enumerate(header)}
    for row in rows:
        row[pos["日付"]] = DATE
    rows[0][pos["摘要"]] = EXPECTED_DESCRIPTION
    _validate_only_reduction(header, base_rows, rows)
    _write(paths["candidate"], header, rows)

    paths["manifest"].write_text(
        json.dumps(
            {
                "schema_version": "1",
                "probe_case": CASE_ID,
                "base_evidence_id": BASE_EVIDENCE_ID,
                "pending_evidence_id": PENDING_EVIDENCE_ID,
                "base_candidate_sha256": _hash(base_candidate),
                "candidate_sha256": _hash(paths["candidate"]),
                "expected_date": DATE,
                "expected_rows": 2,
                "expected_flags": ["1110", "1101"],
                "expected_description": EXPECTED_DESCRIPTION,
                "removed_feature": "TRADE_PARTNER_DESCRIPTION_TRANSFORMATION",
                "target_account": {
                    "observed_master_code": TARGET_ACCOUNT_CODE,
                    "observed_master_name": TARGET_ACCOUNT_NAME,
                    "csv_name": TARGET_CSV_NAME,
                    "observed_subaccount_count": 0,
                },
                "strict_comparison_required": True,
                "component_preflight": "PASS",
                "formal_preflight": "BLOCKED_PENDING_REAL_IMPORT_EVIDENCE",
                "production_allowed": False,
                "NOT_FOR_PRODUCTION": True,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    paths["result"].write_text(
        json.dumps(
            {
                "schema_version": "1",
                "probe_case": CASE_ID,
                "result_status": "UNTESTED",
                "comparison_pass": None,
                "evidence_id": PENDING_EVIDENCE_ID,
                "mapping_promotion_allowed": False,
                "production_allowed": False,
                "NOT_FOR_PRODUCTION": True,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return paths


def compare_reexport(
    candidate: Path, manifest_path: Path, reexport: Path
) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("probe_case") != CASE_ID
        or manifest.get("candidate_sha256") != _hash(candidate)
        or manifest.get("NOT_FOR_PRODUCTION") is not True
    ):
        raise ValueError("2D2C taxable no-subaccount probe manifest mismatch")
    header, expected = _read_csv(candidate, require_header_first=True)
    actual_header, all_actual = _read_csv(reexport)
    if header != actual_header:
        raise ValueError("official header mismatch")
    pos = {name: index for index, name in enumerate(header)}
    actual = [row for row in all_actual if row[pos["日付"]] == DATE]
    mismatches = _semantic_mismatches(header, expected, actual)
    if len(actual) == 2:
        if actual[0][pos["借方補助"]] or actual[0][pos["借方補助名称"]]:
            mismatches.add("tax_side_subaccount_blank")
        if actual[0][pos["摘要"]] != EXPECTED_DESCRIPTION:
            mismatches.add("first_row_description")
        if "取引先:" in actual[0][pos["摘要"]]:
            mismatches.add("trade_partner_absent")
    passed = len(actual) == 2 and not mismatches
    return {
        "schema_version": "1",
        "probe_case": CASE_ID,
        "expected_rows": 2,
        "actual_rows": len(actual),
        "missing_rows": max(2 - len(actual), 0),
        "extra_rows": max(len(actual) - 2, 0),
        "mismatch_field_categories": sorted(mismatches),
        "comparison_pass": passed,
        "evidence_id": PENDING_EVIDENCE_ID,
        "evidence_level": "VERIFIED_BY_REAL_IMPORT" if passed else "UNTESTED",
        "candidate_sha256": _hash(candidate),
        "reexport_sha256": _hash(reexport),
        "mapping_promotion_allowed": False,
        "production_allowed": False,
        "NOT_FOR_PRODUCTION": True,
    }


def _validate_only_reduction(
    header: tuple[str, ...], base: list[list[str]], candidate: list[list[str]]
) -> None:
    pos = {name: index for index, name in enumerate(header)}
    allowed = ({pos["日付"], pos["摘要"]}, {pos["日付"]})
    for row_index, (old, new) in enumerate(zip(base, candidate, strict=True)):
        for index, (left, right) in enumerate(zip(old, new, strict=True)):
            if left != right and index not in allowed[row_index]:
                raise ValueError("verified base changed outside trade-partner removal")

    first, second = candidate
    if [first[pos["//識別フラグ"]], second[pos["//識別フラグ"]]] != ["1110", "1101"]:
        raise ValueError("verified flag sequence is required")
    if first[pos["借方科目名称"]] != TARGET_CSV_NAME:
        raise ValueError("verified no-subaccount target account is required")
    if first[pos["借方補助"]] or first[pos["借方補助名称"]]:
        raise ValueError("tax-side subaccount must remain blank")
    if first[pos["借方課区"]] != "仕　入" or first[pos["借方税区"]] != "10%":
        raise ValueError("verified purchase-10 tax placement is required")
    if first[pos["摘要"]] != EXPECTED_DESCRIPTION or "取引先:" in first[pos["摘要"]]:
        raise ValueError("trade-partner transformation must be absent")
    debit = sum(int(row[pos["借方金額"]] or "0") for row in candidate)
    credit = sum(int(row[pos["貸方金額"]] or "0") for row in candidate)
    if debit != credit or debit != 1000:
        raise ValueError("verified balanced amount structure is required")


def _write(path: Path, header: tuple[str, ...], rows: list[list[str]]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    path.write_bytes(stream.getvalue().encode("cp932"))


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a development-only 2D2C taxable no-subaccount probe"
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path("data/private/jdl_trade_partner_2d2c_no_subaccount_probe"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/private/jdl_2d2c_taxable_no_subaccount_probe"),
    )
    parser.add_argument("--reexport", type=Path)
    args = parser.parse_args()
    candidate = args.output_dir / "compound_2d2c_taxable_no_subaccount.csv"
    manifest = args.output_dir / "compound_2d2c_taxable_no_subaccount.manifest.json"
    if args.reexport:
        print(
            json.dumps(
                compare_reexport(candidate, manifest, args.reexport),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    paths = generate(
        args.base_dir / "compound_2d2c_taxable_trade_partner_no_subaccount.csv",
        args.base_dir
        / "compound_2d2c_taxable_trade_partner_no_subaccount.manifest.json",
        args.output_dir,
        Path("data/private"),
    )
    print(
        json.dumps(
            {key: str(value) for key, value in paths.items()},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
