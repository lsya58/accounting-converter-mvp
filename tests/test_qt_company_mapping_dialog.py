from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QScrollArea,
        QTableWidget,
    )

    from accounting_converter.application.company_mapping_update import (
        CompanyMappingUpdateItem,
        CompanyMappingUpdateReview,
    )
    from accounting_converter.application.moneyforward_description_replacement import (
        MoneyForwardDescriptionReviewItem,
        moneyforward_description_replacement_key,
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
            available_targets=(
                "target-parent-a",
                "target-parent-b",
                "target-parent-no-sub",
            ),
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
                ("target-parent-no-sub", ()),
            ),
            parent_only_targets=("target-parent-no-sub",),
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

    def test_confirmed_parent_without_target_subaccounts_offers_parent_only(self) -> None:
        dialog = CompanyMappingUpdateDialog(object(), self.review)
        parent, parent_confirmed = dialog.account_controls["source-parent"]
        _item, subaccount, _subaccount_confirmed = dialog.subaccount_controls[0]

        parent.setCurrentIndex(parent.findData("target-parent-no-sub"))
        parent_confirmed.setChecked(True)

        self.assertEqual(
            [subaccount.itemData(index) for index in range(subaccount.count())],
            [None, "__PARENT_ONLY_CONFIRMED__"],
        )

    def test_confirmed_subset_enables_partial_save(self) -> None:
        dialog = CompanyMappingUpdateDialog(object(), self.review)
        parent, parent_confirmed = dialog.account_controls["source-parent"]

        parent.setCurrentIndex(parent.findData("target-parent-a"))
        parent_confirmed.setChecked(True)

        self.assertTrue(dialog.save_button.isEnabled())
        self.assertEqual(dialog.save_button.text(), "確認済み1件を保存")
        self.assertEqual(
            dialog.progress_label.text(),
            "この画面で確認済み: 1件 / 未確認: 1件",
        )

    def test_large_review_is_split_into_scrollable_categories(self) -> None:
        accounts = tuple(
            CompanyMappingUpdateItem(
                key=f"ACCOUNT|source-{index}",
                mapping_type="ACCOUNT",
                source_value=f"source-{index}",
                parent_account=None,
                available_targets=("target-parent-a",),
            )
            for index in range(60)
        )
        review = CompanyMappingUpdateReview(
            company_setting_id="company-a",
            source_path=None,
            context_path=None,
            items=accounts,
            tax_categories=("課税仕入10%",),
            unsupported_shape_count=2,
            optional_field_blocker_count=26,
        )

        dialog = CompanyMappingUpdateDialog(object(), review)

        self.assertEqual(dialog.tabs.count(), 5)
        self.assertEqual(dialog.tabs.tabText(0), "科目 0/60")
        account_table = dialog.tabs.widget(0).findChild(QTableWidget)
        self.assertIsNotNone(account_table)
        self.assertEqual(account_table.rowCount(), 60)
        self.assertEqual(
            account_table.verticalScrollMode(),
            QAbstractItemView.ScrollMode.ScrollPerPixel,
        )
        self.assertIsInstance(dialog.tabs.widget(2), QScrollArea)
        self.assertEqual(dialog.tabs.tabText(3), "税区分 0/1")
        self.assertEqual(dialog.tabs.tabText(4), "その他 2構成/26仕訳")

    def test_description_candidate_is_prefilled_but_requires_confirmation(self) -> None:
        original = "髙橋"
        review = CompanyMappingUpdateReview(
            company_setting_id="company-a",
            source_path=None,
            context_path=None,
            items=(),
            descriptions=(
                MoneyForwardDescriptionReviewItem(
                    key=moneyforward_description_replacement_key(original),
                    original_description_sha256="hash",
                    current_description=original,
                    current_length=2,
                    unsafe_positions=(0,),
                    affected_journal_count=10,
                ),
            ),
        )

        dialog = CompanyMappingUpdateDialog(object(), review)
        field, confirmation = next(iter(dialog.description_controls.values()))

        self.assertEqual(field.text(), "高橋")
        self.assertTrue(confirmation.isEnabled())
        self.assertFalse(confirmation.isChecked())
        self.assertFalse(dialog.save_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
