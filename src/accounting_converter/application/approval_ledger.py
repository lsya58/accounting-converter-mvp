"""D0: the tax accountant's decisions for one company — pending items, a what-if preview, an append-only ledger and
a guarded apply step that only calls the EXISTING approval paths. Nothing here approves anything by itself.

What already exists (and is reused, never duplicated):
  - 伝票分割V1: ``voucher_split.approve_split_policy`` (company + row limit, now with a required scope).
  - 控除不可:   ``noncredit_approval.approve_noncredit_identity`` (named journals only, judged sign-off required).
  - 摘要末尾空白: ``tools/jdl_description_trailing_space_acceptance`` (bound to one round trip's record). The ledger can
    hold the decision as a note, but never writes the acceptance: that stays the Human's own tool run.
  - what-if profiles carry ``noncredit_approval.TRIAL_MARKER``; ``ConversionProfileStore`` refuses to save them.

Integrity of the ledger: every entry carries the SHA-256 of the previous one, so an edited or reordered line, a
foreign company and a wrong sequence are detected. It is NOT an electronic signature: anyone who can write the file
can rebuild a consistent chain, and deleting the LAST lines is not detectable from the file alone (each APPLIED entry
therefore also stamps the approval inside the company setting, and `unrecorded_approvals` reports approvals found in
a setting that no ledger entry explains). Treat it as a tamper-evident work log, not as proof against a malicious user.

Every route that writes an approval into a company setting must leave a ledger entry: the ledger's own `apply`, and
the three older routes (screen, voucher-split CLI, 控除不可 CLI) through ``approve_split_direct`` /
``approve_noncredit_direct`` (DIRECT_APPLIED entries). The low-level functions (voucher_split.approve_split_policy,
noncredit_approval.approve_noncredit_identity) stay callable for tests and tools; a setting changed outside these
routes (hand-edited or imported profile) shows up in ``unrecorded_approvals``.

Layers (each one explicit):
  1. ``pending_items``  read-only: what is waiting for a decision, derived from the production diagnosis.
  2. ``preview``        read-only: production ``assess`` on the saved setting and on an IN-MEMORY trial copy with
                        the hypothetical approvals; compared journal by journal (never by adding up class counts).
  3. ``ApprovalLedger.record_decision``  appends APPROVED / REJECTED / ON_HOLD / REVOKED to a hash-chained JSONL file.
                        It does not touch the company setting.
  4. ``apply_decision`` / ``revoke_applied``  write the company setting through the existing functions, only for an
                        APPROVED decision of an applicable kind, after checking company, source, settings and the
                        preview the user confirmed; with a backup, a post-check (restored on mismatch) and an audit entry.
                        A production store (Windows AppData) is refused unless the caller says so explicitly.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from pathlib import Path

from accounting_converter.application import noncredit_approval as nc
from accounting_converter.application import voucher_split as vs
from accounting_converter.domain.journal_identity import stable_journal_identity
from accounting_converter.domain.mapping import MappingStatus, MappingValue

LEDGER_SCHEMA = "approval-ledger-v1"

KIND_SPLIT = "VOUCHER_SPLIT_V1"
KIND_NONCREDIT = "NONCREDIT_JOURNAL"
KIND_TRAILING_SPACE = "DESCRIPTION_TRAILING_SPACE"
KIND_POLICY = "OPERATING_POLICY"        # recorded only: no conversion effect, never extended to other lines
APPLICABLE_KINDS = frozenset({KIND_SPLIT, KIND_NONCREDIT})
RECORD_ONLY_MESSAGE = {
    KIND_TRAILING_SPACE: "摘要末尾空白の許容は、往復照合の記録に紐づく既存ツール jdl_description_trailing_space_acceptance を"
                         "Human自身が実行して記録します。この台帳からは記録しません。",
    KIND_POLICY: "運用方針は記録のみです。変換には使われず、他の明細・仕訳に自動で当てはめません。",
}

APPROVED, REJECTED, ON_HOLD, REVOKED = "APPROVED", "REJECTED", "ON_HOLD", "REVOKED"
DECISIONS = (APPROVED, REJECTED, ON_HOLD, REVOKED)
DECISION_LABELS = {None: "未判断", APPROVED: "承認", REJECTED: "不承認", ON_HOLD: "保留", REVOKED: "取り消し"}

TRAILING_SPACE_EVIDENCE_PREFIX = "EVID-"


class ApprovalError(ValueError):
    pass


def _sha(payload) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------- items
@dataclass(frozen=True)
class Target:
    label: str                 # journal number shown on screen (people only)
    journal_sha256: str        # content identity (matching)
    source_row: int
    voucher: str
    date: str
    lines: tuple[int, ...] = ()  # rows a policy / sign-off is about (empty = whole journal)

    def record(self) -> dict:
        return {"label": self.label, "journal_sha256": self.journal_sha256, "source_row": self.source_row,
                "voucher": self.voucher, "date": self.date, "lines": list(self.lines)}


@dataclass(frozen=True)
class ApprovalItem:
    item_id: str
    kind: str
    company_id: str
    period: tuple[str, str] | None
    jdl_version: str | None
    voucher_row_limit: int | None
    targets: tuple[Target, ...]
    change: str                          # what the approval would change
    evidence_ids: tuple[str, ...]
    default_scope: dict                  # what the approval covers unless the decision states otherwise
    identity: str | None = None          # 控除不可: the Yayoi tax identity
    references: tuple[str, ...] = ()     # files the decision is about (sha256 bound)
    note: str = ""

    @property
    def applies_to_conversion(self) -> bool:
        return self.kind in APPLICABLE_KINDS

    @property
    def fingerprint(self) -> str:
        return _sha({"item": self.item_id, "kind": self.kind, "company": self.company_id, "period": self.period,
                     "jdl_version": self.jdl_version, "row_limit": self.voucher_row_limit,
                     "targets": [t.record() for t in self.targets], "evidence": list(self.evidence_ids),
                     "identity": self.identity, "references": list(self.references)})

    def record(self) -> dict:
        return {"item_id": self.item_id, "kind": self.kind, "company_id": self.company_id,
                "period": list(self.period or ()), "jdl_version": self.jdl_version,
                "voucher_row_limit": self.voucher_row_limit, "targets": [t.record() for t in self.targets],
                "change": self.change, "evidence_ids": list(self.evidence_ids), "default_scope": self.default_scope,
                "identity": self.identity, "references": list(self.references), "note": self.note,
                "applies_to_conversion": self.applies_to_conversion, "item_fingerprint": self.fingerprint}


def item_from_record(record: dict) -> ApprovalItem:
    targets = tuple(Target(t["label"], t["journal_sha256"], t["source_row"], t["voucher"], t["date"], tuple(t["lines"]))
                    for t in record["targets"])
    item = ApprovalItem(record["item_id"], record["kind"], record["company_id"],
                        tuple(record["period"]) if record["period"] else None, record["jdl_version"],
                        record["voucher_row_limit"], targets, record["change"], tuple(record["evidence_ids"]),
                        record["default_scope"], record["identity"], tuple(record["references"]), record["note"])
    if item.fingerprint != record.get("item_fingerprint"):
        raise ApprovalError("台帳の項目記録が改変されています")
    return item


def _label(entry) -> str:
    return entry.id.rsplit(":", 1)[-1]


def _target(entry, lines=()) -> Target:
    from accounting_converter.application.yayoi_ready_only import _first_row

    return Target(_label(entry), stable_journal_identity(entry) or "", _first_row(entry),
                  str(entry.metadata.get("yayoi_voucher_number") or ""), entry.date.isoformat(), tuple(lines))


def _line_row(line) -> int:
    return int(line.metadata.get("journal_row_number", line.source_reference.row_number))


def pending_items(entries, profile, context, company_id: str, *, trailing_space_record: Path | None = None,
                  policies: tuple[dict, ...] = ()) -> tuple[ApprovalItem, ...]:
    """What waits for the tax accountant, from the parsed source and the saved setting. Read-only.

    policies: operating policies to record (private catalog; e.g. the overseas-purchase policy of one journal).
    Each names its journal label and line rows; a policy never applies to anything it does not name.
    """
    from accounting_converter.adapters.output.jdl import scoped_evidence

    dates = sorted(entry.date.isoformat() for entry in entries)
    common = dict(company_id=company_id, period=(dates[0], dates[-1]) if dates else None,
                  jdl_version=getattr(context, "version", None),
                  voucher_row_limit=getattr(context, "voucher_row_limit", None))
    items: list[ApprovalItem] = []
    limit = common["voucher_row_limit"]
    split_targets = []
    if limit is not None:
        for entry in entries:
            plan = vs.plan_split(entry, limit)
            if plan is None or not vs.counterpart_mapped_to_no_tax(entry, plan, profile, context):
                continue
            if vs.approval_covers(entry, profile, context):
                continue  # already approved for this journal
            split_targets.append(_target(entry))
    if split_targets:
        items.append(ApprovalItem(
            item_id="SPLIT-V1", kind=KIND_SPLIT, targets=tuple(split_targets),
            change=(f"振替伝票入力行数{limit}を超える仕訳を、規則 {vs.RULE} で複数のJDL伝票に分ける（相手科目の金額を"
                    "各伝票の明細合計に分割。科目・補助・税・摘要・日付は不変。ダミー科目なし）"),
            evidence_ids=(scoped_evidence.VOUCHER_ROW_LIMIT_EVIDENCE_ID,),
            default_scope={"kind": vs.SCOPE_JOURNALS, "journals": sorted(t.journal_sha256 for t in split_targets),
                           "text": f"指定した{len(split_targets)}仕訳のみ（今後の仕訳は含まない）"},
            **common))
    from collections import Counter

    counts = Counter(stable_journal_identity(entry) for entry in entries)
    for entry in entries:
        for identity in nc.NONCREDIT_SOURCES:
            lines = [line for line in entry.lines if line.tax_info is not None and line.tax_info.category == identity]
            if not lines or identity in nc.journal_approval(entry, profile, context):
                continue
            items.append(ApprovalItem(
                item_id=f"NONCREDIT-{_label(entry)}", kind=KIND_NONCREDIT, identity=identity,
                targets=(_target(entry, tuple(_line_row(line) for line in lines)),),
                change=f"控除不可の明細（{identity}）をJDL非仕入（税区空欄）として取り込む。" + nc.LOSS_TEXT,
                evidence_ids=(nc.TECHNICAL_EVIDENCE.evidence_id,),
                default_scope={"kind": nc.SCOPE_JOURNALS, "journals": [stable_journal_identity(entry)],
                               "text": "この1仕訳のみ（同じ税区分の他の仕訳・内容が変わった仕訳には及ばない）"},
                note=("同じ内容の仕訳が複数あるため承認できません" if counts[stable_journal_identity(entry)] != 1 else ""),
                **common))
    if trailing_space_record is not None:
        record = json.loads(Path(trailing_space_record).read_text(encoding="utf-8"))
        files = record.get("files") or {}
        items.append(ApprovalItem(
            item_id="TRAILING-SPACE", kind=KIND_TRAILING_SPACE, targets=(),
            change=(f"JDLが摘要末尾の空白を取り除くこと（{record.get('rows_count', len(record.get('rows') or ()))}明細・"
                    f"{record.get('journals_count', '?')}伝票）を許容するか"),
            evidence_ids=tuple(record.get("evidence_ids") or ()),
            default_scope={"kind": "ROUND_TRIP_RECORD", "rows_sha256": record.get("rows_sha256"),
                           "text": "この往復照合の記録に含まれる明細のみ"},
            references=tuple(f"{k}:{(v or {}).get('sha256', '')}" for k, v in sorted(files.items()))
            + (f"record:{_file_sha(trailing_space_record)}",),
            note=RECORD_ONLY_MESSAGE[KIND_TRAILING_SPACE], **common))
    by_label = {}
    for entry in entries:
        by_label.setdefault(_label(entry), []).append(entry)
    for policy in policies:
        found = by_label.get(str(policy.get("journal")), [])
        if len(found) != 1:
            raise ApprovalError(f"運用方針の対象仕訳が一意に見つかりません: {policy.get('journal')}")
        lines = tuple(int(r) for r in policy.get("lines") or ())
        if not lines:
            raise ApprovalError("運用方針は対象の明細行を指定してください（仕訳全体・他明細へは広げません）")
        items.append(ApprovalItem(
            item_id=str(policy["item_id"]), kind=KIND_POLICY, targets=(_target(found[0], lines),),
            change=str(policy.get("change", "")), evidence_ids=tuple(policy.get("evidence_ids") or ()),
            default_scope={"kind": "LINES", "lines": list(lines), "text": "指定した明細のみ（同じ仕訳の他明細・他の仕訳には適用しない）"},
            note=RECORD_ONLY_MESSAGE[KIND_POLICY], **common))
    return tuple(items)


# ---------------------------------------------------------------- preview (in memory only)
def _split_scope_from(scope: dict | None) -> vs.SplitScope:
    scope = scope or {}
    kind = scope.get("kind")
    if kind == vs.SCOPE_JOURNALS:
        return vs.SplitScope(kind, tuple(scope.get("journals") or ()))
    if kind == vs.SCOPE_PERIOD:
        try:
            return vs.SplitScope(kind, period=(date.fromisoformat(scope["start"]), date.fromisoformat(scope["end"])))
        except (KeyError, TypeError, ValueError):
            return vs.SplitScope(kind)
    return vs.SplitScope(kind or "")


def trial_profile(profile, context, company_id: str, entries, selections) -> object:
    """In-memory copy AS IF the selected items were approved (with their scopes). Never savable (TRIAL_MARKER).

    selections: iterable of (item, scope dict or None). Record-only kinds change nothing.
    """
    by_sha = {stable_journal_identity(entry): entry for entry in entries}
    result = profile
    noncredit_named: dict[str, list] = {}
    for item, scope in selections:
        if item.kind == KIND_SPLIT:
            split_scope = _split_scope_from(scope or item.default_scope)
            if split_scope.problems() or context is None or context.voucher_row_limit is None:
                continue  # an invalid scope approves nothing, also in a trial
            policies = dict(result.loss_policy_mappings)
            policies[vs.POLICY_KEY] = MappingValue(vs.POLICY_KEY, vs.RULE, MappingStatus.USER_CONFIRMED, metadata={
                "rule": vs.RULE, "company_setting_id": company_id, "profile_id": result.profile_id,
                "voucher_row_limit": str(context.voucher_row_limit), "human_approver": nc.TRIAL_PERSON,
                "tax_accountant": nc.TRIAL_PERSON, "signoff_reference": nc.TRIAL_PERSON, "signoff_date": "0001-01-01",
                nc.TRIAL_MARKER: "true", **split_scope.metadata()})
            result = replace(result, loss_policy_mappings=policies)
        elif item.kind == KIND_NONCREDIT:
            for target in item.targets:
                entry = by_sha.get(target.journal_sha256)
                if entry is not None:
                    noncredit_named.setdefault(item.identity, []).append(entry)
    if noncredit_named:
        trial = nc.signoff_trial_profile(result, context, company_id,
                                         [e for named in noncredit_named.values() for e in named])
        if trial is not None:
            mappings = dict(result.tax_mappings)
            for identity, named in noncredit_named.items():
                trial_mapping = trial.tax_mappings.get(identity)
                if trial_mapping is None:
                    continue
                # keep what is already approved for this identity; add only the named journals
                kept = nc.approved_journals(result.tax_mappings.get(identity)) if not nc.mapping_problems(
                    identity, result.tax_mappings.get(identity), result, context) else {}
                wanted = {stable_journal_identity(e) for e in named}
                records = {sha: r for sha, r in nc.approved_journals(trial_mapping).items() if sha in wanted}
                merged = {**kept, **records}
                mappings[identity] = replace(trial_mapping, metadata={
                    **trial_mapping.metadata, nc.JOURNALS_KEY: json.dumps(list(merged.values()), ensure_ascii=False,
                                                                          sort_keys=True)})
            result = replace(result, tax_mappings=mappings)
    return result


@dataclass(frozen=True)
class JournalChange:
    journal_id: str
    label: str
    source_row: int
    before: tuple[str, ...]
    after: tuple[str, ...]

    @property
    def state(self) -> str:
        if self.before and not self.after:
            return "READYになる"
        if self.before and self.after:
            return "BLOCKのまま"
        if not self.before and self.after:
            return "新たにBLOCK"
        return "READYのまま"


@dataclass(frozen=True)
class Preview:
    item_ids: tuple[str, ...]
    ready_before: int
    block_before: int
    ready_after: int
    block_after: int
    targets: tuple[JournalChange, ...]           # every journal any selected item names
    released: tuple[str, ...]                    # BLOCK -> READY (journal ids)
    still_blocked: tuple[str, ...]               # named, still BLOCK (other open conditions)
    newly_blocked: tuple[str, ...]               # READY -> BLOCK (must be empty)
    outside_scope_changed: tuple[str, ...]       # changed but named by no selected item (must be empty)
    ready_after_ids: tuple[str, ...]
    setting_sensitivity: tuple[str, ...]
    record_only: tuple[str, ...]
    fingerprint: str
    problems: tuple[str, ...] = field(default=())

    def summary(self) -> dict:
        return {"items": list(self.item_ids), "ready_before": self.ready_before, "block_before": self.block_before,
                "ready_after": self.ready_after, "block_after": self.block_after,
                "released": len(self.released), "still_blocked": len(self.still_blocked),
                "newly_blocked": len(self.newly_blocked), "outside_scope_changed": len(self.outside_scope_changed),
                "targets": [{"label": c.label, "source_row": c.source_row, "state": c.state,
                             "remaining_blockers": list(c.after)} for c in self.targets],
                "setting_sensitivity": list(self.setting_sensitivity), "record_only": list(self.record_only),
                "problems": list(self.problems), "preview_fingerprint": self.fingerprint}


def _profile_sha(profile) -> str:
    from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore

    return hashlib.sha256(ConversionProfileStore(Path(".")).to_json_text(profile).encode("utf-8")).hexdigest()


def _sensitivity(items, profile, context, company_id) -> tuple[str, ...]:
    """What a change of the company setting would do to these approvals (each is bound to the current setting)."""
    out = []
    if context is None:
        return ("会社設定が未確定のため、承認は記録できません。",)
    other_limit = 64 if context.voucher_row_limit != 64 else 16
    moved = replace(context, voucher_row_limit=other_limit)
    for item in items:
        if item.kind == KIND_SPLIT:
            out.append(f"{item.item_id}: 承認は振替伝票入力行数{context.voucher_row_limit}に紐づきます。"
                       f"{other_limit}行へ変更すると無効になり（ROW_LIMIT_DIFFERS_FROM_APPROVAL）、対象仕訳はBLOCKに戻ります。")
        elif item.kind == KIND_NONCREDIT:
            problems = nc.technical_problems(item.identity, company_id, moved)
            out.append(f"{item.item_id}: 承認は税設定（税抜・原則・一括比例・端数）と行数{context.voucher_row_limit}に紐づきます。"
                       f"行数{other_limit}では技術Evidenceの範囲外（{', '.join(problems) or '—'}）で、承認は使えません。")
    return tuple(out)


def preview(source: Path, profile, context, company_id: str, selections, *, workflow=None) -> Preview:
    """Production assess on the saved setting and on the trial copy, compared journal by journal."""
    from accounting_converter.application.yayoi_jdl_workflow import YayoiJdlWorkflow
    from accounting_converter.application.yayoi_sources import detect_format

    workflow = workflow or YayoiJdlWorkflow()
    selections = tuple(selections)
    entries = detect_format(source).diagnose(source).entries
    problems = []
    for item, _ in selections:
        if item.company_id != company_id:
            problems.append(f"{item.item_id}: 会社が違います")
    problems.extend(identity_problems(None, company_id, getattr(profile, "profile_id", None), context))
    before = workflow.assess(source, profile, context).journal_blockers
    trial = trial_profile(profile, context, company_id, entries, selections) if not problems else profile
    after = workflow.assess(source, trial, context).journal_blockers if trial is not profile else before
    by_sha = {stable_journal_identity(entry): entry for entry in entries}
    named_ids = []
    for item, scope in selections:
        if item.kind == KIND_SPLIT:
            split_scope = _split_scope_from(scope or item.default_scope)
            named_ids.extend(e.id for e in entries if split_scope.covers(e) and vs.plan_split(e, context.voucher_row_limit))
        else:
            named_ids.extend(by_sha[t.journal_sha256].id for t in item.targets if t.journal_sha256 in by_sha)
    named = tuple(dict.fromkeys(named_ids))
    from accounting_converter.application.yayoi_ready_only import _first_row

    entry_of = {entry.id: entry for entry in entries}
    changes = tuple(JournalChange(j, _label(entry_of[j]), _first_row(entry_of[j]), tuple(sorted(before.get(j, ()))),
                                  tuple(sorted(after.get(j, ())))) for j in named)
    released = tuple(j for j in before if before[j] and not after.get(j))
    newly = tuple(j for j in before if not before[j] and after.get(j))
    outside = tuple(j for j in before if set(before[j]) != set(after.get(j, ())) and j not in set(named))
    if newly:
        problems.append("承認によって新たにBLOCKになる仕訳があります")
    if outside:
        problems.append("承認範囲外の仕訳の判定が変わりました")
    ready_before = sum(1 for v in before.values() if not v)
    ready_after = sum(1 for v in after.values() if not v)
    record_only = tuple(f"{item.item_id}: {RECORD_ONLY_MESSAGE[item.kind]}" for item, _ in selections
                        if item.kind in RECORD_ONLY_MESSAGE)
    ready_after_ids = tuple(sorted(j for j, v in after.items() if not v))
    fingerprint = _sha({"source": _file_sha(source), "profile": _profile_sha(profile), "company": company_id,
                        "items": [(item.fingerprint, scope or item.default_scope) for item, scope in selections],
                        "ready_after": ready_after_ids, "before": ready_before})
    return Preview(tuple(item.item_id for item, _ in selections), ready_before, len(before) - ready_before,
                   ready_after, len(after) - ready_after, changes, released,
                   tuple(c.journal_id for c in changes if c.after), newly, outside, ready_after_ids,
                   _sensitivity([i for i, _ in selections], profile, context, company_id), record_only, fingerprint,
                   tuple(problems))


# ---------------------------------------------------------------- ledger (append-only, hash chained)
class ApprovalLedger:
    """One company's decision log. Each line: one entry with the SHA-256 of the previous one (tamper evident)."""

    def __init__(self, path: Path, company_id: str) -> None:
        self.path, self.company_id = Path(path), company_id

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        out, previous = [], ""
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            entry = json.loads(line)
            body = {k: v for k, v in entry.items() if k != "entry_sha256"}
            if entry.get("prev_sha256") != previous or entry.get("entry_sha256") != _sha(body) \
                    or entry.get("seq") != number or entry.get("schema") != LEDGER_SCHEMA:
                raise ApprovalError(f"承認台帳が改変されています（{number}行目）。記録・適用はできません。")
            if entry.get("company_id") != self.company_id:
                raise ApprovalError(f"承認台帳に別の会社の記録があります（{number}行目）。")
            out.append(entry)
            previous = entry["entry_sha256"]
        return out

    def _append(self, body: dict) -> dict:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.path.with_name(self.path.name + ".lock")
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)  # two writers would fork the chain
        except FileExistsError:
            raise ApprovalError("承認台帳が別の操作で使用中です（残っている場合は .lock を確認して削除）") from None
        try:
            entries = self.entries()
            body = {"schema": LEDGER_SCHEMA, "seq": len(entries) + 1,
                    "prev_sha256": entries[-1]["entry_sha256"] if entries else "", "company_id": self.company_id,
                    "recorded_at": datetime.now(timezone.utc).isoformat(), **body}
            entry = {**body, "entry_sha256": _sha(body)}
            with self.path.open("a", encoding="utf-8") as out:
                out.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        finally:
            os.close(handle)
            lock.unlink(missing_ok=True)
        return entry

    def latest_decision(self, item_id: str) -> dict | None:
        found = [e for e in self.entries() if e["type"] == "DECISION" and e["item_id"] == item_id]
        return found[-1] if found else None

    def applied(self, item_id: str) -> dict | None:
        """The APPLIED entry still in force for this item (None when never applied or applied then revoked)."""
        state = None
        for entry in self.entries():
            if entry.get("item_id") != item_id:
                continue
            if entry["type"] == "APPLIED":
                state = entry
            elif entry["type"] == "UNAPPLIED":
                state = None
        return state

    def recorded_item(self, item_id: str) -> ApprovalItem | None:
        """The item exactly as it was when last decided (for an applied item, which is no longer pending)."""
        decision = self.latest_decision(item_id)
        return item_from_record(decision["item"]) if decision else None

    def status(self, item_id: str) -> str:
        decision = self.latest_decision(item_id)
        return DECISION_LABELS[decision["decision"] if decision else None] + ("（適用済み）" if self.applied(item_id) else "")

    def record_decision(self, item: ApprovalItem, decision: str, *, tax_accountant: str, recorded_by: str,
                        decided_on: date, reference: str, scope: dict | None, bindings: dict,
                        comment: str = "", explicitly_confirmed: bool = False) -> dict:
        problems = []
        if not explicitly_confirmed:
            problems.append("明示的な確認がありません")
        if decision not in DECISIONS:
            problems.append(f"判断が不正です: {decision}")
        if item.company_id != self.company_id or bindings.get("company_id") != self.company_id:
            problems.append("会社が台帳と一致しません")
        if bindings.get("context_company_id") != self.company_id or not bindings.get("profile_id"):
            problems.append("JDL設定の会社ID・プロファイルIDを確認できません（会社設定を正規に解決したものが必要です）")
        if not all(isinstance(v, str) and v.strip() for v in (tax_accountant, recorded_by, reference)):
            problems.append("税理士名・記録者・確認資料の参照は必須です")
        if not isinstance(decided_on, date):
            problems.append("判断日が必要です")
        if not isinstance(scope, dict) or not scope.get("kind"):
            problems.append("承認の適用範囲は必須です")
        elif item.kind == KIND_SPLIT and decision == APPROVED and _split_scope_from(scope).problems():
            problems.append("伝票分割の適用範囲が不正です: " + ", ".join(_split_scope_from(scope).problems()))
        elif item.kind == KIND_NONCREDIT and scope != item.default_scope:
            problems.append("控除不可の承認範囲は対象の1仕訳だけです（広げられません）")
        elif item.kind in (KIND_POLICY, KIND_TRAILING_SPACE) and scope != item.default_scope:
            problems.append("この項目の範囲は変更できません")
        if decision == APPROVED and item.note and item.kind == KIND_NONCREDIT:
            problems.append(item.note)
        latest = self.latest_decision(item.item_id)
        if latest is not None and latest["decision"] == decision and latest["item_fingerprint"] == item.fingerprint \
                and latest.get("scope") == scope:
            problems.append("同じ判断が既に記録されています（重複）")
        if decision == REVOKED and (latest is None or latest["decision"] != APPROVED):
            problems.append("取り消せる承認がありません")
        if decision != REVOKED and self.applied(item.item_id) is not None:
            problems.append("適用済みの承認があります。先に取り消してください")
        if problems:
            raise ApprovalError("判断を記録できません: " + " / ".join(dict.fromkeys(problems)))
        return self._append({
            "type": "DECISION", "item_id": item.item_id, "kind": item.kind, "item_fingerprint": item.fingerprint,
            "item": item.record(), "decision": decision, "tax_accountant": tax_accountant.strip(),
            "recorded_by": recorded_by.strip(), "decided_on": decided_on.isoformat(), "reference": reference.strip(),
            "scope": scope, "comment": comment, "bindings": bindings})


def bindings_for(source: Path, context, company_id: str, profile_id: str | None = None) -> dict:
    """What a decision is bound to: the company, its profile, the exact source file and the JDL setting it was judged
    under. `context_company_id` is the company the JDL setting was resolved for (it must be `company_id`)."""
    from accounting_converter.application import moneyforward_tax_excluded_evidence as ev

    return {"company_id": company_id, "profile_id": profile_id,
            "context_company_id": getattr(context, "company_setting_id", None), "source_sha256": _file_sha(source),
            "jdl_product": getattr(context, "product", None), "jdl_version": getattr(context, "version", None),
            "voucher_row_limit": getattr(context, "voucher_row_limit", None),
            "tax_context_identity_sha256": ev.tax_context_identity_sha256(context) if context is not None else None}


# ---------------------------------------------------------------- apply / revoke (writes the company setting)
PRODUCTION_MARKERS = ("/AppData/Local/AccountingConverter", "\\AppData\\Local\\AccountingConverter")


def _is_production_store(root: Path) -> bool:
    from accounting_converter.infrastructure.company_setting_store import default_company_store_dir

    text = str(Path(root).resolve())
    try:
        default = str(default_company_store_dir().parent.resolve())
    except Exception:  # noqa: BLE001 - an unknown default is not a reason to allow
        default = None
    return any(marker in text for marker in PRODUCTION_MARKERS) or (default is not None and text == default)


def _backup(store_root: Path, backup_dir: Path) -> Path:
    """A full copy for the person (never deleted by the app). Restoring is NOT from this copy as a whole: see _restore."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = Path(backup_dir) / f"before_{stamp}"
    if target.exists():
        raise ApprovalError("バックアップ先が既に存在します")
    for name in ("profiles", "companies"):
        shutil.copytree(Path(store_root) / name, target / name)
    return target


class ConflictError(ApprovalError):
    """The company setting changed while the operation ran; nothing was overwritten."""


def _company_files(store_root: Path, company_id: str, profile_id: str) -> tuple[Path, Path]:
    return (Path(store_root) / "profiles" / f"{profile_id}.json",
            Path(store_root) / "companies" / company_id / "company.json")


def _state(store_root: Path, company_id: str, profile_id: str) -> tuple[str, str]:
    return tuple(_file_sha(path) for path in _company_files(store_root, company_id, profile_id))


def _restore(store_root: Path, backup: Path, company_id: str, profile_id: str, expect: tuple[str, str]) -> None:
    """Put back ONLY this company's profile and company file, and only if they still are what this operation wrote
    (`expect`). Anything else changed meanwhile (another screen, another person): stop and say so, never overwrite."""
    if _state(store_root, company_id, profile_id) != expect:
        raise ConflictError("処理中に会社設定が別の操作で変更されたため、自動では元に戻しません。"
                            f"バックアップ（{backup}）を確認してください。")
    for live, saved in zip(_company_files(store_root, company_id, profile_id),
                           (backup / "profiles" / f"{profile_id}.json", backup / "companies" / company_id / "company.json")):
        shutil.copyfile(saved, live)


def identity_problems(companies, company_id: str, profile_id: str | None, context, setting=None) -> list[str]:
    """Company / profile / setting must agree before anything is recorded, previewed or written (all fail closed):
    the JDL setting was resolved for this company, the company setting points at this profile, and no OTHER company
    setting shares the profile (an approval is stored in the profile, so a shared one would reach both companies)."""
    problems = []
    if getattr(context, "company_setting_id", None) != company_id:
        problems.append("JDL設定が、この会社用に解決されたものではありません（会社IDの不一致）")
    if setting is not None and (setting.company_setting_id != company_id or setting.conversion_profile_id != profile_id):
        problems.append("会社設定の会社ID・プロファイルIDが、指定と一致しません")
    if companies is not None and profile_id:
        try:
            others = [c.company_setting_id for c in companies.list()
                      if c.conversion_profile_id == profile_id and c.company_setting_id != company_id]
        except Exception:  # noqa: BLE001 - an unreadable company list cannot prove the profile is not shared
            others = ["（会社設定一覧を読めません）"]
        if others:
            problems.append("同じプロファイルを別の会社設定が使っています: " + ", ".join(others))
    return problems


def _stores(store_root: Path):
    from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
    from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore

    profiles = ConversionProfileStore(Path(store_root) / "profiles")
    return profiles, CompanySettingStore(Path(store_root) / "companies", profiles)


def _checked(ledger: ApprovalLedger, store_root: Path, company_id: str, source: Path, allow_production_store: bool):
    if _is_production_store(store_root) and not allow_production_store:
        raise ApprovalError("本番の会社設定（AppData）への適用は、明示的な指定がない限り行いません。")
    if ledger.company_id != company_id:
        raise ApprovalError("台帳の会社と適用先の会社が一致しません")
    profiles, companies = _stores(store_root)
    resolved = companies.resolve(company_id)
    if not resolved.available or resolved.profile is None or resolved.context is None:
        raise ApprovalError("会社設定を読めません（会社IDまたは保存先を確認してください）")
    problems = identity_problems(companies, company_id, resolved.profile.profile_id, resolved.context, resolved.setting)
    if problems:
        raise ApprovalError("会社の照合に失敗しました: " + " / ".join(problems))
    return profiles, companies, resolved


def apply_decision(ledger: ApprovalLedger, item_id: str, *, store_root: Path, company_id: str, source: Path,
                   expected_preview_fingerprint: str, backup_dir: Path, applied_by: str,
                   judge_report: Path | None = None, allow_production_store: bool = False) -> dict:
    """Write ONE approved decision to the company setting through the existing approval function."""
    from accounting_converter.application.yayoi_sources import detect_format

    if _is_production_store(store_root) and not allow_production_store:  # checked first, before reading anything
        raise ApprovalError("本番の会社設定（AppData）への適用は、明示的な指定がない限り行いません。")
    decision = ledger.latest_decision(item_id)
    if decision is None or decision["decision"] != APPROVED:
        raise ApprovalError("承認の記録がありません（未判断・保留・不承認・取り消しは適用しません）")
    if ledger.applied(item_id) is not None:
        raise ApprovalError("この承認は既に適用されています（重複適用はしません）")
    if decision["kind"] not in APPLICABLE_KINDS:
        raise ApprovalError(RECORD_ONLY_MESSAGE.get(decision["kind"], "この種類の承認は適用できません"))
    if not isinstance(applied_by, str) or not applied_by.strip():
        raise ApprovalError("適用する人の名前が必要です")
    profiles, companies, resolved = _checked(ledger, store_root, company_id, source, allow_production_store)
    current_bindings = bindings_for(source, resolved.context, company_id, resolved.profile.profile_id)
    if current_bindings != decision["bindings"]:
        diff = sorted(k for k in current_bindings if current_bindings[k] != decision["bindings"].get(k))
        raise ApprovalError("判断時と現在の会社・元データ・設定が一致しません: " + ", ".join(diff))
    entries = detect_format(source).diagnose(source).entries
    items = {i.item_id: i for i in pending_items(entries, resolved.profile, resolved.context, company_id)}
    item = items.get(item_id)
    if item is None or item.fingerprint != decision["item_fingerprint"]:
        raise ApprovalError("承認した対象と現在の承認待ち項目が一致しません（対象が変わったか、既に承認済みです）")
    if item.kind == KIND_NONCREDIT and judge_report is None:
        raise ApprovalError("控除不可の承認には、消費税集計の判定（税理士の「済」）の記録が必要です")
    seen = preview(source, resolved.profile, resolved.context, company_id, [(item, decision["scope"])])
    if seen.fingerprint != expected_preview_fingerprint:
        raise ApprovalError("確認したプレビューと現在の結果が一致しません。プレビューを確認し直してください。")
    if seen.problems:
        raise ApprovalError("プレビューに問題があります: " + " / ".join(seen.problems))
    profile_id = resolved.profile.profile_id
    pre = _state(store_root, company_id, profile_id)
    backup = _backup(store_root, backup_dir)
    written: tuple[str, str] | None = None
    try:
        if _state(store_root, company_id, profile_id) != pre:
            raise ConflictError("プレビュー後に会社設定が変更されました。プレビューからやり直してください。")
        if item.kind == KIND_SPLIT:
            vs.approve_split_policy(
                profiles, resolved.profile.profile_id, company_id, resolved.context,
                human_approver=decision["recorded_by"], tax_accountant=decision["tax_accountant"],
                signoff_reference=decision["reference"], signoff_date=date.fromisoformat(decision["decided_on"]),
                scope=_split_scope_from(decision["scope"]),
                extra_metadata={"approval_ledger_entry_sha256": decision["entry_sha256"]})
        else:
            _apply_noncredit(profiles, resolved, company_id, item, decision, entries, judge_report)
        companies.refresh_profile_fingerprint(company_id)
        written = _state(store_root, company_id, profile_id)
        after = companies.resolve(company_id)
        from accounting_converter.application.yayoi_jdl_workflow import YayoiJdlWorkflow

        blockers = YayoiJdlWorkflow().assess(source, after.profile, after.context).journal_blockers
        ready = tuple(sorted(j for j, v in blockers.items() if not v))
        if ready != seen.ready_after_ids:
            raise ApprovalError("適用後の診断がプレビューと一致しません。元に戻します。")
        # the ledger entry is part of the operation: if it cannot be written the setting goes back too
        return ledger._append({
        "type": "APPLIED", "item_id": item_id, "kind": item.kind, "item_fingerprint": item.fingerprint,
        "decision_entry_sha256": decision["entry_sha256"], "applied_by": applied_by.strip(),
        "preview_fingerprint": seen.fingerprint, "ready_before": seen.ready_before, "ready_after": seen.ready_after,
        "released": len(seen.released), "backup": str(backup),
        "judge_report_sha256": _file_sha(judge_report) if judge_report is not None else None,
        "profile_sha256_after": _profile_sha(after.profile)})
    except Exception:
        _rollback(store_root, backup, company_id, profile_id, pre, written)
        raise


def _rollback(store_root, backup, company_id, profile_id, pre, written) -> None:
    """Undo a failed operation without touching anyone else's change.

    `written` is the state right after this operation's own write (None: it failed before/while writing, so the files
    are either still `pre` or were written by this operation alone a moment ago)."""
    now = _state(store_root, company_id, profile_id)
    if now == pre:
        return  # nothing was written
    _restore(store_root, backup, company_id, profile_id, written if written is not None else now)


def _apply_noncredit(profiles, resolved, company_id, item, decision, entries, judge_report: Path) -> None:
    report = json.loads(Path(judge_report).read_text(encoding="utf-8"))
    case = nc.TECHNICAL_EVIDENCE.probe_cases.get(item.identity)
    if (report.get("cases") or {}).get(case, {}).get("result") != "EQUIVALENCE_CONFIRMED":
        raise ApprovalError(f"消費税集計の判定 {case} が EQUIVALENCE_CONFIRMED ではありません（税理士の「済」が必要）")
    by_sha = {stable_journal_identity(e): e for e in entries}
    journals = [by_sha[t.journal_sha256] for t in item.targets if t.journal_sha256 in by_sha]
    nc.approve_noncredit_identity(
        profiles, resolved.profile.profile_id, company_id, resolved.context, item.identity,
        human_approver=decision["recorded_by"], tax_accountant=decision["tax_accountant"],
        signoff_reference=decision["reference"], signoff_date=date.fromisoformat(decision["decided_on"]),
        rate_distinction_loss_acknowledged=True, judge_report_sha256=_file_sha(judge_report),
        journals=journals, source_entries=entries, labels={e.id: _label(e) for e in journals})


def revoke_applied(ledger: ApprovalLedger, item_id: str, *, store_root: Path, company_id: str, source: Path,
                   backup_dir: Path, revoked_by: str, reference: str, allow_production_store: bool = False) -> dict:
    """Remove an applied approval from the company setting (the decision log keeps both entries)."""
    if _is_production_store(store_root) and not allow_production_store:
        raise ApprovalError("本番の会社設定（AppData）への変更は、明示的な指定がない限り行いません。")
    applied = ledger.applied(item_id)
    if applied is None:
        raise ApprovalError("取り消す適用済みの承認がありません")
    latest = ledger.latest_decision(item_id)
    if latest is None or latest["decision"] != REVOKED:
        raise ApprovalError("取り消しの判断（REVOKED）が台帳に記録されていません")
    if not all(isinstance(v, str) and v.strip() for v in (revoked_by, reference)):
        raise ApprovalError("取り消す人と根拠の参照が必要です")
    profiles, companies, resolved = _checked(ledger, store_root, company_id, source, allow_production_store)
    decision = next(e for e in ledger.entries() if e["entry_sha256"] == applied["decision_entry_sha256"])
    bound = decision["bindings"]
    if (bound.get("company_id"), bound.get("profile_id")) != (company_id, resolved.profile.profile_id):
        raise ApprovalError("承認時の会社・プロファイルと現在の会社設定が一致しません。取り消しません。")
    profile_id = resolved.profile.profile_id
    pre = _state(store_root, company_id, profile_id)
    backup = _backup(store_root, backup_dir)
    written: tuple[str, str] | None = None
    try:
        profile = resolved.profile
        if applied["kind"] == KIND_SPLIT:
            policy = profile.loss_policy_mappings.get(vs.POLICY_KEY)
            if policy is None or (policy.metadata or {}).get("approval_ledger_entry_sha256") != decision["entry_sha256"]:
                raise ApprovalError("会社設定の分割承認が、この台帳の記録と一致しません。取り消しません。")
            policies = {k: v for k, v in profile.loss_policy_mappings.items() if k != vs.POLICY_KEY}
            profiles.update(replace(profile, loss_policy_mappings=policies, updated_at=datetime.now(timezone.utc)))
        else:
            identity = decision["item"]["identity"]
            mapping = profile.tax_mappings.get(identity)
            shas = {t["journal_sha256"] for t in decision["item"]["targets"]}
            records = nc.approved_journals(mapping)
            if not shas <= set(records):
                raise ApprovalError("会社設定の控除不可承認に、この仕訳の記録がありません。取り消しません。")
            signed = {k: decision[src] for k, src in (("tax_accountant", "tax_accountant"), ("human_approver", "recorded_by"),
                                                      ("signoff_reference", "reference"), ("signoff_date", "decided_on"))}
            if any(records[sha].get(k) != v for sha in shas for k, v in signed.items()):
                raise ApprovalError("会社設定の控除不可承認が、この台帳の記録と異なります（後から再承認・変更された可能性）。"
                                    "取り消しません。")
            left = [r for sha, r in records.items() if sha not in shas]
            mappings = dict(profile.tax_mappings)
            if left:
                mappings[identity] = replace(mapping, metadata={
                    **mapping.metadata, nc.JOURNALS_KEY: json.dumps(left, ensure_ascii=False, sort_keys=True)})
            else:
                mappings.pop(identity)  # the identity becomes unresolved again: HUMAN:TAX_MAPPING blocks
            profiles.update(replace(profile, tax_mappings=mappings, updated_at=datetime.now(timezone.utc)))
        companies.refresh_profile_fingerprint(company_id)
        written = _state(store_root, company_id, profile_id)
        return ledger._append({"type": "UNAPPLIED", "item_id": item_id, "kind": applied["kind"],
                               "applied_entry_sha256": applied["entry_sha256"], "revoked_by": revoked_by.strip(),
                               "reference": reference.strip(), "backup": str(backup)})
    except Exception:
        _rollback(store_root, backup, company_id, profile_id, pre, written)
        raise


# ---------------------------------------------------------------- the older routes: same ledger, same checks
def default_ledger_path(store_root: Path, company_id: str) -> Path:
    """Where every route writes by default: next to the company setting it changes."""
    return Path(store_root) / "approval_ledger" / f"{company_id}.jsonl"


def _direct(store, company_id: str, kind: str, write, detail: dict, *, ledger: ApprovalLedger | None = None):
    """Run `write()` (an existing approval function) and record it. The ledger is validated BEFORE writing (a
    tampered ledger blocks the approval) and the setting is put back if the ledger entry cannot be written."""
    store_root = Path(store.root_dir).parent
    ledger = ledger or ApprovalLedger(default_ledger_path(store_root, company_id), company_id)
    ledger.entries()  # raises on a tampered / foreign ledger before anything is written
    profile_id = detail["profile_id"]
    problems = identity_problems(detail.get("companies"), company_id, profile_id, detail.get("context"),
                                 detail.get("setting"))
    if problems:
        raise ApprovalError("会社の照合に失敗しました（何も書き込んでいません）: " + " / ".join(problems))
    pre = _state(store_root, company_id, profile_id)
    backup = _backup(store_root, store_root / "approval_ledger" / "backups")
    written = None
    try:
        result = write()
        written = _state(store_root, company_id, profile_id)
        ledger._append({"type": "DIRECT_APPLIED", "item_id": detail["item_id"], "kind": kind, "backup": str(backup),
                        "profile_sha256_after": written[0], **detail["record"]})
        return result
    except Exception:
        _rollback(store_root, backup, company_id, profile_id, pre, written)
        raise


def _setting_of(companies, company_id: str):
    try:
        return companies.get(company_id)
    except Exception:  # noqa: BLE001 - no readable company setting: identity_problems then reports the mismatch
        return None


def approve_split_direct(store, companies, company_id: str, profile_id: str, context, *, human_approver: str,
                         tax_accountant: str, signoff_reference: str, signoff_date: date, scope: vs.SplitScope,
                         ledger: ApprovalLedger | None = None):
    """The screen / CLI route for the split rule: the existing approval function plus a ledger entry."""
    def write():
        profile = vs.approve_split_policy(store, profile_id, company_id, context, human_approver=human_approver,
                                          tax_accountant=tax_accountant, signoff_reference=signoff_reference,
                                          signoff_date=signoff_date, scope=scope)
        companies.refresh_profile_fingerprint(company_id)
        return profile

    meta_scope = scope.metadata() if isinstance(scope, vs.SplitScope) else {}
    return _direct(store, company_id, KIND_SPLIT, write, {
        "companies": companies, "context": context, "setting": _setting_of(companies, company_id),
        "profile_id": profile_id, "item_id": "SPLIT-V1",
        "record": {"scope": meta_scope, "voucher_row_limit": getattr(context, "voucher_row_limit", None),
                   "tax_accountant": str(tax_accountant).strip(), "recorded_by": str(human_approver).strip(),
                   "reference": str(signoff_reference).strip(), "decided_on": str(signoff_date)}}, ledger=ledger)


def approve_noncredit_direct(store, companies, company_id: str, profile_id: str, context, identity: str, *,
                             journals, source_entries, human_approver: str, tax_accountant: str, signoff_reference: str,
                             signoff_date: date, rate_distinction_loss_acknowledged: bool, judge_report_sha256: str = "",
                             labels: dict | None = None, ledger: ApprovalLedger | None = None):
    """The 控除不可 CLI route: the existing approval function plus a ledger entry."""
    def write():
        mapping = nc.approve_noncredit_identity(
            store, profile_id, company_id, context, identity, human_approver=human_approver,
            tax_accountant=tax_accountant, signoff_reference=signoff_reference, signoff_date=signoff_date,
            rate_distinction_loss_acknowledged=rate_distinction_loss_acknowledged,
            judge_report_sha256=judge_report_sha256, journals=journals, source_entries=source_entries, labels=labels)
        companies.refresh_profile_fingerprint(company_id)
        return mapping

    shas = [stable_journal_identity(entry) or "" for entry in journals]
    return _direct(store, company_id, KIND_NONCREDIT, write, {
        "companies": companies, "context": context, "setting": _setting_of(companies, company_id),
        "profile_id": profile_id, "item_id": "NONCREDIT-" + "+".join(sorted((labels or {}).get(e.id, _label(e)) for e in journals)),
        "record": {"identity": identity, "journal_sha256": sorted(shas), "tax_accountant": str(tax_accountant).strip(),
                   "recorded_by": str(human_approver).strip(), "reference": str(signoff_reference).strip(),
                   "decided_on": str(signoff_date), "judge_report_sha256": judge_report_sha256}}, ledger=ledger)


def unrecorded_approvals(profile, ledger: ApprovalLedger) -> list[str]:
    """Approvals present in the company setting that no ledger entry explains (read-only; a hand edit, an imported
    profile, or a route that bypassed the ledger). A non-empty list is a finding to explain, not an automatic block."""
    entries = ledger.entries()
    found = []
    policy = (getattr(profile, "loss_policy_mappings", None) or {}).get(vs.POLICY_KEY)
    if policy is not None:
        meta = policy.metadata or {}
        if meta.get("company_setting_id") != ledger.company_id:
            found.append(f"伝票分割の承認が別の会社（{meta.get('company_setting_id') or '記録なし'}）のものです")
        via_apply = {e["entry_sha256"] for e in entries if e["type"] == "DECISION"}
        direct_sig = {(e.get("tax_accountant"), e.get("reference"), e.get("decided_on")) for e in entries
                      if e["type"] == "DIRECT_APPLIED" and e["kind"] == KIND_SPLIT}
        explained = meta.get("approval_ledger_entry_sha256") in via_apply or (
            meta.get("tax_accountant"), meta.get("signoff_reference"), meta.get("signoff_date")) in direct_sig
        if not explained:
            found.append(f"伝票分割の承認（{meta.get('tax_accountant', '?')}・{meta.get('signoff_date', '?')}）")
    for identity in nc.NONCREDIT_SOURCES:
        mapping = (getattr(profile, "tax_mappings", None) or {}).get(identity)
        recorded = set()
        for e in entries:
            if e["type"] == "DIRECT_APPLIED" and e["kind"] == KIND_NONCREDIT and e.get("identity") == identity:
                recorded.update(e.get("journal_sha256") or ())
            if e["type"] == "DECISION" and e["kind"] == KIND_NONCREDIT and e.get("item", {}).get("identity") == identity:
                recorded.update(t["journal_sha256"] for t in e["item"]["targets"])
        if mapping is not None and (mapping.metadata or {}).get("noncredit_company_setting_id") not in (None, ledger.company_id):
            found.append(f"控除不可の承認（{identity}）が別の会社のものです")
        for sha, record in nc.approved_journals(mapping).items():
            if sha not in recorded:
                found.append(f"控除不可の承認（{identity}・仕訳{record.get('label', '?')}）")
    return found
