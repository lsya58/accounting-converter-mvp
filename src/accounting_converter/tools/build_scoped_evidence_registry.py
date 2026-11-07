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
import re
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
            if case["description_under_test"] or case["group"] in {"CONTROL", "SUBACCOUNT"}:
                continue
            if result["verdicts"][case["case"]] == "PASS":
                passed += 1
                cases.append(case_record(case["case"], gap_evidence_id(case["case"]), groups[case["journal_index"]]))
        summary[name[:28]] = f"{passed}/{sum(1 for c in manifest['cases'] if not c['description_under_test'] and c['group'] not in {'CONTROL', 'SUBACCOUNT'})}"
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


_SETTING_TOKEN = re.compile(r"(?:仕|入|売|上|内税|外税|別記|軽減\d+%|\d+%|非仕入|非売上|輸出売|対外)$")


def tax_setting_keys(master_pdf: Path) -> dict[str, str]:
    """Code -> printed JDL tax defaults (課区・税区・入力 tokens) of every enabled coded account."""
    from accounting_converter.application.jdl_account_list_pdf import JdlAccountListPdfTextParser as P
    from accounting_converter.infrastructure.jdl_account_pdf_draft import PypdfTextExtractor

    keys: dict[str, str] = {}
    for text in PypdfTextExtractor().extract_pages(master_pdf):
        for line in text.splitlines():
            found = P._PARENT_ROW.match(line) or P._CODED_ROW.match(line)
            if not found or found["use"] != "○":
                continue
            tokens = []
            for token in found["tail"].split():
                if not _SETTING_TOKEN.match(token):
                    break
                tokens.append(token)
            keys[found["code"]] = "".join(tokens)
    return keys


def setting_peers(cases: list[dict], keys: dict[str, str]) -> dict[tuple[str, str, str], frozenset]:
    """Per (side, cell, relation): the accounts printing the same non-empty JDL tax defaults as at least
    three accounts the relation round-tripped on. Observed accounts are grouped by their defaults, so a
    round trip on an account with other defaults never withdraws or widens another group."""
    from accounting_converter.adapters.output.jdl.scoped_evidence import (
        RELATION_ACCOUNT_INDEPENDENCE_MIN_ACCOUNTS,
        RELATION_ACCOUNT_SPECIFIC_ONLY,
    )

    observed: dict[tuple, set] = {}
    for case in cases:
        for side, cell, account, relation in case["taxed"]:
            if relation not in {"", "NONE"}:
                observed.setdefault((side, cell, relation), set()).add(account)
    peers = {}
    for (side, cell, relation), accounts in sorted(observed.items()):
        if (side, cell) in RELATION_ACCOUNT_SPECIFIC_ONLY:
            continue
        by_default: dict[str, set] = {}
        for account in accounts:
            if keys.get(account):
                by_default.setdefault(keys[account], set()).add(account)
        covered = frozenset(code for default, group in by_default.items()
                            if len(group) >= RELATION_ACCOUNT_INDEPENDENCE_MIN_ACCOUNTS
                            for code, value in keys.items() if value == default)
        if covered:
            peers[(side, cell, relation)] = covered
    return peers


def render(cases: list[dict], peers: dict | None = None, master_sha256: str | None = None) -> str:
    lines = ["SCOPED_CASES: tuple[ScopedCase, ...] = ("]
    for case in cases:
        lines.append(
            f"    ScopedCase({case['case_id']!r}, {case['evidence_id']!r}, {case['layout']!r},\n"
            f"        {case['rows']!r},\n"
            f"        {case['taxed']!r}),"
        )
    lines.append(")")
    lines.append("")
    lines.append("# Per (side, cell, relation): accounts printing the same JDL tax defaults as >= 3 accounts it round-tripped on")
    lines.append("# (used by scoped_evidence.relation_covers_account). Generated from the JDL 科目一覧 PDF"
                 + (f" sha256 {master_sha256}." if master_sha256 else "; none given, so no relation is account-independent."))
    lines.append("JDL_TAX_SETTING_PEERS: dict[tuple[str, str, str], frozenset[str]] = {")
    for key, codes in sorted((peers or {}).items()):
        lines.append(f"    {key!r}: frozenset({sorted(codes)!r}),")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--pending-dir", type=Path, required=True)
    parser.add_argument("--gap-dir", type=Path, action="append", default=[],
                        help="gap Probe directory; repeat in round order (2026-11-06 round 3, then the new-account round)")
    parser.add_argument("--gap-reexport", type=Path, action="append", default=[],
                        help="real JDL re-export of that directory's Probe day (same order as --gap-dir)")
    parser.add_argument("--master-pdf", type=Path, help="the company's current JDL 科目一覧 PDF (tax defaults per account)")
    parser.add_argument("--summary", action="store_true", help="print the per-file PASS counts instead of the table")
    args = parser.parse_args()
    cases, summary = collect(args.campaign_dir, args.pending_dir)
    if len(args.gap_dir) != len(args.gap_reexport):
        raise SystemExit("--gap-dir and --gap-reexport go together, one re-export per directory")
    for gap_dir, gap_reexport in zip(args.gap_dir, args.gap_reexport):
        gap_cases, gap_summary = collect_gap_round(gap_dir, gap_reexport)
        cases += gap_cases
        summary["cases_passed"].update(gap_summary)
    ids = [case["evidence_id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise SystemExit("duplicate Evidence ids across rounds; nothing printed")
    peers, master_sha = {}, None
    if args.master_pdf:
        peers = setting_peers(cases, tax_setting_keys(args.master_pdf))
        master_sha = hashlib.sha256(args.master_pdf.read_bytes()).hexdigest()
        summary["setting_peers"] = {"/".join(k): len(v) for k, v in peers.items()}
    print(json.dumps(summary, ensure_ascii=False, indent=1) if args.summary else render(cases, peers, master_sha), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
