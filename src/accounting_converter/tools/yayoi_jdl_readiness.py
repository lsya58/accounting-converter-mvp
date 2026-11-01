"""Privacy-safe Yayoi 仕訳日記帳 (汎用形式) → JDL readiness. Internal diagnostic.

Prints counts only: no account names, descriptions, tax names or amounts.

1. actual: the real workflow assessment for the given CompanySetting (or none).
2. simulated: what would still need JDL Evidence if the Human confirmed the
   natural candidate for each tax identity and the target Tax Context were
   the verified one. Nothing is confirmed; this is not formal readiness.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from types import SimpleNamespace
from pathlib import Path

from accounting_converter.application.yayoi_sources import detect_format
from accounting_converter.adapters.output.jdl.row_evidence import JDL_ROW_DESCRIPTION_VERIFIED_SHAPES
from accounting_converter.adapters.output.jdl import JdlTaxRounding
from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
from accounting_converter.application.yayoi_jdl_workflow import YayoiJournalReportJdlWorkflow
from accounting_converter.application.yayoi_review import _UNSET_ROUNDING, candidate_semantic, review_source
from accounting_converter.domain.journal_rows import journal_physical_rows, physical_row_shape
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore


def simulated_evidence_gaps(entry, context=None) -> set[str]:
    gaps: set[str] = set()
    rows = journal_physical_rows(entry)
    shape = physical_row_shape(rows)
    if shape[:2] != (1, 1) and (shape[:2] not in ev.verified_mf_shapes() or shape not in JDL_ROW_DESCRIPTION_VERIFIED_SHAPES):
        gaps.add("SHAPE")
    taxed = []
    for line in entry.lines:
        semantic = candidate_semantic(line.tax_info.category) if line.tax_info else None
        if semantic is not None and semantic.value != "JDL_NO_TAX":
            taxed.append((line.side.value, semantic.value))
    if shape[:2] in ev.verified_mf_shapes():
        gaps.update(gap for gap in ev.shape_tax_combination_gaps(shape[:2], tuple(taxed))
                    if gap != "SHAPE_UNVERIFIED_IN_TAX_CONTEXT")
    for line in entry.lines:
        semantic = candidate_semantic(line.tax_info.category) if line.tax_info else None
        if semantic is None:
            gaps.add("TAX_SEMANTIC_UNAVAILABLE")
            continue
        if (line.side.value, semantic.value) not in ev.LINE_CAPABILITIES:
            gaps.add("TAX_SIDE_UNVERIFIED")
        explicit = line.tax_info.tax_amount
        if explicit is not None:
            gap = ev.explicit_tax_gap(explicit, line.amount, semantic.value, context or _UNSET_ROUNDING)
            if gap is not None:
                gaps.add(gap)
    if entry.metadata.get("yayoi_closing"):
        gaps.add("CLOSING_ENTRY_REPRESENTATION")
    return gaps


def assess(source: Path, profile=None, context=None, rounding_context=None) -> dict[str, object]:
    """rounding_context: any object with sales/purchase_tax_rounding, for the simulation only."""
    workflow = YayoiJournalReportJdlWorkflow()
    actual = workflow.assess(source, profile, context)
    parsed = detect_format(source).diagnose(source)
    entries = parsed.entries
    review = review_source(entries, profile, context, rounding_context)
    simulated = {entry.id: simulated_evidence_gaps(entry, rounding_context) for entry in entries}
    shapes = Counter(
        physical_row_shape(journal_physical_rows(entry)) for entry in entries if "SHAPE" in simulated[entry.id]
    )
    return {
        "total_journals": len(entries) + parsed.rejected_journals,
        "physical_rows": parsed.detail_rows,
        "strict_parse_ready": len(entries) if parsed.ok else 0,
        "common_journal_ready": sum(1 for entry in entries if journal_physical_rows(entry) is not None),
        "formal_ready": actual.ready_journals,
        "actual": {"by_owner": actual.owner_counts(), "by_blocker": actual.blocker_counts(),
                   "likely_after_tax_confirmation": actual.likely_blocker_counts(),
                   "non_retained_journals": actual.non_retained_journals,
                   "information_fully_retained": actual.information_fully_retained},
        "human_setting_items": review.setting_item_counts,
        "tax_identities": [
            {"mapping": t.mapping_state, "evidence": t.evidence_state,
             "candidate": t.candidate.value if t.candidate else None,
             "explicit_tax_gaps": t.explicit_tax_gaps,
             "debit": t.debit_lines, "credit": t.credit_lines, "journals": t.journals,
             "explicit_tax": t.explicit_tax_lines, "explicit_tax_unverified": t.explicit_tax_unverified_lines,
             "has_invoice_class": bool(t.invoice_class), "has_purchase_credit": bool(t.purchase_credit)}
            for t in review.taxes
        ],
        "department_journals": sum(1 for entry in entries if any(line.department for line in entry.lines)),
        "description_groups": len(review.descriptions),
        "description_affected_journals": sum(item.affected_journal_count for item in review.descriptions),
        "simulated_evidence": {
            "journals_with_gaps": sum(1 for gaps in simulated.values() if gaps),
            "by_gap": dict(Counter(gap for gaps in simulated.values() for gap in gaps)),
            "unverified_shapes": len(shapes),
            "top10_unverified_shapes_cover": sum(count for _, count in shapes.most_common(10)),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--company-store", type=Path)
    parser.add_argument("--company-id")
    choices = [item.value for item in JdlTaxRounding]
    parser.add_argument("--sales-rounding", choices=choices, default="UNCONFIRMED",
                        help="simulation only: target JDL 売上の端数処理")
    parser.add_argument("--purchase-rounding", choices=choices, default="UNCONFIRMED",
                        help="simulation only: target JDL 仕入の端数処理")
    args = parser.parse_args()
    rounding = SimpleNamespace(sales_tax_rounding=JdlTaxRounding(args.sales_rounding),
                               purchase_tax_rounding=JdlTaxRounding(args.purchase_rounding))
    profile = context = None
    if args.company_store and args.company_id:
        profiles = ConversionProfileStore(args.company_store / "profiles")
        resolved = CompanySettingStore(args.company_store / "companies", profiles).resolve(args.company_id)
        profile, context = resolved.profile, resolved.context
    print(json.dumps(assess(args.source, profile, context, context or rounding), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
