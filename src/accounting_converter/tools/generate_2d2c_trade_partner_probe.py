from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

from accounting_converter.tools.generate_2d2c_taxable_probe import (
    CASE_ID as BASE_CASE_ID,
    EVIDENCE_ID as BASE_EVIDENCE_ID,
    _read_csv,
    _semantic_mismatches,
)


CASE_ID = "compound_2d2c_taxable_one_sided_trade_partner"
DATE = "20261127"
EXPECTED_DESCRIPTION = "TEST / 取引先:PARTNER-A"


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
        raise ValueError("verified 2D2C taxable base identity mismatch")
    header, rows = _read_csv(base_candidate, require_header_first=True)
    if len(rows) != 2:
        raise ValueError("verified two-row base is required")

    paths = {
        "candidate": output_dir / "compound_2d2c_taxable_trade_partner.csv",
        "manifest": output_dir / "compound_2d2c_taxable_trade_partner.manifest.json",
        "result": output_dir / "compound_2d2c_taxable_trade_partner_result.json",
    }
    if any(path.exists() for path in paths.values()):
        raise FileExistsError("trade-partner probe output already exists")
    output_dir.mkdir(parents=True, exist_ok=True)

    candidate_rows = [list(row) for row in rows]
    pos = {name: index for index, name in enumerate(header)}
    for row in candidate_rows:
        row[pos["日付"]] = DATE
    candidate_rows[0][pos["摘要"]] = EXPECTED_DESCRIPTION
    _validate_only_expected_changes(header, rows, candidate_rows)
    _write(paths["candidate"], header, candidate_rows)
    payload = {
        "schema_version": "1",
        "probe_case": CASE_ID,
        "base_evidence_id": BASE_EVIDENCE_ID,
        "base_candidate_sha256": _hash(base_candidate),
        "candidate_sha256": _hash(paths["candidate"]),
        "expected_date": DATE,
        "expected_description": EXPECTED_DESCRIPTION,
        "trade_partner_row": 1,
        "trade_partner_side": "DEBIT",
        "trade_partner_count": 1,
        "expected_rows": 2,
        "expected_flags": ["1110", "1101"],
        "strict_comparison_required": True,
        "production_allowed": False,
        "NOT_FOR_PRODUCTION": True,
    }
    paths["manifest"].write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths["result"].write_text(
        json.dumps({
            "schema_version": "1", "probe_case": CASE_ID,
            "result_status": "UNTESTED", "comparison_pass": None,
            "mapping_promotion_allowed": False, "production_allowed": False,
            "NOT_FOR_PRODUCTION": True,
        }, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
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
        raise ValueError("trade-partner probe manifest mismatch")
    header, expected = _read_csv(candidate, require_header_first=True)
    actual_header, all_actual = _read_csv(reexport)
    if header != actual_header:
        raise ValueError("official header mismatch")
    pos = {name: index for index, name in enumerate(header)}
    actual = [row for row in all_actual if row[pos["日付"]] == DATE]
    mismatches = _semantic_mismatches(header, expected, actual)
    if len(actual) == 2 and actual[0][pos["摘要"]] != EXPECTED_DESCRIPTION:
        mismatches.add("trade_partner_description")
    passed = len(actual) == 2 and not mismatches
    return {
        "schema_version": "1", "probe_case": CASE_ID,
        "expected_rows": 2, "actual_rows": len(actual),
        "missing_rows": max(2 - len(actual), 0),
        "extra_rows": max(len(actual) - 2, 0),
        "mismatch_field_categories": sorted(mismatches),
        "comparison_pass": passed,
        "evidence_level": "VERIFIED_BY_REAL_IMPORT" if passed else "UNTESTED",
        "candidate_sha256": _hash(candidate), "reexport_sha256": _hash(reexport),
        "mapping_promotion_allowed": False, "production_allowed": False,
        "NOT_FOR_PRODUCTION": True,
    }


def _validate_only_expected_changes(
    header: tuple[str, ...], base: list[list[str]], candidate: list[list[str]]
) -> None:
    pos = {name: index for index, name in enumerate(header)}
    if len(EXPECTED_DESCRIPTION) > 32:
        raise ValueError("description exceeds JDL limit")
    EXPECTED_DESCRIPTION.encode("cp932", errors="strict")
    allowed = {pos["日付"], pos["摘要"]}
    for row_index, (old, new) in enumerate(zip(base, candidate, strict=True)):
        for index, (left, right) in enumerate(zip(old, new, strict=True)):
            if left != right and index not in allowed:
                raise ValueError("base structure changed outside description/date")
        if row_index == 1 and new[pos["摘要"]] != old[pos["摘要"]]:
            raise ValueError("only first-row description may change")
    if candidate[0][pos["摘要"]] != EXPECTED_DESCRIPTION:
        raise ValueError("expected trade-partner description is required")


def _write(path: Path, header: tuple[str, ...], rows: list[list[str]]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    path.write_bytes(stream.getvalue().encode("cp932"))


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a development-only 2D2C taxable trade-partner probe")
    parser.add_argument("--base-dir", type=Path, default=Path("data/private/jdl_2d2c_taxable_probe"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/private/jdl_trade_partner_2d2c_probe"))
    parser.add_argument("--reexport", type=Path)
    args = parser.parse_args()
    if args.reexport:
        print(json.dumps(compare_reexport(args.output_dir / "compound_2d2c_taxable_trade_partner.csv", args.output_dir / "compound_2d2c_taxable_trade_partner.manifest.json", args.reexport), ensure_ascii=False, sort_keys=True))
        return 0
    paths = generate(
        args.base_dir / "compound_2d2c_taxable.csv",
        args.base_dir / "compound_2d2c_taxable.manifest.json",
        args.output_dir,
        Path("data/private"),
    )
    print(json.dumps({key: str(value) for key, value in paths.items()}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
