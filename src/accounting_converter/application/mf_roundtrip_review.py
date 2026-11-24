"""JDL round-trip check for the screen, Phase 2: Money Forward pilot companies only. Read-only.

Binding by regeneration (the command line tools' own steps, nothing re-implemented):
1. The fiscal year is chosen on screen (its last day, with the pilot entry's fiscal year end); it is NOT taken from
   the candidate CSV. Every source journal dated in that year is converted again with the CURRENT company setting
   (`tools.mf_formal_output_by_period.regenerate_period`: the normal MoneyForwardConversionWorkflow on whole source
   records, so no journal is split) into a TemporaryDirectory, removed on exit, also after an exception.
2. Only a byte-identical regenerated CSV lets the check go on. A candidate that lacks the year's first or last
   journals, comes from another source / company / year, or was made with another mapping is not reproduced:
   未照合. So is a year whose conversion is not READY.
3. Then the existing strict comparison `tools.mf_full_e2e_compare.compare` (MoneyForwardJdlRoundTripComparator)
   of the candidate with the JDL re-export decides the round trip.

What a PASS means: the candidate CSV is reproduced from the chosen source and the CURRENT setting (not proof of
the setting used back then), and the re-export agrees with it. Whether the re-export really went through JDL cannot
be proved by this app. A recorded result is shown only when the source, year, candidate and re-export all equal the
record (never on the candidate hash alone); the company setting is not part of the record. Nothing here registers
Evidence or records an approval. Exceptions keep their type only (messages may quote file contents) and nothing is
logged.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from accounting_converter.application import jdl_roundtrip_pilot as pilot
from accounting_converter.application import jdl_roundtrip_review as rr

ROUTE_MONEYFORWARD = pilot.ROUTE_MONEYFORWARD
JDL_ROUTE_PROOF = "NOT_PROVABLE"  # the re-export's passage through JDL is not independently provable here


@dataclass(frozen=True)
class RecordedRoundTrip:
    """A copy of a result already written in docs/development/jdl_real_evidence_log.md. NOT Evidence: display only."""
    evidence_id: str
    recorded_on: str
    period_end: str
    source_sha256: str
    candidate_sha256: str
    reexport_sha256: str
    verdict: str
    journals: int
    physical_rows: int
    reference: str


RECORDED_ROUNDTRIPS = (
    RecordedRoundTrip(
        evidence_id="EVID-MF-JDL-35-5-REAL-482-FY2026-05-FULL-ROUNDTRIP-001", recorded_on="2026-10-31",
        period_end="2026-05-31",
        source_sha256="f056c8d7781ab6743ac8a82fd3785a5c603a4a9d8d40984c618deef3241687ea",
        candidate_sha256="ec2bcc3bd02aa2e31b818bcfffba3b1b4d02fe25ab87b37ca7ba5e76f4f9b90b",
        reexport_sha256="d8b5014194978970ee2a1d0c7172222baaaed55e43688d73a537f0a57a0c17df",
        verdict="PASS", journals=378, physical_rows=479,
        reference="docs/development/jdl_real_evidence_log.md"),
)


def is_moneyforward(profile) -> bool:
    from accounting_converter.profiles.known_formats import (
        jdl_ibex_cashbook_official_journal_import_schema_definition,
        moneyforward_cloud_journal_export_observed_schema,
    )

    if profile is None:
        return False
    return (profile.source_format_identity.stable_key
            == moneyforward_cloud_journal_export_observed_schema().identity.stable_key
            and profile.target_format_identity.stable_key
            == jdl_ibex_cashbook_official_journal_import_schema_definition().identity.stable_key)


def route_status(resolved, pilot_file: Path) -> tuple[pilot.PilotEntry | None, str | None]:
    if resolved is None or not resolved.available or resolved.profile is None or resolved.context is None:
        return None, "COMPANY_SETTING_NOT_AVAILABLE"
    if not is_moneyforward(resolved.profile):
        return None, "ROUTE_NOT_MONEYFORWARD"
    return pilot.entry_for(pilot_file, resolved, ROUTE_MONEYFORWARD)


def _setting_key(resolved) -> tuple | None:
    if resolved is None or not resolved.available:
        return None
    s = resolved.setting
    return (s.company_setting_id, s.conversion_profile_id, s.profile_fingerprint, s.context_fingerprint,
            s.expected_source_format_key, s.expected_target_format_key, str(s.updated_at))


def _candidate_shape(path: Path) -> tuple[list[date], int, int]:
    """Journal dates, journal count and row count of a JDL 30-column CSV (strict CP932, YYYYMMDD dates)."""
    from accounting_converter.tools import mf_full_e2e_compare as compare_tool

    rows = compare_tool._rows(path)
    groups = compare_tool._groups(rows)
    dates = [datetime.strptime(group[0][2], "%Y%m%d").date() for group in groups]
    return dates, len(groups), len(rows)


def _recorded(source_sha: str, period_end: date, candidate_sha: str, reexport_sha: str | None) -> dict:
    for record in RECORDED_ROUNDTRIPS:
        if (record.source_sha256 == source_sha and record.period_end == period_end.isoformat()
                and record.candidate_sha256 == candidate_sha and record.reexport_sha256 == reexport_sha):
            return {"evidence_id": record.evidence_id, "recorded_on": record.recorded_on,
                    "recorded_verdict": record.verdict, "journals": record.journals,
                    "physical_rows": record.physical_rows, "reference": record.reference,
                    "matched": ["source", "period", "candidate", "reexport"],
                    "not_in_record": ["company_setting"]}
    return {}


def review(resolve: Callable[[], object], company_id: str, source: Path, candidate: Path, reexport: Path | None,
           period_end: date | None, pilot_file: Path) -> rr.RoundTripReview:
    """`resolve()`: the company store's ResolvedCompanySetting for company_id (called before and after the run)."""
    route = ROUTE_MONEYFORWARD
    resolved = resolve()
    if resolved is None or not resolved.available or resolved.profile is None or resolved.context is None:
        return rr.RoundTripReview(rr.NOT_RUN, company_id, reasons=("COMPANY_SETTING_NOT_AVAILABLE",))
    if str(resolved.setting.company_setting_id) != company_id:
        return rr.RoundTripReview(rr.NOT_RUN, company_id, reasons=("COMPANY_SETTING_MISMATCH",))
    entry, problem = route_status(resolved, pilot_file)
    if entry is None:
        return rr.RoundTripReview(rr.NOT_RUN, company_id, reasons=(problem or "PILOT_NOT_ENABLED",))
    if period_end is None:
        return rr.RoundTripReview(rr.NOT_RUN, company_id, route, reasons=("PERIOD_NOT_SELECTED",))
    if (period_end.month, period_end.day) != entry.fiscal_year_end_month_day:
        return rr.RoundTripReview(rr.NOT_RUN, company_id, route, reasons=("PERIOD_NOT_FISCAL_YEAR_END",))
    from accounting_converter.tools import mf_formal_output_by_period as by_period

    start, end = by_period.period_bounds(period_end)
    period = {"start": start.isoformat(), "end": end.isoformat(), "fiscal_year_end": entry.fiscal_year_end,
              "chosen_on_screen": True}
    paths = {"source": Path(source), "candidate": Path(candidate)}
    if reexport is not None:
        paths["reexport"] = Path(reexport)
    missing = [role for role, path in paths.items() if not path.is_file()]
    if missing:
        return rr.RoundTripReview(rr.READ_ERROR, company_id, route, reasons=tuple(f"FILE_NOT_FOUND:{r}" for r in missing),
                                  period=period)
    if len({path.resolve() for path in paths.values()}) != len(paths):
        return rr.RoundTripReview(rr.NOT_RUN, company_id, route, reasons=("SAME_FILE_SELECTED_TWICE",), period=period)
    try:
        before = {role: rr._sha256(path) for role, path in paths.items()}
    except OSError as exc:
        return rr.RoundTripReview(rr.READ_ERROR, company_id, route, reasons=("FILE_NOT_READABLE",),
                                  error_type=type(exc).__name__, period=period)
    files = tuple(rr.FileRef(role, paths[role].name, before[role]) for role in paths)
    if "reexport" in before and before["candidate"] == before["reexport"]:
        return rr.RoundTripReview(rr.NOT_RUN, company_id, route, reasons=("REEXPORT_IDENTICAL_TO_CANDIDATE",),
                                  files=files, period=period)
    if len(set(before.values())) != len(before):
        return rr.RoundTripReview(rr.NOT_RUN, company_id, route, reasons=("SAME_FILE_SELECTED_TWICE",), files=files,
                                  period=period)
    setting_before = _setting_key(resolved)
    comparison = None
    try:
        dates, candidate_journals, candidate_rows = _candidate_shape(paths["candidate"])
        with tempfile.TemporaryDirectory() as directory:
            regenerated = Path(directory) / "regenerated.csv"
            info = by_period.regenerate_period(paths["source"], resolved.profile, resolved.context, period_end,
                                               regenerated)
            regenerated_sha = rr._sha256(regenerated) if regenerated.exists() else None
            matched = regenerated.exists() and regenerated.read_bytes() == paths["candidate"].read_bytes()
        outside = sum(1 for day in dates if not start <= day <= end)
        if matched and not outside and "reexport" in paths:
            from accounting_converter.tools.mf_full_e2e_compare import compare

            try:
                comparison = compare(paths["candidate"], paths["reexport"])
            except ValueError as exc:  # the strict reader refused the re-export (encoding, header, balance …)
                comparison = {"error": type(exc).__name__}
        reexport_range = rr._date_range(paths["reexport"]) if comparison and "error" not in comparison else None
        after = {role: rr._sha256(path) for role, path in paths.items()}
        setting_after = _setting_key(resolve())
    except Exception as exc:  # noqa: BLE001 - any failure to read, regenerate or compare is a READ_ERROR, never a PASS
        return rr.RoundTripReview(rr.READ_ERROR, company_id, route, reasons=("CHECK_RAISED",),
                                  error_type=type(exc).__name__, files=files, period=period)
    if after != before:
        return rr.RoundTripReview(rr.READ_ERROR, company_id, route, reasons=("FILES_CHANGED_DURING_CHECK",),
                                  files=files, period=period)
    if setting_after != setting_before:
        return rr.RoundTripReview(rr.READ_ERROR, company_id, route, reasons=("SETTING_CHANGED_DURING_CHECK",),
                                  files=files, period=period)
    regeneration = {
        "source_journals_in_period": info["source_journals"],
        "source_physical_rows_in_period": info["source_physical_rows"],
        "source_journals_total": info["source_journals_total"],
        "readiness": info["readiness"], "status": info["status"],
        "regenerated_sha256": regenerated_sha, "candidate_sha256": before["candidate"],
        "byte_identical": bool(matched), "candidate_journals_outside_period": outside,
        "meaning": "選択した元データと現在の会社設定から、出力CSVを再現できるか（過去の設定の証明ではない）",
    }
    counts = {"source": {"journals": info["source_journals"], "physical_rows": info["source_physical_rows"]},
              "candidate": {"journals": candidate_journals, "physical_rows": candidate_rows}}
    date_ranges = {"candidate": [min(dates).isoformat(), max(dates).isoformat()] if dates else None}
    if reexport_range:
        date_ranges["reexport"] = [f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in reexport_range]
    common = dict(files=files, counts=counts, period=period, regeneration=regeneration, date_ranges=date_ranges)

    def not_run(reason: str) -> rr.RoundTripReview:
        return rr.RoundTripReview(rr.NOT_RUN, company_id, route, reasons=(reason,), **common)

    if outside:
        return not_run("CANDIDATE_OUTSIDE_PERIOD")
    if not info["source_journals"]:
        return not_run("SOURCE_HAS_NO_JOURNALS_IN_PERIOD")
    if info["readiness"] != "READY" or regenerated_sha is None:
        return not_run("REGENERATION_NOT_READY")
    if not matched:
        return not_run("CANDIDATE_NOT_REPRODUCED")
    if comparison is None:
        return not_run("REEXPORT_NOT_SELECTED")
    reexport_view, failures = rr._reexport_view({"candidate_vs_reexport": comparison})
    if "error" in comparison:
        state, reasons = rr.READ_ERROR, ("REEXPORT_NOT_COMPARABLE",)
    elif comparison.get("strict_passed"):
        state, reasons = rr.PASS, ()
    elif comparison.get("passed_with_evidenced_information_loss"):
        state, reasons = rr.PENDING, ("NORMALIZATION_ACCEPTANCE_PENDING",)
    else:
        state, reasons = rr.FAIL, ("JDL_ROUNDTRIP_FAIL",)
    reference = (_recorded(before["source"], period_end, before["candidate"], before.get("reexport"))
                 if state == rr.PASS else {})
    return rr.RoundTripReview(
        state, company_id, route, reasons=reasons,
        verdict_jdl_roundtrip={rr.PASS: "PASS", rr.PENDING: "PENDING", rr.FAIL: "FAIL"}.get(state),
        reexport=reexport_view, first_failures=failures, evidence_reference=reference, **common)
