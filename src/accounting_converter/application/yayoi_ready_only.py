"""Yayoi → JDL READY-only output: only the journals the formal diagnosis found READY, never a full migration.

The default formal output stays all-or-nothing (YayoiJdlWorkflow.prepare refuses any BLOCK). This separate
mode exists only for a user who explicitly asks for it, and it never hides what was left out:

1. ``plan_ready_only`` diagnoses EVERY source journal with the production ``assess`` (no setting is changed;
   no split, 64-row setting or approval is assumed) and splits them into READY (written) and BLOCK (excluded,
   listed one by one with date, voucher, amounts and reasons). Input = output + excluded is checked.
2. ``ReadyOnlyConfirmation``: the user's explicit final confirmation of exactly that plan (its fingerprint,
   the two counts, three acknowledgements, a name). Without it nothing is written.
3. ``prepare_ready_only`` re-diagnoses and refuses if anything changed, then builds the SAME production
   conversion (``YayoiJdlWorkflow.formal_service``) restricted to the READY journals. A READY journal is written
   whole (as approved split parts if a split approval is recorded), never in part; a BLOCK journal never.
4. ``execute_ready_only`` writes, in this order, the JDL CSV, the non-retained audit scoped to the written
   journals, the exclusion list (CSV for people) and last the manifest (``.ready_only.json``) that binds all of
   them by SHA-256. Any failure removes every file of the run, so an incomplete CSV is never left as a result.
5. ``verify_ready_only_output`` re-checks the files later (tampering, a deleted list, changed settings).

Nothing here widens Evidence, approves anything or reports the company as migrated: the manifest and the
screen always say NOT a full migration and how many journals are still not migrated.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from accounting_converter.application import closing_entries, voucher_split
from accounting_converter.application.first_release_workflow import (
    FirstReleasePreparedConversion,
    FirstReleaseReadiness,
    FirstReleaseSummary,
)
from accounting_converter.application.yayoi_jdl_workflow import (
    YayoiJdlWorkflow,
    audit_path_for,
    begin_non_retained_audit,
    finish_non_retained_audit,
    pending_audit_path_for,
    verify_non_retained_audit,
)
from accounting_converter.application.yayoi_sources import detect_format, format_for_identity_key
from accounting_converter.domain.journal import Side
from accounting_converter.domain.journal_rows import ROW_ORDER_KEY

MODE = "READY_ONLY"
MANIFEST_SCHEMA = "yayoi-jdl-ready-only-v1"
EXCLUDED_HEADER = ("元の行", "日付", "伝票No.", "仕訳番号", "借方金額合計", "貸方金額合計", "BLOCK理由", "BLOCKコード")
# A blocker on these means the company setting itself is not usable: no journal may be written in any mode.
COMPANY_WIDE_BLOCKERS = frozenset({
    "HUMAN:TARGET_JDL_COMPANY_SETTING",
    "HUMAN:COMPANY_SETTING_SOURCE_MISMATCH",
    "SYSTEM_EVIDENCE:TAX_CONTEXT_UNVERIFIED",
    "SYSTEM_EVIDENCE:VOUCHER_ROW_LIMIT_SETTING_UNVERIFIED",
    "HUMAN:VOUCHER_ROW_LIMIT_SETTING",
    "HUMAN:JDL_TAX_ROUNDING_SETTING",
})
FOLLOW_UP_NOTES = (
    "全件移行ではありません。除外した仕訳はJDLに取り込まれず、未移行のまま残ります。",
    "JDLの取込先に同じ期間の仕訳が既にないか（二重取込）を、取込前に確認してください。",
    "除外した仕訳は、承認・修正の後に再診断して変換するか、JDLで手入力するかを決めてください。",
    "税務・会計上の整合（除外分を含む会社全体）が確認できるまで、実運用完了とは扱いません。",
)

# Plan problems (any of them: READY-only is not offered).
PARSE_INCOMPLETE = "PARSE_INCOMPLETE"
NO_READY_JOURNAL = "NO_READY_JOURNAL"
NOTHING_EXCLUDED = "NOTHING_EXCLUDED"   # use the ordinary full conversion instead
COMPANY_SETTING_INCOMPLETE = "COMPANY_SETTING_INCOMPLETE"
COUNT_MISMATCH = "COUNT_MISMATCH"
PROBLEM_MESSAGES = {
    PARSE_INCOMPLETE: "入力ファイルに読み込めない仕訳があるため、除外一覧を正確に作れません。READYのみ変換はできません。",
    NO_READY_JOURNAL: "READYの仕訳がありません。",
    NOTHING_EXCLUDED: "すべての仕訳がREADYです。通常の全件変換を使ってください。",
    COMPANY_SETTING_INCOMPLETE: "会社設定（JDL会社・税設定・行数）が未確定です。READYのみ変換はできません。",
    COUNT_MISMATCH: "入力仕訳数と、出力対象＋除外の件数が一致しません。",
}


@dataclass(frozen=True)
class ExcludedJournal:
    journal_id: str
    source_row: int
    date: str
    voucher: str
    journal_numbers: tuple[str, ...]
    debit_total: Decimal
    credit_total: Decimal
    blockers: tuple[str, ...]
    reasons: tuple[str, ...]

    def record(self) -> dict:
        return {"source_row": self.source_row, "date": self.date, "voucher": self.voucher,
                "journal_numbers": list(self.journal_numbers), "debit_total": str(self.debit_total),
                "credit_total": str(self.credit_total), "blockers": list(self.blockers), "reasons": list(self.reasons)}


@dataclass(frozen=True)
class ReadyOnlyPlan:
    source_name: str
    source_sha256: str
    company_setting_id: str | None
    profile_id: str | None
    profile_updated_at: str | None
    settings: dict
    total_journals: int
    ready_ids: tuple[str, ...]          # source order
    ready_rows: tuple[int, ...]         # first source row of each READY journal
    excluded: tuple[ExcludedJournal, ...]
    totals: dict                         # {"all"|"ready"|"excluded": {"debit": str, "credit": str}}
    period: tuple[str, str] | None
    problems: tuple[str, ...] = field(default=())

    @property
    def ready_count(self) -> int:
        return len(self.ready_ids)

    @property
    def excluded_count(self) -> int:
        return len(self.excluded)

    @property
    def available(self) -> bool:
        return not self.problems

    @property
    def fingerprint(self) -> str:
        """Binds a confirmation to exactly this diagnosis (files, settings, both journal sets and reasons)."""
        payload = {"source_sha256": self.source_sha256, "company": self.company_setting_id,
                   "profile_id": self.profile_id, "profile_updated_at": self.profile_updated_at,
                   "settings": self.settings, "ready_rows": list(self.ready_rows),
                   "excluded": [item.record() for item in self.excluded], "totals": self.totals}
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ReadyOnlyConfirmation:
    """The user's explicit final confirmation. Every field must match the plan being written."""
    plan_fingerprint: str
    output_journals: int
    excluded_journals: int
    confirmed_by: str
    acknowledged_not_full_migration: bool
    acknowledged_duplicate_check: bool
    acknowledged_excluded_follow_up: bool

    def problems(self, plan: ReadyOnlyPlan) -> tuple[str, ...]:
        found = []
        if self.plan_fingerprint != plan.fingerprint:
            found.append("確認した診断結果と現在の診断結果が一致しません。もう一度確認してください。")
        if (self.output_journals, self.excluded_journals) != (plan.ready_count, plan.excluded_count):
            found.append("確認した出力件数・除外件数が診断結果と一致しません。")
        if not (self.acknowledged_not_full_migration and self.acknowledged_duplicate_check
                and self.acknowledged_excluded_follow_up):
            found.append("全件移行ではないこと・二重取込の確認・除外分の扱いをすべて確認してください。")
        if not isinstance(self.confirmed_by, str) or not self.confirmed_by.strip():
            found.append("確認者の名前を入力してください。")
        return tuple(found)

    def record(self) -> dict:
        return {"confirmed_by": self.confirmed_by.strip(), "plan_fingerprint": self.plan_fingerprint,
                "output_journals": self.output_journals, "excluded_journals": self.excluded_journals,
                "acknowledged_not_full_migration": self.acknowledged_not_full_migration,
                "acknowledged_duplicate_check": self.acknowledged_duplicate_check,
                "acknowledged_excluded_follow_up": self.acknowledged_excluded_follow_up}


def manifest_path_for(output: Path) -> Path:
    return output.with_name(output.name + ".ready_only.json")


def excluded_list_path_for(output: Path) -> Path:
    return output.with_name(output.name + ".excluded.csv")


def run_paths(output: Path) -> tuple[Path, ...]:
    """Every file one READY-only run may create (none may exist beforehand; all go on failure)."""
    return (output, audit_path_for(output), pending_audit_path_for(output), excluded_list_path_for(output),
            manifest_path_for(output), _temp(manifest_path_for(output)), _temp(excluded_list_path_for(output)))


def _temp(path: Path) -> Path:
    return path.with_name(path.name + ".tmp")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _first_row(entry) -> int:
    rows = entry.metadata.get(ROW_ORDER_KEY) or ()
    return int(rows[0]) if rows else int(entry.source_reference.row_number)


def _side_total(entry, side: Side) -> Decimal:
    return sum((Decimal(line.amount) for line in entry.lines if line.side is side), Decimal(0))


def _settings(profile, context) -> dict:
    if context is None:
        return {}
    return {"jdl_product": context.product, "jdl_version": context.version,
            "tax_processing_mode": context.tax_processing_mode.value,
            "taxation_method": getattr(context.effective_taxation_method, "value", None),
            "input_tax_credit_method": getattr(context.effective_input_tax_credit_method, "value", None),
            "rounding": [context.sales_tax_rounding.value if context.sales_tax_rounding else None,
                         context.purchase_tax_rounding.value if context.purchase_tax_rounding else None],
            "voucher_row_limit": context.voucher_row_limit,
            "context_confirmed": context.confirmation_state.value,
            "split_policy_recorded": profile is not None and not voucher_split.policy_problems(profile, context)}


def plan_ready_only(source: Path, profile, context, company_setting_id: str | None,
                    workflow: YayoiJdlWorkflow | None = None) -> ReadyOnlyPlan:
    """Diagnose every journal (production assess, saved settings as they are) and split READY / excluded."""
    from accounting_converter.application.resolution_report import rule_for_code

    workflow = workflow or YayoiJdlWorkflow()
    source_format = (format_for_identity_key(profile.source_format_identity.stable_key) if profile is not None
                     else None) or detect_format(source)
    parsed = source_format.diagnose(source)
    assessment = workflow.assess(source, profile, context)
    entries = {entry.id: entry for entry in parsed.entries}
    problems = []
    if not parsed.ok or parsed.rejected_journals or assessment.parse_issue_codes:
        problems.append(PARSE_INCOMPLETE)
    ready_ids, excluded = [], []
    for entry in parsed.entries:
        found = assessment.journal_blockers.get(entry.id)
        if found is None:
            problems.append(COUNT_MISMATCH)
            continue
        if not found:
            ready_ids.append(entry.id)
            continue
        codes = tuple(sorted(found))
        excluded.append(ExcludedJournal(
            journal_id=entry.id, source_row=_first_row(entry), date=entry.date.isoformat(),
            voucher=str(entry.metadata.get("yayoi_voucher_number") or entry.source_reference.source_journal_id or ""),
            journal_numbers=tuple(str(n) for n in entry.metadata.get("yayoi_journal_numbers", ()) if n),
            debit_total=_side_total(entry, Side.DEBIT), credit_total=_side_total(entry, Side.CREDIT),
            blockers=codes, reasons=tuple(dict.fromkeys(rule_for_code(code).title for code in codes))))
        if set(codes) & COMPANY_WIDE_BLOCKERS:
            problems.append(COMPANY_SETTING_INCOMPLETE)
    if len(ready_ids) + len(excluded) != len(parsed.entries) or len(parsed.entries) != assessment.entry_count \
            or set(assessment.journal_blockers) != set(entries):
        problems.append(COUNT_MISMATCH)
    if not ready_ids:
        problems.append(NO_READY_JOURNAL)
    if not excluded and not problems:
        problems.append(NOTHING_EXCLUDED)

    def totals(items) -> dict:
        items = list(items)
        return {"debit": str(sum((_side_total(e, Side.DEBIT) for e in items), Decimal(0))),
                "credit": str(sum((_side_total(e, Side.CREDIT) for e in items), Decimal(0)))}

    dates = sorted(entry.date.isoformat() for entry in parsed.entries)
    return ReadyOnlyPlan(
        source_name=source.name, source_sha256=_sha256(source), company_setting_id=company_setting_id,
        profile_id=getattr(profile, "profile_id", None),
        profile_updated_at=profile.updated_at.isoformat() if getattr(profile, "updated_at", None) else None,
        settings=_settings(profile, context), total_journals=len(parsed.entries),
        ready_ids=tuple(ready_ids), ready_rows=tuple(_first_row(entries[i]) for i in ready_ids),
        excluded=tuple(excluded),
        totals={"all": totals(parsed.entries), "ready": totals(entries[i] for i in ready_ids),
                "excluded": totals(entries[e.journal_id] for e in excluded)},
        period=(dates[0], dates[-1]) if dates else None,
        problems=tuple(dict.fromkeys(problems)),
    )


def expected_vouchers(source: Path, profile, context, ready_ids) -> int:
    """JDL vouchers the READY journals become (an approved split writes one journal as several vouchers)."""
    source_format = format_for_identity_key(profile.source_format_identity.stable_key) or detect_format(source)
    entries = [entry for entry in source_format.read(source) if entry.id in set(ready_ids)]
    return len(voucher_split.apply_split(closing_entries.mark_closing(entries, profile, context), profile, context))


def prepare_ready_only(plan: ReadyOnlyPlan, confirmation: ReadyOnlyConfirmation | None, *, input_path: Path,
                       output_path: Path, profile, context, company_setting_validated: bool,
                       workflow: YayoiJdlWorkflow | None = None) -> FirstReleasePreparedConversion:
    workflow = workflow or YayoiJdlWorkflow()
    reasons: list[str] = []
    current = plan_ready_only(input_path, profile, context, plan.company_setting_id, workflow)
    reasons.extend(PROBLEM_MESSAGES.get(code, code) for code in current.problems)
    if current.fingerprint != plan.fingerprint:
        reasons.append("診断結果が変わりました（入力ファイルまたは会社設定）。もう一度診断して確認してください。")
    if confirmation is None:
        reasons.append("READYのみ変換の最終確認がありません。")
    else:
        reasons.extend(confirmation.problems(current))
    if profile is None or context is None or not company_setting_validated:
        reasons.append("会社設定を確認できません。")
    if any(path.exists() for path in run_paths(output_path)):
        reasons.append("既存のファイル（CSV・監査記録・除外一覧）は上書きしません。別の保存先を選択してください。")
    summary = FirstReleaseSummary(
        readiness=FirstReleaseReadiness.BLOCKED if reasons else FirstReleaseReadiness.READY,
        blocking_reasons=tuple(dict.fromkeys(reasons)),
        source_name=input_path.name,
        source_format="弥生（READYのみ変換・全件移行ではありません）",
        profile_name=getattr(profile, "profile_name", None),
    )
    if reasons:
        return FirstReleasePreparedConversion(summary)
    assessment = workflow.assess(input_path, profile, context)
    request, service = workflow.formal_service(input_path, output_path, profile, context, assessment,
                                               only_journals=frozenset(current.ready_ids))
    return FirstReleasePreparedConversion(summary, request, service)


@dataclass(frozen=True)
class ReadyOnlyResult:
    status: str                      # SUCCESS / FAILED
    output_path: Path | None
    manifest_path: Path | None
    excluded_list_path: Path | None
    audit_path: Path | None
    output_journals: int
    output_vouchers: int
    output_rows: int
    excluded_journals: int
    total_journals: int
    errors: tuple[str, ...] = ()


def _jdl_rows(path: Path) -> list[list[str]]:
    rows = list(csv.reader(io.StringIO(path.read_bytes().decode("cp932"), newline="")))
    return [row for row in rows if row and row[0].isdigit() and len(row) == 30]


def _vouchers(rows) -> int:
    return sum(1 for row in rows if row[0] in {"1111", "1101", "1000"})


def _excluded_csv(plan: ReadyOnlyPlan) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(EXCLUDED_HEADER)
    for item in plan.excluded:
        writer.writerow((item.source_row, item.date, item.voucher, " ".join(item.journal_numbers),
                         item.debit_total, item.credit_total, " / ".join(item.reasons), " ".join(item.blockers)))
    return buffer.getvalue().encode("utf-8-sig")


def _atomic_write(path: Path, data: bytes) -> None:
    temp = _temp(path)
    with temp.open("xb") as handle:
        handle.write(data)
    temp.replace(path)


def _cleanup(output: Path) -> None:
    for path in run_paths(output):
        path.unlink(missing_ok=True)


def execute_ready_only(prepared: FirstReleasePreparedConversion, plan: ReadyOnlyPlan,
                       confirmation: ReadyOnlyConfirmation) -> ReadyOnlyResult | None:
    if (prepared.summary.readiness is not FirstReleaseReadiness.READY or prepared.request is None
            or prepared.conversion_service is None):
        return None
    request = prepared.request
    source, output = Path(request.input_path), Path(request.output_path)
    profile, context = request.conversion_profile, request.target_runtime_context
    ready = frozenset(plan.ready_ids)
    try:
        begin_non_retained_audit(source, output, profile, context, journal_ids=ready)
        result = prepared.conversion_service.convert(request)
        if result.status.value != "SUCCESS" or result.output_path is None:
            _cleanup(output)
            return ReadyOnlyResult("FAILED", None, None, None, None, 0, 0, 0, plan.excluded_count,
                                   plan.total_journals, tuple(sorted({v.rule_id for v in result.validation_results
                                                                      if v.severity.value == "ERROR"})))
        finish_non_retained_audit(output)
        audit = verify_non_retained_audit(source, output, profile, context, journal_ids=ready)
        if audit["verdict"] not in {"PASS", "NOT_NEEDED"}:
            raise RuntimeError("audit record does not match the READY-only CSV")
        rows = _jdl_rows(output)
        vouchers = _vouchers(rows)
        debit = sum((Decimal(row[11] or 0) for row in rows if row[3]), Decimal(0))
        credit = sum((Decimal(row[21] or 0) for row in rows if row[13]), Decimal(0))
        expected = expected_vouchers(source, profile, context, plan.ready_ids)
        if vouchers != expected or str(debit) != plan.totals["ready"]["debit"] \
                or str(credit) != plan.totals["ready"]["credit"] \
                or result.output_journal_count != expected:
            raise RuntimeError("READY-only CSV does not match the READY journals (count or amount)")
        excluded_bytes = _excluded_csv(plan)
        _atomic_write(excluded_list_path_for(output), excluded_bytes)
        audit_path = audit_path_for(output) if audit_path_for(output).exists() else None
        manifest = {
            "schema": MANIFEST_SCHEMA, "mode": MODE, "full_migration": False,
            "not_migrated_journals": plan.excluded_count,
            "notes": list(FOLLOW_UP_NOTES),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": {"file": plan.source_name, "sha256": plan.source_sha256, "period": list(plan.period or ())},
            "company_setting_id": plan.company_setting_id, "profile_id": plan.profile_id,
            "profile_updated_at": plan.profile_updated_at, "settings": plan.settings,
            "counts": {"input_journals": plan.total_journals, "output_journals": plan.ready_count,
                       "excluded_journals": plan.excluded_count, "output_vouchers": vouchers,
                       "output_rows": len(rows)},
            "totals": plan.totals,
            "output": {"file": output.name, "sha256": _sha256(output)},
            "audit": {"file": audit_path.name, "sha256": _sha256(audit_path)} if audit_path else None,
            "excluded_list": {"file": excluded_list_path_for(output).name,
                              "sha256": hashlib.sha256(excluded_bytes).hexdigest()},
            "plan_fingerprint": plan.fingerprint,
            "confirmation": confirmation.record(),
            "ready_source_rows": list(plan.ready_rows),
            "excluded": [item.record() for item in plan.excluded],
        }
        _atomic_write(manifest_path_for(output),
                      (json.dumps(manifest, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    except Exception:
        _cleanup(output)  # never leave a CSV (or a list) without the manifest that binds the run
        raise
    return ReadyOnlyResult("SUCCESS", output, manifest_path_for(output), excluded_list_path_for(output), audit_path,
                           plan.ready_count, vouchers, len(rows), plan.excluded_count, plan.total_journals)


def ready_ids_from_manifest(manifest: dict, source: Path, profile) -> frozenset[str]:
    source_format = format_for_identity_key(profile.source_format_identity.stable_key) or detect_format(source)
    rows = set(manifest.get("ready_source_rows") or ())
    return frozenset(entry.id for entry in source_format.read(source) if _first_row(entry) in rows)


def _confirmation_ok(record, manifest: dict, plan: ReadyOnlyPlan) -> bool:
    """The recorded confirmation names this plan, these counts, the three acknowledgements and a person."""
    if not isinstance(record, dict):
        return False
    return (record.get("plan_fingerprint") == manifest.get("plan_fingerprint") == plan.fingerprint
            and (record.get("output_journals"), record.get("excluded_journals")) == (plan.ready_count, plan.excluded_count)
            and record.get("acknowledged_not_full_migration") is True
            and record.get("acknowledged_duplicate_check") is True
            and record.get("acknowledged_excluded_follow_up") is True
            and isinstance(record.get("confirmed_by"), str) and bool(record["confirmed_by"].strip()))


def verify_ready_only_output(source: Path, output: Path, profile, context, company_setting_id: str | None) -> dict:
    """Re-check a READY-only run: every file present and bound, counts and amounts, current diagnosis unchanged."""
    manifest_path = manifest_path_for(output)
    if not manifest_path.exists() or not output.exists():
        return {"verdict": "FAIL", "manifest_present": manifest_path.exists(), "output_present": output.exists()}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError:
        return {"verdict": "FAIL", "manifest_readable": False}
    plan = plan_ready_only(source, profile, context, company_setting_id)
    excluded_path = excluded_list_path_for(output)
    rows = _jdl_rows(output)
    counts = manifest.get("counts") or {}
    audit = manifest.get("audit")
    ready = ready_ids_from_manifest(manifest, source, profile)
    audit_check = verify_non_retained_audit(source, output, profile, context, journal_ids=ready)
    checks = {
        "schema_and_mode": manifest.get("schema") == MANIFEST_SCHEMA and manifest.get("mode") == MODE
        and manifest.get("full_migration") is False,
        "source_sha256": (manifest.get("source") or {}).get("sha256") == _sha256(source),
        "output_sha256": (manifest.get("output") or {}).get("sha256") == _sha256(output),
        "excluded_list_sha256": excluded_path.exists()
        and (manifest.get("excluded_list") or {}).get("sha256") == _sha256(excluded_path),
        "excluded_list_content": excluded_path.exists() and excluded_path.read_bytes() == _excluded_csv(plan),
        "audit_bound": (audit is None and audit_check["verdict"] == "NOT_NEEDED")
        or (audit is not None and audit_path_for(output).exists()
            and audit.get("sha256") == _sha256(audit_path_for(output)) and audit_check["verdict"] == "PASS"),
        "counts_add_up": counts.get("input_journals") == counts.get("output_journals", -1)
        + counts.get("excluded_journals", -1) == plan.total_journals,
        # The statements a reader relies on: not a full migration, how many are NOT migrated, what to do next, and
        # the user's recorded confirmation of exactly this plan. None of them may be edited without detection.
        "not_migrated_statement": manifest.get("not_migrated_journals") == counts.get("excluded_journals")
        == plan.excluded_count,
        "follow_up_notes": manifest.get("notes") == list(FOLLOW_UP_NOTES),
        "confirmation_recorded": _confirmation_ok(manifest.get("confirmation"), manifest, plan),
        "current_diagnosis_matches": manifest.get("plan_fingerprint") == plan.fingerprint,
        "excluded_equals_current_block": manifest.get("excluded") == [item.record() for item in plan.excluded],
        "ready_rows_equal": manifest.get("ready_source_rows") == list(plan.ready_rows) and len(ready) == plan.ready_count,
        "csv_vouchers": _vouchers(rows) == counts.get("output_vouchers")
        == expected_vouchers(source, profile, context, plan.ready_ids),
        "csv_rows": len(rows) == counts.get("output_rows"),
        "csv_amounts": str(sum((Decimal(r[11] or 0) for r in rows if r[3]), Decimal(0))) == plan.totals["ready"]["debit"]
        and str(sum((Decimal(r[21] or 0) for r in rows if r[13]), Decimal(0))) == plan.totals["ready"]["credit"],
    }
    return {"verdict": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
            "audit_verdict": audit_check["verdict"], "full_migration": False,
            "not_migrated_journals": counts.get("excluded_journals")}
