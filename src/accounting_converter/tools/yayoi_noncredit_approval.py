"""Yayoi 控除不可 → JDL 非仕入: show the state, or record the tax accountant's sign-off for one company.

  status   --company-store --company-id [--source]
           Evidence state, whether this company / JDL setting is covered, the saved approval per identity,
           the source lines involved and what JDL will not hold. Read-only.
  approve  --company-store --company-id --identity --source --journal ID [--journal ID ...] --judge-report
           --human-approver --tax-accountant --signoff-reference --signoff-date --acknowledge-rate-loss
           Writes the sign-off for the NAMED JOURNALS ONLY (by their content identity in --source; the ID is the
           journal number shown on screen, e.g. 565). Other journals with the same Yayoi tax identity stay blocked,
           and a later change to a named journal's content invalidates it for that journal. Refused unless the judge report (made from the
           readings sheet whose SIGNOFF row the tax accountant marked 済) says EQUIVALENCE_CONFIRMED for the
           probe case of the same rate, and every technical condition holds. Run it yourself on purpose; it is
           never run automatically and never against a store you have not chosen.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

from accounting_converter.application import noncredit_approval as nc
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore


def _stores(root: Path):
    profiles = ConversionProfileStore(root / "profiles")
    return profiles, CompanySettingStore(root / "companies", profiles)


def status(company_store: Path, company_id: str, source: Path | None = None) -> dict:
    _, companies = _stores(company_store)
    resolved = companies.resolve(company_id)
    profile, context = resolved.profile, resolved.context
    evidence = nc.TECHNICAL_EVIDENCE
    out = {
        "evidence_id": evidence.evidence_id,
        "technical_state": evidence.technical_state,
        "evidence_note": evidence.note,
        "what_jdl_receives": {"課区": nc.JDL_SCOPE, "課区コード": nc.JDL_SCOPE_CODE, "税区": "", "税入力方法": "", "消費税": ""},
        "lost_in_jdl": nc.LOSS_TEXT,
        "identities": {},
    }
    for identity in nc.NONCREDIT_SOURCES:
        mapping = profile.tax_mappings.get(identity) if profile is not None else None
        problems = nc.mapping_problems(identity, mapping, profile, context)
        out.setdefault("approval_scope", "journals named in the sign-off only (content identity), never the identity as such")
        out.setdefault("approved_journals", {})[identity] = [
            {k: r.get(k) for k in ("label", "date", "journal_content_sha256", "tax_accountant", "signoff_reference", "signoff_date")}
            for r in nc.approved_journals(mapping).values()] if not problems else []
        out["identities"][identity] = {
            "technical_problems": list(nc.technical_problems(identity, company_id, context)),
            "approval_problems": list(problems),
            "converted": not problems,
            "signoff_reference": (mapping.metadata or {}).get("noncredit_signoff_reference") if mapping else None,
        }
    if source is not None:
        from accounting_converter.application.yayoi_sources import detect_format

        lines = []
        for entry in detect_format(source).diagnose(source).entries:
            for line in entry.lines:
                category = line.tax_info.category if line.tax_info else None
                if category and category.rsplit("｜", 1)[-1] == "控除不可":
                    covered = nc.journal_approval(entry, profile, context).get(category)
                    lines.append({"journal": entry.id, "date": entry.date.isoformat(), "identity": category,
                                  "approved_for_this_journal": covered is not None,
                                  "side": line.side.value, "amount": str(line.amount),
                                  "tax": str(line.tax_info.tax_amount), "shape_problems": list(nc.line_problems(line)),
                                  "journal_lines": len(entry.lines)})
        out["source_lines"] = lines
        out["source_journals"] = len({line["journal"] for line in lines})
    return out


def approve(args) -> dict:
    report_bytes = args.judge_report.read_bytes()
    report = json.loads(report_bytes.decode("utf-8"))
    case = nc.TECHNICAL_EVIDENCE.probe_cases.get(args.identity)
    if case is None:
        raise SystemExit(f"not one of the verified identities: {args.identity}")
    found = (report.get("cases") or {}).get(case, {}).get("result")
    if found != "EQUIVALENCE_CONFIRMED":
        raise SystemExit(f"judge report: {case} is {found}, not EQUIVALENCE_CONFIRMED (the tax accountant's 済 is required)")
    if not args.acknowledge_rate_loss:
        raise SystemExit("--acknowledge-rate-loss is required: " + nc.LOSS_TEXT)
    profiles, companies = _stores(args.company_store)
    resolved = companies.resolve(args.company_id)
    from accounting_converter.application.yayoi_sources import detect_format

    entries = detect_format(args.source).diagnose(args.source).entries
    by_label = {}
    for entry in entries:
        by_label.setdefault(entry.id.rsplit(":", 1)[-1], []).append(entry)
    wanted = list(dict.fromkeys(args.journal))
    missing = [j for j in wanted if len(by_label.get(j, ())) != 1]
    if missing:
        raise SystemExit(f"journal not found exactly once in --source: {', '.join(missing)}")
    journals = [by_label[j][0] for j in wanted]
    from accounting_converter.application import approval_ledger

    approval_ledger.approve_noncredit_direct(
        profiles, companies, args.company_id, resolved.profile.profile_id, resolved.context, args.identity,
        human_approver=args.human_approver, tax_accountant=args.tax_accountant,
        signoff_reference=args.signoff_reference, signoff_date=date.fromisoformat(args.signoff_date),
        rate_distinction_loss_acknowledged=True,
        judge_report_sha256=hashlib.sha256(report_bytes).hexdigest(),
        journals=journals, source_entries=entries, labels={entry.id: entry.id.rsplit(":", 1)[-1] for entry in journals},
    )
    return status(args.company_store, args.company_id, args.source)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("status")
    s.add_argument("--company-store", type=Path, required=True)
    s.add_argument("--company-id", required=True)
    s.add_argument("--source", type=Path)
    a = sub.add_parser("approve")
    a.add_argument("--company-store", type=Path, required=True)
    a.add_argument("--company-id", required=True)
    a.add_argument("--identity", required=True, choices=tuple(nc.NONCREDIT_SOURCES))
    a.add_argument("--source", type=Path, required=True, help="the Yayoi file the journals are read from")
    a.add_argument("--journal", action="append", required=True,
                   help="journal number as shown on screen (repeat for several); each is approved individually")
    a.add_argument("--judge-report", type=Path, required=True)
    a.add_argument("--human-approver", required=True)
    a.add_argument("--tax-accountant", required=True)
    a.add_argument("--signoff-reference", required=True, help="where the tax accountant's decision is recorded")
    a.add_argument("--signoff-date", required=True, help="YYYY-MM-DD")
    a.add_argument("--acknowledge-rate-loss", action="store_true")
    args = parser.parse_args()
    result = status(args.company_store, args.company_id, args.source) if args.command == "status" else approve(args)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
