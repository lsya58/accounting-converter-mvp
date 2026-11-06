"""Emit the data table of `scoped_evidence_registry.py` from the real JDL probes.

Reads the private probe files and the real JDL re-exports, judges every case
again with the existing strict comparator (nothing is read from notes), and
prints a Python table of structure only: physical-row layout, which side of
which row carried which JDL tax cell, the target account codes, and how the
explicit tax amount related to the amount. No customer value, description,
date or file name is printed.

  PYTHONPATH=src python3 -m accounting_converter.tools.build_scoped_evidence_registry \\
      --campaign-dir data/private/yayoi_buddies/evidence_campaign_20261105 \\
      --pending-dir data/private/yayoi_buddies/evidence_pending_20261104
"""
from __future__ import annotations

import argparse
import hashlib
import json
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal
from pathlib import Path

from accounting_converter.adapters.output.jdl.tax_semantics import JdlTaxSemantic, semantic_for_target
from accounting_converter.tools.mf_full_e2e_compare import _groups, _rows
from accounting_converter.tools.yayoi_campaign_session import check_session
from accounting_converter.tools.yayoi_probe_check import check, manifest_path_for

CELL = {
    JdlTaxSemantic.NO_TAX: "NO",
    JdlTaxSemantic.SALES_10_EXTERNAL: "S10",
    JdlTaxSemantic.PURCHASE_10_INTERNAL: "P10",
    JdlTaxSemantic.NON_TAXABLE_PURCHASE: "NP",
    JdlTaxSemantic.NON_TAXABLE_SALES: "NS",
    JdlTaxSemantic.EXPORT_SALES: "XS",
    JdlTaxSemantic.PURCHASE_REDUCED_8_INTERNAL: "R8",
    JdlTaxSemantic.PURCHASE_10_TRANSITIONAL_80_INTERNAL: "T80",
}
EXISTING_IDS = {
    "BUD-SALES-3D3C": "EVID-YAYOI-JDL-35-5-BUDDIES-3D3C-SALES10-SYNTHETIC-ROUNDTRIP-001",
    "BUD-SALES-4D4C": "EVID-YAYOI-JDL-35-5-BUDDIES-4D4C-SALES10-SYNTHETIC-ROUNDTRIP-001",
}
# Rounding of the company the probes ran on (売上 切上げ / 仕入 四捨五入).
COMPANY = {"S10": ROUND_UP, "P10": ROUND_HALF_UP}


def _cell(row, scope_i, category_i):
    semantic = semantic_for_target(row[category_i], row[scope_i])
    if semantic is None:
        raise ValueError("a probe row carries a tax literal that has no registered semantic")
    return CELL[semantic]


def _relation(cell: str, amount: Decimal, tax: str) -> str:
    if cell in {"S10", "P10"}:
        written = Decimal(tax)
        raw = amount * 10 / 110
        floor, up, half = (raw.quantize(Decimal(1), rounding=mode) for mode in (ROUND_DOWN, ROUND_UP, ROUND_HALF_UP))
        if floor == up == half == written:
            return ""  # no fraction: every rounding agrees
        company = raw.quantize(Decimal(1), rounding=COMPANY[cell])
        if written == floor == company:
            return ""
        if written == company:
            return "COMPANY"
        if written == floor:
            return "FLOOR"
        raise ValueError("unclassified explicit tax in a PASS case")
    if cell in {"R8", "T80"}:
        from accounting_converter.adapters.output.jdl.scoped_evidence import relation_of

        relation = relation_of(cell, amount, Decimal(tax))
        if relation is None:
            raise ValueError("reduced 8% / 80% transitional tax is not a relation to the exact amount that is modelled")
        return relation
    if tax not in {"", "0"}:
        raise ValueError("tax amount on a cell that carries none")
    return "NONE"


def case_record(case_id: str, evidence_id: str, group: list[list[str]]) -> dict:
    rows, taxed = [], []
    layout_kinds = []
    for row in group:
        debit_present, credit_present = bool(row[3]), bool(row[13])
        debit = _cell(row, 8, 9) if debit_present else "-"
        credit = _cell(row, 18, 19) if credit_present else "-"
        rows.append((debit, credit))
        layout_kinds.append("B" if debit_present and credit_present else "D" if debit_present else "C")
        for side, present, cell, account, amount, tax in (
            ("DEBIT", debit_present, debit, row[3], row[11], row[12]),
            ("CREDIT", credit_present, credit, row[13], row[21], row[22]),
        ):
            if present and cell != "NO":
                taxed.append((side, cell, account, _relation(cell, Decimal(amount), tax)))
    layout = []
    for kind in layout_kinds:
        if layout and layout[-1][0] == kind:
            layout[-1][1] += 1
        else:
            layout.append([kind, 1])
    return {
        "case_id": case_id, "evidence_id": evidence_id,
        "layout": "".join(f"{kind}{count}" for kind, count in layout),
        "rows": tuple(rows), "taxed": tuple(taxed),
    }


def gap_evidence_id(case: str) -> str:
    return f"EVID-YAYOI-JDL-35-5-BUDDIES-GAP-{case}-SYNTHETIC-ROUNDTRIP-001"


def collect_gap_round(gap_dir: Path, reexport: Path) -> tuple[list[dict], dict]:
    """Structural / explicit-tax PASS cases of the gap round (2026-11-06 Probes), re-judged here.

    Nothing is taken unless the round is valid (no duplicate, no unexplained journal,
    every control of an imported file PASS). Description and control cases are not
    layout Evidence and are never added to this table."""
    from accounting_converter.tools.yayoi_gap_probe_check import check_round

    report = check_round(gap_dir, reexport)
    if not report["round_valid"]:
        raise ValueError("the gap round is not valid (duplicate, unexplained journal or failed control); nothing registered")
    cases, summary = [], {}
    for name, result in report["files"].items():
        manifest = json.loads(manifest_path_for(gap_dir / name).read_text(encoding="utf-8"))
        groups = _groups(_rows(gap_dir / name))
        passed = 0
        for case in manifest["cases"]:
            if case["description_under_test"] or case["group"] == "CONTROL":
                continue
            if result["verdicts"][case["case"]] == "PASS":
                passed += 1
                cases.append(case_record(case["case"], gap_evidence_id(case["case"]), groups[case["journal_index"]]))
        summary[name[:28]] = f"{passed}/{sum(1 for c in manifest['cases'] if not c['description_under_test'] and c['group'] != 'CONTROL')}"
    return cases, summary


def collect(campaign_dir: Path, pending_dir: Path) -> tuple[list[dict], dict]:
    cases, summary, sources = [], {}, {}

    def add(path: Path, verdicts: dict, manifest: dict, ids) -> None:
        groups = _groups(_rows(path))
        passed = failed = 0
        for case in manifest["cases"]:
            if verdicts[case["case"]] != "PASS":
                failed += 1
                continue
            passed += 1
            cases.append(case_record(case["case"], ids(case["case"]), groups[case["journal_index"]]))
        summary[path.name[:28]] = f"{passed}/{passed + failed}"
        sources[path.name[:28]] = hashlib.sha256(path.read_bytes()).hexdigest()

    # 2026-11-04: 3D3C / 4D4C (existing, not re-probed)
    probe = pending_dir / "BUDDIES_3D3C_4D4C_SALES10_NOT_FOR_PRODUCTION.csv"
    manifest = json.loads(manifest_path_for(probe).read_text(encoding="utf-8"))
    result = check(probe, pending_dir / "BUDDIES_probe_reexport_20260615_16.csv", manifest)
    add(probe, {k: v["verdict"] for k, v in result["cases"].items()}, manifest, EXISTING_IDS.__getitem__)

    def campaign_id(case: str) -> str:
        return f"EVID-YAYOI-JDL-35-5-BUDDIES-CAMP-{case}-SYNTHETIC-ROUNDTRIP-001"

    session1 = [campaign_dir / f"YAYOI_EVIDENCE_CAMPAIGN_{name}_NOT_FOR_PRODUCTION.csv" for name in (
        "A1_20260628", "A2_20260628", "A3_20260628_ROWS16", "A4_20260628_OVER16")]
    session1 = [Path(str(p)) for p in session1]
    result1 = check_session(campaign_dir / "A1~A3までの再エクスポート.csv", session1, "BM-", [])
    for probe in session1:
        manifest = json.loads(manifest_path_for(probe).read_text(encoding="utf-8"))
        add(probe, result1["batches"][manifest["batch"]]["verdicts"], manifest, campaign_id)
    probe_b = campaign_dir / "YAYOI_EVIDENCE_CAMPAIGN_B_20260627_NOT_FOR_PRODUCTION.csv"
    result2 = check_session(
        campaign_dir / "YAYOI_EVIDENCE_CAMPAIGN_B_20260627_NOT_FOR_PRODUCTION再エクスポート.csv", [probe_b], "BM2-", [])
    manifest = json.loads(manifest_path_for(probe_b).read_text(encoding="utf-8"))
    add(probe_b, result2["batches"]["B"]["verdicts"], manifest, campaign_id)
    return cases, {"cases_passed": summary, "source_sha256": sources}


def render(cases: list[dict]) -> str:
    lines = ["SCOPED_CASES: tuple[ScopedCase, ...] = ("]
    for case in cases:
        lines.append(
            f"    ScopedCase({case['case_id']!r}, {case['evidence_id']!r}, {case['layout']!r},\n"
            f"        {case['rows']!r},\n"
            f"        {case['taxed']!r}),"
        )
    lines.append(")")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--pending-dir", type=Path, required=True)
    parser.add_argument("--gap-dir", type=Path, help="2026-11-06 gap Probe directory (round 3)")
    parser.add_argument("--gap-reexport", type=Path, help="real JDL re-export of the gap Probe day")
    parser.add_argument("--summary", action="store_true", help="print the per-file PASS counts instead of the table")
    args = parser.parse_args()
    cases, summary = collect(args.campaign_dir, args.pending_dir)
    if args.gap_dir or args.gap_reexport:
        if not (args.gap_dir and args.gap_reexport):
            raise SystemExit("--gap-dir and --gap-reexport go together")
        gap_cases, gap_summary = collect_gap_round(args.gap_dir, args.gap_reexport)
        cases += gap_cases
        summary["cases_passed"].update(gap_summary)
    print(json.dumps(summary, ensure_ascii=False, indent=1) if args.summary else render(cases), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
