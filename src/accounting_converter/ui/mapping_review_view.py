"""対応の確認 (要確認ページ) の表示内容 (Phase 3C-2). Pure data: no Qt, no I/O, no decision of its own.

The input is a read-only snapshot of what the existing confirmation screens already compute
(`CompanyMappingUpdateService.review(include_confirmed=True)`, the tax mapping review, the saved tax mappings). This
module only sorts and labels it:
- 未確認 comes first; 確認済み is kept apart so the page can fold it;
- three kinds of "not done" are never mixed:
    UNCONFIRMED   the accountant / the office has to choose or confirm (人の確認)
    NEEDS_JDL     the JDL side has no matching account / subaccount: register it in JDL, or pick another (JDL側の登録)
    NEEDS_EVIDENCE no real-JDL Evidence exists for this tax or shape: nobody can confirm it on screen (JDLでの確認待ち)
  and a failure to read anything at all is an ERROR message, not a row;
- a candidate is shown as a candidate (with its basis), never as a decision. Nothing is confirmed by being shown.
"""
from __future__ import annotations

from dataclasses import dataclass, field

UNCONFIRMED, CONFIRMED, NEEDS_JDL, NEEDS_EVIDENCE, WAITING_PARENT = (
    "UNCONFIRMED", "CONFIRMED", "NEEDS_JDL", "NEEDS_EVIDENCE", "WAITING_PARENT")

STATE_WORDS = {
    UNCONFIRMED: "未確認（人の確認が必要）",
    CONFIRMED: "確認済み",
    NEEDS_JDL: "JDL側で登録が必要",
    NEEDS_EVIDENCE: "JDLでの確認待ち（実機の確認が必要）",
    WAITING_PARENT: "親科目の確認待ち",
}
_ORDER = {UNCONFIRMED: 0, WAITING_PARENT: 1, NEEDS_JDL: 2, NEEDS_EVIDENCE: 3, CONFIRMED: 9}

# Group keys (also the tab the existing dialog opens at).
G_ACCOUNT, G_SUBACCOUNT, G_TAX, G_DESCRIPTION, G_RETENTION = "accounts", "subaccounts", "tax", "descriptions", "retention"
GROUP_TITLES = {
    G_ACCOUNT: "勘定科目の対応", G_SUBACCOUNT: "補助科目の対応", G_TAX: "税区分の対応",
    G_DESCRIPTION: "摘要の文字の確認", G_RETENTION: "JDLに保持されない情報の扱い",
}


@dataclass(frozen=True)
class ReviewRow:
    group: str
    source: str                      # the source's own name (account / subaccount / tax category / information)
    state: str
    parent: str = ""                 # subaccounts: the parent account
    candidate: str = ""              # the confirmed target, or the best candidate (never both blank when known)
    basis: str = ""                  # why this candidate / what the confirmation means
    reason: str = ""                 # for NEEDS_*: what is missing
    journals: int | None = None      # how many journals (仕訳) or rows (行, tax categories) use it
    unit: str = "仕訳"
    technical: str = ""              # codes for the collapsed technical section

    @property
    def state_words(self) -> str:
        return STATE_WORDS[self.state]


@dataclass(frozen=True)
class ReviewGroup:
    key: str
    title: str
    rows: tuple[ReviewRow, ...]      # unconfirmed first (stable inside a state), confirmed last

    @property
    def pending(self) -> tuple[ReviewRow, ...]:
        return tuple(r for r in self.rows if r.state != CONFIRMED)

    @property
    def confirmed(self) -> tuple[ReviewRow, ...]:
        return tuple(r for r in self.rows if r.state == CONFIRMED)

    def count(self, state: str) -> int:
        return sum(r.state == state for r in self.rows)


@dataclass(frozen=True)
class MappingSnapshot:
    """Read-only inputs (built by controller.company_mapping_review_snapshot)."""
    review: object                                   # CompanyMappingUpdateReview (include_confirmed=True)
    tax_review: object | None = None                 # TaxMappingSetupReview (pending / evidence-missing items only)
    saved_tax: tuple[tuple[str, str], ...] = ()      # (source tax category, confirmed target) from the saved profile
    observed_tax: tuple[tuple[str, int], ...] = ()   # (source tax category, rows) seen in the source file
    tax_context_ready: bool = True                   # False while the JDL tax settings are not confirmed


@dataclass(frozen=True)
class MappingReviewView:
    groups: tuple[ReviewGroup, ...]
    journals: int
    shape_blocked: int                               # journals whose structure has no Evidence (SYSTEM_EVIDENCE)
    notes: tuple[str, ...] = ()
    message: tuple[str, str] | None = None           # (level, text)
    next_steps: tuple[tuple[str, str], ...] = ()     # (text, group key)

    def group(self, key: str) -> ReviewGroup | None:
        return next((g for g in self.groups if g.key == key), None)

    @property
    def pending_total(self) -> int:
        return sum(len(g.pending) for g in self.groups)


def _sorted(rows) -> tuple[ReviewRow, ...]:
    return tuple(sorted(rows, key=lambda r: (_ORDER[r.state], r.parent, r.source)))


def _top_candidate(item) -> tuple[str, str]:
    """(target text, basis) of the confirmed target or the best-ranked candidate. A suggestion, not a decision."""
    candidates = tuple(getattr(item, "candidates", ()) or ())
    if item.already_confirmed and item.exact_candidate:
        return item.exact_candidate, "この会社で確認済みの対応先"
    if candidates:
        top = candidates[0]
        code = f"{top.code} " if getattr(top, "code", "") else ""
        warning = f"（注意: {top.warning}）" if getattr(top, "warning", "") else ""
        return f"{code}{top.name}", f"候補: {top.basis or top.kind}{warning}"
    if item.exact_candidate:
        return item.exact_candidate, item.recommended_reason or "候補"
    return "", "候補なし。JDLの科目一覧から選びます"


def _account_rows(items) -> list[ReviewRow]:
    rows = []
    for item in items:
        target, basis = _top_candidate(item)
        if item.already_confirmed:
            state = CONFIRMED
        elif item.blocker_code:
            state = NEEDS_JDL
        else:
            state = UNCONFIRMED
        rows.append(ReviewRow(
            G_ACCOUNT, item.source_value, state, candidate=target, basis=basis,
            reason=item.blocker_reason or "", journals=item.affected_journal_count or None,
            technical=item.blocker_code or ""))
    return rows


def _subaccount_rows(items) -> list[ReviewRow]:
    rows = []
    for item in items:
        target, basis = _top_candidate(item)
        if item.already_confirmed:
            state = CONFIRMED
        elif item.blocker_code:
            state = NEEDS_JDL
        elif not item.available_targets and not item.subaccount_targets_by_parent:
            state = WAITING_PARENT
        else:
            state = UNCONFIRMED
        reason = item.blocker_reason or ("親科目を確認すると、JDLの補助の候補が表示されます。" if state == WAITING_PARENT else "")
        if item.parent_only_available and state == UNCONFIRMED:
            basis = (basis + "／" if basis else "") + "親科目のみで変換する選択もあります（補助の情報はJDLに入りません）"
        rows.append(ReviewRow(
            G_SUBACCOUNT, item.source_value, state, parent=item.parent_account or "", candidate=target, basis=basis,
            reason=reason, journals=item.affected_journal_count or None, technical=item.blocker_code or ""))
    return rows


def _tax_rows(snapshot: MappingSnapshot) -> list[ReviewRow]:
    rows: list[ReviewRow] = []
    pending: set[str] = set()
    counts = dict(snapshot.observed_tax)
    if snapshot.tax_review is not None:
        for item in snapshot.tax_review.items:
            pending.add(item.source_value)
            if item.human_confirmable:
                rows.append(ReviewRow(
                    G_TAX, item.source_value, UNCONFIRMED, candidate=item.target_display or "",
                    basis="税理士が確認する対応先の候補", reason=item.reason or "",
                    journals=item.affected_row_count or counts.get(item.source_value) or None, unit="行",
                    technical=f"{item.blocker_code} / {item.action_owner}"))
            else:
                rows.append(ReviewRow(
                    G_TAX, item.source_value, NEEDS_EVIDENCE, reason=item.reason or
                    "この税区分には、現在のJDL設定で使える実機の確認がありません。",
                    journals=item.affected_row_count or counts.get(item.source_value) or None, unit="行",
                    technical=f"{item.blocker_code} / {item.action_owner}"))
    saved = dict(snapshot.saved_tax)
    for source, rows_used in snapshot.observed_tax:
        if source in pending:
            continue
        if source in saved:
            rows.append(ReviewRow(G_TAX, source, CONFIRMED, candidate=saved[source],
                                  basis="この会社で確認済みの対応", journals=rows_used or None, unit="行"))
        else:
            rows.append(ReviewRow(
                G_TAX, source, UNCONFIRMED, basis="まだ確認されていません（確認画面を開くと候補と確認の可否が表示されます）",
                journals=rows_used or None, unit="行", technical="NOT_YET_REGISTERED"))
    return rows


def _description_rows(review) -> list[ReviewRow]:
    return [
        ReviewRow(G_DESCRIPTION, f"{item.current_length}文字の摘要", UNCONFIRMED,
                  basis="JDLが保てない文字を含みます。置換する文字を確認します",
                  journals=item.affected_journal_count or None, technical=item.key)
        for item in getattr(review, "descriptions", ())
    ]


def _retention_rows(review) -> list[ReviewRow]:
    rows = []
    for field_ in getattr(review, "information_fields", ()) or ():
        confirmed = bool(getattr(field_, "confirmed", False))
        rows.append(ReviewRow(
            G_RETENTION, field_.field, CONFIRMED if confirmed else UNCONFIRMED,
            candidate=f"意味: {field_.meaning}" if confirmed else "",
            basis="JDLへは出さず、監査記録に残します" if confirmed else "JDLに入らない情報です。意味を確認すると監査記録に残します",
            journals=field_.journals or None))
    blockers = getattr(review, "optional_field_blocker_count", 0)
    if blockers and not getattr(review, "source_is_yayoi", False):
        rows.append(ReviewRow(G_RETENTION, "取引先などの保持方法", UNCONFIRMED,
                              basis="取引先情報の扱い（会社設定）を確認します", journals=blockers))
    return rows


def build_mapping_review(snapshot: MappingSnapshot) -> MappingReviewView:
    review = snapshot.review
    items = tuple(getattr(review, "items", ()))
    account_items = tuple(i for i in items if i.mapping_type == "ACCOUNT")
    sub_items = tuple(i for i in items if i.mapping_type != "ACCOUNT")
    groups = (
        ReviewGroup(G_ACCOUNT, GROUP_TITLES[G_ACCOUNT], _sorted(_account_rows(account_items))),
        ReviewGroup(G_SUBACCOUNT, GROUP_TITLES[G_SUBACCOUNT], _sorted(_subaccount_rows(sub_items))),
        ReviewGroup(G_TAX, GROUP_TITLES[G_TAX], _sorted(_tax_rows(snapshot))),
        ReviewGroup(G_DESCRIPTION, GROUP_TITLES[G_DESCRIPTION], _sorted(_description_rows(review))),
        ReviewGroup(G_RETENTION, GROUP_TITLES[G_RETENTION], _sorted(_retention_rows(review))),
    )
    shape = int(getattr(review, "unsupported_shape_count", 0) or 0)
    notes = []
    if not snapshot.tax_context_ready:
        notes.append("JDL税設定が未確認のため、税区分は確認できません。先に「設定」でJDL税設定を確認してください。")
    if shape:
        notes.append(f"仕訳の構造に実機の確認がない仕訳が{shape:,}仕訳あります（人が確認しても変換できません。"
                     "変換診断の「JDLでの確認待ち」に表示されます）。")
    steps = tuple(
        (f"{g.title}: 未確認 {len(g.pending):,}件", g.key) for g in groups
        if any(r.state in (UNCONFIRMED, WAITING_PARENT) for r in g.rows))
    pending = sum(len(g.pending) for g in groups)
    if pending:
        message = ("warning", f"未確認・対応待ちの項目が{pending:,}件あります。内容は表示だけで、確認・保存は確認画面で行います。")
    else:
        message = ("success", "確認が必要な対応はありません（確認済みの内容は下で見直せます）。")
    return MappingReviewView(groups, int(getattr(review, "logical_journal_count", 0) or 0), shape,
                             tuple(notes), message, steps)
