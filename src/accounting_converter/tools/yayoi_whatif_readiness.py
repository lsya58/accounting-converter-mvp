"""What-if readiness diagnosis of one Yayoi company, run on a SCRATCH COPY of its settings.

Real diagnosis first: the saved CompanySetting is assessed exactly as it is
(`actual`). Then, only inside a temporary copy that is deleted afterwards, the
Human decisions that are still open are filled in through the production save
paths and the same assessment is run again (`what_if`). This answers "which
journals would have no technical blocker left (JDL Evidence, implementation,
voucher row limit) IF the Human made these choices". It never approves
anything: nothing is written to the real settings, no CSV is generated, and the
numbers are not READY counts.

Scenarios for the open mapping choices (all in the copy):
  exact  only accounts / subaccounts whose name equals a JDL name, and every
         tax identity that has an Evidence-backed candidate
  best   additionally the top-ranked suggestion for accounts / subaccounts
         without an exact name (an assumption, for sizing only)

Prints counts only: no account, tax, description or amount text.
"""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections import Counter
from pathlib import Path

from accounting_converter.application.company_voucher_row_limit import CompanyVoucherRowLimitService
from accounting_converter.application.yayoi_jdl_workflow import YayoiJournalReportJdlWorkflow
from accounting_converter.application.yayoi_review import candidate_semantic
from accounting_converter.application.yayoi_sources import detect_format
from accounting_converter.domain.journal_rows import journal_physical_rows
from accounting_converter.infrastructure.application_preferences import ApplicationPreferencesStore
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.ui.controllers import AccountingConverterController

# Technical (non-Human) blocker families.
CLOSING = "SYSTEM_EVIDENCE:CLOSING_ENTRY_REPRESENTATION"


def _classify(entries, blockers: dict, row_limit: int | None) -> dict:
    """Seven mutually exclusive classes, first match wins (priority = how final the stop is)."""
    classes: Counter = Counter()
    evidence_codes: Counter = Counter()
    human_codes: Counter = Counter()
    unresolved_kinds: Counter = Counter()
    for entry in entries:
        found = blockers[entry.id]
        rows = journal_physical_rows(entry)
        over = row_limit is not None and rows is not None and len(rows) > row_limit
        no_candidate = sorted({
            line.tax_info.category for line in entry.lines
            if line.tax_info and line.tax_info.category and candidate_semantic(line.tax_info.category) is None
        })
        closing = bool(entry.metadata.get("yayoi_closing")) or CLOSING in found
        system = {b for b in found if b.startswith("SYSTEM_EVIDENCE")} - {CLOSING}
        implementation = {b for b in found if b.startswith("SYSTEM_IMPLEMENTATION")}
        human = {b for b in found if b.startswith("HUMAN:")}
        if over or "HUMAN:VOUCHER_ROW_LIMIT_EXCEEDED" in found:
            classes["voucher_row_limit_exceeded"] += 1
        elif closing or no_candidate:
            classes["unresolved_representation"] += 1
            unresolved_kinds["closing_entry" if closing else "tax_without_jdl_representation"] += 1
        elif implementation:
            classes["system_implementation_missing"] += 1
        elif system:
            classes["jdl_evidence_missing"] += 1
            evidence_codes.update(b.split(":", 1)[1] for b in system)
        elif human:
            classes["human_confirmation_pending"] += 1
            human_codes.update(human)
        else:
            classes["no_blocker_left"] += 1
    return {
        "journals": len(entries),
        "classes": dict(classes),
        "jdl_evidence_missing_codes": dict(evidence_codes.most_common()),
        "human_pending_codes": dict(human_codes.most_common()),
        "unresolved_kinds": dict(unresolved_kinds),
    }


def technical_sizing(entries, context, *, with_campaign: bool) -> dict:
    """Technical (JDL Evidence / voucher row limit) status of every journal, whatever accounts the Human picks.

    Assumes the Human would confirm the natural tax candidate of every tax
    identity, and asks the production rules which target accounts would satisfy
    each taxed line. with_campaign=False reproduces the rules and candidates as
    they were before the 2026-11-05 Evidence (existing MF / ACT Evidence only).

    free        every taxed line is covered on any account
    restricted  covered only if the Human picks one of the accounts that round-tripped
    missing     some structure, tax cell or amount relation has no Evidence
    """
    from decimal import Decimal

    from accounting_converter.adapters.output.jdl.row_evidence import jdl_row_description_rows
    from accounting_converter.adapters.output.jdl.scoped_evidence import SEMANTIC_CELL
    from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
    from accounting_converter.application import scoped_evidence_composition as composition
    from accounting_converter.application.yayoi_jdl_workflow import structural_evidence_gaps
    from accounting_converter.tools import yayoi_evidence_campaign as legacy

    universe = sorted({item.target_master_code for item in context.account_master})
    candidate = (lambda identity: __import__(
        "accounting_converter.application.yayoi_review", fromlist=["x"]).candidate_semantic(identity)
    ) if with_campaign else legacy.candidate_semantic

    def mf_gaps(side, semantic, account, amount, explicit):
        capability = ev.LINE_CAPABILITIES.get((side, semantic))
        if semantic == "JDL_NO_TAX":
            return [] if capability and capability.covers(account) else ["x"]
        if capability is None or not capability.covers(account):
            return ["x"]
        gap = ev.explicit_tax_gap(explicit, amount, semantic, context) if explicit is not None else None
        if gap is not None:
            return [gap]
        if (semantic == "JDL_SALES_10_EXTERNAL" and not ev._tax_rounding_is_unambiguous(amount)
                and account not in ev.SALES10_ROUNDING_VERIFIED_ACCOUNTS):
            return ["x"]
        return []

    classes: Counter = Counter()
    reasons: Counter = Counter()
    restricted: Counter = Counter()
    missing_layouts: Counter = Counter()
    for entry in entries:
        rows = journal_physical_rows(entry)
        limit = context.voucher_row_limit
        if limit is not None and rows is not None and len(rows) > limit:
            classes["voucher_row_limit_exceeded"] += 1
            continue
        semantics = {}
        unresolved = bool(entry.metadata.get("yayoi_closing"))
        for line in entry.lines:
            if line.tax_info and line.tax_info.category:
                semantic = candidate(line.tax_info.category)
                if semantic is None:
                    unresolved = True
                semantics[id(line)] = semantic.value if semantic else None
            else:
                semantics[id(line)] = "JDL_NO_TAX"
        if unresolved:
            classes["unresolved_representation"] += 1
            continue
        # --- structure (account-free), existing Evidence first
        debit = sum(line.side.value == "DEBIT" for line in entry.lines)
        taxed = tuple((l.side.value, semantics[id(l)]) for l in entry.lines if semantics[id(l)] != "JDL_NO_TAX")
        existing_gaps = ev.shape_tax_combination_gaps((debit, len(entry.lines) - debit), taxed)
        composable = all(semantics[id(l)] in ev.COMPOSABLE_TAX_IDENTITIES for l in entry.lines)
        multi = rows is not None and len(rows) > 1
        existing_structure = (
            not existing_gaps and composable
            and (not multi or jdl_row_description_rows(entry) is not None or (debit, len(entry.lines) - debit) == (1, 1))
        )
        structure_ok = existing_structure
        structure_gaps = ()
        if not structure_ok and with_campaign:
            structure_gaps = composition.structural_gaps(entry, lambda l: semantics[id(l)], context) or ()
            structure_ok = structure_gaps == ()
        if not structure_ok:
            classes["jdl_evidence_missing"] += 1
            reasons["structure" + (":" + structure_gaps[0] if structure_gaps else "")] += 1
            from accounting_converter.adapters.output.jdl.scoped_evidence import layout_of

            missing_layouts[layout_of(rows) if rows else "?"] += 1
            continue
        # --- lines (which accounts satisfy them)
        status = "free"
        why = None
        for line in entry.lines:
            semantic = semantics[id(line)]
            explicit = line.tax_info.tax_amount if line.tax_info else None
            if semantic in {"JDL_PURCHASE_10_INTERNAL", "JDL_SALES_10_EXTERNAL"} and explicit is None:
                explicit = ev.ten_percent_tax_amount(line.amount)
            ok = []
            for account in universe:
                if with_campaign:
                    gaps_here, _ = composition.line_gaps(composition.ScopedLine(
                        line.side.value, account, SEMANTIC_CELL[semantic], line.amount, explicit))
                else:
                    gaps_here = mf_gaps(line.side.value, semantic, account, line.amount, explicit)
                if not gaps_here:
                    ok.append(account)
            if not ok:
                status, why = "missing", SEMANTIC_CELL.get(semantic, semantic) + ":" + line.side.value[0]
                break
            if len(ok) < len(universe):
                status = "restricted"
                restricted[SEMANTIC_CELL.get(semantic, semantic) + ":" + line.side.value[0]] += 1
        if status == "missing":
            classes["jdl_evidence_missing"] += 1
            reasons["line:" + why] += 1
        else:
            classes[f"technical_ok_account_{status}"] += 1
    return {
        "classes": dict(classes),
        "evidence_missing_reasons": dict(reasons.most_common()),
        "restricted_lines_by_cell": dict(restricted.most_common()),
        "evidence_missing_distinct_layouts": len(missing_layouts),
        "evidence_missing_layouts_top": dict(missing_layouts.most_common(12)),
    }


def _blockers_of(assessment) -> dict:
    return {key: set(value) for key, value in assessment.journal_blockers.items()}


def _fill_in(controller, company_id: str, source: Path, scenario: str) -> dict:
    """Production save paths, in the scratch copy: accounts, subaccounts, taxes."""
    controller.load_company_settings()
    controller.select_file(source)
    controller.select_company_setting(company_id)
    done = Counter()
    review = controller.review_company_mapping_updates(company_id, source)
    accounts = {}
    for item in review.items:
        if item.mapping_type != "ACCOUNT" or item.already_confirmed:
            continue
        target = item.exact_candidate
        if target is None and scenario == "best":
            target = next((c.name for c in getattr(item, "candidates", ()) if c.name in item.available_targets), None)
        if target is not None and target in item.available_targets:
            accounts[item.key] = target
    if accounts:
        controller.apply_company_mapping_updates(review, accounts, set(accounts), {}, set())
    done["accounts"] = len(accounts)
    review = controller.review_company_mapping_updates(company_id, source)
    subaccounts = {}
    for item in review.items:
        if item.mapping_type == "ACCOUNT" or item.already_confirmed:
            continue
        parent = item.confirmed_parent_target
        if not parent:
            continue
        options = list(item.subaccount_targets_for(parent))
        target = item.source_value if item.source_value in options else None
        if target is None and scenario == "best":
            ranked = item.ranked_subaccount_targets_for(parent)
            target = ranked[0].target_name if ranked else None
        if target is not None:
            subaccounts[item.key] = target
    if subaccounts:
        controller.apply_company_mapping_updates(review, subaccounts, set(subaccounts), {}, set())
    done["subaccounts"] = len(subaccounts)
    review = controller.review_company_mapping_updates(company_id, source)
    state = controller.ensure_selected_tax_requirements(review)
    if state.developer_error is None:
        tax = controller.company_tax_mapping_review(
            company_id, affected_counts=dict(review.tax_category_counts),
            observed_source_values=review.observed_tax_categories or review.tax_categories)
        values = tuple(item.source_value for item in tax.confirmable_items)
        if values:
            controller.confirm_company_tax_mappings(company_id, values)
        done["tax_identities"] = len(values)
    return dict(done)


def diagnose(source: Path, company_store: Path, company_id: str, *, set_row_limit: int | None, scenarios) -> dict:
    entries = detect_format(source).diagnose(source).entries

    def assess(store: Path):
        profiles = ConversionProfileStore(store / "profiles")
        companies = CompanySettingStore(store / "companies", profiles)
        resolved = companies.resolve(company_id)
        return YayoiJournalReportJdlWorkflow().assess(source, resolved.profile, resolved.context), resolved.context

    real, context = assess(company_store)
    result = {
        "journals": len(entries),
        "physical_rows": sum(len(journal_physical_rows(e) or ()) for e in entries),
        "actual_saved_setting": {
            "voucher_row_limit": context.voucher_row_limit if context else None,
            "ready": real.ready_journals,
            "by_owner": real.owner_counts(),
            "by_blocker": dict(sorted(real.blocker_counts().items(), key=lambda item: -item[1])),
            "likely_after_tax_confirmation": dict(sorted(real.likely_blocker_counts().items(), key=lambda item: -item[1])),
        },
        "what_if": {},
    }
    if set_row_limit is not None:
        from dataclasses import replace

        sized = replace(context, voucher_row_limit=set_row_limit)
        result["technical_sizing_before_2026_11_05"] = technical_sizing(entries, replace(sized, voucher_row_limit=None), with_campaign=False)
        result["technical_sizing_now"] = technical_sizing(entries, sized, with_campaign=True)
    for scenario in scenarios:
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory) / "store"
            shutil.copytree(company_store, scratch)
            profiles = ConversionProfileStore(scratch / "profiles")
            companies = CompanySettingStore(scratch / "companies", profiles)
            if set_row_limit is not None:
                CompanyVoucherRowLimitService(companies, profiles).set(company_id, set_row_limit, confirmed=True)
            controller = AccountingConverterController(
                profile_store=profiles, company_store=companies,
                preferences_store=ApplicationPreferencesStore(Path(directory) / "prefs.json"))
            filled = _fill_in(controller, company_id, source, scenario)
            assessment, scratch_context = assess(scratch)
            limit = scratch_context.voucher_row_limit if scratch_context else None
            result["what_if"][scenario] = {
                "simulated_decisions": filled,
                "voucher_row_limit_used": limit,
                "assessment_ready_journals": assessment.ready_journals,
                **_classify(entries, _blockers_of(assessment), limit),
            }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--company-store", type=Path, required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--set-row-limit", type=int, default=None,
                        help="enter this 振替伝票入力行数 in the scratch copy only")
    parser.add_argument("--scenario", action="append", choices=("exact", "best"))
    args = parser.parse_args()
    print(json.dumps(diagnose(args.source, args.company_store, args.company_id,
                              set_row_limit=args.set_row_limit, scenarios=args.scenario or ["exact"]),
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
