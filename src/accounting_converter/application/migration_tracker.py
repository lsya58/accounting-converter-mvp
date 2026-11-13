"""D2: the journals a READY-only run left out, tracked until each one is really in JDL (or recorded as not needed).
Phase 3 foundation: one verdict over the whole source (READY-only output + the tracked journals), never optimistic.

Input is a READY-only run that ``yayoi_ready_only.verify_ready_only_output`` still accepts (same source, company,
settings, untouched CSV / audit / excluded list / manifest). The tracker file binds those SHA-256s and lists every
excluded journal with its blockers. Each change is an event in a hash chain, so a status edited by hand (for example
to RECONCILED without the reconciliation record) is detected.

States (``STATES``). Planned / entered is NEVER done: RECONCILED needs a manual entry recorded first AND a Human's
reconciliation bound to the JDL re-export file (SHA-256) naming the JDL vouchers; NOT_REQUIRED needs the
approver, the reason and a reference. Nothing here matches journals automatically or by guess: the READY-only part
is checked only by the existing round-trip comparison (``tools/yayoi_roundtrip_check.check``).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from accounting_converter.domain.journal_identity import stable_journal_identity

SCHEMA = "yayoi-jdl-migration-tracker-v1"

NOT_STARTED = "NOT_STARTED"
PLANNING = "PLANNING"
AWAITING_TAX_ACCOUNTANT = "AWAITING_TAX_ACCOUNTANT"
AWAITING_TECHNICAL = "AWAITING_TECHNICAL"
MANUAL_ENTRY_PLANNED = "MANUAL_ENTRY_PLANNED"
MANUAL_ENTERED_UNRECONCILED = "MANUAL_ENTERED_UNRECONCILED"
RECONCILED = "RECONCILED"
NOT_REQUIRED = "NOT_REQUIRED"
STATES = {
    NOT_STARTED: "未対応", PLANNING: "対応方針の検討中", AWAITING_TAX_ACCOUNTANT: "税理士承認待ち",
    AWAITING_TECHNICAL: "技術対応待ち", MANUAL_ENTRY_PLANNED: "手入力予定",
    MANUAL_ENTERED_UNRECONCILED: "手入力済み・未照合", RECONCILED: "照合済み", NOT_REQUIRED: "対応不要（根拠・明示承認あり）",
}
OPEN_STATES = frozenset({NOT_STARTED, PLANNING, AWAITING_TAX_ACCOUNTANT, AWAITING_TECHNICAL, MANUAL_ENTRY_PLANNED})
CLOSED_STATES = frozenset({RECONCILED, NOT_REQUIRED})
# allowed (from -> to). Closed states are left only through reopen().
TRANSITIONS = {
    **{state: (OPEN_STATES | {MANUAL_ENTERED_UNRECONCILED, NOT_REQUIRED}) - {state} for state in OPEN_STATES},
    MANUAL_ENTERED_UNRECONCILED: frozenset({RECONCILED, PLANNING}),
    RECONCILED: frozenset(),
    NOT_REQUIRED: frozenset(),
}
EDITABLE_FIELDS = ("plan", "owner", "memo", "evidence_ids", "manual_entry_required")
CSV_HEADER = ("元の行", "伝票No.", "日付", "仕訳番号", "借方合計", "BLOCKコード", "BLOCK理由", "状態", "対応方針", "担当者",
              "対応メモ", "関連Evidence", "手入力が必要か", "JDL入力（伝票・日付・入力者）", "照合（再Export SHA-256・照合者・日時）",
              "最終確認者", "最終確認日時")

RECONCILED_VERDICTS = frozenset({"PASS", "PASS_WITH_ACCEPTED_NORMALIZATION"})


class TrackerError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(payload) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                     default=str).encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _parse_time(value):
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _required(*values) -> bool:
    return all(isinstance(v, str) and v.strip() for v in values)


def _entries(source: Path):
    from accounting_converter.application.yayoi_sources import detect_format

    return detect_format(source).diagnose(source).entries


def _baseline(source: Path, output: Path) -> dict:
    from accounting_converter.application import yayoi_ready_only as ro

    manifest_path = ro.manifest_path_for(output)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {"source_sha256": _file_sha(source), "output_file": output.name, "output_sha256": _file_sha(output),
            "manifest_sha256": _file_sha(manifest_path), "excluded_list_sha256": _file_sha(ro.excluded_list_path_for(output)),
            "plan_fingerprint": manifest.get("plan_fingerprint"), "company_setting_id": manifest.get("company_setting_id"),
            "profile_id": manifest.get("profile_id"), "counts": manifest.get("counts"),
            "period": (manifest.get("source") or {}).get("period")}


def create_tracker(source: Path, output: Path, profile, context, company_id: str, *, created_by: str) -> dict:
    """A new tracker for one READY-only run (refused unless the run still verifies for this company)."""
    from accounting_converter.application import yayoi_ready_only as ro
    from accounting_converter.application.yayoi_ready_only import _first_row

    if not _required(created_by):
        raise TrackerError("作成者の名前が必要です")
    verification = ro.verify_ready_only_output(source, output, profile, context, company_id)
    if verification["verdict"] != "PASS":
        failed = sorted(k for k, v in (verification.get("checks") or {}).items() if not v) or sorted(verification)
        raise TrackerError("READY-only出力の検証に失敗しました（改変・会社・設定・元データの不一致）: " + ", ".join(failed))
    baseline = _baseline(source, output)
    if baseline["company_setting_id"] != company_id:
        raise TrackerError("READY-only出力の会社IDが一致しません")
    manifest = json.loads(ro.manifest_path_for(output).read_text(encoding="utf-8"))
    by_row = {}
    for entry in _entries(source):
        by_row.setdefault(_first_row(entry), []).append(entry)
    journals = []
    for item in manifest["excluded"]:
        found = by_row.get(item["source_row"], [])
        if len(found) != 1:
            raise TrackerError(f"除外仕訳 {item['source_row']} を元データで一意に特定できません")
        journal = {
            "source_row": item["source_row"], "journal_sha256": stable_journal_identity(found[0]) or "",
            "voucher": item["voucher"], "date": item["date"], "journal_numbers": item["journal_numbers"],
            "debit_total": item["debit_total"], "credit_total": item["credit_total"],
            "blockers": item["blockers"], "reasons": item["reasons"],
            "status": NOT_STARTED, "plan": "", "owner": "", "memo": "", "evidence_ids": [],
            "manual_entry_required": None, "jdl_entry": None, "reconciliation": None, "not_required": None,
            "final_checker": "", "final_checked_at": "", "history": [],
        }
        _event(journal, {"event": "CREATED", "by": created_by.strip(), "status": NOT_STARTED})
        journals.append(journal)
    return {"schema": SCHEMA, "company_id": company_id, "created_at": _now(), "created_by": created_by.strip(),
            "baseline": baseline, "full_migration": False, "journals": journals}


def _event(journal: dict, body: dict) -> None:
    history = journal["history"]
    event = {"at": _now(), "prev": history[-1]["sha256"] if history else "", **body}
    event["sha256"] = _sha({k: v for k, v in event.items() if k != "sha256"})
    history.append(event)


def _find(tracker: dict, source_row: int) -> dict:
    found = [j for j in tracker["journals"] if j["source_row"] == source_row]
    if len(found) != 1:
        raise TrackerError(f"管理表に元の行 {source_row} がありません（または重複しています）")
    return found[0]


def update_fields(tracker: dict, source_row: int, *, by: str, **fields) -> dict:
    if not _required(by):
        raise TrackerError("更新者の名前が必要です")
    unknown = set(fields) - set(EDITABLE_FIELDS)
    if unknown:
        raise TrackerError("変更できない項目です: " + ", ".join(sorted(unknown)))
    journal = _find(tracker, source_row)
    journal.update(fields)
    _event(journal, {"event": "FIELDS", "by": by.strip(), "fields": fields, "status": journal["status"]})
    return journal


def set_status(tracker: dict, source_row: int, status: str, *, by: str, note: str = "", jdl_entry: dict | None = None,
               reconciliation: dict | None = None, reexport_path: Path | None = None,
               not_required: dict | None = None) -> dict:
    """Move one journal to `status`, only along TRANSITIONS and only with what that state needs."""
    if status not in STATES:
        raise TrackerError(f"不明な状態です: {status}")
    if not _required(by):
        raise TrackerError("更新者の名前が必要です")
    journal = _find(tracker, source_row)
    current = journal["status"]
    if status not in TRANSITIONS[current]:
        raise TrackerError(f"{STATES[current]} から {STATES[status]} へは変更できません")
    extra = {}
    if status == MANUAL_ENTERED_UNRECONCILED:
        if not isinstance(jdl_entry, dict) or not _required(*(str(jdl_entry.get(k, "")) for k in
                                                             ("jdl_vouchers", "jdl_date", "entered_by", "entered_at"))):
            raise TrackerError("手入力済みには、JDLの伝票番号・日付・入力者・入力日時が必要です")
        others = [j for j in tracker["journals"] if j is not journal and j.get("jdl_entry")
                  and set(str(j["jdl_entry"]["jdl_vouchers"]).split()) & set(str(jdl_entry["jdl_vouchers"]).split())
                  and j["jdl_entry"].get("jdl_date") == jdl_entry.get("jdl_date")]
        if others:
            raise TrackerError("同じJDL伝票が別の元仕訳の入力として記録されています（重複処理の疑い）")
        extra["jdl_entry"] = dict(jdl_entry)
    if status == RECONCILED:
        if journal.get("jdl_entry") is None:
            raise TrackerError("照合済みにするには、先にJDLでの入力（手入力済み）の記録が必要です")
        if reexport_path is None or not Path(reexport_path).exists():
            raise TrackerError("照合済みにするには、JDL再Exportファイルが必要です（SHA-256を記録します）")
        if not isinstance(reconciliation, dict) or not _required(*(str(reconciliation.get(k, "")) for k in
                                                                   ("matched_jdl_vouchers", "checked_by", "checked_at",
                                                                    "method_reference"))):
            raise TrackerError("照合済みには、照合したJDL伝票・照合者・照合日時・照合方法（資料）の記録が必要です")
        if set(str(reconciliation["matched_jdl_vouchers"]).split()) != set(str(journal["jdl_entry"]["jdl_vouchers"]).split()):
            raise TrackerError("照合したJDL伝票が、手入力として記録した伝票と一致しません")
        if _parse_time(reconciliation["checked_at"]) is None or _parse_time(journal["jdl_entry"]["entered_at"]) is None \
                or _parse_time(reconciliation["checked_at"]) < _parse_time(journal["jdl_entry"]["entered_at"]):
            raise TrackerError("照合日時は、JDLへの入力日時より後（同時刻を含む）の有効な日時が必要です")
        extra["reconciliation"] = {**reconciliation, "jdl_reexport_file": Path(reexport_path).name,
                                   "jdl_reexport_sha256": _file_sha(reexport_path),
                                   "bound_journal_sha256": journal["journal_sha256"]}
        extra["final_checker"], extra["final_checked_at"] = reconciliation["checked_by"], reconciliation["checked_at"]
    if status == NOT_REQUIRED:
        if not isinstance(not_required, dict) or not _required(*(str(not_required.get(k, "")) for k in
                                                                 ("approved_by", "approved_at", "reason", "reference"))):
            raise TrackerError("対応不要には、承認者・承認日時・理由・根拠資料の参照が必要です")
        extra["not_required"] = dict(not_required)
        extra["final_checker"], extra["final_checked_at"] = not_required["approved_by"], not_required["approved_at"]
    if status == PLANNING and current == MANUAL_ENTERED_UNRECONCILED:
        extra["jdl_entry"] = None  # the recorded entry was wrong: it no longer counts
    journal.update(extra)
    journal["status"] = status
    _event(journal, {"event": "STATUS", "by": by.strip(), "from": current, "status": status, "note": note,
                     **{k: v for k, v in extra.items() if k in ("jdl_entry", "reconciliation", "not_required")}})
    return journal


def reopen(tracker: dict, source_row: int, *, by: str, reason: str) -> dict:
    journal = _find(tracker, source_row)
    if journal["status"] not in CLOSED_STATES:
        raise TrackerError("照合済み・対応不要の仕訳だけを戻せます")
    if not _required(by, reason):
        raise TrackerError("戻す人と理由が必要です")
    current = journal["status"]
    journal.update(status=PLANNING, reconciliation=None, not_required=None, jdl_entry=None, final_checker="",
                   final_checked_at="")
    _event(journal, {"event": "REOPEN", "by": by.strip(), "from": current, "status": PLANNING, "note": reason})
    return journal


def save(tracker: dict, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(tracker, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    temp.replace(path)


def load(path: Path) -> dict:
    tracker = json.loads(Path(path).read_text(encoding="utf-8"))
    if tracker.get("schema") != SCHEMA:
        raise TrackerError("未移行管理表の形式が違います")
    return tracker


# ---------------------------------------------------------------- integrity
def _history_problems(journal: dict) -> list[str]:
    problems, previous, status = [], "", None
    entered = 0
    for event in journal.get("history") or ():
        if event.get("prev") != previous or event.get("sha256") != _sha({k: v for k, v in event.items() if k != "sha256"}):
            problems.append("HISTORY_TAMPERED")
            break
        previous, status = event["sha256"], event.get("status")
        if event.get("status") == MANUAL_ENTERED_UNRECONCILED and event.get("event") == "STATUS":
            entered += 1
        if event.get("event") in ("REOPEN",) or (event.get("event") == "STATUS" and event.get("from") ==
                                                 MANUAL_ENTERED_UNRECONCILED and event.get("status") == PLANNING):
            entered = 0
    if not journal.get("history"):
        problems.append("HISTORY_MISSING")
    elif status != journal.get("status"):
        problems.append("STATUS_NOT_IN_HISTORY")  # edited by hand
    if entered > 1:
        problems.append("ENTERED_MORE_THAN_ONCE")
    if journal.get("status") == RECONCILED:
        rec, entry = journal.get("reconciliation") or {}, journal.get("jdl_entry") or {}
        if rec.get("bound_journal_sha256") != journal.get("journal_sha256"):
            problems.append("RECONCILIATION_NOT_BOUND_TO_THIS_JOURNAL")
        if not (_required(*(str(rec.get(k, "")) for k in ("matched_jdl_vouchers", "checked_by", "checked_at",
                                                           "method_reference", "jdl_reexport_sha256")))
                and _required(*(str(entry.get(k, "")) for k in ("jdl_vouchers", "jdl_date", "entered_by", "entered_at")))):
            problems.append("RECONCILED_WITHOUT_EVIDENCE")
    if journal.get("status") == NOT_REQUIRED and not _required(*(str((journal.get("not_required") or {}).get(k, ""))
                                                                for k in ("approved_by", "approved_at", "reason", "reference"))):
        problems.append("NOT_REQUIRED_WITHOUT_APPROVAL")
    if journal.get("status") not in STATES:
        problems.append("UNKNOWN_STATUS")
    return problems


def check(tracker: dict, source: Path, output: Path, profile, context, company_id: str) -> dict:
    """Every source journal accounted for exactly once; the tracker bound to the run it was made from."""
    from accounting_converter.application import yayoi_ready_only as ro
    from accounting_converter.application.yayoi_ready_only import _first_row

    problems: dict[str, list] = {k: [] for k in (
        "company", "ready_only_run", "baseline", "duplicates_in_tracker", "ready_and_tracked", "missing_from_both",
        "excluded_not_tracked", "tracked_not_excluded", "source_identity_not_unique", "journal_history",
        "jdl_voucher_reused")}
    if tracker.get("company_id") != company_id:
        problems["company"].append(tracker.get("company_id"))
    verification = ro.verify_ready_only_output(source, output, profile, context, company_id)
    if verification["verdict"] != "PASS":
        problems["ready_only_run"] = sorted(k for k, v in (verification.get("checks") or {}).items() if not v) or ["FAIL"]
    manifest_path = ro.manifest_path_for(output)
    current = _baseline(source, output) if manifest_path.exists() and output.exists() else {}
    for key, value in (tracker.get("baseline") or {}).items():
        if current.get(key) != value:
            problems["baseline"].append(key)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    entries = _entries(source)
    rows = [_first_row(entry) for entry in entries]
    shas = Counter(stable_journal_identity(entry) for entry in entries)
    problems["source_identity_not_unique"] = sorted(r for r, e in zip(rows, entries) if shas[stable_journal_identity(e)] != 1)
    ready = set(manifest.get("ready_source_rows") or ())
    excluded = {item["source_row"] for item in manifest.get("excluded") or ()}
    tracked = Counter(j["source_row"] for j in tracker.get("journals") or ())
    tracked_sha = Counter(j.get("journal_sha256") for j in tracker.get("journals") or ())
    problems["duplicates_in_tracker"] = sorted({r for r, n in tracked.items() if n > 1}
                                               | {j["source_row"] for j in tracker.get("journals") or ()
                                                  if tracked_sha[j.get("journal_sha256")] > 1})
    problems["ready_and_tracked"] = sorted(ready & set(tracked))
    problems["missing_from_both"] = sorted(set(rows) - ready - set(tracked))
    problems["excluded_not_tracked"] = sorted(excluded - set(tracked))
    problems["tracked_not_excluded"] = sorted(set(tracked) - excluded)
    by_row = dict(zip(rows, entries))
    used: dict = {}
    for journal in tracker.get("journals") or ():
        found = _history_problems(journal)
        entry = by_row.get(journal["source_row"])
        if entry is None or stable_journal_identity(entry) != journal.get("journal_sha256"):
            found.append("SOURCE_JOURNAL_CHANGED")
        if found:
            problems["journal_history"].append({"source_row": journal["source_row"], "problems": found})
        if journal.get("jdl_entry"):
            for voucher in str(journal["jdl_entry"].get("jdl_vouchers", "")).split():
                used.setdefault((journal["jdl_entry"].get("jdl_date"), voucher), []).append(journal["source_row"])
    problems["jdl_voucher_reused"] = [{"jdl": list(k), "source_rows": v} for k, v in used.items() if len(v) > 1]
    states = Counter(j.get("status") for j in tracker.get("journals") or ())
    return {"verdict": "PASS" if not any(problems.values()) else "FAIL", "problems": problems,
            "counts": {"source_journals": len(entries), "ready_only_output": len(ready), "tracked": sum(tracked.values()),
                       "by_status": {STATES.get(k, k): v for k, v in sorted(states.items())}},
            "full_migration": False}


def journal_table(tracker: dict, source: Path, output: Path) -> list[dict]:
    """Where each of the source journals is now (all of them, in source order). Read-only."""
    from accounting_converter.application import yayoi_ready_only as ro
    from accounting_converter.application.yayoi_ready_only import _first_row

    manifest = json.loads(ro.manifest_path_for(output).read_text(encoding="utf-8"))
    ready = set(manifest.get("ready_source_rows") or ())
    tracked = {j["source_row"]: j for j in tracker["journals"]}
    out = []
    for entry in _entries(source):
        row = _first_row(entry)
        if row in ready:
            where = "READY-only出力済み（新CSVのJDL実機照合は未実施なら未確認）"
        elif row in tracked:
            where = "未移行管理: " + STATES.get(tracked[row]["status"], tracked[row]["status"])
        else:
            where = "行方不明（出力にも管理表にもない）"
        out.append({"source_row": row, "date": entry.date.isoformat(),
                    "voucher": str(entry.metadata.get("yayoi_voucher_number") or ""), "where": where})
    return out


def to_csv(tracker: dict) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(CSV_HEADER)
    for j in tracker["journals"]:
        entry, rec = j.get("jdl_entry") or {}, j.get("reconciliation") or {}
        writer.writerow((
            j["source_row"], j["voucher"], j["date"], " ".join(j["journal_numbers"]), j["debit_total"],
            " ".join(j["blockers"]), " / ".join(j["reasons"]), STATES.get(j["status"], j["status"]), j["plan"], j["owner"],
            j["memo"], " ".join(j["evidence_ids"]),
            {None: "未定", True: "必要", False: "不要"}.get(j["manual_entry_required"], ""),
            " ".join(str(entry.get(k, "")) for k in ("jdl_vouchers", "jdl_date", "entered_by")) if entry else "",
            " ".join(str(rec.get(k, "")) for k in ("jdl_reexport_sha256", "checked_by", "checked_at")) if rec else "",
            j["final_checker"], j["final_checked_at"]))
    return buffer.getvalue().encode("utf-8-sig")


# ---------------------------------------------------------------- Phase 3: final reconciliation (foundation)
def tracker_state_sha256(tracker: dict) -> str:
    """The tracker's state that a final record must name: change any journal and an older record no longer fits."""
    return _sha([[j["source_row"], j["journal_sha256"], j["status"], j.get("jdl_entry"), j.get("reconciliation"),
                  j.get("not_required")] for j in tracker.get("journals") or ()])


def ready_only_roundtrip(source: Path, output: Path, reexport: Path, profile, context, company_id: str,
                         acceptance: Path | None = None) -> dict:
    """The EXISTING round-trip comparison of the READY-only CSV against a JDL re-export, bound by SHA-256 to the
    source, the manifest and the company (a result about one run can never be used for another)."""
    from accounting_converter.application import yayoi_ready_only as ro
    from accounting_converter.tools.yayoi_roundtrip_check import check as roundtrip_check

    manifest = json.loads(ro.manifest_path_for(output).read_text(encoding="utf-8"))
    ids = ro.ready_ids_from_manifest(manifest, source, profile)
    result = roundtrip_check(source, profile, context, output, reexport, company_setting_id=company_id,
                             acceptance=acceptance, journal_ids=ids)
    return {"candidate_sha256": _file_sha(output), "reexport_sha256": _file_sha(reexport),
            "source_sha256": _file_sha(source), "manifest_sha256": _file_sha(ro.manifest_path_for(output)),
            "company_id": company_id, "verdict": result["verdict"],
            "verdict_jdl_roundtrip": result["verdict_jdl_roundtrip"]}


def _roundtrip_problems(tracker: dict, roundtrip: dict | None) -> list[str]:
    if roundtrip is None:
        return ["READY-only出力のJDL実機往復照合が未実施"]
    base = tracker.get("baseline") or {}
    mismatched = [k for k, expected in (("candidate_sha256", base.get("output_sha256")),
                                        ("source_sha256", base.get("source_sha256")),
                                        ("manifest_sha256", base.get("manifest_sha256")),
                                        ("company_id", tracker.get("company_id"))) if roundtrip.get(k) != expected]
    if mismatched or not roundtrip.get("reexport_sha256"):
        return ["往復照合が、この管理表のREADY-only出力・元データ・会社と一致しない: " + ", ".join(mismatched or ["reexport_sha256"])]
    if roundtrip.get("verdict") not in RECONCILED_VERDICTS:
        return [f"READY-only出力の往復照合が合格していない（{roundtrip.get('verdict')}）"]
    return []


def _trial_balance_problems(tracker: dict, trial_balance) -> list[str]:
    """Who checked, when, which company and period, on what document, and for exactly this tracker state."""
    if not isinstance(trial_balance, dict) or not _required(*(str(trial_balance.get(k, "")) for k in (
            "checked_by", "checked_at", "reference", "company_id", "period_start", "period_end"))):
        return ["弥生とJDLの試算表（科目別）の一致確認が未記録（確認者・日時・会社・対象期間・根拠資料が必要）"]
    base_period = (tracker.get("baseline") or {}).get("period") or []
    problems = []
    if trial_balance["company_id"] != tracker.get("company_id"):
        problems.append("試算表の確認が別の会社のものです")
    if [trial_balance["period_start"], trial_balance["period_end"]] != list(base_period):
        problems.append("試算表の確認の対象期間が、移行対象の期間と一致しません")
    if trial_balance.get("tracker_state_sha256") != tracker_state_sha256(tracker):
        problems.append("試算表の確認が、現在の未移行管理表の状態を対象にしていません（その後に管理表が変更された）")
    checked = _parse_time(trial_balance["checked_at"])
    last = max((t for t in (_parse_time(j.get("final_checked_at")) for j in tracker["journals"]) if t is not None),
               default=None)
    if checked is None or (last is not None and checked < last):
        problems.append("試算表の確認日時が無効、または最後の照合・承認より前です")
    return problems


def final_reconciliation(tracker: dict, integrity: dict, *, roundtrip: dict | None = None,
                         trial_balance: dict | None = None) -> dict:
    """MIGRATION_COMPLETE only when every part is proven; otherwise MIGRATION_INCOMPLETE with every reason."""
    reasons = []
    if integrity.get("verdict") != "PASS":
        reasons.append("整合チェックがFAIL（漏れ・重複・改変・不一致）")
    reasons.extend(_roundtrip_problems(tracker, roundtrip))
    open_rows = [j["source_row"] for j in tracker["journals"] if j["status"] not in CLOSED_STATES]
    if open_rows:
        reasons.append(f"未移行の仕訳が{len(open_rows)}件残っている")
    reasons.extend(_trial_balance_problems(tracker, trial_balance))
    return {"verdict": "MIGRATION_INCOMPLETE" if reasons else "MIGRATION_COMPLETE", "reasons": reasons,
            "open_journals": open_rows, "tracker_state_sha256": tracker_state_sha256(tracker),
            "closed_journals": len(tracker["journals"]) - len(open_rows), "full_migration": not reasons}


# ---------------------------------------------------------------- opening a READY-only run without picking files
TRACKER_SUFFIX = ".migration_tracker.json"
MANIFEST_SUFFIX = ".ready_only.json"

CHECK_MESSAGES = {
    "schema_and_mode": "READY-only出力の記録（manifest）の形式・種別が違います（改変の可能性）",
    "source_sha256": "元データが、READY-only出力を作った時から変わっています",
    "output_sha256": "出力CSVが変更されています（manifestのSHA-256と一致しません）",
    "excluded_list_sha256": "除外一覧が変更されています", "excluded_list_content": "除外一覧の内容が現在の診断と一致しません",
    "audit_bound": "監査記録が出力CSVと一致しません", "counts_add_up": "manifestの件数が合いません（改変の可能性）",
    "not_migrated_statement": "manifestの未移行件数の記載が改変されています",
    "follow_up_notes": "manifestの注意書きが改変されています", "confirmation_recorded": "manifestの確認記録が不正です",
    "current_diagnosis_matches": "現在の診断が、出力を作った時の診断と一致しません（会社設定・承認・元データが変わった可能性）",
    "excluded_equals_current_block": "未移行の一覧が、現在のBLOCKと一致しません",
    "ready_rows_equal": "出力対象の行が、現在のREADYと一致しません",
    "csv_vouchers": "出力CSVの伝票数がmanifestと一致しません", "csv_rows": "出力CSVの行数がmanifestと一致しません",
    "csv_amounts": "出力CSVの金額がmanifestと一致しません",
}


def tracker_path_for(output: Path) -> Path:
    """Where a run's tracker lives: next to its CSV, with a fixed suffix (never guessed from similar names)."""
    return Path(output).with_name(Path(output).name + TRACKER_SUFFIX)


def explain_failed_checks(verification: dict) -> list[str]:
    if verification.get("manifest_present") is False or verification.get("output_present") is False:
        return ["出力CSVまたはmanifest（.ready_only.json）が見つかりません"]
    if verification.get("manifest_readable") is False:
        return ["manifest（.ready_only.json）を読めません"]
    failed = [key for key, ok in (verification.get("checks") or {}).items() if not ok]
    return [CHECK_MESSAGES.get(key, f"検証項目 {key} が一致しません") for key in failed] or ["検証に失敗しました"]


@dataclass(frozen=True)
class RunCandidate:
    output: Path
    manifest: Path
    accepted: bool
    reason: str            # why it is not offered ("" when accepted)
    counts: dict


def discover_runs(folder: Path, company_id: str, source_sha256: str) -> tuple[RunCandidate, ...]:
    """READY-only runs in ONE folder: only `<csv>.ready_only.json` files the app itself writes, paired with the CSV of
    exactly that name. A run is offered only when its manifest names this company and this exact source file; the full
    SHA / audit verification still happens when it is opened. Nothing is matched by similar names."""
    found = []
    for manifest in sorted(Path(folder).glob("*" + MANIFEST_SUFFIX)):
        output = manifest.with_name(manifest.name[: -len(MANIFEST_SUFFIX)])
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            found.append(RunCandidate(output, manifest, False, "manifestを読めません", {}))
            continue
        counts = data.get("counts") or {}
        if not output.exists():
            reason = "対応する出力CSVがありません"
        elif data.get("schema") != "yayoi-jdl-ready-only-v1":
            reason = "READY-only出力の記録ではありません"
        elif data.get("company_setting_id") != company_id:
            reason = "別の会社の出力です"
        elif (data.get("source") or {}).get("sha256") != source_sha256:
            reason = "読み込み中の元データと一致しません（元データが違う、または変更されています）"
        else:
            reason = ""
        found.append(RunCandidate(output, manifest, not reason, reason, counts))
    return tuple(found)


def open_run(source: Path, output: Path, profile, context, company_id: str) -> dict:
    """Verify a READY-only run with the existing checks, then load its tracker only if it belongs to exactly this run.

    state: REJECTED (the run does not verify) / NO_TRACKER / TRACKER_INVALID / TRACKER_MISMATCH / TRACKED.
    Never creates, repairs or overwrites anything."""
    from accounting_converter.application import yayoi_ready_only as ro

    verification = ro.verify_ready_only_output(source, output, profile, context, company_id)
    result = {"output": output, "tracker_path": tracker_path_for(output), "tracker": None, "integrity": None,
              "final": None, "problems": []}
    if verification["verdict"] != "PASS":
        return {**result, "state": "REJECTED", "problems": explain_failed_checks(verification)}
    path = result["tracker_path"]
    if not path.exists():
        return {**result, "state": "NO_TRACKER"}
    try:
        tracker = load(path)
    except (OSError, ValueError):
        return {**result, "state": "TRACKER_INVALID", "problems": ["管理表を読めません、または形式が違います"]}
    integrity = check(tracker, source, output, profile, context, company_id)
    result.update(tracker=tracker, integrity=integrity)
    if integrity["verdict"] != "PASS":
        problems = [f"{key}: {value}" for key, value in integrity["problems"].items() if value]
        return {**result, "state": "TRACKER_MISMATCH", "tracker": None,
                "problems": ["この出力と対応しない管理表です（使いません）", *problems]}
    return {**result, "state": "TRACKED", "final": final_reconciliation(tracker, integrity)}


def start_tracking(source: Path, output: Path, profile, context, company_id: str, *, created_by: str) -> Path:
    """The explicit start of status management: verify the run, write the tracker next to the CSV, never overwrite."""
    path = tracker_path_for(output)
    if path.exists():
        raise TrackerError("管理表が既に存在します。上書き・初期化はしません（開いて確認してください）。")
    tracker = create_tracker(source, output, profile, context, company_id, created_by=created_by)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("xb") as handle:      # exclusive: a leftover temp file stops the start instead of being replaced
        handle.write((json.dumps(tracker, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    if path.exists():
        temp.unlink(missing_ok=True)
        raise TrackerError("管理表が同時に作成されました。上書きはしません。")
    temp.replace(path)
    return path
