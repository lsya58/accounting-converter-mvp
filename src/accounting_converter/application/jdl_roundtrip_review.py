"""JDL round-trip check for the screen (Phase 1: 弥生インポート形式 companies only). Read-only.

The judgement is the EXISTING command line one: `tools.yayoi_roundtrip_check.run_check` (source ↔ formal CSV,
formal CSV ↔ JDL re-export with the strict JDL comparator, information outside JDL via the audit record,
決算整理 rows; READY-only outputs verified against their manifest and company first). This module only
- checks the inputs before running it (company setting, route, files present, distinct, re-export ≠ CSV),
- binds the three files by SHA-256 before and after the run (a file changed meanwhile → no verdict),
- turns the existing verdict into one of the screen states without ever upgrading it, and
- keeps a summary WITHOUT customer values (no descriptions, accounts, amounts or row contents).

States: PASS / PASS_WITH_ACCEPTED_NORMALIZATION (only the existing verdict, never created here: this module
passes no acceptance) / PENDING (Evidence-backed loss without acceptance) / FAIL / READ_ERROR (a file could not
be read or compared: never a PASS) / NOT_RUN (refused before comparing: unsupported route, same file …).

Exceptions are not written to the diagnostic log (their messages may quote file contents): only the exception
type is kept. The strict comparator's same-day-order re-check (run only after a strict FAIL) writes the two row
groups it compares to a TemporaryDirectory in the OS temp folder and removes it on exit; that is the command
line's behaviour, unchanged, and it never changes the verdict (content_match is reported only).
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from accounting_converter.application import jdl_description_trailing_space as trailing
from accounting_converter.application import yayoi_ready_only as ro
from accounting_converter.application.yayoi_jdl_workflow import locate_non_retained_audit
from accounting_converter.application.yayoi_sources import IMPORT, REPORT

SUMMARY_SCHEMA = "jdl-roundtrip-review-summary-v1"

PASS = "PASS"
PASS_WITH_ACCEPTED_NORMALIZATION = "PASS_WITH_ACCEPTED_NORMALIZATION"
PENDING = "PENDING"
FAIL = "FAIL"
READ_ERROR = "READ_ERROR"
NOT_RUN = "NOT_RUN"
STATES = (PASS, PASS_WITH_ACCEPTED_NORMALIZATION, PENDING, FAIL, READ_ERROR, NOT_RUN)

ROUTE_YAYOI_IMPORT = "YAYOI_IMPORT_FORMAT"
FIRST_FAILURES_LIMIT = 20  # the existing comparator keeps the details of the first 20 unexplained differences

# Comparator field (moneyforward_roundtrip._FIELDS) -> category shown on screen.
_FIELD_CATEGORY = {
    "debit_amount": "AMOUNT", "credit_amount": "AMOUNT",
    "debit_tax_amount": "TAX_AMOUNT", "credit_tax_amount": "TAX_AMOUNT",
    "debit_account_code": "ACCOUNT", "debit_account_name": "ACCOUNT", "debit_account_formal_name": "ACCOUNT",
    "credit_account_code": "ACCOUNT", "credit_account_name": "ACCOUNT", "credit_account_formal_name": "ACCOUNT",
    "debit_subaccount_code": "SUBACCOUNT", "debit_subaccount_name": "SUBACCOUNT",
    "credit_subaccount_code": "SUBACCOUNT", "credit_subaccount_name": "SUBACCOUNT",
    "debit_tax_scope": "TAX_CATEGORY", "debit_tax_category": "TAX_CATEGORY", "debit_tax_input_method": "TAX_CATEGORY",
    "credit_tax_scope": "TAX_CATEGORY", "credit_tax_category": "TAX_CATEGORY",
    "credit_tax_input_method": "TAX_CATEGORY",
    "description": "DESCRIPTION", "date": "DATE", "flag": "VOUCHER", "voucher": "VOUCHER",
    "debit_department_code": "DEPARTMENT", "debit_department_name": "DEPARTMENT",
    "credit_department_code": "DEPARTMENT", "credit_department_name": "DEPARTMENT",
    "reserved_25": "OTHER", "reserved_26": "OTHER", "journal_grouping": "JOURNAL_GROUPING",
}


def field_category(classification: str, field_name: str) -> str:
    if classification == "MISSING_ROW":
        return "MISSING_ROW"
    if classification == "EXTRA_ROW":
        return "EXTRA_ROW"
    return _FIELD_CATEGORY.get(field_name, "OTHER")


@dataclass(frozen=True)
class FileRef:
    role: str  # source / candidate / reexport
    name: str
    sha256: str


@dataclass(frozen=True)
class RoundTripReview:
    state: str
    company_id: str
    route: str | None = None
    ready_only: bool = False
    existing_verdict: str | None = None  # the command line's "verdict", unchanged
    verdict_jdl_roundtrip: str | None = None
    verdict_information_outside_jdl: str | None = None
    reasons: tuple[str, ...] = ()  # codes (no customer values)
    error_type: str | None = None
    files: tuple[FileRef, ...] = ()
    counts: dict = field(default_factory=dict)  # journals / physical rows per file
    source_vs_candidate: dict = field(default_factory=dict)
    reexport: dict = field(default_factory=dict)
    first_failures: tuple[dict, ...] = ()  # at most FIRST_FAILURES_LIMIT: row, field, category, classification
    closing_verdict: str | None = None
    trailing_space: dict = field(default_factory=dict)  # counts and Evidence IDs only, never the descriptions
    date_ranges: dict = field(default_factory=dict)
    audit_found_by: str | None = None

    @property
    def is_pass(self) -> bool:
        return self.state in {PASS, PASS_WITH_ACCEPTED_NORMALIZATION}

    def summary(self) -> dict:
        """What may be saved: states, verdicts, counts, codes, file names and SHA-256 (no customer values)."""
        return {
            "schema": SUMMARY_SCHEMA,
            "state": self.state,
            "company_id": self.company_id,
            "route": self.route,
            "ready_only": self.ready_only,
            "existing_verdict": self.existing_verdict,
            "verdict_jdl_roundtrip": self.verdict_jdl_roundtrip,
            "verdict_information_outside_jdl": self.verdict_information_outside_jdl,
            "reasons": list(self.reasons),
            "error_type": self.error_type,
            "files": [{"role": f.role, "name": f.name, "sha256": f.sha256} for f in self.files],
            "counts": self.counts,
            "source_vs_candidate": self.source_vs_candidate,
            "reexport": self.reexport,
            "first_failures": list(self.first_failures),
            "first_failures_note": f"最初の{FIRST_FAILURES_LIMIT}件までの差分詳細（全件数は reexport.unexplained_differences）",
            "closing_verdict": self.closing_verdict,
            "trailing_space": self.trailing_space,
            "date_ranges": self.date_ranges,
            "audit_found_by": self.audit_found_by,
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Phase 1 is bound to company B, the only company with real JDL round-trip Evidence. Another 弥生インポート形式
# company is NOT offered the check (company B's Evidence is never reused for another company).
EVIDENCE_COMPANY_IDS = frozenset({"company-yayoi-act"})


def route_of(profile, company_id=None) -> str | None:
    """Phase 1: the 弥生インポート形式 route of an Evidence company (company B) only."""
    key = profile.source_format_identity.stable_key if profile is not None else None
    if key != IMPORT.identity().stable_key or str(company_id) not in EVIDENCE_COMPANY_IDS:
        return None
    return ROUTE_YAYOI_IMPORT


def unsupported_reason(profile) -> str:
    key = profile.source_format_identity.stable_key if profile is not None else None
    if key == IMPORT.identity().stable_key:
        return "ROUTE_COMPANY_NOT_IN_PHASE_1"
    if key == REPORT.identity().stable_key:
        return "ROUTE_YAYOI_JOURNAL_REPORT_NOT_IN_PHASE_1"
    return "ROUTE_NOT_YAYOI_IMPORT_FORMAT"


def _date_range(path: Path) -> list[str] | None:
    from accounting_converter.tools import mf_full_e2e_compare

    days = sorted({row[2] for row in mf_full_e2e_compare._rows(path)})
    return [days[0], days[-1]] if days else None


def _state_of(result: dict) -> tuple[str, tuple[str, ...]]:
    """Existing verdict -> screen state. Never upgrades: anything unknown is a FAIL."""
    if "ready_only_files" in result:
        return FAIL, ("READY_ONLY_FILES_DO_NOT_MATCH",)
    comparison = result.get("candidate_vs_reexport")
    if isinstance(comparison, dict) and comparison.get("error"):
        return READ_ERROR, ("REEXPORT_NOT_COMPARABLE",)
    verdict = result.get("verdict")
    if verdict == "PASS":
        return PASS, ()
    if verdict == "PASS_WITH_ACCEPTED_NORMALIZATION":
        loss = result.get("description_trailing_space_loss") or {}
        if (loss.get("acceptance") or {}).get("state") == trailing.ACCEPTED:
            return PASS_WITH_ACCEPTED_NORMALIZATION, ()
        return FAIL, ("ACCEPTANCE_NOT_VERIFIED",)
    if verdict == "NORMALIZATION_ACCEPTANCE_PENDING":
        return PENDING, ("NORMALIZATION_ACCEPTANCE_PENDING",)
    if verdict == "SOURCE_TO_CSV_PASS_REEXPORT_PENDING":
        return NOT_RUN, ("REEXPORT_NOT_COMPARED",)
    reasons = []
    if result.get("verdict_information_outside_jdl") == "FAIL":
        reasons.append("INFORMATION_OUTSIDE_JDL_FAIL")
    if result.get("verdict_jdl_roundtrip") == "FAIL":
        reasons.append("JDL_ROUNDTRIP_FAIL")
    if (result.get("closing_entries") or {}).get("verdict") == "FAIL":
        reasons.append("CLOSING_ROWS_FAIL")
    return FAIL, tuple(reasons) or ("VERDICT_NOT_PASS",)


def _reexport_view(result: dict) -> tuple[dict, tuple[dict, ...]]:
    comparison = result.get("candidate_vs_reexport")
    if not isinstance(comparison, dict):
        return {}, ()
    counts = Counter(comparison.get("classification_counts") or {})
    view = {
        "strict_passed": bool(comparison.get("strict_passed")),
        "unexplained_differences": comparison.get("unexplained_differences"),
        "journals": comparison.get("journals"),
        "physical_rows": comparison.get("physical_rows"),
        # Totals from the comparator's own classification counts (all differences, not a sample).
        "missing_rows": counts.get("MISSING_ROW", 0),
        "extra_rows": counts.get("EXTRA_ROW", 0),
        "unexpected_changes": counts.get("UNEXPECTED_CHANGE", 0),
        "canonical_normalizations": counts.get("EXPECTED_JDL_CANONICAL_NORMALIZATION", 0),
        "evidenced_information_loss": counts.get("EVIDENCED_DESCRIPTION_TRAILING_SPACE_REMOVED", 0),
    }
    if "error" in comparison:
        view["error_type"] = comparison["error"]
    match = comparison.get("content_match")
    if isinstance(match, dict):  # counts only (the groups carry dates of customer journals)
        view["content_match"] = {
            "unmatched_groups": len(match.get("unmatched_groups") or ()),
            "dates_with_order_only_difference": len(match.get("dates_with_order_only_difference") or ()),
            "content_equal_ignoring_same_day_order": bool(match.get("content_equal_ignoring_same_day_order")),
        }
    failures = tuple(
        {"row": item.get("row"), "field": item.get("field"), "classification": item.get("classification"),
         "category": field_category(str(item.get("classification")), str(item.get("field")))}
        for item in (comparison.get("first_failures") or ())[:FIRST_FAILURES_LIMIT]
    )
    view["first_failures_shown"] = len(failures)
    view["first_failure_categories"] = dict(Counter(item["category"] for item in failures))  # sample only
    return view, failures


def _trailing_view(result: dict) -> dict:
    loss = result.get("description_trailing_space_loss")
    if not isinstance(loss, dict):
        return {"scope": result.get("description_trailing_space_scope")}
    return {
        "scope": result.get("description_trailing_space_scope"),
        "rows": loss.get("rows_count"), "journals": loss.get("journals_count"),
        "evidence_ids": list(loss.get("evidence_ids") or ()),
        "source_alignment": loss.get("source_alignment"),
        "acceptance_state": (loss.get("acceptance") or {}).get("state"),
    }


def review(resolved, company_id: str, source: Path, candidate: Path, reexport: Path) -> RoundTripReview:
    """The screen's check. `resolved`: the company store's ResolvedCompanySetting for company_id."""
    if resolved is None or not resolved.available or resolved.profile is None or resolved.context is None:
        return RoundTripReview(NOT_RUN, company_id, reasons=("COMPANY_SETTING_NOT_AVAILABLE",))
    if str(resolved.setting.company_setting_id) != company_id:
        return RoundTripReview(NOT_RUN, company_id, reasons=("COMPANY_SETTING_MISMATCH",))
    route = route_of(resolved.profile, company_id)
    if route is None:
        return RoundTripReview(NOT_RUN, company_id, reasons=(unsupported_reason(resolved.profile),))
    paths = {"source": Path(source), "candidate": Path(candidate), "reexport": Path(reexport)}
    missing = [role for role, path in paths.items() if not path.is_file()]
    if missing:
        return RoundTripReview(READ_ERROR, company_id, route, reasons=tuple(f"FILE_NOT_FOUND:{r}" for r in missing))
    if len({path.resolve() for path in paths.values()}) != 3:
        return RoundTripReview(NOT_RUN, company_id, route, reasons=("SAME_FILE_SELECTED_TWICE",))
    try:
        before = {role: _sha256(path) for role, path in paths.items()}
    except OSError as exc:
        return RoundTripReview(READ_ERROR, company_id, route, reasons=("FILE_NOT_READABLE",),
                               error_type=type(exc).__name__)
    files = tuple(FileRef(role, paths[role].name, before[role]) for role in paths)
    if before["candidate"] == before["reexport"]:
        # The CSV itself chosen as its own re-export would "pass" without JDL: never compared.
        return RoundTripReview(NOT_RUN, company_id, route, reasons=("REEXPORT_IDENTICAL_TO_CANDIDATE",), files=files)
    if before["source"] in {before["candidate"], before["reexport"]}:
        return RoundTripReview(NOT_RUN, company_id, route, reasons=("SAME_FILE_SELECTED_TWICE",), files=files)
    ready_only = ro.manifest_path_for(paths["candidate"]).exists()
    from accounting_converter.tools.yayoi_roundtrip_check import run_check

    try:
        result = run_check(paths["source"], resolved.profile, resolved.context, company_id, paths["candidate"],
                           paths["reexport"], ready_only=ready_only)
        date_ranges = {role: _date_range(paths[role]) for role in ("candidate", "reexport")}
        audit_found_by = locate_non_retained_audit(paths["candidate"])[1]
        after = {role: _sha256(path) for role, path in paths.items()}
    except Exception as exc:  # noqa: BLE001 - any failure to read or compare is a READ_ERROR, never a PASS
        return RoundTripReview(READ_ERROR, company_id, route, ready_only, reasons=("CHECK_RAISED",),
                               error_type=type(exc).__name__, files=files)
    if after != before:
        return RoundTripReview(READ_ERROR, company_id, route, ready_only, reasons=("FILES_CHANGED_DURING_CHECK",),
                               files=files)
    state, reasons = _state_of(result)
    reexport_view, failures = _reexport_view(result)
    source_vs_candidate = dict(result.get("source_vs_candidate") or {})
    information = result.get("information_not_in_jdl") or {}
    counts = {key: result[key] for key in ("source", "candidate") if isinstance(result.get(key), dict)}
    if "ready_only_files" in result:
        counts["ready_only_verification"] = (result["ready_only_files"] or {}).get("verdict")
    if information.get("verdict") == "FAIL" and not information.get("final_present", True):
        reasons = (*reasons, "AUDIT_RECORD_NOT_FOUND_NEXT_TO_CSV")
    return RoundTripReview(
        state, company_id, route, ready_only,
        existing_verdict=result.get("verdict"),
        verdict_jdl_roundtrip=result.get("verdict_jdl_roundtrip"),
        verdict_information_outside_jdl=result.get("verdict_information_outside_jdl"),
        reasons=reasons, files=files, counts=counts, source_vs_candidate=source_vs_candidate,
        reexport=reexport_view, first_failures=failures,
        closing_verdict=(result.get("closing_entries") or {}).get("verdict"),
        trailing_space=_trailing_view(result), date_ranges=date_ranges, audit_found_by=audit_found_by,
    )


def save_summary(review_result: RoundTripReview, path: Path) -> None:
    """Writes the summary (no customer values). Never overwrites: an existing file raises FileExistsError."""
    payload = json.dumps(review_result.summary(), ensure_ascii=False, indent=1) + "\n"
    with Path(path).open("xb") as handle:
        handle.write(payload.encode("utf-8"))
