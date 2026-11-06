"""Judge the gap Probe files (`generate_yayoi_gap_probes`) against the JDL re-export. Counts and verdicts only.

  check     one re-export of the probe day against every Probe file of the round
  simulate  DRY RUN: assume every structural case passed and recompute the technical
            sizing. Never writes Evidence; the result is a forecast, not READY.

check reports, per file and for the whole round:
  - imported / rejected counts the Human read from the JDL import screen (optional --import-counts)
  - re-exported journals and rows against the expected ones
  - per case: PASS (exactly one re-exported journal equals the probe under the existing strict
    comparator, known JDL normalizations only), CHANGED (the case ID is present but a column
    differs: raw differences listed), MISSING (not re-exported: rejected or lost), DUPLICATE
  - missing / extra (re-exported journals no case explains) / duplicate (an ID seen twice)
  - description cases: ACCEPTED_AS_IS / CHANGED (text returned) / MISSING
  - for every PASS: the exact application condition (layout, rows, taxed cells, accounts, relation)

A PASS is NOT registered here: it only becomes Evidence through
`build_scoped_evidence_registry --gap-dir ... --gap-reexport ...` and a reviewed code change.
Without a real re-export nothing is PASS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from accounting_converter.profiles.jdl_official import jdl_ibex_cashbook_official_journal_import_spec
from accounting_converter.tools.generate_mf_final_evidence_batch import _temporary_pair
from accounting_converter.tools.mf_full_e2e_compare import FAILURES, _groups, _rows
from accounting_converter.tools.yayoi_probe_check import _comparator, manifest_path_for

DESCRIPTION = 23
COLUMNS = jdl_ibex_cashbook_official_journal_import_spec().column_names


def _marker(group) -> str:
    return re.sub(r"-R\d+$", "", group[0][DESCRIPTION])


def _raw_differences(expected_group, actual_group) -> list[dict]:
    if len(expected_group) != len(actual_group):
        return [{"row": None, "column": "row_count", "expected": len(expected_group), "actual": len(actual_group)}]
    found = []
    for index, (left, right) in enumerate(zip(expected_group, actual_group, strict=True), start=1):
        for column, (a, b) in enumerate(zip(left, right, strict=True)):
            if a != b and column != 1:  # 伝番 is assigned by JDL
                found.append({"row": index, "column": COLUMNS[column], "expected": a, "actual": b})
    return found


def _manifests(probe_dir: Path) -> list[tuple[Path, dict]]:
    result = []
    for path in sorted(probe_dir.glob("YAYOI_GAP_*_NOT_FOR_PRODUCTION.csv")):
        result.append((path, json.loads(manifest_path_for(path).read_text(encoding="utf-8"))))
    if not result:
        raise SystemExit("no Probe files with manifests in the directory")
    return result


MANUAL_PREFIX = "BM3-"  # optional hand-entered examples (控除不可) on the same day; never Probe cases


def check_round(probe_dir: Path, reexport: Path, import_counts: dict | None = None) -> dict:
    reexport_rows = _rows(reexport)
    reexport_groups = _groups(reexport_rows)
    by_marker: dict[str, list[int]] = {}
    for index, group in enumerate(reexport_groups):
        by_marker.setdefault(_marker(group), []).append(index)
    explained: set[int] = set()
    files, pass_records = {}, []
    totals = Counter()
    for path, manifest in _manifests(probe_dir):
        candidate_rows = _rows(path)
        groups = _groups(candidate_rows)
        comparator = _comparator(candidate_rows)
        verdicts, details = {}, {}
        for case in manifest["cases"]:
            group = groups[case["journal_index"]]
            marker_hits = by_marker.get(_marker(group), [])
            if case["description_under_test"]:
                # Found by the 7-character case tag at the start of the 摘要, so a truncated text is still identified.
                tag = group[0][DESCRIPTION][:7]
                marker_hits = [i for i, g in enumerate(reexport_groups) if g[0][DESCRIPTION][:7] == tag]
                verdict, detail = _description_verdict(group, marker_hits, reexport_groups, comparator)
                if len(marker_hits) > 1:
                    verdict = "DUPLICATE"
                if marker_hits:
                    explained.update(marker_hits)
            else:
                hits = []
                for index, other in enumerate(reexport_groups):
                    if len(other) != len(group):
                        continue
                    try:
                        with _temporary_pair(group, other) as (left, right):
                            report = comparator.compare(left, right)
                    except ValueError:
                        continue  # a re-exported journal the comparator cannot read never matches
                    if report.passed and not any(d.classification in FAILURES for d in report.differences):
                        hits.append((index, dict(Counter(d.classification.value for d in report.differences))))
                explained.update(index for index, _ in hits)
                explained.update(marker_hits)
                if len(hits) == 1 and len(marker_hits) == 1 and hits[0][0] == marker_hits[0]:
                    normalized = {k: n for k, n in hits[0][1].items() if k != "EXACT_PRESERVED"}
                    verdict, detail = "PASS", ({"normalizations": normalized} if normalized else {})
                elif len(marker_hits) > 1 or len(hits) > 1:
                    verdict, detail = "DUPLICATE", {"identifier_seen": len(marker_hits), "equal_journals": len(hits)}
                elif marker_hits:
                    verdict = "CHANGED"
                    detail = {"raw_differences": _raw_differences(group, reexport_groups[marker_hits[0]])}
                else:
                    verdict, detail = "MISSING", {}
            verdicts[case["case"]] = verdict
            details[case["case"]] = detail
            totals[verdict] += 1
            if verdict == "PASS" and not case["description_under_test"]:
                pass_records.append(_pass_record(case, group, manifest))
        expected_cases = len(manifest["cases"])
        files[path.name] = {
            "batch": manifest["batch"], "probe_sha256_matches_manifest":
                hashlib.sha256(path.read_bytes()).hexdigest() == manifest["probe_sha256"],
            "expected_journals": expected_cases, "expected_rows": manifest["expected_physical_rows"],
            "import_counts_reported_by_human": (import_counts or {}).get(manifest["batch"]),
            "verdict_counts": dict(Counter(verdicts.values())),
            "verdicts": verdicts, "details": {k: v for k, v in details.items() if v and (verdicts[k] != "PASS" or v.get("normalizations"))},
        }
    duplicates = sorted(m for m, hits in by_marker.items() if len(hits) > 1 and m)
    manual = {index: _marker(group) for index, group in enumerate(reexport_groups)
              if _marker(group).startswith(MANUAL_PREFIX)}
    manual_literals = {
        _marker(group): [{"flag": row[0], "debit_tax": row[8:11], "debit_tax_amount": row[12],
                          "credit_tax": row[18:21], "credit_tax_amount": row[22]} for row in group]
        for index, group in enumerate(reexport_groups) if index in manual
    }
    unexplained = [index for index in range(len(reexport_groups)) if index not in explained and index not in manual]
    # A file of which nothing came back was not imported (or wholly rejected): reported, it does not
    # invalidate the other files. In every file that did come back, the control must PASS.
    not_imported = sorted(n for n, f in files.items()
                          if all(v == "MISSING" for v in f["verdicts"].values()))
    controls_ok = all(v == "PASS" for n, f in files.items() if n not in not_imported
                      for k, v in f["verdicts"].items() if k.startswith("CTL-"))
    return {
        "reexport_journals": len(reexport_groups), "reexport_rows": len(reexport_rows),
        "expected_journals": sum(f["expected_journals"] for f in files.values()),
        "expected_rows": sum(f["expected_rows"] for f in files.values()),
        "verdict_totals": dict(totals),
        "manual_examples_observed_literals": manual_literals,
        "duplicate_identifiers": duplicates,
        "extra_unexplained_reexport_journals": len(unexplained),
        "files_with_nothing_reexported": not_imported,
        "controls_pass_in_imported_files": controls_ok,
        "round_valid": controls_ok and not duplicates and not unexplained,
        "note": None if (controls_ok and not duplicates and not unexplained) else (
            "round_valid false: the JDL company was not clean or the controls failed; "
            "no case of this round may be registered"),
        "files": files,
        "pass_records": pass_records,
    }


def _strict_equal(comparator, group, other) -> bool:
    try:
        with _temporary_pair(group, other) as (left, right):
            report = comparator.compare(left, right)
    except ValueError:
        return False
    return report.passed and not any(d.classification in FAILURES for d in report.differences)


def _description_verdict(group, marker_hits, reexport_groups, comparator):
    """ACCEPTED_AS_IS: strict comparator equal (known JDL normalizations only).
    TRUNCATED / DESCRIPTION_CHANGED: every other column equal, only the 摘要 differs.
    CHANGED: other columns differ too. MISSING: not re-exported."""
    expected = group[0][DESCRIPTION]
    if not marker_hits:
        return "MISSING", {"expected_chars": len(expected), "expected_cp932_bytes": len(expected.encode("cp932"))}
    other = reexport_groups[marker_hits[0]]
    actual = other[0][DESCRIPTION]
    detail = {"expected_chars": len(expected), "expected_cp932_bytes": len(expected.encode("cp932")),
              "actual_chars": len(actual), "actual_cp932_bytes": len(actual.encode("cp932"))}
    if actual == expected and _strict_equal(comparator, group, other):
        return "ACCEPTED_AS_IS", detail
    patched = [[expected if i == DESCRIPTION else v for i, v in enumerate(row)] for row in other]
    if _strict_equal(comparator, group, patched):
        return ("TRUNCATED" if expected.startswith(actual) else "DESCRIPTION_CHANGED"), detail
    detail["raw_differences"] = _raw_differences(group, other)
    return "CHANGED", detail


def _pass_record(case: dict, group, manifest: dict) -> dict:
    from accounting_converter.tools.build_scoped_evidence_registry import case_record, gap_evidence_id

    evidence_id = gap_evidence_id(case["case"])
    record = case_record(case["case"], evidence_id, group)
    return {
        "case": case["case"], "evidence_id_if_registered": evidence_id,
        "applies_only_to": {
            "scope_id": manifest["scope_id"], "product": manifest["target"],
            "voucher_row_limit": manifest["voucher_row_limit"],
            "sales_tax_rounding": manifest["sales_tax_rounding"], "purchase_tax_rounding": manifest["purchase_tax_rounding"],
            "layout": record["layout"], "rows": [list(r) for r in record["rows"]],
            "taxed_side_cell_account_relation": [list(t) for t in record["taxed"]],
        },
        "not_generalised_to": "other layouts, tax cells, accounts, amount relations, roundings or row limits",
    }


# ---------------------------------------------------------------- simulate
def simulate(probe_dir: Path, source: Path, company_store: Path, company_id: str) -> dict:
    """What the plan would be if every structural / fraction case round-tripped. A forecast only."""
    from decimal import Decimal  # noqa: F401

    from accounting_converter.adapters.output.jdl import scoped_evidence as scoped
    from accounting_converter.application import scoped_evidence_composition as composition
    from accounting_converter.tools import yayoi_gap_probe_plan as gap_plan
    from accounting_converter.tools.build_scoped_evidence_registry import case_record
    from accounting_converter.tools.yayoi_whatif_readiness import technical_sizing

    entries, context = gap_plan.load(source, company_store, company_id, 16)
    before = technical_sizing(entries, context, with_campaign=True)["classes"]
    original = scoped.SCOPED_CASES
    added = []
    for path, manifest in _manifests(probe_dir):
        groups = _groups(_rows(path))
        for case in manifest["cases"]:
            if case["description_under_test"] or case["group"] == "CONTROL":
                continue
            record = case_record(case["case"], case["pending_evidence_id"], groups[case["journal_index"]])
            added.append(scoped.ScopedCase(record["case_id"], record["evidence_id"], record["layout"],
                                           record["rows"], record["taxed"]))
    try:
        scoped.SCOPED_CASES = original + tuple(added)
        (scoped.LAYOUT_CELLS, scoped.LAYOUT_EVIDENCE_IDS, scoped.ROW_PAIRS,
         scoped.CELL_ACCOUNTS, scoped.RELATION_ACCOUNTS) = scoped._build()
        composition.UNITED_CAPABILITIES = composition.united_capabilities()
        missing: list = []
        after = technical_sizing(entries, context, with_campaign=True, evidence_missing=missing)
    finally:
        scoped.SCOPED_CASES = original
        (scoped.LAYOUT_CELLS, scoped.LAYOUT_EVIDENCE_IDS, scoped.ROW_PAIRS,
         scoped.CELL_ACCOUNTS, scoped.RELATION_ACCOUNTS) = scoped._build()
        composition.UNITED_CAPABILITIES = composition.united_capabilities()
    return {
        "SIMULATION_NOT_EVIDENCE": True,
        "assumed_pass_cases": len(added),
        "technical_classes_now": before,
        "technical_classes_if_all_pass": after["classes"],
        "remaining_evidence_missing_reasons": after["evidence_missing_reasons"],
        "remaining_missing_layouts": after["evidence_missing_layouts_top"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check")
    c.add_argument("--probe-dir", type=Path, required=True)
    c.add_argument("--reexport", type=Path, required=True)
    c.add_argument("--import-counts", type=Path, help='JSON {"G1a": {"imported": 22, "rejected": 0}, ...}')
    c.add_argument("--out", type=Path, help="write the full report here (under data/private)")
    s = sub.add_parser("simulate")
    s.add_argument("--probe-dir", type=Path, required=True)
    s.add_argument("--source", type=Path, required=True)
    s.add_argument("--company-store", type=Path, required=True)
    s.add_argument("--company-id", required=True)
    args = parser.parse_args()
    if args.command == "check":
        counts = json.loads(args.import_counts.read_text(encoding="utf-8")) if args.import_counts else None
        report = check_round(args.probe_dir, args.reexport, counts)
        if args.out:
            if "data/private" not in args.out.resolve().as_posix():
                raise SystemExit("write the report under data/private only")
            args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        summary = {k: v for k, v in report.items() if k not in {"files", "pass_records"}}
        summary["files"] = {n: {"verdict_counts": f["verdict_counts"], "import": f["import_counts_reported_by_human"]}
                            for n, f in report["files"].items()}
        print(json.dumps(summary, ensure_ascii=False, indent=1))
    else:
        print(json.dumps(simulate(args.probe_dir, args.source, args.company_store, args.company_id),
                         ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
