"""Read-only description of what the voucher split rule would write for one journal (for the approval screen/brief).

Nothing here records an approval or changes a journal; it only runs the existing rule (application/voucher_split).
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from accounting_converter.adapters.output.jdl import scoped_evidence as scoped
from accounting_converter.application import voucher_split as vs
from accounting_converter.domain.journal_rows import journal_physical_rows


def brief(entry, limit: int, *, ignore_signs: bool = False) -> dict:
    probe = replace(entry, lines=[replace(l, amount=abs(l.amount)) for l in entry.lines]) if ignore_signs else entry
    plan = vs.plan_split(probe, limit)
    if plan is None:
        return {"journal": entry.id, "split": False, "why_not": vs.ineligible_reason(probe, limit)}
    parts = vs.split_entry(entry, plan)
    anchor_side = plan.counterpart_side
    original = {
        "physical_rows": len(journal_physical_rows(entry)), "lines": len(entry.lines),
        "layout": scoped.layout_of(journal_physical_rows(entry)),
        "debit": str(entry.debit_total()), "credit": str(entry.credit_total()),
        "explicit_tax": str(sum((l.tax_info.tax_amount or 0 for l in entry.lines if l.tax_info), Decimal(0))),
        "negative_lines": sum(l.amount < 0 for l in entry.lines),
        "tax_categories": sorted({l.tax_info.category for l in entry.lines if l.tax_info}),
    }
    rows = []
    for number, (source_rows, part) in enumerate(zip(plan.parts, parts), start=1):
        counterpart = next(l for l in part.lines if l.side.value == anchor_side)
        rows.append({
            "part": number, "source_rows": [min(source_rows), max(source_rows), len(source_rows)],
            "jdl_rows": len(journal_physical_rows(part)), "layout": scoped.layout_of(journal_physical_rows(part)),
            "counterpart_account": counterpart.account, "counterpart_amount": str(counterpart.amount),
            "other_side_total": str(sum((l.amount for l in part.lines if l.side.value != anchor_side), Decimal(0))),
            "explicit_tax": str(sum((l.tax_info.tax_amount or 0 for l in part.lines if l.tax_info), Decimal(0))),
            "negative_lines": sum(l.amount < 0 for l in part.lines),
        })
    return {
        "journal": entry.id, "date": entry.date.isoformat(), "row_limit": limit, "rule": vs.RULE, "split": True,
        "original": original, "parts": rows,
        "rebuilds_original": not vs.reconstruction_problems(entry, parts, plan, limit),
        "unchanged": ["借方・貸方の各明細（科目・補助・税区分・税額・金額・摘要・元の行番号）", "日付", "貸方の相手科目・補助・税区分",
                      "各伝票の借貸一致"],
        "changes": ["JDLでは1つの仕訳が%d枚の伝票になる（伝票番号は別々）" % len(parts),
                    "相手科目(%s)の金額が各伝票の合計額に分かれる（合計は元の金額と一致）" % counterpart.account],
        "lost": "元の1伝票としての一体性（JDL上で伝票が分かれる）。明細・金額・税額・摘要の欠落はない（再構成検査で確認）",
    }
