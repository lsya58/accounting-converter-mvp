"""Formal JDL CSV for one Yayoi company: only when every journal is READY.

Writes the CSV and, when anything is not written to JDL, its audit file
(<output>.audit.json) next to it. Never overwrites. Prints counts only.

--probe: instead, a NOT_FOR_PRODUCTION file with only the journals whose sole
blocker is an unverified shape x tax combination (all Human mappings already
confirmed). For a test company restored from a backup only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from accounting_converter.application.first_release_workflow import FirstReleaseReadiness
from accounting_converter.application.yayoi_jdl_workflow import (
    YayoiJdlWorkflow,
    audit_path_for,
    verify_non_retained_audit,
)
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--company-store", type=Path, required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    if "data/private" not in args.output.resolve().as_posix():
        raise SystemExit("formal CSV and its audit record contain customer data; write them under data/private only")
    profiles = ConversionProfileStore(args.company_store / "profiles")
    resolved = CompanySettingStore(args.company_store / "companies", profiles).resolve(args.company_id)
    workflow = YayoiJdlWorkflow()
    if args.probe:
        prepared, ids = workflow.prepare_probe(input_path=args.source, output_path=args.output,
                                               profile=resolved.profile, context=resolved.context)
        result = workflow.execute(prepared)
        ok = result is not None and result.status.value == "SUCCESS"
        print(json.dumps({"probe_written": ok, "probe_journals": len(ids),
                          "reasons": list(prepared.summary.blocking_reasons),
                          "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest() if ok else None},
                         ensure_ascii=False, indent=1))
        return 0 if ok else 1
    prepared = workflow.prepare(input_path=args.source, output_path=args.output, profile=resolved.profile,
                                context=resolved.context, company_setting_validated=resolved.available)
    if prepared.summary.readiness is not FirstReleaseReadiness.READY:
        assessment = workflow.assess(args.source, resolved.profile, resolved.context)
        print(json.dumps({"written": False, "ready": assessment.ready_journals, "total": assessment.entry_count,
                          "by_blocker": assessment.blocker_counts(),
                          "reasons": list(prepared.summary.blocking_reasons)}, ensure_ascii=False, indent=1))
        return 1
    result = workflow.execute(prepared)
    ok = result is not None and result.status.value == "SUCCESS"
    audit = audit_path_for(args.output)
    preservation = verify_non_retained_audit(args.source, args.output, resolved.profile) if ok else {"verdict": "NOT_RUN"}
    print(json.dumps({
        "written": ok,
        "verdict_information_outside_jdl": preservation["verdict"],
        "journals": result.output_journal_count if result else 0,
        "rows": result.output_record_count if result else 0,
        "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest() if ok else None,
        "audit_file": audit.name if audit.exists() else None,
        "information_fully_retained": not audit.exists(),
        "errors": sorted({v.rule_id for v in result.validation_results if v.severity.value == "ERROR"}) if result else [],
    }, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
