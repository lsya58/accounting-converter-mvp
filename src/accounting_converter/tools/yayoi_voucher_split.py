"""Over-limit Yayoi journals and the Human-approved voucher split (application/voucher_split).

  status   --source --company-store --company-id
           every journal over the company's 振替伝票入力行数: whether the rule applies (or why not), the parts it
           would write, their JDL layouts and whether each part is covered by registered Evidence. Read-only; the
           approval is NOT assumed (parts are judged as they would be after it).
  approve  --company-store --company-id --human-approver --tax-accountant --signoff-reference --signoff-date
           records, for this company and its current row limit, that the tax accountant accepted the rule.
           Run it yourself on purpose, on the store you mean; nothing approves it automatically.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from accounting_converter.application import voucher_split as vs
from accounting_converter.application.yayoi_sources import detect_format
from accounting_converter.domain.journal_rows import journal_physical_rows
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore


def status(source: Path, company_store: Path, company_id: str) -> dict:
    from accounting_converter.adapters.output.jdl import scoped_evidence as scoped
    from accounting_converter.tools.generate_yayoi_split_probes import signature
    from accounting_converter.tools.yayoi_gap_probe_plan import conditions

    profiles = ConversionProfileStore(company_store / "profiles")
    resolved = CompanySettingStore(company_store / "companies", profiles).resolve(company_id)
    limit = resolved.context.voucher_row_limit if resolved.context else None
    entries = detect_format(source).diagnose(source).entries
    journals = []
    for entry in entries:
        rows = journal_physical_rows(entry)
        if limit is None or rows is None or len(rows) <= limit:
            continue
        reason = vs.ineligible_reason(entry, limit)
        item = {"journal": entry.id, "date": entry.date.isoformat(), "rows": len(rows),
                "layout": scoped.layout_of(rows), "split": reason is None, "why_not": reason}
        if reason is None:
            plan = vs.plan_split(entry, limit)
            if not vs.counterpart_mapped_to_no_tax(entry, plan, resolved.profile, resolved.context):
                item.update(split=False, why_not="COUNTERPART_NOT_CONFIRMED_AS_JDL_NO_TAX")
            else:
                parts = []
                for part in vs.split_entry(entry, plan):
                    record = signature(part)
                    needs = sorted("/".join(map(str, c)) for c in conditions(*record, ())) if record else ["UNRESOLVED_TAX"]
                    parts.append({"layout": scoped.layout_of(journal_physical_rows(part)), "missing_evidence": needs})
                item["parts"] = parts
        journals.append(item)
    return {
        "voucher_row_limit": limit,
        "approval_problems": list(vs.policy_problems(resolved.profile, resolved.context)),
        "over_limit": len(journals),
        "split_rule_applies": sum(1 for j in journals if j["split"]),
        "parts_all_covered": sum(1 for j in journals if j["split"] and not any(p["missing_evidence"] for p in j["parts"])),
        "journals": journals,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("status")
    s.add_argument("--source", type=Path, required=True)
    s.add_argument("--company-store", type=Path, required=True)
    s.add_argument("--company-id", required=True)
    a = sub.add_parser("approve")
    a.add_argument("--company-store", type=Path, required=True)
    a.add_argument("--company-id", required=True)
    a.add_argument("--human-approver", required=True)
    a.add_argument("--tax-accountant", required=True)
    a.add_argument("--signoff-reference", required=True)
    a.add_argument("--signoff-date", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps(status(args.source, args.company_store, args.company_id), ensure_ascii=False, indent=1))
        return 0
    profiles = ConversionProfileStore(args.company_store / "profiles")
    companies = CompanySettingStore(args.company_store / "companies", profiles)
    resolved = companies.resolve(args.company_id)
    vs.approve_split_policy(profiles, resolved.profile.profile_id, args.company_id, resolved.context,
                            human_approver=args.human_approver, tax_accountant=args.tax_accountant,
                            signoff_reference=args.signoff_reference, signoff_date=date.fromisoformat(args.signoff_date))
    companies.refresh_profile_fingerprint(args.company_id)
    print(json.dumps({"approved": vs.RULE, "approval_problems": list(vs.policy_problems(
        companies.resolve(args.company_id).profile, companies.resolve(args.company_id).context))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
