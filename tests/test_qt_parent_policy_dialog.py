"""Per-parent policy dialog (skipped where PySide6 is not installed; run it on Windows). Synthetic data."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication

    from accounting_converter.application import parent_subaccount_policy as policy
    from accounting_converter.application.company_mapping_update import (
        CompanyMappingUpdateItem,
        CompanyMappingUpdateReview,
    )
    from accounting_converter.ui_qt.parent_policy_dialog import PARENT_ONLY, ParentPolicyDialog

    PYSIDE6_AVAILABLE = True
except ModuleNotFoundError:
    PYSIDE6_AVAILABLE = False


def _account(name, target):
    return CompanyMappingUpdateItem(
        key=f"ACCOUNT|{name}", mapping_type="ACCOUNT", source_value=name, parent_account=None,
        available_targets=(target,), exact_candidate=target, already_confirmed=True)


def _sub(parent, parent_target, name, *, jdl_subs=(), journals=2):
    return CompanyMappingUpdateItem(
        key=f"SUBACCOUNT|{name}|{parent}", mapping_type="SUBACCOUNT", source_value=name, parent_account=parent,
        available_targets=tuple(jdl_subs), parent_only_available=not jdl_subs,
        subaccount_targets_by_parent=((parent_target, tuple(jdl_subs)),),
        parent_only_targets=() if jdl_subs else (parent_target,),
        confirmed_parent_target=parent_target, affected_journal_count=journals)


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class ParentPolicyDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self, rows):
        # Destroy the dialog before the interpreter exits; leaving it to GC at shutdown aborts on Windows.
        dialog = ParentPolicyDialog(rows)

        def cleanup():
            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()
        self.addCleanup(cleanup)
        return dialog

    def _rows(self):
        items = (_account("手数料", "支払手数料"), _account("預金", "普通預金"),
                 _sub("手数料", "支払手数料", "取引先P"), _sub("手数料", "支払手数料", "取引先Q"),
                 _sub("預金", "普通預金", "銀行A", jdl_subs=("銀行A",)), _sub("預金", "普通預金", "銀行Z", jdl_subs=("銀行A",)))
        review = CompanyMappingUpdateReview("c", None, __import__("pathlib").Path("x"), items, 4)
        return policy.policy_rows(policy.parent_groups(review))

    def test_nothing_is_chosen_by_default_and_parent_only_is_offered_only_where_possible(self):
        rows = self._rows()
        dialog = self._dialog(rows)
        self.assertEqual(dialog.choices(), {})
        self.assertFalse(dialog.next_button.isEnabled())
        by_parent = {row.group.source_parent: combo for row, combo in zip(rows, dialog.combos)}
        fee, bank = by_parent["手数料"], by_parent["預金"]
        self.assertTrue(fee.model().item(2).isEnabled())  # 親科目のみ
        self.assertFalse(fee.model().item(1).isEnabled())  # 補助を保持: the JDL parent has no subaccount
        self.assertFalse(bank.model().item(2).isEnabled())  # JDL parent has subaccounts: parent-only forbidden
        self.assertTrue(bank.model().item(1).isEnabled())

    def test_parent_only_needs_an_explicit_acknowledgement_and_only_chosen_parents_are_returned(self):
        rows = self._rows()
        dialog = self._dialog(rows)
        for row, combo in zip(rows, dialog.combos):
            if row.group.source_parent == "手数料":
                combo.setCurrentIndex(combo.findData(PARENT_ONLY))
        self.assertEqual(dialog.choices(), {"手数料": PARENT_ONLY})
        dialog._show_confirm()
        self.assertFalse(dialog.apply_button.isEnabled())
        dialog.loss_ack.setChecked(True)
        self.assertTrue(dialog.apply_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
