from __future__ import annotations

import argparse
import json
from pathlib import Path

from accounting_converter.adapters.input.moneyforward import MoneyForwardInputAdapter
from accounting_converter.application.mapping_review import MappingRequirementExtractor
from accounting_converter.application.moneyforward_jdl_loss import MoneyForwardToJdlLossRule
from accounting_converter.domain.mapping import MappingStatus
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore, default_company_store_dir
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore, default_profile_store_dir
from accounting_converter.profiles.known_formats import moneyforward_cloud_journal_export_observed_schema


def main() -> int:
    parser = argparse.ArgumentParser(description="Privacy-safe CompanySetting dry-run diagnostics")
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--profile-store", type=Path, default=default_profile_store_dir())
    parser.add_argument("--company-store", type=Path, default=default_company_store_dir())
    args = parser.parse_args()
    profiles = ConversionProfileStore(args.profile_store)
    companies = CompanySettingStore(args.company_store, profiles)
    setting = companies.get(args.company_id)
    profile = profiles.get(setting.conversion_profile_id)
    schema = moneyforward_cloud_journal_export_observed_schema()
    source_profile = FormatProfile("Money Forward", "Money Forward クラウド会計", "UNKNOWN", schema.identity.stable_key, "cp932")
    entries = tuple(MoneyForwardInputAdapter().read(args.input, source_profile))
    requirements = MappingRequirementExtractor().extract(entries, profile)
    unresolved_accounts = {item.source_value for item in requirements.accounts if item.requires_confirmation}
    unresolved_subs = {item.key for item in requirements.subaccounts if item.requires_confirmation}
    unresolved_tax = {item.source_value for item in requirements.tax_categories if item.requires_confirmation}
    counts = {"account": 0, "subaccount": 0, "tax": 0, "trade_partner": 0, "multiple_description": 0, "ready": 0}
    loss_rule = MoneyForwardToJdlLossRule()
    for entry in entries:
        account = any(line.account in unresolved_accounts for line in entry.lines)
        subaccount = any(
            line.sub_account
            and next((item.key for item in requirements.subaccounts if item.source_value == line.sub_account and item.parent_account == line.account), None) in unresolved_subs
            for line in entry.lines
        )
        tax = any(line.tax_info and line.tax_info.category in unresolved_tax for line in entry.lines)
        loss_fields = {item.field for item in loss_rule.validate(entry)}
        trade = "trade_partner" in loss_fields
        description = "description" in loss_fields
        counts["account"] += account
        counts["subaccount"] += subaccount
        counts["tax"] += tax
        counts["trade_partner"] += trade
        counts["multiple_description"] += description
        counts["ready"] += not any((account, subaccount, tax, trade, description, bool(loss_fields - {"trade_partner", "description"})))
    resolved = companies.resolve(args.company_id)
    payload = {
        "logical_journals": len(entries),
        "account_requirements": len(requirements.accounts),
        "account_unresolved": len(unresolved_accounts),
        "account_blocker_journals": counts["account"],
        "subaccount_requirements": len(requirements.subaccounts),
        "subaccount_unresolved": len(unresolved_subs),
        "subaccount_blocker_journals": counts["subaccount"],
        "tax_requirements": len(requirements.tax_categories),
        "tax_unresolved": len(unresolved_tax),
        "tax_blocker_journals": counts["tax"],
        "trade_partner_blocker_journals": counts["trade_partner"],
        "multiple_description_blocker_journals": counts["multiple_description"],
        "immediately_ready_journals": counts["ready"],
        "formal_conversion_possible": resolved.available and counts["ready"] == len(entries),
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
