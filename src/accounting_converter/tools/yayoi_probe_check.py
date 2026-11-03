"""Per-case judgment of a Yayoi → JDL NOT_FOR_PRODUCTION probe.

The probe CSV holds several cases (one journal each). Its manifest
(<probe>.manifest.json, written by yayoi_formal_output --probe) says which
journal is which case. After the Human imports the probe into the test
company and re-exports the same period, each case is judged on its own: the
case passes only when exactly one re-exported journal matches it under the
existing strict comparator (known JDL canonical normalizations only).

Prints counts and verdicts only. A PASS here is what allows registering the
case's Evidence (a separate, explicit code change); nothing is registered here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from accounting_converter.application.moneyforward_roundtrip import MoneyForwardJdlRoundTripComparator
from accounting_converter.tools.generate_mf_final_evidence_batch import _temporary_pair
from accounting_converter.tools.mf_full_e2e_compare import FAILURES, _groups, _rows


def manifest_path_for(probe: Path) -> Path:
    return probe.with_name(probe.name + ".manifest.json")


def _comparator(candidate_rows) -> MoneyForwardJdlRoundTripComparator:
    normalizations = frozenset(
        (side, row[account], row[code].zfill(4), row[name])
        for row in candidate_rows
        for side, account, code, name in (("DEBIT", 3, 6, 7), ("CREDIT", 13, 16, 17))
        if row[code]
    )
    return MoneyForwardJdlRoundTripComparator(numeric_subaccount_normalizations=normalizations)


def check(probe: Path, reexport: Path, manifest: dict) -> dict:
    candidate_rows, reexport_rows = _rows(probe), _rows(reexport)
    candidate_groups, reexport_groups = _groups(candidate_rows), _groups(reexport_rows)
    comparator = _comparator(candidate_rows)
    used: set[int] = set()
    cases = {}
    for case in manifest["cases"]:
        group = candidate_groups[case["journal_index"]]
        matches = []
        for index, other in enumerate(reexport_groups):
            if len(other) != len(group):
                continue
            with _temporary_pair(group, other) as (left, right):
                report = comparator.compare(left, right)
            if report.passed and not any(d.classification in FAILURES for d in report.differences):
                matches.append(index)
        cases[case["case"]] = {
            "pending_evidence_id": case["pending_evidence_id"],
            "candidate_rows": len(group),
            "matching_reexport_journals": len(matches),
            "verdict": "PASS" if len(matches) == 1 and len(group) == case["physical_rows"] else "FAIL",
        }
        used.update(matches)
    return {
        "journals": [len(candidate_groups), len(reexport_groups)],
        "physical_rows": [len(candidate_rows), len(reexport_rows)],
        "unmatched_reexport_journals": len(set(range(len(reexport_groups))) - used),
        "cases": cases,
        "note": "re-export holds only this period of the test company; extra journals mean the company was not clean",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--reexport", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(manifest_path_for(args.probe).read_text(encoding="utf-8"))
    print(json.dumps(check(args.probe, args.reexport, manifest), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
