from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from accounting_converter.application.jdl_master_observation import (
    JdlMasterObservation,
)


class JdlMasterChangeKind(str, Enum):
    ACCOUNT_ADDED = "ACCOUNT_ADDED"
    ACCOUNT_REMOVED = "ACCOUNT_REMOVED"
    ACCOUNT_RENAMED = "ACCOUNT_RENAMED"
    ACCOUNT_ENABLED_CHANGED = "ACCOUNT_ENABLED_CHANGED"
    ACCOUNT_CODE_CHANGED = "ACCOUNT_CODE_CHANGED"
    SUBACCOUNT_ADDED = "SUBACCOUNT_ADDED"
    SUBACCOUNT_REMOVED = "SUBACCOUNT_REMOVED"
    SUBACCOUNT_RENAMED = "SUBACCOUNT_RENAMED"
    SUBACCOUNT_PARENT_CHANGED = "SUBACCOUNT_PARENT_CHANGED"
    SUBACCOUNT_CODE_CHANGED = "SUBACCOUNT_CODE_CHANGED"
    AMBIGUOUS_IDENTITY = "AMBIGUOUS_IDENTITY"


@dataclass(frozen=True)
class JdlMasterChange:
    kind: JdlMasterChangeKind
    account_code: str = ""
    subaccount_code: str = ""


@dataclass(frozen=True)
class JdlMasterDiff:
    changes: tuple[JdlMasterChange, ...]

    def affects_account(self, code: str) -> bool:
        return any(change.account_code == code for change in self.changes)

    def affects_subaccount(self, parent_code: str, code: str) -> bool:
        return any(
            change.account_code == parent_code
            and change.subaccount_code == code
            for change in self.changes
        )


def compare_jdl_masters(
    old: JdlMasterObservation,
    new: JdlMasterObservation,
) -> JdlMasterDiff:
    changes: list[JdlMasterChange] = []
    old_accounts = {item.code: item for item in old.printed_accounts}
    new_accounts = {item.code: item for item in new.printed_accounts}

    for code in sorted(old_accounts.keys() | new_accounts.keys()):
        before = old_accounts.get(code)
        after = new_accounts.get(code)
        if before is None:
            changes.append(JdlMasterChange(JdlMasterChangeKind.ACCOUNT_ADDED, code))
        elif after is None:
            changes.append(JdlMasterChange(JdlMasterChangeKind.ACCOUNT_REMOVED, code))
        else:
            if before.name != after.name:
                changes.append(JdlMasterChange(JdlMasterChangeKind.ACCOUNT_RENAMED, code))
            if before.enabled != after.enabled:
                changes.append(
                    JdlMasterChange(JdlMasterChangeKind.ACCOUNT_ENABLED_CHANGED, code)
                )

    old_name_codes = _unique_name_codes(old_accounts.values())
    new_name_codes = _unique_name_codes(new_accounts.values())
    for name in sorted(old_name_codes.keys() & new_name_codes.keys()):
        if old_name_codes[name] != new_name_codes[name]:
            changes.append(
                JdlMasterChange(
                    JdlMasterChangeKind.ACCOUNT_CODE_CHANGED,
                    new_name_codes[name],
                )
            )

    old_subs = {(item.parent_account_code, item.code): item for item in old.subaccounts}
    new_subs = {(item.parent_account_code, item.code): item for item in new.subaccounts}
    for key in sorted(old_subs.keys() | new_subs.keys()):
        before = old_subs.get(key)
        after = new_subs.get(key)
        parent_code, code = key
        if before is None:
            changes.append(
                JdlMasterChange(JdlMasterChangeKind.SUBACCOUNT_ADDED, parent_code, code)
            )
        elif after is None:
            changes.append(
                JdlMasterChange(JdlMasterChangeKind.SUBACCOUNT_REMOVED, parent_code, code)
            )
        elif before.name != after.name:
            changes.append(
                JdlMasterChange(JdlMasterChangeKind.SUBACCOUNT_RENAMED, parent_code, code)
            )

    old_sub_identity = _unique_subaccount_identity(old.subaccounts)
    new_sub_identity = _unique_subaccount_identity(new.subaccounts)
    for name in sorted(old_sub_identity.keys() & new_sub_identity.keys()):
        old_parent, old_code = old_sub_identity[name]
        new_parent, new_code = new_sub_identity[name]
        if old_parent != new_parent:
            changes.append(
                JdlMasterChange(
                    JdlMasterChangeKind.SUBACCOUNT_PARENT_CHANGED,
                    new_parent,
                    new_code,
                )
            )
        elif old_code != new_code:
            changes.append(
                JdlMasterChange(
                    JdlMasterChangeKind.SUBACCOUNT_CODE_CHANGED,
                    new_parent,
                    new_code,
                )
            )

    duplicate_accounts = len(old_accounts) != len(old.printed_accounts) or len(
        new_accounts
    ) != len(new.printed_accounts)
    duplicate_subs = len(old_subs) != len(old.subaccounts) or len(new_subs) != len(
        new.subaccounts
    )
    if duplicate_accounts or duplicate_subs or old.conflicts or new.conflicts:
        changes.append(JdlMasterChange(JdlMasterChangeKind.AMBIGUOUS_IDENTITY))
    return JdlMasterDiff(tuple(dict.fromkeys(changes)))


def _unique_name_codes(items) -> dict[str, str]:
    grouped: dict[str, set[str]] = {}
    for item in items:
        grouped.setdefault(item.name, set()).add(item.code)
    return {name: next(iter(codes)) for name, codes in grouped.items() if len(codes) == 1}


def _unique_subaccount_identity(items) -> dict[str, tuple[str, str]]:
    grouped: dict[str, set[tuple[str, str]]] = {}
    for item in items:
        grouped.setdefault(item.name, set()).add((item.parent_account_code, item.code))
    return {name: next(iter(values)) for name, values in grouped.items() if len(values) == 1}
