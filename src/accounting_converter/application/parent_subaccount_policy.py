"""Per-parent view of the subaccount decisions (read-only; confirms nothing).

The mapping screen asks one question per (source parent, source subaccount). The Human thinks
per parent account: "keep this parent's subaccounts" or "parent only". This module groups the
existing review items by source parent and says, per parent, which policy is possible and why,
how many subaccounts and journals it touches, and what each choice costs. It never chooses a
policy and never saves: the selections it returns go through the existing
`CompanyMappingUpdateService.apply` (explicit confirmation, JDL-side checks, audit).

Classes (per subaccount item, against the JDL master read now):
  A  PRESERVE_READY     the JDL parent has a subaccount with this exact name: confirm the match
  B  PARENT_ONLY_OK     the JDL parent has NO subaccount: parent-only is possible (Human approves)
  C  NEEDS_JDL_SUB      the JDL parent has subaccounts but none with this name: pick one or
                        register it in JDL, then reload the account list. Parent-only is forbidden.
  D  PARENT_UNDECIDED   the parent account is not confirmed / has no single JDL candidate yet
  X  (default)          "no subaccount" lines of a parent whose JDL accounts need one: a default
                        JDL subaccount must be chosen (not a loss decision)
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

from .company_mapping_update import PARENT_ONLY_SELECTION, CompanyMappingUpdateItem, CompanyMappingUpdateReview

# Real JDL: blank subaccount on a parent that has subaccounts was rejected at Import (2026-05-15/16).
BLANK_SUBACCOUNT_REJECTION_EVIDENCE = (
    "EVID-JDL-35-5-BLANK-SUB-REJECT-1551-001",
    "EVID-JDL-35-5-BLANK-SUB-REJECT-1311-001",
)

PRESERVE_READY = "A"
PARENT_ONLY_OK = "B"
NEEDS_JDL_SUB = "C"
PARENT_UNDECIDED = "D"
DEFAULT_NEEDED = "X"

CLASS_LABEL = {
    PRESERVE_READY: "JDLに同名の補助あり（対応付けだけ）",
    PARENT_ONLY_OK: "JDLの親科目に補助なし（親科目のみにできる）",
    NEEDS_JDL_SUB: "JDLの親科目に補助あり・同名なし（対応付けまたはJDL登録が必要。親科目のみは不可）",
    PARENT_UNDECIDED: "親科目が未確定（先に親科目を確認）",
    DEFAULT_NEEDED: "補助なし仕訳に既定補助が必要（JDL側が補助必須）",
}


@dataclass(frozen=True)
class SubaccountClass:
    item: CompanyMappingUpdateItem
    klass: str
    parent_target: str | None  # the JDL parent this was judged against (confirmed or exact-name candidate)


@dataclass(frozen=True)
class ParentGroup:
    source_parent: str
    parent_target: str | None
    parent_confirmed: bool
    members: tuple[SubaccountClass, ...]

    @property
    def counts(self) -> dict[str, int]:
        result: dict[str, int] = defaultdict(int)
        for member in self.members:
            result[member.klass] += 1
        return dict(result)

    @property
    def unconfirmed(self) -> tuple[SubaccountClass, ...]:
        return tuple(m for m in self.members if not m.item.already_confirmed)

    @property
    def parent_only_possible(self) -> bool:
        """Every subaccount of this parent can be 'parent only': the JDL parent has no subaccount."""
        subs = [m for m in self.members if m.item.mapping_type == "SUBACCOUNT"]
        return bool(subs) and all(m.klass == PARENT_ONLY_OK or m.item.exact_candidate == PARENT_ONLY_SELECTION for m in subs) \
            and not any(m.klass == DEFAULT_NEEDED for m in self.members)

    @property
    def journals(self) -> int:
        """Journals touched, counted per member (a journal with two subaccounts of one parent counts twice)."""
        return sum(m.item.affected_journal_count for m in self.members)

    @property
    def reason_parent_only_forbidden(self) -> str | None:
        if self.parent_only_possible:
            return None
        if self.parent_target is None:
            return "親科目がまだ確定していません。先に親科目を確認してください。"
        if any(m.klass in {NEEDS_JDL_SUB, PRESERVE_READY, DEFAULT_NEEDED} for m in self.members):
            return ("JDL側でこの親科目に補助科目が設定されているため、親科目のみにはできません。"
                    "補助のある科目へ補助を空欄で取り込むと、JDLは『科目に補助が設定されています』で拒否します"
                    f"（実機で確認: {', '.join(BLANK_SUBACCOUNT_REJECTION_EVIDENCE)}）。"
                    "補助を対応付けるか、JDLへ補助を登録して科目一覧を読み込み直してください。"
                    "補助を省略する別の書き方（補助コード0000など）は実機検証待ちです。")
        return "この親科目は親科目のみにできません。"


def classify(item: CompanyMappingUpdateItem, parent_target_of: dict[str, tuple[str | None, bool]]) -> SubaccountClass:
    parent_target, _confirmed = parent_target_of.get(item.parent_account or "", (None, False))
    if item.mapping_type == "DEFAULT_SUBACCOUNT":
        return SubaccountClass(item, DEFAULT_NEEDED if parent_target else PARENT_UNDECIDED, parent_target)
    if parent_target is None:
        return SubaccountClass(item, PARENT_UNDECIDED, None)
    targets = item.subaccount_targets_for(parent_target)
    if item.source_value in targets:
        return SubaccountClass(item, PRESERVE_READY, parent_target)
    if item.allows_parent_only_for(parent_target):
        return SubaccountClass(item, PARENT_ONLY_OK, parent_target)
    return SubaccountClass(item, NEEDS_JDL_SUB, parent_target)


def parent_targets(review: CompanyMappingUpdateReview) -> dict[str, tuple[str | None, bool]]:
    """Source parent -> (JDL parent to judge against, confirmed?). Confirmed mapping first, else the exact-name candidate."""
    result: dict[str, tuple[str | None, bool]] = {}
    for item in review.items:
        if item.mapping_type == "ACCOUNT":
            if item.already_confirmed and item.exact_candidate:
                result[item.source_value] = (item.exact_candidate, True)
            elif item.exact_candidate:
                result[item.source_value] = (item.exact_candidate, False)
    for item in review.items:
        if item.mapping_type != "ACCOUNT" and item.confirmed_parent_target:
            result[item.parent_account or ""] = (item.confirmed_parent_target, True)
    return result


def parent_groups(review: CompanyMappingUpdateReview, *, only_unconfirmed: bool = True) -> tuple[ParentGroup, ...]:
    targets = parent_targets(review)
    grouped: dict[str, list[SubaccountClass]] = defaultdict(list)
    for item in review.items:
        if item.mapping_type == "ACCOUNT" or (only_unconfirmed and item.already_confirmed):
            continue
        grouped[item.parent_account or ""].append(classify(item, targets))
    return tuple(
        ParentGroup(parent, *targets.get(parent, (None, False)), tuple(members))
        for parent, members in sorted(grouped.items(), key=lambda kv: -sum(m.item.affected_journal_count for m in kv[1]))
    )


def parent_only_selections(group: ParentGroup) -> dict[str, str]:
    """Selections (item key -> PARENT_ONLY_SELECTION) for every unconfirmed subaccount of a parent.

    Only when parent-only is possible for the whole parent. The caller still has to put the keys in the
    `confirmed` set after the Human has seen the loss; nothing here confirms anything."""
    if not group.parent_only_possible:
        raise ValueError(group.reason_parent_only_forbidden or "親科目のみにはできません。")
    return {m.item.key: PARENT_ONLY_SELECTION for m in group.unconfirmed if m.item.mapping_type == "SUBACCOUNT"}


def preserve_selections(group: ParentGroup) -> dict[str, str]:
    """Selections for the subaccounts that already have an exact same-name JDL subaccount (class A)."""
    return {m.item.key: m.item.source_value for m in group.unconfirmed if m.klass == PRESERVE_READY}


def summarize(groups: tuple[ParentGroup, ...]) -> dict:
    """Counts only: items, parents, journals per class, and how many approvals a per-parent choice replaces."""
    by_class_items: dict[str, int] = defaultdict(int)
    by_class_parents: dict[str, set[str]] = defaultdict(set)
    by_class_journals: dict[str, int] = defaultdict(int)
    for group in groups:
        for member in group.unconfirmed:
            by_class_items[member.klass] += 1
            by_class_parents[member.klass].add(group.source_parent)
            by_class_journals[member.klass] += member.item.affected_journal_count
    parent_only_groups = [g for g in groups if g.parent_only_possible and g.unconfirmed]
    return {
        "unconfirmed_items": sum(by_class_items.values()),
        "parents": len({g.source_parent for g in groups if g.unconfirmed}),
        "items_by_class": dict(sorted(by_class_items.items())),
        "parents_by_class": {k: len(v) for k, v in sorted(by_class_parents.items())},
        "journals_by_class_counted_per_item": dict(sorted(by_class_journals.items())),
        "parent_only_whole_parent_possible": {
            "parents": len(parent_only_groups),
            "items": sum(len([m for m in g.unconfirmed if m.item.mapping_type == "SUBACCOUNT"]) for g in parent_only_groups),
            "approvals_if_chosen_per_parent": len(parent_only_groups),
        },
    }


NO_JDL_SUB_REASON = ("JDLのこの親科目には補助科目がありません。補助まで引き継ぐには、JDLで補助科目を登録し、"
                     "科目一覧を読み込み直してからこの画面を開き直してください。")


@dataclass(frozen=True)
class ParentPolicyRow:
    """One line of the per-parent policy screen: what is possible for this parent, and what each choice costs."""

    group: ParentGroup
    subaccounts: int  # unconfirmed named subaccounts of this parent
    journals: int  # 延べ（補助ごとの仕訳数の合計）
    parent_only_allowed: bool
    parent_only_reason: str | None  # why not, when not allowed
    preserve_matches: int  # subaccounts with an exact same-name JDL subaccount
    preserve_allowed: bool
    preserve_reason: str | None
    individual_after_preserve: int  # still to be mapped or registered one by one
    jdl_subaccounts: int = 0  # subaccounts of the JDL parent in the current master

    @property
    def owner(self) -> str:
        """Who acts next: the Human chooses a policy / maps individually, or the parent comes first."""
        if self.group.parent_target is None:
            return "PARENT_FIRST"
        if self.parent_only_allowed or self.preserve_allowed:
            return "HUMAN_CHOOSES_POLICY"
        return "HUMAN_MAPS_EACH"

    @property
    def owner_label(self) -> str:
        return {
            "PARENT_FIRST": "親科目の確認が先",
            "HUMAN_CHOOSES_POLICY": "判断が必要（補助を保持するか親科目のみか）",
            "HUMAN_MAPS_EACH": "個別に判断（JDLの既存補助から選ぶか、JDLで登録）。親科目のみは技術的に不可",
        }[self.owner]


def policy_rows(
    groups: tuple[ParentGroup, ...],
    can_use_parent_only: Callable[[CompanyMappingUpdateItem], bool] = lambda _item: True,
    can_use_exact: Callable[[CompanyMappingUpdateItem], bool] = lambda _item: True,
) -> tuple[ParentPolicyRow, ...]:
    """The screen needs the model's verdict AND whether the open form can actually carry the choice
    (for example the form offers 'parent only' only after the parent account is confirmed there)."""
    rows = []
    for group in groups:
        named = [m for m in group.unconfirmed if m.item.mapping_type == "SUBACCOUNT"]
        if not named:
            continue
        exact = [m for m in named if m.klass == PRESERVE_READY and can_use_exact(m.item)]
        parent_only = group.parent_only_possible and all(can_use_parent_only(m.item) for m in named)
        reason = None if parent_only else (
            group.reason_parent_only_forbidden
            or "この画面で親科目が未確定、または一部の補助がすでに選択済みのため選べません。")
        if group.parent_target is None:
            preserve_reason = "先に親科目を確認してください。"
        elif not exact:
            preserve_reason = (NO_JDL_SUB_REASON if all(m.klass == PARENT_ONLY_OK for m in named)
                               else "JDLに同名の補助がありません。補助を選ぶか、JDLで登録して科目一覧を読み込み直してください。")
        else:
            preserve_reason = None
        jdl_subs = len(named[0].item.subaccount_targets_for(group.parent_target)) if group.parent_target else 0
        rows.append(ParentPolicyRow(
            jdl_subaccounts=jdl_subs,
            group=group, subaccounts=len(named), journals=sum(m.item.affected_journal_count for m in named),
            parent_only_allowed=parent_only, parent_only_reason=reason,
            preserve_matches=len(exact), preserve_allowed=preserve_reason is None, preserve_reason=preserve_reason,
            individual_after_preserve=len(named) - len(exact)))
    return tuple(rows)
