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
    PROBE_CASE_SALES10_ACCOUNT,
    PROBE_CASE_UNTAXED_COMPOUND,
    YayoiJdlWorkflow,
    audit_path_for,
    verify_non_retained_audit,
)
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.tools.mf_full_e2e_compare import _groups, _rows
from accounting_converter.tools.yayoi_probe_check import manifest_path_for
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore


PENDING_EVIDENCE_IDS = {
    PROBE_CASE_SALES10_ACCOUNT: "PENDING:EVID-YAYOI-JDL-35-5-SALES10-{debit}-{credit}-ROUNDTRIP-001",
    PROBE_CASE_UNTAXED_COMPOUND: "PENDING:EVID-YAYOI-JDL-35-5-2D2C-NO-TAX-ROUNDTRIP-001",
}


def write_probe_manifest(probe: Path, ids, cases) -> dict:
    """Which probe journal is which case, so each case is judged on its own."""
    groups = _groups(_rows(probe))
    if len(groups) != len(ids):
        raise RuntimeError("probe journal count does not match the planned cases")
    items = []
    for index, (key, group) in enumerate(zip(ids, groups)):
        case = cases[key][0]
        items.append({
            "case": case,
            "journal_index": index,
            "physical_rows": len(group),
            "date": group[0][2],
            "pending_evidence_id": PENDING_EVIDENCE_IDS[case].format(debit=group[0][3], credit=group[0][13]),
        })
    payload = {"probe_file": probe.name, "probe_sha256": hashlib.sha256(probe.read_bytes()).hexdigest(),
               "status": "PENDING_REAL_JDL_IMPORT", "cases": items}
    path = manifest_path_for(probe)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return payload


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
        cases = workflow.probe_cases(args.source, resolved.profile, resolved.context)
        prepared, ids = workflow.prepare_probe(input_path=args.source, output_path=args.output,
                                               profile=resolved.profile, context=resolved.context)
        result = workflow.execute(prepared)
        ok = result is not None and result.status.value == "SUCCESS"
        manifest = None
        if ok:
            manifest = write_probe_manifest(args.output, ids, cases)
        print(json.dumps({"probe_written": ok, "probe_journals": len(ids),
                          "cases": [item["case"] for item in manifest["cases"]] if manifest else [],
                          "rows": result.output_record_count if ok else 0,
                          "reasons": list(prepared.summary.blocking_reasons),
                          "errors": sorted({v.rule_id for v in result.validation_results
                                            if v.severity.value == "ERROR"}) if result else [],
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
