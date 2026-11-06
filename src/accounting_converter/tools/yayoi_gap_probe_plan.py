"""Enumerate the JDL Evidence still missing for one Yayoi company and plan the smallest Probe set.

Counts and structural keys only: no account, tax, description or amount text.

Assumes (like `yayoi_whatif_readiness.technical_sizing`) that the Human confirms
the natural tax candidate of every tax identity. For each journal whose
structure or tax amount has no Evidence it lists the account-free conditions a
real JDL round trip must prove, using the registered scoped Evidence:

  LAYOUT(L)                  the physical-row layout L never round-tripped
  CELL(L, side, cell)        the tax cell on that side never round-tripped in L
  PAIR(debit, credit)        a row with tax on both sides never round-tripped
  EXPLICIT(side, cell, rel)  an explicit tax amount relation never kept by JDL

A candidate Probe is the real row signature (layout + cell per row) of a gap
journal. A journal is settled when every condition it needs is provided by the
chosen Probes. Conditions already proven are never listed again.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

from accounting_converter.adapters.output.jdl import scoped_evidence as scoped
from accounting_converter.application.yayoi_review import candidate_semantic
from accounting_converter.application.yayoi_sources import detect_format
from accounting_converter.domain.journal_rows import journal_physical_rows
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore

NO = "NO"


def journal_record(entry, context):
    """(row_cells, layout, explicit_needs) for a journal, or None if representation is unresolved."""
    rows = journal_physical_rows(entry)
    if rows is None or entry.metadata.get("yayoi_closing"):
        return None
    cell_by_line = {}
    for line in entry.lines:
        category = line.tax_info.category if line.tax_info and line.tax_info.category else None
        if category is None:
            cell_by_line[id(line)] = NO
            continue
        semantic = candidate_semantic(category)
        cell = scoped.SEMANTIC_CELL.get(semantic.value) if semantic else None
        if cell is None:
            return None
        cell_by_line[id(line)] = cell
    row_cells = tuple(
        tuple(cell_by_line[id(line)] if line is not None else "-" for line in (row.debit, row.credit)) for row in rows
    )
    explicit = []
    for line in entry.lines:
        cell = cell_by_line[id(line)]
        if cell in {"S10", "P10", "R8", "T80", "XS", "NP", "NS"}:
            written = line.tax_info.tax_amount if line.tax_info else None
            if cell in {"S10", "P10"} and written is None:
                continue  # implicit 10%: the existing Evidence decides, not a new condition
            relation = scoped.relation_of(cell, line.amount, written)
            explicit.append((line.side.value, cell, relation))
    return row_cells, scoped.layout_of(rows), tuple(explicit)


def conditions(row_cells, layout, explicit) -> set[tuple]:
    needs: set[tuple] = set()
    if layout not in scoped.LAYOUT_CELLS:
        needs.add(("LAYOUT", layout))
    observed = scoped.LAYOUT_CELLS.get(layout, frozenset())
    for debit, credit in row_cells:
        if (debit, credit) not in scoped.ROW_PAIRS and debit not in {NO, "-"} and credit not in {NO, "-"}:
            needs.add(("PAIR", debit, credit))
        for side, cell in (("DEBIT", debit), ("CREDIT", credit)):
            if cell not in {NO, "-"} and (side, cell) not in observed:
                needs.add(("CELL", layout, side, cell))
    for side, cell, relation in explicit:
        if relation is None:
            needs.add(("EXPLICIT", side, cell, "UNOBSERVED_AMOUNT"))
        elif relation not in {"", "NONE"} and not scoped.relation_accounts(side, cell, relation):
            needs.add(("EXPLICIT", side, cell, relation))
    return needs


def provided(row_cells, layout) -> set[tuple]:
    """What one Probe of this signature would prove if it round-trips."""
    result = {("LAYOUT", layout)}
    for debit, credit in row_cells:
        if debit not in {NO, "-"} and credit not in {NO, "-"}:
            result.add(("PAIR", debit, credit))
        for side, cell in (("DEBIT", debit), ("CREDIT", credit)):
            if cell not in {NO, "-"}:
                result.add(("CELL", layout, side, cell))
    return result


def plan(entries, context, row_limit: int) -> dict:
    from accounting_converter.tools.yayoi_whatif_readiness import technical_sizing

    missing: list = []
    technical_sizing(entries, context, with_campaign=True, evidence_missing=missing)
    gap_journals = []
    for entry, _kind, _why in missing:
        rows = journal_physical_rows(entry)
        record = journal_record(entry, context)
        if record is None:
            continue
        row_cells, layout, explicit = record
        needs = conditions(row_cells, layout, explicit)
        if needs:
            gap_journals.append((entry.id, row_cells, layout, explicit, needs))
    by_signature: dict[tuple, list] = defaultdict(list)
    for item in gap_journals:
        by_signature[item[1]].append(item)
    needed = Counter(c for item in gap_journals for c in item[4])
    # Greedy set cover over structural conditions: each chosen Probe is a real signature.
    open_journals = {item[0]: item for item in gap_journals}
    chosen: list[tuple] = []
    proven: set[tuple] = set()
    while open_journals:
        best, best_score = None, 0
        for signature, items in by_signature.items():
            gain = provided(signature, items[0][2]) - proven
            score = sum(1 for item in items if item[0] in open_journals) * 1000 + len(gain)
            if signature in chosen:
                continue
            if score > best_score:
                best, best_score = signature, score
        if best is None:
            break
        chosen.append(best)
        proven |= provided(best, by_signature[best][0][2])
        for journal_id in [j for j, item in open_journals.items() if item[4] <= proven]:
            del open_journals[journal_id]
        if not any(by_signature[s][0][0] in open_journals or any(i[0] in open_journals for i in by_signature[s])
                   for s in by_signature if s not in chosen):
            break
    unresolved = [j for j in open_journals]
    return {
        "gap_journals": len(gap_journals),
        "distinct_signatures": len(by_signature),
        "distinct_layouts": len({item[2] for item in gap_journals}),
        "condition_kinds": dict(Counter(c[0] for c in needed)),
        "distinct_conditions": len(needed),
        "journals_per_condition_kind": dict(Counter(c[0] for item in gap_journals for c in item[4])),
        "explicit_amount_conditions": {"/".join(str(p) for p in c[1:]): n for c, n in needed.items() if c[0] == "EXPLICIT"},
        "minimal_probe_signatures": [
            {"layout": by_signature[s][0][2], "rows": [list(r) for r in s], "journals_settled": len(by_signature[s])}
            for s in chosen
        ],
        "probes": len(chosen),
        "journals_not_settled_by_plan": len(unresolved),
        "_signatures": chosen,
    }


def load(source: Path, company_store: Path, company_id: str, row_limit: int):
    profiles = ConversionProfileStore(company_store / "profiles")
    resolved = CompanySettingStore(company_store / "companies", profiles).resolve(company_id)
    context = replace(resolved.context, voucher_row_limit=row_limit)
    return detect_format(source).diagnose(source).entries, context


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--company-store", type=Path, required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--row-limit", type=int, default=16)
    args = parser.parse_args()
    entries, context = load(args.source, args.company_store, args.company_id, args.row_limit)
    result = plan(entries, context, args.row_limit)
    result.pop("_signatures")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
