"""Formal READY of one Yayoi company, then step by step what each open Human decision would release.

Everything runs on a SCRATCH COPY of the saved settings (the real store is never written) and
only through the app's own paths:

  0. optional --new-pdf: the JDL 科目一覧 is reloaded the way the app does it (same-name codes
     excluded, saved approvals kept only by exact code + name, confirmed Tax Context kept).
  1. the target context is checked by the production validator FIRST. A duplicate identity or code
     stops here and names the JDL codes involved (never "repaired" by merging same-name accounts).
  2. ladder (cumulative, each step is a Human decision taken in the copy only):
       L0 saved setting as is                       -> formal READY now
       L1 + 振替伝票入力行数 16 (JDL limit verified)
       L2 + tax identities with an Evidence-backed candidate, same-name subaccounts
       L3 + parent-only for every parent where the app allows it
       L4 + remaining subaccounts on the top-ranked existing JDL subaccount   (ASSUMPTION:
            sizing only, to expose the technical gaps that subaccount decisions hide)
     Per step: READY, journals blocked only by Human decisions, by technical gaps (tax / structure),
     the row limit, unresolved representations (closing entries, taxes without JDL form).

Prints counts and blocker codes only. Not READY counts except L0.
"""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections import Counter
from pathlib import Path

from accounting_converter.adapters.output.jdl.context import JdlTargetContextValidator
import hashlib

from accounting_converter.adapters.output.jdl.scoped_evidence_registry import SCOPED_CASES
from accounting_converter.application import parent_subaccount_policy as policy
from accounting_converter.application import readiness_breakdown as breakdown
from accounting_converter.application.company_voucher_row_limit import CompanyVoucherRowLimitService
from accounting_converter.application.yayoi_jdl_workflow import YayoiJournalReportJdlWorkflow
from accounting_converter.application.yayoi_sources import detect_format
from accounting_converter.domain.journal_rows import journal_physical_rows
from accounting_converter.infrastructure.application_preferences import ApplicationPreferencesStore
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.ui.controllers import AccountingConverterController

TAX_GAPS = frozenset({
    "TAX_ACCOUNT_UNVERIFIED", "TAX_SIDE_UNVERIFIED", "EXPLICIT_TAX_AMOUNT_UNVERIFIED",
    "EXPLICIT_TAX_COMPANY_ROUNDING_UNVERIFIED", "EXPLICIT_TAX_KEEP_UNVERIFIED", "TAX_CONTEXT_UNVERIFIED",
})
UNRESOLVED_GAPS = frozenset({"CLOSING_ENTRY_REPRESENTATION"})


def classify(assessment, entries_by_id, row_limit) -> dict:
    """Mutually exclusive classes (first match wins) plus the tax / structure gap journals."""
    classes, codes = Counter(), Counter()
    tax_ids, structure_ids = set(), set()
    for journal_id, found in assessment.journal_blockers.items():
        found = set(found)
        codes.update(found)
        technical = {b.split(":", 1)[1] for b in found if b.startswith("SYSTEM_")}
        human = any(b.startswith("HUMAN:") for b in found)
        entry = entries_by_id[journal_id]
        rows = journal_physical_rows(entry)
        tax, structure = technical & TAX_GAPS, technical - TAX_GAPS - UNRESOLVED_GAPS
        if tax:
            tax_ids.add(journal_id)
        if structure:
            structure_ids.add(journal_id)
        if not found:
            classes["ready"] += 1
        elif row_limit is not None and rows is not None and len(rows) > row_limit:
            classes["row_limit_exceeded"] += 1
        elif technical & UNRESOLVED_GAPS or entry.metadata.get("yayoi_closing"):
            classes["unresolved_closing_entry"] += 1
        elif "HUMAN:TAX_MAPPING" in found and not (tax or structure) and not any(
                b.startswith("HUMAN:") and b != "HUMAN:TAX_MAPPING" for b in found):
            classes["human_tax_mapping_only"] += 1
        elif (tax or structure) and human:
            classes["human_and_technical"] += 1
        elif tax or structure:
            classes["technical_only"] += 1
        else:
            classes["human_only"] += 1
    return {"ready": assessment.ready_journals, "classes": dict(classes),
            "tax_gap_journals": len(tax_ids), "structure_gap_journals": len(structure_ids),
            "blockers": dict(codes.most_common())}, sorted(tax_ids), sorted(structure_ids)


def store_identity(source: Path, company_store: Path, company_id: str) -> dict:
    """What the diagnosis is reading, so two runs can be compared condition by condition. No names."""
    profiles = ConversionProfileStore(company_store / "profiles")
    resolved = CompanySettingStore(company_store / "companies", profiles).resolve(company_id)
    profile, context = resolved.profile, resolved.context
    entries = detect_format(source).diagnose(source).entries
    resolved_of = lambda mappings: sum(1 for m in mappings.values() if m.is_resolved)  # noqa: E731
    identity = {
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "journals": len(entries),
        "company_id": company_id,
        "evidence_registry_cases": len(SCOPED_CASES),
        "account_approvals": resolved_of(profile.account_mappings),
        "subaccount_approvals": resolved_of(profile.subaccount_context_mappings),
        "tax_approvals": resolved_of(profile.tax_mappings),
        "profile_updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }
    if context is not None:
        identity.update({
            "master_accounts": len(context.account_master), "master_subaccounts": len(context.subaccounts),
            "unusable_subaccounts": len(context.unusable_subaccounts),
            "context_fingerprint": getattr(resolved, "context_fingerprint", None),
            "tax_processing_mode": context.tax_processing_mode.value,
            "rounding": [context.sales_tax_rounding.value, context.purchase_tax_rounding.value],
            "voucher_row_limit": context.voucher_row_limit,
            "context_confirmed": context.confirmation_state.value,
        })
    return identity


def diagnose(source: Path, company_store: Path, company_id: str, *, new_pdf: Path | None = None,
             row_limit: int = 16, reference: tuple[Path, str] | None = None,
             l0_only: bool = False) -> dict:
    entries = detect_format(source).diagnose(source).entries
    by_id = {entry.id: entry for entry in entries}
    result: dict = {"journals": len(entries), "identity": store_identity(source, company_store, company_id), "steps": {}}
    identity = result["identity"]
    result["store_warnings"] = list(breakdown.store_check(
        account_mappings=identity["account_approvals"], subaccount_mappings=identity["subaccount_approvals"],
        master_accounts=identity.get("master_accounts"), account_blocked_journals=0,
        voucher_row_limit=identity.get("voucher_row_limit"), confirmed_context=identity.get("context_confirmed") == "CONFIRMED"))
    with tempfile.TemporaryDirectory() as directory:
        store = Path(directory) / "store"
        shutil.copytree(company_store, store)
        profiles = ConversionProfileStore(store / "profiles")
        companies = CompanySettingStore(store / "companies", profiles)
        controller = AccountingConverterController(
            profile_store=profiles, company_store=companies,
            preferences_store=ApplicationPreferencesStore(Path(directory) / "prefs.json"))
        controller.load_company_settings()
        if new_pdf is not None:
            plan = controller.plan_company_master_refresh(company_id, new_pdf)
            result["master_refresh"] = {
                "reconfirmation_needed": plan.reconfirmation_count,
                "confirmed_context_preservable": plan.confirmed_context_preservable,
                "master_identity_unchanged": plan.master_identity_unchanged,
            }
            if plan.reconfirmation_count or not plan.confirmed_context_preservable:
                result["stopped"] = "the reload would drop saved approvals or the confirmed JDL settings"
                return result
            controller.apply_company_master_refresh(plan, {}, set(), preserve_confirmed_context=True)

        resolved = companies.resolve(company_id)
        problems = JdlTargetContextValidator().validate(resolved.context) if resolved.context else ()
        result["context_check"] = [{"rule": p.rule_id, "message": p.message} for p in problems] or "PASS"
        if problems:
            result["stopped"] = "the JDL target context is invalid; fix the master, never merge same-name codes"
            return result

        def step(name: str, decisions: dict | None = None) -> None:
            resolved = companies.resolve(company_id)
            assessment = YayoiJournalReportJdlWorkflow().assess(source, resolved.profile, resolved.context)
            summary, tax_ids, structure_ids = classify(
                assessment, by_id, resolved.context.voucher_row_limit if resolved.context is not None else None)
            if decisions is not None:
                summary["decisions_in_copy"] = decisions
            result["steps"][name] = summary
            if name.startswith("L0"):
                blockers = {k: set(v) for k, v in assessment.journal_blockers.items()}
                result["l0_breakdown"] = [
                    {"blocker": r.blocker, "category": r.category, "first": r.first, "all": r.all, "only_this": r.only_this}
                    for r in breakdown.breakdown(blockers)]
                result["l0_by_category"] = breakdown.by_category(blockers)
                if reference is not None:
                    ref_store, ref_id = reference
                    ref_resolved = CompanySettingStore(ref_store / "companies", ConversionProfileStore(ref_store / "profiles")).resolve(ref_id)
                    ref_assessment = YayoiJournalReportJdlWorkflow().assess(source, ref_resolved.profile, ref_resolved.context)
                    ready_here = [j for j, b in assessment.journal_blockers.items() if not b]
                    ready_ref = [j for j, b in ref_assessment.journal_blockers.items() if not b]
                    result["reference_identity"] = store_identity(source, ref_store, ref_id)
                    result["reference_ready"] = len(ready_ref)
                    result["trace_of_reference_ready_here"] = breakdown.trace_ready(ready_ref, blockers)
                    result["ready_here_that_reference_blocks"] = breakdown.trace_ready(ready_here, {k: set(v) for k, v in ref_assessment.journal_blockers.items()})
            result.setdefault("_ids", {})[name] = {"tax": tax_ids, "structure": structure_ids}

        def review():
            controller.load_company_settings()
            controller.select_file(source)
            controller.select_company_setting(company_id)
            return controller.review_company_mapping_updates(company_id, source)

        step("L0_saved_setting_formal_ready")
        if l0_only or identity["account_approvals"] == 0 or companies.resolve(company_id).context is None:
            result["ladder_skipped"] = (
                "requested" if l0_only else
                "the JDL tax setting is not confirmed (the master is only a PDF draft): nothing can be READY, "
                "and the what-if steps need a confirmed setting" if companies.resolve(company_id).context is None else
                "this setting has no confirmed account approvals; the what-if steps need a confirmed parent account")
            return result
        CompanyVoucherRowLimitService(companies, profiles).set(company_id, row_limit, confirmed=True)
        step("L1_row_limit", {"voucher_row_limit": row_limit})

        current = review()
        taxes = 0
        state = controller.ensure_selected_tax_requirements(current)
        if state.developer_error is None:
            tax = controller.company_tax_mapping_review(
                company_id, affected_counts=dict(current.tax_category_counts),
                observed_source_values=current.observed_tax_categories or current.tax_categories)
            values = tuple(item.source_value for item in tax.confirmable_items)
            if values:
                controller.confirm_company_tax_mappings(company_id, values)
            taxes = len(values)
        current = review()
        same_name: dict[str, str] = {}
        for group in policy.parent_groups(current):
            same_name.update(policy.preserve_selections(group))
        if same_name:
            controller.apply_company_mapping_updates(current, same_name, set(same_name), {}, set())
        step("L2_tax_and_same_name_subaccounts", {"tax_identities": taxes, "subaccounts": len(same_name)})

        current = review()
        parent_only: dict[str, str] = {}
        parents = 0
        for group in policy.parent_groups(current):
            if group.parent_only_possible:
                parent_only.update(policy.parent_only_selections(group))
                parents += 1
        if parent_only:
            controller.apply_company_mapping_updates(current, parent_only, set(parent_only), {}, set())
        step("L3_parent_only_where_allowed", {"parents": parents, "subaccounts": len(parent_only)})

        current = review()
        assumed: dict[str, str] = {}
        for item in current.items:
            if item.mapping_type != "SUBACCOUNT" or item.already_confirmed or not item.confirmed_parent_target:
                continue
            ranked = item.ranked_subaccount_targets_for(item.confirmed_parent_target)
            if ranked:
                assumed[item.key] = ranked[0].target_name
        if assumed:
            controller.apply_company_mapping_updates(current, assumed, set(assumed), {}, set())
        step("L4_ASSUMED_remaining_subaccounts", {"assumed_subaccounts": len(assumed)})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--company-store", type=Path, required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--new-pdf", type=Path, help="reload this JDL 科目一覧 PDF in the copy first")
    parser.add_argument("--row-limit", type=int, default=16)
    parser.add_argument("--l0-only", action="store_true", help="only the saved setting (no what-if steps)")
    parser.add_argument("--reference-store", type=Path, help="another store whose READY journals are traced here")
    parser.add_argument("--reference-company-id")
    parser.add_argument("--ids-out", type=Path, help="journal ids per step (data/private only)")
    args = parser.parse_args()
    result = diagnose(args.source, args.company_store, args.company_id, new_pdf=args.new_pdf, row_limit=args.row_limit,
                       reference=(args.reference_store, args.reference_company_id) if args.reference_store else None,
                       l0_only=args.l0_only)
    ids = result.pop("_ids", {})
    if args.ids_out:
        if "data/private" not in args.ids_out.resolve().as_posix():
            raise SystemExit("--ids-out must be under data/private")
        args.ids_out.write_text(json.dumps(ids), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if "stopped" not in result else 2


if __name__ == "__main__":
    raise SystemExit(main())
