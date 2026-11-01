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
from pathlib import Path

from accounting_converter.adapters.input.yayoi.journal_report_parser import YayoiJournalReportParser
from accounting_converter.adapters.output.jdl.row_evidence import JDL_ROW_DESCRIPTION_VERIFIED_SHAPES
from accounting_converter.adapters.output.jdl.tax_semantics import JdlTaxSemantic
from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
from accounting_converter.application.yayoi_jdl_workflow import YayoiJournalReportJdlWorkflow
from accounting_converter.application.yayoi_review import candidate_semantic, review_source
from accounting_converter.domain.journal_rows import journal_physical_rows, physical_row_shape
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore


def simulated_evidence_gaps(entry) -> set[str]:
    gaps: set[str] = set()
    rows = journal_physical_rows(entry)
    shape = physical_row_shape(rows)
    if shape[:2] != (1, 1) and (shape[:2] not in ev.verified_mf_shapes() or shape not in JDL_ROW_DESCRIPTION_VERIFIED_SHAPES):
        gaps.add("SHAPE")
    for line in entry.lines:
        semantic = candidate_semantic(line.tax_info.category) if line.tax_info else None
        if semantic is None:
            gaps.add("TAX_SEMANTIC_UNAVAILABLE")
            continue
        if (line.side.value, semantic.value) not in ev.LINE_CAPABILITIES:
            gaps.add("TAX_SIDE_UNVERIFIED")
        explicit = line.tax_info.tax_amount
        taxed = semantic in {JdlTaxSemantic.PURCHASE_10_INTERNAL, JdlTaxSemantic.SALES_10_EXTERNAL}
        if explicit is not None and ((taxed and explicit != ev.ten_percent_tax_amount(line.amount)) or (not taxed and explicit != 0)):
            gaps.add("EXPLICIT_TAX_AMOUNT")
    if entry.metadata.get("yayoi_closing"):
        gaps.add("CLOSING_ENTRY_REPRESENTATION")
    return gaps


def assess(source: Path, profile=None, context=None) -> dict[str, object]:
    workflow = YayoiJournalReportJdlWorkflow()
    actual = workflow.assess(source, profile, context)
    parsed = YayoiJournalReportParser().diagnose(source)
    entries = parsed.entries
    review = review_source(entries, profile, context)
    simulated = {entry.id: simulated_evidence_gaps(entry) for entry in entries}
    shapes = Counter(
        physical_row_shape(journal_physical_rows(entry)) for entry in entries if "SHAPE" in simulated[entry.id]
    )
    return {
        "total_journals": len(entries) + parsed.rejected_journals,
        "physical_rows": parsed.detail_rows,
        "strict_parse_ready": len(entries) if parsed.ok else 0,
        "common_journal_ready": sum(1 for entry in entries if journal_physical_rows(entry) is not None),
        "formal_ready": actual.ready_journals,
        "actual": {"by_owner": actual.owner_counts(), "by_blocker": actual.blocker_counts()},
        "human_setting_items": review.setting_item_counts,
        "tax_identities": [
            {"mapping": t.mapping_state, "evidence": t.evidence_state,
             "candidate": t.candidate.value if t.candidate else None,
             "debit": t.debit_lines, "credit": t.credit_lines, "journals": t.journals,
             "explicit_tax": t.explicit_tax_lines, "explicit_tax_unverified": t.explicit_tax_unverified_lines,
             "has_invoice_class": bool(t.invoice_class), "has_purchase_credit": bool(t.purchase_credit)}
            for t in review.taxes
        ],
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
    args = parser.parse_args()
    profile = context = None
    if args.company_store and args.company_id:
        profiles = ConversionProfileStore(args.company_store / "profiles")
        resolved = CompanySettingStore(args.company_store / "companies", profiles).resolve(args.company_id)
        profile, context = resolved.profile, resolved.context
    print(json.dumps(assess(args.source, profile, context), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
