"""Privacy-safe staged readiness of one MF CSV against a saved CompanySetting.

Internal diagnostic. Every journal gets the full set of blockers that keep it
from formal output, each with an owner. Stages then show how many journals
become READY after each next action, without changing any saved setting:

  persisted -> Human tax mappings -> Human まとめ先補助 -> pending Evidence batch
            -> Human description replacements

Optionally (--formal-check DIR) the journals READY after the Human tax step
are converted with the real workflow, using a temporary copy of the store in
which the Evidence-backed tax candidates are confirmed.
"""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections import Counter
from pathlib import Path

from accounting_converter.adapters.input.moneyforward import MoneyForwardInputAdapter
from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
from accounting_converter.application.mapping_engine import MappingEngine
from accounting_converter.application.mapping_review import MappingRequirementExtractor
from accounting_converter.application.moneyforward_conversion_workflow import MoneyForwardConversionWorkflow
from accounting_converter.application.moneyforward_description_replacement import MoneyForwardDescriptionReplacementPolicy
from accounting_converter.application.moneyforward_jdl_loss import MoneyForwardToJdlLossRule
from accounting_converter.application.moneyforward_profile_setup import MoneyForwardProfileSetupService
from accounting_converter.application.moneyforward_trade_partner import MoneyForwardTradePartnerDescriptionPolicy
from accounting_converter.application.profile_preflight import mapping_rule_set_from_profile
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.profiles.known_formats import moneyforward_cloud_journal_export_observed_schema

IDENTITY_NOISE = {
    "ACCOUNT_CODE_MISMATCH", "SUBACCOUNT_CODE_MISMATCH", "TAX_CATEGORY_MISMATCH",
    "SHAPE_MISMATCH", "EVIDENCE_SCOPE_CHANGED_BY_MASTER",
}
COMPOSITION_GAPS = {
    "SHAPE_UNVERIFIED_IN_TAX_CONTEXT", "TAX_ACCOUNT_UNVERIFIED", "TAX_SIDE_UNVERIFIED",
    "TAX_AMOUNT_ROUNDING_UNVERIFIED", "MULTIPLE_TAXED_LINES_UNVERIFIED",
    "SHAPE_TAX_COMBINATION_UNVERIFIED", "TRADE_PARTNER_SHAPE_UNVERIFIED",
    "TAX_IDENTITY_NOT_COMPOSABLE",
}
# Gaps the pending final Evidence batch is designed to close.
PENDING_BATCH_GAPS = {
    "SHAPE_UNVERIFIED_IN_TAX_CONTEXT", "TAX_AMOUNT_ROUNDING_UNVERIFIED",
    "TAX_ACCOUNT_UNVERIFIED", "MULTIPLE_TAXED_LINES_UNVERIFIED",
}
STAGES = (
    ("persisted", set()),
    ("after_human_tax", {"HUMAN:TAX_MAPPING"}),
    ("after_human_subaccount", {"HUMAN:TAX_MAPPING", "HUMAN:SUBACCOUNT_DEFAULT"}),
    ("after_evidence_batch", {"HUMAN:TAX_MAPPING", "HUMAN:SUBACCOUNT_DEFAULT", "SYSTEM_EVIDENCE:*"}),
    ("after_description_review", {"HUMAN:TAX_MAPPING", "HUMAN:SUBACCOUNT_DEFAULT", "SYSTEM_EVIDENCE:*", "HUMAN:DESCRIPTION"}),
)


def _input_profile() -> FormatProfile:
    schema = moneyforward_cloud_journal_export_observed_schema()
    return FormatProfile("Money Forward", "Money Forward クラウド会計", "UNKNOWN", schema.identity.stable_key, "cp932")


def journal_blockers(source: Path, profile, context) -> list[tuple[object, frozenset[str]]]:
    raw = tuple(MoneyForwardInputAdapter().read(source, _input_profile()))
    partner = MoneyForwardTradePartnerDescriptionPolicy(profile, context).apply(raw)
    description = MoneyForwardDescriptionReplacementPolicy(profile).apply(partner.entries)
    entries = description.entries
    partner_errors = {item.journal_id for item in partner.validation_results}
    description_errors = {item.journal_id for item in description.validation_results}
    requirements = MappingRequirementExtractor().extract(entries, profile)
    unresolved_accounts = {item.source_value for item in requirements.accounts if item.requires_confirmation}
    unresolved_subaccounts = {
        (item.parent_account, item.source_value) for item in requirements.subaccounts if item.requires_confirmation
    }
    mapped = MappingEngine(mapping_rule_set_from_profile(profile)).apply(entries).entries
    loss = MoneyForwardToJdlLossRule()
    result = []
    for entry, mapped_entry in zip(entries, mapped, strict=True):
        blockers: set[str] = set()
        if entry.id in partner_errors:
            blockers.add("HUMAN:TRADE_PARTNER_POLICY")
        if entry.id in description_errors:
            blockers.add("HUMAN:DESCRIPTION")
        for line in entry.lines:
            if line.account in unresolved_accounts:
                blockers.add("HUMAN:ACCOUNT_MAPPING")
            if line.sub_account and (line.account, line.sub_account) in unresolved_subaccounts:
                blockers.add("HUMAN:SUBACCOUNT_MAPPING")
            category = line.tax_info.category if line.tax_info else None
            if category and ev.confirmed_mapping_mismatch_fields(category, profile.tax_mappings.get(category), context):
                blockers.add("HUMAN:TAX_MAPPING")
        for item in loss.validate(entry):
            if item.field == "description_character":
                blockers.add("HUMAN:DESCRIPTION")
            elif item.field == "trade_partner":
                blockers.add("HUMAN:TRADE_PARTNER_POLICY")
            else:
                blockers.add(f"SYSTEM_IMPLEMENTATION:OPTIONAL_{item.field.upper()}")
        match = ev.match_evidence_for_occurrence(entry, mapped_entry, context, profile)
        if match.evidence is None:
            gaps = set(match.mismatch_fields) - IDENTITY_NOISE
            if "SUBACCOUNT_REQUIRED_BY_MASTER" in gaps:
                blockers.add("HUMAN:SUBACCOUNT_DEFAULT")
            if "TAX_MAPPING_UNCONFIRMED" in gaps:
                blockers.add("HUMAN:TAX_MAPPING")
            for gap in gaps & COMPOSITION_GAPS:
                blockers.add(f"SYSTEM_EVIDENCE:{gap}")
            unexplained = gaps - COMPOSITION_GAPS - {"SUBACCOUNT_REQUIRED_BY_MASTER", "TAX_MAPPING_UNCONFIRMED"}
            if unexplained or not gaps:
                blockers.add("SYSTEM_IMPLEMENTATION:" + ",".join(sorted(unexplained or match.mismatch_fields) or ["UNMATCHED"]))
        result.append((entry, frozenset(blockers)))
    return result


def _resolved(blocker: str, resolved: set[str]) -> bool:
    if blocker in resolved:
        return True
    if "SYSTEM_EVIDENCE:*" in resolved and blocker.startswith("SYSTEM_EVIDENCE:"):
        return blocker.split(":", 1)[1] in PENDING_BATCH_GAPS
    return False


def summarize(rows) -> dict[str, object]:
    def rows_of(entry) -> int:
        return len(entry.metadata.get("physical_row_numbers", ()))

    stages = {}
    for name, resolved in STAGES:
        ready = [entry for entry, blockers in rows if all(_resolved(b, resolved) for b in blockers)]
        stages[name] = {"ready_journals": len(ready), "ready_physical_rows": sum(rows_of(e) for e in ready)}
    owners = Counter()
    blocker_counts = Counter()
    for _entry, blockers in rows:
        for blocker in blockers:
            blocker_counts[blocker] += 1
        kinds = {blocker.split(":", 1)[0] for blocker in blockers}
        owners["READY" if not kinds else "+".join(sorted(kinds))] += 1
    return {
        "logical_journals": len(rows),
        "physical_rows": sum(rows_of(entry) for entry, _ in rows),
        "journals_by_owner_combination": dict(sorted(owners.items())),
        "journals_by_blocker": dict(sorted(blocker_counts.items())),
        "stages": stages,
    }


def formal_check(source: Path, store: Path, company_id: str, rows, output_dir: Path) -> dict[str, object]:
    """Convert the after_human_tax READY subset with tax candidates confirmed in a temp copy."""
    with tempfile.TemporaryDirectory() as directory:
        copy = Path(directory) / "store"
        shutil.copytree(store, copy)
        profiles = ConversionProfileStore(copy / "profiles")
        companies = CompanySettingStore(copy / "companies", profiles)
        resolved = companies.resolve(company_id)
        service = MoneyForwardProfileSetupService(profiles)
        profile = resolved.profile
        review = service.tax_mapping_review(profile, resolved.context)
        for item in review.confirmable_items:
            profile = service.confirm_evidence_backed_tax_mapping(
                profile_id=profile.profile_id, context=resolved.context, source_value=item.source_value
            )
            companies.replace_profile(company_id, profile.profile_id)
        resolved = companies.resolve(company_id)
        ready_rows = {
            number
            for entry, blockers in rows
            if all(_resolved(b, {"HUMAN:TAX_MAPPING"}) for b in blockers)
            for number in entry.metadata.get("physical_row_numbers", ())
        }
        subset = Path(directory) / source.name
        subset.write_bytes(_subset_csv(source, ready_rows))
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / "formal_after_human_tax.csv"
        if output.exists():
            raise FileExistsError(output)
        workflow = MoneyForwardConversionWorkflow()
        prepared = workflow.prepare(
            input_path=subset, output_path=output, profile=resolved.profile,
            context=resolved.context, company_setting_validated=resolved.available,
        )
        result = workflow.execute(prepared)
        return {
            "readiness": prepared.summary.readiness.value,
            "blocking_reasons": list(prepared.summary.blocking_reasons),
            "status": result.status.value if result else None,
            "journals": prepared.summary.simple_journal_count + prepared.summary.compound_journal_count,
            "output": str(output) if output.exists() else None,
        }


def _subset_csv(source: Path, keep_rows: set[int]) -> bytes:
    """Keep whole CSV records (descriptions may contain line breaks)."""
    text = source.read_bytes().decode("cp932")
    records, buffer = [], ""
    for line in text.splitlines(keepends=True):
        buffer += line
        if buffer.count('"') % 2 == 0:
            records.append(buffer)
            buffer = ""
    kept = [records[0]] + [record for number, record in enumerate(records[1:], start=2) if number in keep_rows]
    return "".join(kept).encode("cp932")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--company-store", type=Path, required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--formal-check", type=Path)
    args = parser.parse_args()
    profiles = ConversionProfileStore(args.company_store / "profiles")
    companies = CompanySettingStore(args.company_store / "companies", profiles)
    resolved = companies.resolve(args.company_id)
    rows = journal_blockers(args.source, resolved.profile, resolved.context)
    payload = summarize(rows)
    if args.formal_check:
        payload["formal_check"] = formal_check(args.source, args.company_store, args.company_id, rows, args.formal_check)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
