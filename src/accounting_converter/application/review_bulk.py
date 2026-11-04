"""Grouped confirmation for the review screen (no Qt; tested directly).

Nothing here saves anything. It decides what a bulk preview may offer and
which rows may be pre-ticked in that preview; the Human approves the list,
the screen fills its normal per-row selections, and the existing save
re-validates everything against the current JDL master.

Pre-ticking rule: only same-name candidates. Similar / alias / partial
candidates are listed but never pre-ticked.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable, Sequence

from accounting_converter.tools.yayoi_decision_sheet import (
    _digits,
    apply_rules,
    description_fits,
    propose_rules,
)

PRE_TICKED_KINDS = frozenset({"EXACT", "SAME_NAME"})


@dataclass(frozen=True)
class BulkRow:
    index: int  # position in the caller's own list of rows
    source: str
    parent: str
    target: str
    target_label: str
    kind: str
    kind_label: str
    journals: int
    warning: str = ""

    @property
    def pre_ticked(self) -> bool:
        return self.kind in PRE_TICKED_KINDS and not self.warning


def account_bulk_row(index: int, item) -> BulkRow | None:
    """Best suggestion for one account review item (None when there is none)."""
    if item.exact_candidate:
        return BulkRow(index, item.source_value, "", item.exact_candidate, item.exact_candidate,
                       "EXACT", item.recommended_reason or "名前が同じ", item.affected_journal_count)
    candidates = tuple(getattr(item, "candidates", ()))
    if not candidates:
        return None
    best = candidates[0]
    return BulkRow(index, item.source_value, "", best.name, f"{best.code} {best.name}",
                   best.kind, best.label, item.affected_journal_count, best.warning)


def subaccount_bulk_row(index: int, item, options: Sequence[tuple[str, str]]) -> BulkRow | None:
    """options: (label, target) offered for the item's confirmed parent, best first."""
    if not options:
        return None
    for label, target in options:
        if target == item.source_value:
            return BulkRow(index, item.source_value, item.parent_account or "", target, target,
                           "SAME_NAME", "名前が同じ", item.affected_journal_count)
    label, target = options[0]
    return BulkRow(index, item.source_value, item.parent_account or "", target, label,
                   "SUGGESTED", "候補（名前が違う）", item.affected_journal_count)


# ---------------------------------------------------------------- descriptions

def description_rules(originals: Iterable[str]) -> list[dict]:
    """Proposed rules as editable records (nothing approved)."""
    return [
        {"ルールID": rule_id, "種類": kind, "対象の語句": phrase, "影響する摘要数": count, "説明": explanation,
         "【記入】短縮後の語句": "", "【記入】承認": ""}
        for rule_id, kind, phrase, count, explanation in propose_rules(list(originals))
    ]


@dataclass(frozen=True)
class DescriptionPreviewLine:
    key: str
    original: str
    result: str
    state: str  # FIT / DIGITS_CHANGED / INDIVIDUAL

    @property
    def fits(self) -> bool:
        return self.state == "FIT"


def rule_problems(rules: Sequence[dict]) -> list[str]:
    return [
        f"{rule['ルールID']}: 短縮後の語句を入力してください"
        for rule in rules
        if rule["【記入】承認"] == "OK" and rule["種類"] == "語句の短縮" and not rule["【記入】短縮後の語句"].strip()
    ]


def description_preview(descriptions: Sequence[tuple[str, str]], rules: Sequence[dict]) -> list[DescriptionPreviewLine]:
    """Every description, before/after, with whether the result may be used.

    A result is used only when it fits JDL (1-32 characters, no line break,
    CP932, no characters JDL changes) and every digit is unchanged.
    """
    approved = [rule for rule in rules if rule["【記入】承認"] == "OK"]
    lines = []
    for key, original in descriptions:
        result = apply_rules(original, approved) if approved else ""
        if result and _digits(result) != _digits(original):
            state = "DIGITS_CHANGED"
        elif result and description_fits(result):
            state = "FIT"
        else:
            state = "INDIVIDUAL"
        lines.append(DescriptionPreviewLine(key, original, result, state))
    return lines


def preview_signature(lines: Sequence[DescriptionPreviewLine]) -> str:
    """Identity of a preview: what was shown is exactly what is applied."""
    payload = [(line.key, line.original, line.result, line.state) for line in lines]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()
