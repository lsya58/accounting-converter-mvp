"""Why journals are not READY, and what each fix would release. Counts only; no customer values.

One place used by the GUI (controller messages) and the CLI diagnosis, so both always say the same.

  first       the journal's first blocker in `PRIORITY` (the thing to fix first)
  all         journals that have this blocker at all (a journal can have several)
  only_this   journals whose ONLY blocker is this one: fixing it alone makes them READY
              (given the current Evidence; nothing is confirmed or assumed)

`store_check` flags a CompanySetting that looks like the wrong one (e.g. a setting with no account
approvals, or a master that is much smaller than the data needs). It never changes the diagnosis.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

# (blocker, category, what the user does). Order = what to fix first.
PRIORITY: tuple[tuple[str, str, str], ...] = (
    ("SYSTEM_EVIDENCE:TAX_CONTEXT_UNVERIFIED", "会社設定", "JDL税設定（課税方式・端数処理など）を確認・保存してください。"),
    ("HUMAN:JDL_TAX_ROUNDING_SETTING", "会社設定", "JDL会社の消費税の端数処理（売上・仕入）を設定してください。"),
    ("HUMAN:VOUCHER_ROW_LIMIT_SETTING", "会社設定", "JDLの会社設定「振替伝票入力行数」を確認して入力してください。"),
    ("SYSTEM_EVIDENCE:VOUCHER_ROW_LIMIT_SETTING_UNVERIFIED", "会社設定", "この振替伝票入力行数（例: 64行以内）はJDL実機で未確認です。実機確認（tools/yayoi_row64_probe）が済むまで変換しません。"),
    ("SYSTEM_EVIDENCE:VOUCHER_ROW_LIMIT_SUBACCOUNT_UNVERIFIED", "会社設定", "この振替伝票入力行数の設定では補助科目付きの行が実機で未確認です（tools/yayoi_row64_probe の SUB 対照）。"),
    ("HUMAN:ACCOUNT_MAPPING", "科目", "科目の対応（JDL科目の選択）を確認してください。"),
    ("HUMAN:SUBACCOUNT_MAPPING", "補助", "補助科目の対応を確認してください（親科目のみ・既存補助・JDL新規登録のいずれか）。"),
    ("HUMAN:SUBACCOUNT_DEFAULT", "補助", "補助なしの仕訳のまとめ先補助を確認してください。"),
    ("HUMAN:TAX_MAPPING", "税区分", "税区分の対応を確認してください。"),
    ("HUMAN:DEPARTMENT_POLICY", "任意項目", "部門の扱い（JDLへは出さず監査記録に残す）を確認してください。"),
    ("HUMAN:OPTIONAL_FIELD_POLICY", "任意項目", "生成元・付箋などJDLに入らない情報の扱いを確認してください。"),
    ("HUMAN:DESCRIPTION_REPLACEMENT", "摘要", "JDLに入らない摘要の置き換えを確認してください。"),
    ("HUMAN:VOUCHER_SPLIT_APPROVAL", "伝票分割の承認", "行数超過の仕訳を分割できます（各伝票はJDL実機で確認済み）。分割してよいかの税理士確認を記録してください（tools/yayoi_voucher_split approve）。"),
    ("HUMAN:VOUCHER_ROW_LIMIT_EXCEEDED", "行数超過", "振替伝票入力行数を超えています。分割するかJDLで手入力してください（自動分割はしません）。"),
    ("HUMAN:NEGATIVE_AMOUNT", "負の金額", "JDLのCSV取込は負の金額を受け付けません（実機確認）。符号・借貸・税額は変えません。弥生側での表し方を税理士と確認してください。"),
    ("SYSTEM_EVIDENCE:CLOSING_ENTRY_REPRESENTATION", "決算仕訳", "本決はJDL実機で確認済みの形だけ決算整理仕訳（日付13月）で出力します。中決と未確認の形は止めます。通常仕訳への置き換えは会計判断です。"),
)
_EVIDENCE_TAX = frozenset({
    "TAX_ACCOUNT_UNVERIFIED", "TAX_SIDE_UNVERIFIED", "EXPLICIT_TAX_AMOUNT_UNVERIFIED",
    "EXPLICIT_TAX_COMPANY_ROUNDING_UNVERIFIED", "EXPLICIT_TAX_KEEP_UNVERIFIED",
    "SHAPE_TAX_COMBINATION_UNVERIFIED", "SHAPE_UNVERIFIED_IN_TAX_CONTEXT", "MULTIPLE_TAXED_LINES_UNVERIFIED",
})
_BY_CODE = {code: (category, action) for code, category, action in PRIORITY}
_RANK = {code: index for index, (code, _c, _a) in enumerate(PRIORITY)}
_EVIDENCE_RANK = len(PRIORITY)


def describe(blocker: str) -> tuple[str, str]:
    """(category, action) for a blocker code."""
    if blocker in _BY_CODE:
        return _BY_CODE[blocker]
    if blocker.startswith("SYSTEM_EVIDENCE:"):
        gap = blocker.split(":", 1)[1]
        if gap in _EVIDENCE_TAX:
            return "Evidence不足（税）", "この税の書き方はJDL実機で未確認です。追加の実機確認が必要です（設定では解消しません）。"
        return "Evidence不足（仕訳構造）", "この仕訳の形はJDL実機で未確認です。追加の実機確認が必要です（設定では解消しません）。"
    if blocker.startswith("SYSTEM_IMPLEMENTATION:"):
        return "実装不足", "アプリ側の未対応です。開発側の対応が必要です。"
    return "その他", "確認が必要です。"


def _rank(blocker: str) -> int:
    return _RANK.get(blocker, _EVIDENCE_RANK + (1 if blocker.startswith("SYSTEM_IMPLEMENTATION") else 0))


@dataclass(frozen=True)
class BreakdownRow:
    blocker: str
    category: str
    action: str
    first: int
    all: int
    only_this: int


def breakdown(journal_blockers: dict) -> tuple[BreakdownRow, ...]:
    """One row per blocker code, in fix order. READY journals (no blockers) are not counted."""
    first, every, only = Counter(), Counter(), Counter()
    for found in journal_blockers.values():
        found = sorted(set(found), key=lambda b: (_rank(b), b))
        if not found:
            continue
        first[found[0]] += 1
        for blocker in found:
            every[blocker] += 1
        if len(found) == 1:
            only[found[0]] += 1
    rows = []
    for blocker in sorted(every, key=lambda b: (_rank(b), b)):
        category, action = describe(blocker)
        rows.append(BreakdownRow(blocker, category, action, first[blocker], every[blocker], only[blocker]))
    return tuple(rows)


def by_category(journal_blockers: dict) -> dict[str, dict[str, int]]:
    """Per category: journals whose FIRST blocker is in it, and journals with any blocker in it."""
    first, every = Counter(), Counter()
    for found in journal_blockers.values():
        found = sorted(set(found), key=lambda b: (_rank(b), b))
        if not found:
            continue
        first[describe(found[0])[0]] += 1
        for category in {describe(b)[0] for b in found}:
            every[category] += 1
    return {category: {"first": first[category], "all": every[category]} for category in every}


def summary_lines(journal_blockers: dict, limit: int = 8) -> tuple[str, ...]:
    """Short GUI lines: reason, journals blocked, journals blocked ONLY by it, and what to do."""
    lines = []
    for row in breakdown(journal_blockers)[:limit]:
        lines.append(
            f"【{row.category}】{row.all:,}仕訳（これだけで止まっている仕訳 {row.only_this:,}）: {row.action}"
        )
    return tuple(lines)


def store_check(*, account_mappings: int, subaccount_mappings: int, master_accounts: int | None,
                account_blocked_journals: int, voucher_row_limit: int | None,
                confirmed_context: bool) -> tuple[str, ...]:
    """Warnings when a CompanySetting does not look like the one the data was prepared with."""
    warnings = []
    if not confirmed_context:
        warnings.append("【会社設定の確認】JDL税設定が確認済みではありません。")
    if account_mappings == 0:
        warnings.append("【会社設定の確認】確認済みの科目対応が0件です。別の（古い・空の）会社設定を選んでいないか確認してください。")
    elif account_blocked_journals:
        warnings.append(f"【会社設定の確認】科目対応が未確認の仕訳が{account_blocked_journals:,}件あります（確認済み{account_mappings}件）。")
    if master_accounts == 0:  # None = unknown (the master is still a PDF draft)
        warnings.append("【会社設定の確認】JDL科目一覧が空です。")
    if voucher_row_limit is None:
        warnings.append("【会社設定の確認】振替伝票入力行数が未入力です（アプリは黙って補完しません）。")
    return tuple(warnings)


def trace_ready(reference_ready_ids, journal_blockers: dict) -> dict:
    """Journals READY in a reference diagnosis: what blocks them here (first and all reasons)."""
    reference_ready_ids = list(reference_ready_ids)
    first, every, still_ready = Counter(), Counter(), 0
    for journal_id in reference_ready_ids:
        found = sorted(set(journal_blockers.get(journal_id, ())), key=lambda b: (_rank(b), b))
        if not found:
            still_ready += 1
            continue
        first[found[0]] += 1
        every.update(found)
    return {"reference_ready": len(reference_ready_ids),
            "still_ready": still_ready, "first_blocker": dict(first.most_common()), "all_blockers": dict(every.most_common())}
