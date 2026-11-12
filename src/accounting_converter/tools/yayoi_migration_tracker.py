"""D2: track the journals a READY-only run left out (application/migration_tracker). Customer data: data/private.

  create   --source --output <READY-only CSV> --company-store --company-id --tracker T --created-by
           refused unless the READY-only run still verifies for this company; never overwrites T.
  check    --source --output --company-store --company-id --tracker T
           every source journal accounted for once; tracker bound to the run; no hand-edited status.
  final    ... --tracker T [--reexport R [--acceptance A]] [--trial-balance-json '{...}']
           the overall verdict (MIGRATION_INCOMPLETE unless every part is proven). Read-only.
  set      --tracker T --row N --status S --by NAME [--note] [--jdl-entry-json] [--reconciliation-json --reexport R]
           [--not-required-json]   one state change, with what that state needs.
  update   --tracker T --row N --by NAME [--plan] [--owner] [--memo] [--evidence-id ...]
  export   --tracker T --csv OUT   the management sheet for people (UTF-8 BOM, never overwrites).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from accounting_converter.application import migration_tracker as mt
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore


def _private(path: Path) -> None:
    if "data/private" not in Path(path).resolve().as_posix():
        raise SystemExit("customer data: write under data/private only")


def _resolved(args):
    return CompanySettingStore(args.company_store / "companies",
                               ConversionProfileStore(args.company_store / "profiles")).resolve(args.company_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = {name: sub.add_parser(name) for name in ("create", "check", "final", "set", "update", "export")}
    for name in ("create", "check", "final"):
        p[name].add_argument("--source", type=Path, required=True)
        p[name].add_argument("--output", type=Path, required=True)
        p[name].add_argument("--company-store", type=Path, required=True)
        p[name].add_argument("--company-id", required=True)
    for parser_ in p.values():
        parser_.add_argument("--tracker", type=Path, required=True)
    p["create"].add_argument("--created-by", required=True)
    p["final"].add_argument("--reexport", type=Path)
    p["final"].add_argument("--acceptance", type=Path)
    p["final"].add_argument("--trial-balance-json")
    for name in ("set", "update"):
        p[name].add_argument("--row", type=int, required=True)
        p[name].add_argument("--by", required=True)
    p["set"].add_argument("--status", required=True, choices=tuple(mt.STATES))
    p["set"].add_argument("--note", default="")
    p["set"].add_argument("--jdl-entry-json")
    p["set"].add_argument("--reconciliation-json")
    p["set"].add_argument("--reexport", type=Path)
    p["set"].add_argument("--not-required-json")
    for flag in ("--plan", "--owner", "--memo"):
        p["update"].add_argument(flag)
    p["update"].add_argument("--evidence-id", action="append")
    p["export"].add_argument("--csv", type=Path, required=True)
    args = parser.parse_args()
    loads = lambda text: json.loads(text) if text else None  # noqa: E731

    if args.command == "create":
        _private(args.tracker)
        if args.tracker.exists():
            raise SystemExit("the tracker exists already; it is never overwritten")
        resolved = _resolved(args)
        tracker = mt.create_tracker(args.source, args.output, resolved.profile, resolved.context, args.company_id,
                                    created_by=args.created_by)
        mt.save(tracker, args.tracker)
        print(json.dumps({"tracked": len(tracker["journals"]), "baseline": tracker["baseline"]}, ensure_ascii=False, indent=1))
        return 0
    tracker = mt.load(args.tracker)
    if args.command in ("check", "final"):
        resolved = _resolved(args)
        integrity = mt.check(tracker, args.source, args.output, resolved.profile, resolved.context, args.company_id)
        if args.command == "check":
            print(json.dumps(integrity, ensure_ascii=False, indent=1))
            return 0 if integrity["verdict"] == "PASS" else 1
        roundtrip = (mt.ready_only_roundtrip(args.source, args.output, args.reexport, resolved.profile, resolved.context,
                                             args.company_id, args.acceptance) if args.reexport else None)
        result = mt.final_reconciliation(tracker, integrity, roundtrip=roundtrip,
                                         trial_balance=loads(args.trial_balance_json))
        print(json.dumps({**result, "roundtrip": roundtrip}, ensure_ascii=False, indent=1))
        return 0 if result["verdict"] == "MIGRATION_COMPLETE" else 1
    if args.command == "export":
        _private(args.csv)
        with args.csv.open("xb") as handle:
            handle.write(mt.to_csv(tracker))
        print(json.dumps({"written": args.csv.name, "journals": len(tracker["journals"])}, ensure_ascii=False))
        return 0
    if args.command == "set":
        journal = mt.set_status(tracker, args.row, args.status, by=args.by, note=args.note,
                                jdl_entry=loads(args.jdl_entry_json), reconciliation=loads(args.reconciliation_json),
                                reexport_path=args.reexport, not_required=loads(args.not_required_json))
    else:
        fields = {k: v for k, v in (("plan", args.plan), ("owner", args.owner), ("memo", args.memo),
                                     ("evidence_ids", args.evidence_id)) if v is not None}
        journal = mt.update_fields(tracker, args.row, by=args.by, **fields)
    mt.save(tracker, args.tracker)
    print(json.dumps({"row": journal["source_row"], "status": mt.STATES[journal["status"]]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
