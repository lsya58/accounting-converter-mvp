from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

from accounting_converter.profiles.jdl_official import jdl_ibex_cashbook_official_journal_import_spec
from accounting_converter.tools.generate_mf_exact_shape_probe import _atomic_write_pair
from accounting_converter.tools.mf_tax_context_probe import _journal_rows


CASES = (
    ("20260521", "8571", "", "非仕入", "3181", "0001", "MF-TAX-NONPUR-PENDING"),
    ("20260522", "1311", "0002", "", "9111", "", "MF-TAX-NONSALE-PENDING"),
)


def generate_clean_non_taxable_probe(source: Path, output_dir: Path) -> tuple[Path, Path]:
    if output_dir.exists():
        raise FileExistsError("clean probe output already exists")
    header = tuple(jdl_ibex_cashbook_official_journal_import_spec().column_names)
    positions = {name: index for index, name in enumerate(header)}
    source_rows = _journal_rows(source)
    if len(source_rows) != 3:
        raise ValueError("expected the exact original three-case candidate")
    selected = []
    for date, debit_code, debit_sub, debit_tax, credit_code, credit_sub, marker in CASES:
        matches = [row for row in source_rows if row[positions["摘要"]] == marker]
        if len(matches) != 1:
            raise ValueError("pending case marker is missing or duplicated")
        row = matches[0]
        expected = {
            "//識別フラグ": "1111",
            "日付": date,
            "借方科目": debit_code,
            "借方補助": debit_sub,
            "借方課区": debit_tax,
            "貸方科目": credit_code,
            "貸方補助": credit_sub,
            "貸方課区": "非売上" if marker == "MF-TAX-NONSALE-PENDING" else "",
            "借方金額": "1100",
            "貸方金額": "1100",
        }
        if any(row[positions[name]] != value for name, value in expected.items()):
            raise ValueError("original candidate differs from the Human-observed case")
        if row[positions["借方税区"]] or row[positions["貸方税区"]]:
            raise ValueError("non-taxable probe requires blank tax rates")
        selected.append(row)
    if any(row[positions["摘要"]] == "MF-TAX-SALES10-PENDING" for row in selected):
        raise ValueError("failed sales-10 case must not be included")
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(["// MF NON-TAXABLE PROBE / NOT FOR PRODUCTION", *([""] * 29)])
    writer.writerow(["// 出力期間 ： 20260521 ～ 20260522", *([""] * 29)])
    writer.writerow([""] * 30)
    writer.writerow(header)
    writer.writerows(selected)
    raw = stream.getvalue().encode("cp932", errors="strict")
    output = output_dir / "mf_tax_nonpur_nonsale_pending.csv"
    manifest_path = output_dir / "mf_tax_nonpur_nonsale_pending.manifest.private.json"
    manifest = {
        "NOT_FOR_PRODUCTION": True,
        "production_allowed": False,
        "evidence_status": "PENDING_REAL_JDL_IMPORT_REEXPORT",
        "source_candidate_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "candidate_sha256": hashlib.sha256(raw).hexdigest(),
        "journal_count": 2,
        "physical_row_count": 2,
        "import_period": {"start": "20260521", "end": "20260522"},
        "cases": ["CASE-TAX-NONPUR", "CASE-TAX-NONSALE"],
        "comparison_policy": "Use existing compare_probe_patterns case-by-case; promote only after real re-export strict PASS.",
    }
    _atomic_write_pair(
        (output, raw),
        (manifest_path, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")),
    )
    return output, manifest_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    print(generate_clean_non_taxable_probe(args.source, args.output_dir))


if __name__ == "__main__":
    main()
