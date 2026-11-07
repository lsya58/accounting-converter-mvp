"""Where each still-open subaccount could go in JDL: a sorted worklist, never a decision.

For subaccounts whose JDL parent HAS subaccounts but none with the same name (class C of
`parent_subaccount_policy`), parent-only is impossible (blank / 0000 rejected by JDL), so the
office must either pick an existing JDL subaccount or register a new one in JDL. This module
sorts those items so the Human sees the few that need thought first:

  NOTATION_DIFF     after search-only normalization (width, spaces, ㈱/(株)/株式会社, ー/-,
                    separated dakuten) the name equals exactly ONE usable JDL subaccount of the
                    parent. Still a Human confirmation: the names are not identical.
  JDL_NAME_UNUSABLE the same normalization matches a JDL subaccount whose JDL name cannot be
                    written in the import field: the JDL name must be shortened in JDL first.
  NEW_REGISTRATION  nothing in the parent matches: register in JDL (or pick another subaccount
                    if the office manages it differently). Similar-looking names are shown for
                    reference only; similarity never makes a candidate.
  SOURCE_UNCLEAR    the Yayoi name reads as a channel / arrangement (代引, 経由, 案件 ...), so the
                    source data alone cannot say which JDL customer/supplier it is.

Nothing here selects, confirms or saves. Applying a filled sheet goes through
`check_filled_rows` and the production mapping save path (exact code + name in the CURRENT
JDL master, unique under the parent, usable, explicitly marked done by the Human).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from accounting_converter.profiles.jdl_official import jdl_subaccount_name_fits

from .subaccount_candidate_discovery import rank_subaccount_candidates

NOTATION_DIFF = "NOTATION_DIFF"
JDL_NAME_UNUSABLE = "JDL_NAME_UNUSABLE"
NEW_REGISTRATION = "NEW_REGISTRATION"
SOURCE_UNCLEAR = "SOURCE_UNCLEAR"

LABELS = {
    NOTATION_DIFF: "表記差のある既存補助あり（確認待ち）",
    JDL_NAME_UNUSABLE: "JDLに同じ相手らしき補助があるが名前が取込欄に入らない（JDLで名称を短くする）",
    NEW_REGISTRATION: "JDLに該当なし（新規登録の候補）",
    SOURCE_UNCLEAR: "名称から取引先を特定できない（元データだけでは判断不可）",
}
ORDER = (JDL_NAME_UNUSABLE, NOTATION_DIFF, SOURCE_UNCLEAR, NEW_REGISTRATION)

# Words that name a delivery / payment channel or an arrangement rather than a counterparty.
_UNCLEAR_WORDS = ("代引", "経由", "案件", "さん")
_COMPANY_MARKS = ("株式会社", "有限会社", "(株)", "(有)", "㈱", "㈲")
_SEPARATED_MARKS = {"゛": "゙", "゜": "゚", "ﾞ": "゙", "ﾟ": "゚"}


def search_key(value: str) -> str:
    """Search-only normalization. Stored identities and outputs always stay exact."""
    text = "".join(value.split())
    # Join a separated (spacing) voiced mark to the kana before it: ト゛ -> ド.
    out: list[str] = []
    for char in text:
        mark = _SEPARATED_MARKS.get(char)
        if mark and out:
            out[-1] = unicodedata.normalize("NFC", out[-1] + mark)
        else:
            out.append(char)
    text = unicodedata.normalize("NFKC", "".join(out))
    for mark in _COMPANY_MARKS:
        text = text.replace(unicodedata.normalize("NFKC", mark), "")
    text = re.sub(r"[\-‐‑–—―ー－ｰ・･]", "", text)
    return text.lower()


@dataclass(frozen=True)
class JdlSub:
    parent_code: str
    code: str
    name: str
    usable: bool


@dataclass(frozen=True)
class RegistrationRow:
    source_parent: str
    source_name: str
    jdl_parent_code: str
    journals: int
    category: str
    matched: tuple[JdlSub, ...]           # NOTATION_DIFF / JDL_NAME_UNUSABLE matches
    similar_for_reference: tuple[str, ...]  # display only, never a candidate
    source_name_fits_jdl: bool

    @property
    def label(self) -> str:
        return LABELS[self.category]

    @property
    def suggested_new_name(self) -> str:
        """The Yayoi name when JDL can hold it; else blank (the Human decides a short name)."""
        return self.source_name if self.source_name_fits_jdl else ""


def classify(source_parent: str, source_name: str, jdl_parent_code: str, journals: int,
             jdl_subs: tuple[JdlSub, ...]) -> RegistrationRow:
    key = search_key(source_name)
    in_parent = tuple(s for s in jdl_subs if s.parent_code == jdl_parent_code)
    same = tuple(s for s in in_parent if key and search_key(s.name) == key)
    usable_same = tuple(s for s in same if s.usable)
    unusable_same = tuple(s for s in same if not s.usable)
    if len(usable_same) == 1 and not unusable_same:
        category, matched = NOTATION_DIFF, usable_same
    elif unusable_same and not usable_same:
        category, matched = JDL_NAME_UNUSABLE, unusable_same
    elif same:
        # Several JDL subaccounts read the same: never pick one; the Human sees all of them.
        category, matched = NOTATION_DIFF, same
    elif any(word in source_name for word in _UNCLEAR_WORDS):
        category, matched = SOURCE_UNCLEAR, ()
    else:
        category, matched = NEW_REGISTRATION, ()
    similar = ()
    if category in {NEW_REGISTRATION, SOURCE_UNCLEAR}:
        ranked = rank_subaccount_candidates(source_name, tuple(s.name for s in in_parent if s.usable))
        similar = tuple(c.target_name for c in ranked if c.priority <= 3)[:3]
    return RegistrationRow(source_parent, source_name, jdl_parent_code, journals, category, matched,
                           similar, jdl_subaccount_name_fits(source_name))


def sort_rows(rows) -> list[RegistrationRow]:
    return sorted(rows, key=lambda r: (ORDER.index(r.category), r.jdl_parent_code, -r.journals, r.source_name))


@dataclass(frozen=True)
class FilledRow:
    sheet_row: int
    source_parent: str
    source_name: str
    jdl_parent_code: str
    decision: str  # 既存補助 / 新規登録 / 保留 / ""
    code: str
    name: str
    done: bool


DECISIONS = ("既存補助", "新規登録", "保留", "")


def check_filled_rows(rows: list[FilledRow], jdl_subs: tuple[JdlSub, ...]) -> tuple[list[FilledRow], list[tuple[int, str]]]:
    """Rows that may be saved, and every problem. Any problem means nothing is saved.

    A row is saved only when the Human marked it done, chose 既存補助 or 新規登録, and wrote a
    code AND name that exist exactly, once, as a usable subaccount of that JDL parent in the
    CURRENT master (so a 新規登録 row passes only after JDL registration and a reloaded 科目一覧).
    """
    ready: list[FilledRow] = []
    problems: list[tuple[int, str]] = []
    seen: dict[tuple[str, str], int] = {}
    for row in rows:
        if row.decision not in DECISIONS:
            problems.append((row.sheet_row, "判断は 既存補助 / 新規登録 / 保留 / 空欄 のどれか"))
            continue
        if row.decision in {"", "保留"}:
            if row.done:
                problems.append((row.sheet_row, "保留・空欄の行に確認済みが付いている"))
            continue
        if not row.done:
            continue  # filled but not yet marked done by the Human: stays open
        if not (row.code.isdigit() and len(row.code) == 4) or not row.name:
            problems.append((row.sheet_row, "JDL補助コード（4桁）と名称の両方が必要"))
            continue
        exact = [s for s in jdl_subs if s.parent_code == row.jdl_parent_code and s.code == row.code]
        if not exact:
            problems.append((row.sheet_row, "そのコードの補助が現在のJDL科目一覧の親科目にない"
                                            "（新規登録なら、JDLで登録後に科目一覧PDFを読み込み直す）"))
            continue
        if exact[0].name != row.name:
            problems.append((row.sheet_row, "コードと名称がJDL科目一覧と一致しない"))
            continue
        if not exact[0].usable:
            problems.append((row.sheet_row, "JDLの補助名称が取込欄に入らないため使えない（JDLで名称を短くする）"))
            continue
        if sum(s.parent_code == row.jdl_parent_code and s.name == row.name and s.usable for s in jdl_subs) != 1:
            problems.append((row.sheet_row, "同じ名称の補助が親科目に複数あり、名称で特定できない"))
            continue
        target = (row.jdl_parent_code, row.code)
        if target in seen:
            # Two Yayoi names on one JDL subaccount merges them: allowed only as an explicit,
            # visible choice, so flag it instead of silently accepting.
            problems.append((row.sheet_row, f"{seen[target]}行目と同じJDL補助を選んでいる（統合になる。意図した場合は片方を保留にして個別に確認）"))
            continue
        seen[target] = row.sheet_row
        ready.append(row)
    return ready, problems
