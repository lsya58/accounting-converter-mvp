"""What a newly printed JDL 科目一覧 changes for one Yayoi company. Analysis only: the real settings are never written.

Everything happens in a SCRATCH COPY of the settings:
  1. the new PDF is imported and the account-list refresh is applied as the app does it, keeping the
     confirmed Tax Context (rounding, row limit, ...); it stops if the app would not keep it;
  2. SCENARIO "same name": the Human is assumed to confirm every account whose JDL name equals the
     Yayoi name or differs only in width / dash (the app's EXACT and NORMALIZED candidates). ALIAS /
     SIMILAR / CONTAINS candidates are never assumed; those parents stay open. Tax identities with an
     Evidence-backed candidate are assumed confirmed. No subaccount is assumed.
  3. it reports readiness, the JDL Evidence gaps that the assumed accounts create (per JDL code), and the
     subaccount decisions per parent (`parent_subaccount_policy`).
Counts and JDL codes only on stdout; names go to the optional sheet under data/private.
"""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

from accounting_converter.adapters.output.jdl.scoped_evidence import SEMANTIC_CELL
from accounting_converter.application import parent_subaccount_policy as policy
from accounting_converter.application import scoped_evidence_composition as composition
from accounting_converter.application.yayoi_review import candidate_semantic
from accounting_converter.application.yayoi_sources import detect_format
from accounting_converter.infrastructure.application_preferences import ApplicationPreferencesStore
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.tools.yayoi_whatif_readiness import _classify, _blockers_of
from accounting_converter.ui.controllers import AccountingConverterController
from accounting_converter.application.yayoi_jdl_workflow import YayoiJournalReportJdlWorkflow

SAME_NAME_KINDS = {"EXACT", "NORMALIZED"}


def prepare(store: Path, company_id: str, new_pdf: Path, scratch: Path):
    """Scratch copy with the new master, refreshed the way the app does it: the confirmed Tax Context
    (rounding, row limit, ...) is kept by `preserve_confirmed_context` when the app allows it."""
    work = scratch / "store"
    shutil.copytree(store, work)
    old = CompanySettingStore(store / "companies", ConversionProfileStore(store / "profiles")).resolve(company_id).context
    profiles = ConversionProfileStore(work / "profiles")
    companies = CompanySettingStore(work / "companies", profiles)
    controller = AccountingConverterController(
        profile_store=profiles, company_store=companies,
        preferences_store=ApplicationPreferencesStore(scratch / "prefs.json"))
    controller.load_company_settings()
    plan = controller.plan_company_master_refresh(company_id, new_pdf)
    if plan.reconfirmation_count:
        raise SystemExit(f"{plan.reconfirmation_count} confirmed parents would need re-confirmation; not assumed here")
    if not plan.confirmed_context_preservable:
        raise SystemExit("the app would not keep the confirmed JDL settings for this PDF; nothing is assumed")
    controller.apply_company_master_refresh(plan, {}, set(), preserve_confirmed_context=True)
    new = companies.resolve(company_id).context
    kept = new is not None and all(getattr(new, field) == getattr(old, field) for field in (
        "tax_processing_mode", "sales_tax_rounding", "purchase_tax_rounding", "voucher_row_limit",
        "effective_taxation_method", "effective_input_tax_credit_method", "confirmation_state"))
    if not kept:
        raise SystemExit("confirmed JDL settings were not kept by the refresh")
    return controller, companies, profiles, plan


def fill_same_name(controller, company_id: str, source: Path) -> dict:
    controller.select_file(source)
    controller.select_company_setting(company_id)
    review = controller.review_company_mapping_updates(company_id, source)
    chosen, tiers = {}, Counter()
    for item in review.items:
        if item.mapping_type != "ACCOUNT" or item.already_confirmed:
            continue
        pick = next((c for c in item.candidates if c.kind in SAME_NAME_KINDS and c.name in item.available_targets), None)
        if pick is not None:
            chosen[item.key] = pick.name
            tiers[pick.kind] += 1
    if chosen:
        controller.apply_company_mapping_updates(review, chosen, set(chosen), {}, set())
    review = controller.review_company_mapping_updates(company_id, source)
    state = controller.ensure_selected_tax_requirements(review)
    taxes = 0
    if state.developer_error is None:
        tax = controller.company_tax_mapping_review(
            company_id, affected_counts=dict(review.tax_category_counts),
            observed_source_values=review.observed_tax_categories or review.tax_categories)
        values = tuple(item.source_value for item in tax.confirmable_items)
        if values:
            controller.confirm_company_tax_mappings(company_id, values)
        taxes = len(values)
    return {"accounts_confirmed": len(chosen), "by_candidate_kind": dict(tiers), "tax_identities_confirmed": taxes}


def evidence_by_code(entries, profile, context) -> dict:
    """Per (JDL code, side, tax cell): lines and journals whose Evidence gap is the account itself."""
    codes = {}
    for source, mapping in profile.account_mappings.items():
        if mapping.status.value == "USER_CONFIRMED":
            codes[source] = mapping.metadata.get("target_code", "")
    lines, journals = Counter(), defaultdict(set)
    for entry in entries:
        for line in entry.lines:
            code = codes.get(line.account)
            category = line.tax_info.category if line.tax_info and line.tax_info.category else None
            if not code or category is None:
                continue
            semantic = candidate_semantic(category)
            cell = SEMANTIC_CELL.get(semantic.value) if semantic else None
            if cell is None or cell == "NO":
                continue
            explicit = line.tax_info.tax_amount
            gaps, _ = composition.line_gaps(composition.ScopedLine(line.side.value, code, cell, line.amount, explicit))
            if gaps:
                key = (code, line.side.value[0], cell, gaps[0])
                lines[key] += 1
                journals[key].add(entry.id)
    return {k: (lines[k], len(journals[k])) for k in lines}


def analyse(store: Path, company_id: str, source: Path, new_pdf: Path) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        scratch = Path(directory)
        controller, companies, profiles, plan = prepare(store, company_id, new_pdf, scratch)
        filled = fill_same_name(controller, company_id, source)
        resolved = companies.resolve(company_id)
        entries = detect_format(source).diagnose(source).entries
        assessment = YayoiJournalReportJdlWorkflow().assess(source, resolved.profile, resolved.context)
        limit = resolved.context.voucher_row_limit
        classified = _classify(entries, _blockers_of(assessment), limit)
        gaps = evidence_by_code(entries, resolved.profile, resolved.context)
        review = controller.review_company_mapping_updates(company_id, source)
        groups = policy.parent_groups(review)
        return {
            "master_diff_vs_saved": dict(Counter(ch.kind.value for ch in plan.master_diff.changes)),
            "confirmed_parents_preserved": f"{sum(i.preserved for i in plan.items)}/{len(plan.items)}",
            "assumed_human_decisions": filled,
            "journals": len(entries),
            "classes": classified["classes"],
            "jdl_evidence_missing_codes": classified["jdl_evidence_missing_codes"],
            "human_pending_codes": classified["human_pending_codes"],
            "unresolved_kinds": classified["unresolved_kinds"],
            "account_evidence_gaps_by_jdl_code": {
                f"{c}/{side}/{cell}/{gap}": {"lines": n, "journals": j} for (c, side, cell, gap), (n, j) in sorted(gaps.items())},
            "subaccounts": policy.summarize(groups),
            "_review_items_unconfirmed": {t: sum(1 for i in review.items if i.mapping_type == t and not i.already_confirmed)
                                          for t in ("ACCOUNT", "SUBACCOUNT", "DEFAULT_SUBACCOUNT")},
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--company-store", type=Path, required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--new-pdf", type=Path, required=True)
    parser.add_argument("--out", type=Path, help="write the JSON result here (under data/private)")
    args = parser.parse_args()
    result = analyse(args.company_store, args.company_id, args.source.resolve(), args.new_pdf)
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        if "data/private" not in args.out.resolve().as_posix():
            raise SystemExit("write the result under data/private only")
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
