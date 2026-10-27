from __future__ import annotations

import unittest

from accounting_converter.application.jdl_master_diff import (
    JdlMasterChangeKind,
    compare_jdl_masters,
)
from accounting_converter.application.jdl_master_observation import (
    JdlMasterObservation,
    JdlObservedSubaccount,
    JdlPrintedAccount,
)


class JdlMasterDiffTests(unittest.TestCase):
    def test_unrelated_additions_do_not_affect_existing_identity(self) -> None:
        old = self._observation()
        new = self._observation(
            accounts=(self._account("9999", "追加科目"),),
            subaccounts=(self._subaccount("9999", "0001", "追加補助"),),
        )

        diff = compare_jdl_masters(old, new)

        self.assertFalse(diff.affects_account("3181"))
        self.assertFalse(diff.affects_subaccount("3181", "0001"))

    def test_relevant_subaccount_lifecycle_is_scoped_to_parent_and_code(self) -> None:
        old = self._observation()
        added = self._observation(
            subaccounts=(self._subaccount("3181", "0001", "カード"),)
        )
        renamed = self._observation(
            subaccounts=(self._subaccount("3181", "0001", "カード変更"),)
        )

        addition = compare_jdl_masters(old, added)
        rename = compare_jdl_masters(added, renamed)
        removal = compare_jdl_masters(added, old)

        self.assertIn(
            JdlMasterChangeKind.SUBACCOUNT_ADDED,
            {item.kind for item in addition.changes},
        )
        self.assertIn(
            JdlMasterChangeKind.SUBACCOUNT_RENAMED,
            {item.kind for item in rename.changes},
        )
        self.assertIn(
            JdlMasterChangeKind.SUBACCOUNT_REMOVED,
            {item.kind for item in removal.changes},
        )
        self.assertTrue(addition.affects_subaccount("3181", "0001"))

    def test_account_rename_enable_and_code_change_are_reported(self) -> None:
        old = self._observation()
        new = JdlMasterObservation(
            accounts=(),
            subaccounts=(),
            departments=(),
            sources=(),
            printed_accounts=(self._account("3199", "未払金", enabled=False),),
        )

        kinds = {item.kind for item in compare_jdl_masters(old, new).changes}

        self.assertIn(JdlMasterChangeKind.ACCOUNT_REMOVED, kinds)
        self.assertIn(JdlMasterChangeKind.ACCOUNT_ADDED, kinds)
        self.assertIn(JdlMasterChangeKind.ACCOUNT_CODE_CHANGED, kinds)

    @classmethod
    def _observation(cls, *, accounts=(), subaccounts=()):
        return JdlMasterObservation(
            accounts=(),
            subaccounts=(cls._subaccount("3181", "0000", "既存補助"), *subaccounts),
            departments=(),
            sources=(),
            printed_accounts=(cls._account("3181", "未払金"), *accounts),
        )

    @staticmethod
    def _account(code: str, name: str, enabled: bool = True) -> JdlPrintedAccount:
        return JdlPrintedAccount(code, name, name, "貸", enabled)

    @staticmethod
    def _subaccount(parent: str, code: str, name: str) -> JdlObservedSubaccount:
        return JdlObservedSubaccount(parent, "未払金", code, name)


if __name__ == "__main__":
    unittest.main()
