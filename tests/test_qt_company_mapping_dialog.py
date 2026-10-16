from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication

    from accounting_converter.application.company_mapping_update import (
        CompanyMappingUpdateItem,
        CompanyMappingUpdateReview,
    )
    from accounting_converter.ui_qt.main_window import CompanyMappingUpdateDialog

    PYSIDE6_AVAILABLE = True
except ModuleNotFoundError:
    PYSIDE6_AVAILABLE = False


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class CompanyMappingUpdateDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        account = CompanyMappingUpdateItem(
            key="ACCOUNT:source-parent:",
            mapping_type="ACCOUNT",
            source_value="source-parent",
            parent_account=None,
            available_targets=("target-parent-a", "target-parent-b"),
        )
        subaccount = CompanyMappingUpdateItem(
            key="SUBACCOUNT:source-sub:source-parent",
            mapping_type="SUBACCOUNT",
            source_value="source-sub",
            parent_account="source-parent",
            available_targets=(),
            subaccount_targets_by_parent=(
                ("target-parent-a", ("target-sub-a1", "target-sub-a2")),
                ("target-parent-b", ("target-sub-b1",)),
            ),
        )
        self.review = CompanyMappingUpdateReview(
            company_setting_id="company-a",
            source_path=None,
            context_path=None,
            items=(account, subaccount),
            tax_categories=(),
        )

    def test_dialog_initializes_before_initial_subaccount_refresh(self) -> None:
        dialog = CompanyMappingUpdateDialog(object(), self.review)

        self.assertFalse(dialog.save_button.isEnabled())
        _item, subaccount, confirmed = dialog.subaccount_controls[0]
        self.assertEqual(subaccount.count(), 1)
        self.assertIsNone(subaccount.currentData())
        self.assertFalse(confirmed.isEnabled())

    def test_confirmed_parent_updates_candidates_and_parent_change_resets(self) -> None:
        dialog = CompanyMappingUpdateDialog(object(), self.review)
        parent, parent_confirmed = dialog.account_controls["source-parent"]
        _item, subaccount, subaccount_confirmed = dialog.subaccount_controls[0]

        parent.setCurrentIndex(parent.findData("target-parent-a"))
        self.assertEqual(subaccount.count(), 1)
        parent_confirmed.setChecked(True)
        self.assertEqual(
            [subaccount.itemData(index) for index in range(subaccount.count())],
            [None, "target-sub-a1", "target-sub-a2"],
        )

        subaccount.setCurrentIndex(subaccount.findData("target-sub-a1"))
        subaccount_confirmed.setChecked(True)
        parent.setCurrentIndex(parent.findData("target-parent-b"))
        self.assertEqual(
            [subaccount.itemData(index) for index in range(subaccount.count())],
            [None, "target-sub-b1"],
        )
        self.assertIsNone(subaccount.currentData())
        self.assertFalse(subaccount_confirmed.isChecked())


if __name__ == "__main__":
    unittest.main()
