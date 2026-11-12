"""D0: the tax accountant's decisions for one Yayoi company (application/approval_ledger). Customer data: data/private.

  items    --source --company-store --company-id [--trailing-space-record R] [--catalog C]
           what is waiting, with targets, change, Evidence, scope and the ledger state. Read-only.
  preview  ... --item ID [--item ID ...] [--scope-json '{...}' (one item only)]
           READY/BLOCK now and after, journal by journal, from the production diagnosis on an in-memory copy.
           Read-only. Prints the preview fingerprint that `apply` needs.
  record   ... --ledger L --item ID --decision APPROVED|REJECTED|ON_HOLD|REVOKED --tax-accountant --recorded-by
           --decided-on YYYY-MM-DD --reference [--scope-json] [--comment] --explicitly-confirmed
           appends the decision to the ledger. Does NOT change the company setting.
  apply    ... --ledger L --item ID --preview-fingerprint F --backup-dir B --applied-by [--judge-report J]
           [--production-store]  writes the approved decision through the existing approval function
           (voucher split / 控除不可) after every check; backup first, restored if the result differs from the preview.
  revoke   ... --ledger L --item ID --backup-dir B --revoked-by --reference [--production-store]
           removes an applied approval (after a REVOKED decision is recorded).
  audit    --company-store --company-id --source [--ledger L]
           the ledger's integrity and any approval in the company setting that no ledger entry explains. Read-only.

--ledger defaults to <company-store>/approval_ledger/<company-id>.jsonl, the file the screen and the two older CLIs
(yayoi_voucher_split / yayoi_noncredit_approval) also write to. The ledger is a tamper-evident log, not an electronic
signature (see application/approval_ledger.py).

Nothing is ever recorded or applied without these explicit commands. The Windows AppData store is refused unless
--production-store is given.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from accounting_converter.application import approval_ledger as al
from accounting_converter.application.yayoi_sources import detect_format
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore


def _context(args):
    resolved = CompanySettingStore(args.company_store / "companies",
                                   ConversionProfileStore(args.company_store / "profiles")).resolve(args.company_id)
    if not resolved.available:
        raise SystemExit("company setting not available: " + str(args.company_id))
    entries = detect_format(args.source).diagnose(args.source).entries
    catalog = json.loads(args.catalog.read_text(encoding="utf-8")) if getattr(args, "catalog", None) else {}
    if catalog and catalog.get("company_id") != args.company_id:
        raise SystemExit("the catalog is for another company")
    items = al.pending_items(entries, resolved.profile, resolved.context, args.company_id,
                             trailing_space_record=getattr(args, "trailing_space_record", None),
                             policies=tuple(catalog.get("policies") or ()))
    return resolved, {item.item_id: item for item in items}


def _ledger(args):
    path = getattr(args, "ledger", None) or al.default_ledger_path(args.company_store, args.company_id)
    return al.ApprovalLedger(path, args.company_id)


def _scope(args):
    return json.loads(args.scope_json) if getattr(args, "scope_json", None) else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    commands = {name: sub.add_parser(name) for name in ("items", "preview", "record", "apply", "revoke", "audit")}
    for name, p in commands.items():
        p.add_argument("--source", type=Path, required=True)
        p.add_argument("--company-store", type=Path, required=True)
        p.add_argument("--company-id", required=True)
        p.add_argument("--trailing-space-record", type=Path)
        p.add_argument("--catalog", type=Path, help="private catalog of operating policies (JSON)")
        p.add_argument("--ledger", type=Path)
        if name not in ("items", "audit"):
            p.add_argument("--item", action="append", required=True)
        if name in ("preview", "record"):
            p.add_argument("--scope-json")
    r = commands["record"]
    r.add_argument("--decision", required=True, choices=al.DECISIONS)
    for flag in ("--tax-accountant", "--recorded-by", "--reference"):
        r.add_argument(flag, required=True)
    r.add_argument("--decided-on", required=True, type=date.fromisoformat)
    r.add_argument("--comment", default="")
    r.add_argument("--explicitly-confirmed", action="store_true")
    a = commands["apply"]
    a.add_argument("--preview-fingerprint", required=True)
    a.add_argument("--backup-dir", type=Path, required=True)
    a.add_argument("--applied-by", required=True)
    a.add_argument("--judge-report", type=Path)
    a.add_argument("--production-store", action="store_true")
    v = commands["revoke"]
    v.add_argument("--backup-dir", type=Path, required=True)
    v.add_argument("--revoked-by", required=True)
    v.add_argument("--reference", required=True)
    v.add_argument("--production-store", action="store_true")
    args = parser.parse_args()

    resolved, items = _context(args)
    ledger = _ledger(args)
    if args.command == "audit":
        mismatch = al.identity_problems(None, args.company_id, resolved.profile.profile_id, resolved.context,
                                        resolved.setting)
        if mismatch:
            raise SystemExit("company identity mismatch: " + " / ".join(mismatch))
        entries = ledger.entries()  # raises on a tampered / foreign ledger
        print(json.dumps({"ledger": str(ledger.path), "entries": len(entries),
                          "types": sorted({e["type"] for e in entries}),
                          "unrecorded_approvals": al.unrecorded_approvals(resolved.profile, ledger)},
                         ensure_ascii=False, indent=1))
        return 1 if al.unrecorded_approvals(resolved.profile, ledger) else 0
    if args.command == "items":
        out = [{**item.record(), "ledger_state": ledger.status(item.item_id)} for item in items.values()]
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    if args.command == "revoke":  # an applied item is no longer pending: the ledger names it
        if len(args.item) != 1:
            raise SystemExit("one --item at a time")
        entry = al.revoke_applied(ledger, args.item[0], store_root=args.company_store, company_id=args.company_id,
                                  source=args.source, backup_dir=args.backup_dir, revoked_by=args.revoked_by,
                                  reference=args.reference, allow_production_store=args.production_store)
        print(json.dumps(entry, ensure_ascii=False, indent=1))
        return 0
    if args.command == "record" and args.decision == al.REVOKED and len(args.item) == 1 and args.item[0] not in items:
        recorded = ledger.recorded_item(args.item[0])  # applied: no longer pending, decided as recorded
        if recorded is not None:
            items[recorded.item_id] = recorded
    missing = [i for i in args.item if i not in items]
    if missing:
        raise SystemExit("not a pending item: " + ", ".join(missing))
    if args.command == "preview":
        scope = _scope(args)
        if scope is not None and len(args.item) != 1:
            raise SystemExit("--scope-json applies to one --item only")
        result = al.preview(args.source, resolved.profile, resolved.context, args.company_id,
                            [(items[i], scope) for i in args.item])
        print(json.dumps(result.summary(), ensure_ascii=False, indent=1))
        return 1 if result.problems else 0
    if len(args.item) != 1:
        raise SystemExit("one --item at a time")
    item = items[args.item[0]]
    if args.command == "record":
        entry = ledger.record_decision(
            item, args.decision, tax_accountant=args.tax_accountant, recorded_by=args.recorded_by,
            decided_on=args.decided_on, reference=args.reference, scope=_scope(args) or item.default_scope,
            bindings=al.bindings_for(args.source, resolved.context, args.company_id, resolved.profile.profile_id), comment=args.comment,
            explicitly_confirmed=args.explicitly_confirmed)
        print(json.dumps({"recorded": entry["seq"], "decision": entry["decision"], "item": item.item_id}, ensure_ascii=False))
        return 0
    entry = al.apply_decision(ledger, item.item_id, store_root=args.company_store, company_id=args.company_id,
                              source=args.source, expected_preview_fingerprint=args.preview_fingerprint,
                              backup_dir=args.backup_dir, applied_by=args.applied_by, judge_report=args.judge_report,
                              allow_production_store=args.production_store)
    print(json.dumps(entry, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
