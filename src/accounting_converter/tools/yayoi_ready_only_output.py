"""READY-only JDL CSV for one Yayoi company: NOT a full migration (application/yayoi_ready_only).

  plan   diagnose every journal; print the counts and the plan fingerprint (counts only on screen;
         --excluded-out writes the exclusion list, customer data, data/private only)
  write  write the READY journals only, after the explicit confirmation of exactly that plan:
         --fingerprint, --expect-output, --expect-excluded, the three --acknowledge-* flags and --confirmed-by.
         Never overwrites. Files: <output>, .audit.json (if needed), .excluded.csv, .ready_only.json
  verify re-check the files of a run

The saved settings are only read (use a copy of the store for trials).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from accounting_converter.application import yayoi_ready_only as ro
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore


def _private(path: Path) -> None:
    if "data/private" not in path.resolve().as_posix():
        raise SystemExit("customer data: write it under data/private only")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("plan", "write", "verify"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--company-store", type=Path, required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--excluded-out", type=Path)
    parser.add_argument("--fingerprint")
    parser.add_argument("--expect-output", type=int)
    parser.add_argument("--expect-excluded", type=int)
    parser.add_argument("--acknowledge-not-full-migration", action="store_true")
    parser.add_argument("--acknowledge-duplicate-check", action="store_true")
    parser.add_argument("--acknowledge-excluded-follow-up", action="store_true")
    parser.add_argument("--confirmed-by", default="")
    args = parser.parse_args()
    profiles = ConversionProfileStore(args.company_store / "profiles")
    resolved = CompanySettingStore(args.company_store / "companies", profiles).resolve(args.company_id)
    if args.command == "verify":
        result = ro.verify_ready_only_output(args.source, args.output, resolved.profile, resolved.context,
                                             args.company_id)
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0 if result["verdict"] == "PASS" else 1
    plan = ro.plan_ready_only(args.source, resolved.profile, resolved.context, args.company_id)
    if args.command == "plan":
        if args.excluded_out is not None:
            _private(args.excluded_out)
            with args.excluded_out.open("xb") as handle:
                handle.write(ro._excluded_csv(plan))  # noqa: SLF001
        print(json.dumps({
            "mode": ro.MODE, "full_migration": False, "available": plan.available,
            "problems": [ro.PROBLEM_MESSAGES.get(p, p) for p in plan.problems],
            "input_journals": plan.total_journals, "output_journals": plan.ready_count,
            "excluded_journals": plan.excluded_count, "fingerprint": plan.fingerprint,
            "notes": list(ro.FOLLOW_UP_NOTES)}, ensure_ascii=False, indent=1))
        return 0 if plan.available else 1
    if args.output is None:
        raise SystemExit("--output is required")
    _private(args.output)
    confirmation = ro.ReadyOnlyConfirmation(
        plan_fingerprint=args.fingerprint or "", output_journals=args.expect_output or -1,
        excluded_journals=args.expect_excluded if args.expect_excluded is not None else -1,
        confirmed_by=args.confirmed_by, acknowledged_not_full_migration=args.acknowledge_not_full_migration,
        acknowledged_duplicate_check=args.acknowledge_duplicate_check,
        acknowledged_excluded_follow_up=args.acknowledge_excluded_follow_up)
    prepared = ro.prepare_ready_only(plan, confirmation, input_path=args.source, output_path=args.output,
                                     profile=resolved.profile, context=resolved.context,
                                     company_setting_validated=resolved.available)
    if prepared.summary.readiness.value != "READY":
        print(json.dumps({"written": False, "reasons": list(prepared.summary.blocking_reasons)},
                         ensure_ascii=False, indent=1))
        return 1
    result = ro.execute_ready_only(prepared, plan, confirmation)
    print(json.dumps({
        "written": result.status == "SUCCESS", "mode": ro.MODE, "full_migration": False,
        "input_journals": result.total_journals, "output_journals": result.output_journals,
        "output_vouchers": result.output_vouchers, "output_rows": result.output_rows,
        "excluded_journals": result.excluded_journals, "not_migrated_journals": result.excluded_journals,
        "errors": list(result.errors),
        "files": [p.name for p in (result.output_path, result.audit_path, result.excluded_list_path,
                                   result.manifest_path) if p is not None]}, ensure_ascii=False, indent=1))
    return 0 if result.status == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
