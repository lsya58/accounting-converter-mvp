"""Strict comparison of a formal JDL CSV with the real JDL re-export of the same period.

1. Positional strict comparison of the whole file (the acceptance criterion).
2. If it fails, a per-date content match separates "only the order of journals
   within a day changed" from real content differences, so the cause is clear.

Only existing canonical normalizations are allowed; numeric subaccount zero
suppression is allowed only for (side, account, code, name) present in the
candidate with the name unchanged.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
from collections import defaultdict
from pathlib import Path

from accounting_converter.application.moneyforward_roundtrip import (
    MoneyForwardJdlRoundTripComparator,
    MoneyForwardRoundTripClassification,
)
from accounting_converter.tools.generate_mf_final_evidence_batch import _temporary_pair

FAILURES = {
    MoneyForwardRoundTripClassification.UNEXPECTED_CHANGE,
    MoneyForwardRoundTripClassification.MISSING_ROW,
    MoneyForwardRoundTripClassification.EXTRA_ROW,
}


def _rows(path: Path) -> list[list[str]]:
    text = path.read_bytes().decode("cp932", errors="strict")
    return [
        row for row in csv.reader(io.StringIO(text, newline=""))
        if len(row) == 30 and row[0][:1].isdigit()
    ]


def _groups(rows: list[list[str]]) -> list[list[list[str]]]:
    groups, current = [], []
    for row in rows:
        current.append(row)
        if row[0] in {"1111", "1101", "1000"}:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def compare(candidate: Path, reexport: Path) -> dict[str, object]:
    candidate_rows = _rows(candidate)
    normalizations = frozenset(
        (side, row[account], row[code].zfill(4), row[name])
        for row in candidate_rows
        for side, account, code, name in (("DEBIT", 3, 6, 7), ("CREDIT", 13, 16, 17))
        if row[code]
    )
    comparator = MoneyForwardJdlRoundTripComparator(numeric_subaccount_normalizations=normalizations)
    report = comparator.compare(candidate, reexport)
    failures = [item for item in report.differences if item.classification in FAILURES]
    result: dict[str, object] = {
        "strict_passed": report.passed,
        "journals": [report.candidate_journal_count, report.reexport_journal_count],
        "physical_rows": [report.candidate_row_count, report.reexport_row_count],
        "classification_counts": report.classification_counts,
        "first_failures": [
            {"row": item.row_index, "field": item.field, "classification": item.classification.value}
            for item in failures[:20]
        ],
    }
    if report.passed:
        return result
    by_date_candidate, by_date_reexport = defaultdict(list), defaultdict(list)
    for group in _groups(candidate_rows):
        by_date_candidate[group[0][2]].append(group)
    for group in _groups(_rows(reexport)):
        by_date_reexport[group[0][2]].append(group)
    unmatched, order_only_dates = [], []
    for day in sorted(set(by_date_candidate) | set(by_date_reexport)):
        remaining = list(by_date_reexport.get(day, []))
        positional = True
        for index, group in enumerate(by_date_candidate.get(day, [])):
            match = None
            for position, other in enumerate(remaining):
                with _temporary_pair(group, other) as (left, right):
                    if comparator.compare(left, right).passed:
                        match = position
                        break
            if match is None:
                unmatched.append({"date": day, "candidate_group_index": index, "rows": len(group)})
                continue
            positional = positional and match == 0
            remaining.pop(match)
        for index, group in enumerate(remaining):
            unmatched.append({"date": day, "extra_reexport_group": index, "rows": len(group)})
        if not positional:
            order_only_dates.append(day)
    result["content_match"] = {
        "unmatched_groups": unmatched,
        "dates_with_order_only_difference": order_only_dates,
        "content_equal_ignoring_same_day_order": not unmatched,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--reexport", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(compare(args.candidate, args.reexport), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
