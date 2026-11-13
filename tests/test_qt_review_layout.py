"""Table-centred review screen: layout and safety of the compact UI (synthetic data only)."""
from __future__ import annotations

from tests import _appdata_guard  # noqa: F401  (keeps tests away from the real application data)

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QCheckBox, QStackedWidget, QTableWidget, QToolButton, QWidget

    from accounting_converter.application.company_mapping_update import (
        CompanyMappingUpdateItem,
        CompanyMappingUpdateReview,
    )
    from accounting_converter.application.mapping_candidates import MappingCandidate
    from accounting_converter.application.moneyforward_description_replacement import (
        MoneyForwardDescriptionReviewItem,
        moneyforward_description_replacement_key,
    )
    from accounting_converter.application.review_bulk import BulkRow
    from accounting_converter.ui_qt import main_window
    from accounting_converter.ui_qt.bulk_review import BulkCandidateDialog
    from accounting_converter.ui_qt.main_window import CompanyMappingUpdateDialog
    from accounting_converter.ui_qt.theme import APP_STYLE_SHEET

    PYSIDE6_AVAILABLE = True
except ModuleNotFoundError:
    PYSIDE6_AVAILABLE = False


def _account(name, *, exact=None, candidates=(), journals=3):
    targets = tuple(f"科目{index:03d}" for index in range(40)) + ((exact,) if exact else ())
    return CompanyMappingUpdateItem(
        key=f"ACCOUNT|{name}", mapping_type="ACCOUNT", source_value=name, parent_account=None,
        available_targets=targets, exact_candidate=exact, recommended_reason="名前が同じ" if exact else "",
        candidates=candidates, affected_journal_count=journals,
    )


def _subaccount(name, parent, targets_by_parent=()):
    return CompanyMappingUpdateItem(
        key=f"SUBACCOUNT|{name}|{parent}", mapping_type="SUBACCOUNT", source_value=name,
        parent_account=parent, available_targets=(), subaccount_targets_by_parent=targets_by_parent,
        affected_journal_count=2,
    )


def _description(index):
    text = f"テスト用の長い摘要 {index:04d} 架空の取引先 定期購入代金 定期購入代金 定期購入代金"
    return MoneyForwardDescriptionReviewItem(
        moneyforward_description_replacement_key(text), "sha", text, len(text), (), 1
    )


def _large_review():
    accounts = tuple(_account(f"入力科目{index:03d}", exact=f"入力科目{index:03d}" if index % 3 else None)
                     for index in range(80))
    subaccounts = tuple(_subaccount(f"補助{index:03d}", f"入力科目{index % 80:03d}") for index in range(170))
    return CompanyMappingUpdateReview(
        company_setting_id="company-test", source_path=None, context_path=None,
        items=accounts + subaccounts, logical_journal_count=1000,
        descriptions=tuple(_description(index) for index in range(250)),
        tax_categories=tuple(f"税区分{index}" for index in range(11)),
        unsupported_shape_count=12,
    )


# (name, logical width, logical height) — physical size divided by the Windows scale.
# 48px is a typical taskbar.
SCREENS = (
    ("1920x1200 100%", 1920, 1200 - 48),
    ("1920x1200 125%", 1536, 960 - 48),
    ("1920x1200 150%", 1280, 800 - 48),
    ("1366x768 100%", 1366, 768 - 48),
    ("1920x1080 125%", 1536, 864 - 48),
)


def visible_rows(table: QTableWidget) -> float:
    # Rows may all be filtered out (e.g. subaccounts waiting for a parent),
    # so measure against the fixed row height.
    return table.viewport().height() / table.verticalHeader().defaultSectionSize()


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class ReviewLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(APP_STYLE_SHEET)

    def open_dialog(self, review, width, height):
        dialog = CompanyMappingUpdateDialog(object(), review)
        # The dialog opens at 90% x 92% of the available screen.
        dialog.resize(int(width * 0.9), int(height * 0.92))
        dialog.show()
        self.app.processEvents()
        # hide() rather than close: closing with unsaved checks asks for confirmation.
        self.addCleanup(dialog.hide)
        return dialog

    def table_in(self, dialog, key):
        dialog.tabs.setCurrentIndex(dialog.category_tabs[key])
        self.app.processEvents()
        return dialog.tabs.widget(dialog.category_tabs[key]).findChild(QTableWidget)

    def test_tables_show_at_least_eight_rows_on_common_screens_and_scales(self):
        review = _large_review()
        for name, width, height in SCREENS:
            with self.subTest(screen=name):
                dialog = self.open_dialog(review, width, height)
                for key in ("accounts", "subaccounts", "descriptions"):
                    self.assertGreaterEqual(visible_rows(self.table_in(dialog, key)), 8, (name, key))
                dialog.hide()

    def test_details_are_folded_and_the_footer_stays_visible(self):
        dialog = self.open_dialog(_large_review(), 1366, 768 - 48)
        self.assertFalse(dialog.details_section.is_expanded())
        self.assertFalse(dialog.triage_label.isVisible())
        self.assertTrue(dialog.save_button.isVisible())
        self.assertFalse(dialog.save_button.isEnabled())
        dialog.details_section.set_expanded(True)
        self.app.processEvents()
        self.assertTrue(dialog.triage_label.isVisible())
        # The table shrinks but keeps a usable minimum; the footer is still on screen.
        table = self.table_in(dialog, "accounts")
        self.assertGreaterEqual(table.height(), table.minimumHeight())
        self.assertTrue(dialog.save_button.isVisible())

    def test_other_tab_scrolls_and_never_clips_with_details_expanded(self):
        from PySide6.QtWidgets import QLabel, QScrollArea

        for name, width, height in SCREENS + (("small 760x480", 760, 480),):
            with self.subTest(screen=name):
                dialog = self.open_dialog(_large_review(), width, height)
                dialog.details_section.set_expanded(True)
                dialog.tabs.setCurrentIndex(dialog.category_tabs["other"])
                self.app.processEvents()
                page = dialog.tabs.widget(dialog.category_tabs["other"])
                self.assertIsInstance(page, QScrollArea)
                self.assertTrue(dialog.save_button.isVisible())
                self.assertLessEqual(dialog.details_section.body.height(), main_window.CompanyMappingUpdateDialog._DETAILS_MAX_HEIGHT)
                inner = page.widget()
                warning = next(l for l in inner.findChildren(QLabel) if l.objectName() == "warningCard")
                # The page keeps its natural height (scrolls) rather than squeezing the label.
                self.assertGreaterEqual(inner.height(), inner.minimumSizeHint().height())
                self.assertGreaterEqual(warning.height(), warning.heightForWidth(warning.width()))
                bar = page.verticalScrollBar()
                bar.setValue(bar.maximum())
                self.app.processEvents()
                self.assertTrue(dialog.save_button.isVisible())

    def test_other_tabs_are_unchanged_scroll_wise(self):
        from PySide6.QtWidgets import QScrollArea

        dialog = self.open_dialog(_large_review(), 1366, 768 - 48)
        for key in ("accounts", "subaccounts", "descriptions"):
            self.assertIsNotNone(self.table_in(dialog, key), key)
        self.assertNotIsInstance(dialog.tabs.widget(dialog.category_tabs["accounts"]), QScrollArea)

    def test_tab_labels_are_short_and_carry_meaning_without_colour(self):
        dialog = self.open_dialog(_large_review(), 1280, 800 - 48)
        texts = [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())]
        self.assertEqual(texts[:3], ["科目 残り80", "補助 残り170", "摘要 残り250"])
        self.assertEqual(texts[3], "税区分 残り11")
        self.assertTrue(all(len(text) <= 14 for text in texts), texts)
        self.assertIn("確認済み0 / 全80件", dialog.tabs.tabToolTip(dialog.category_tabs["accounts"]))
        bar = dialog.tabs.tabBar()
        needed = sum(bar.tabSizeHint(index).width() for index in range(bar.count()))
        self.assertLessEqual(needed, dialog.tabs.width(), "tabs need scroll arrows at 1920x1200 150%")

    def test_confirmation_stays_in_the_table_when_the_side_pane_is_hidden(self):
        dialog = self.open_dialog(_large_review(), 1920, 1200 - 48)
        page = dialog.tabs.widget(dialog.category_tabs["accounts"])
        table = page.findChild(QTableWidget)
        toggle = next(button for button in page.findChildren(QToolButton) if button.text() == "候補と根拠")
        toggle.setChecked(False)
        self.app.processEvents()
        self.assertFalse(page.findChild(QStackedWidget).isVisible())
        combo, check = dialog.account_controls["入力科目001"]
        self.assertIs(table.cellWidget(1, 0).findChild(QCheckBox), check)
        self.assertTrue(check.isVisible())
        check.setChecked(True)
        self.assertIn("確認済み（保存待ち）1件", dialog.progress_label.text())
        toggle.setChecked(True)

    def test_unconfirmed_parent_is_shown_as_undetermined_not_zero_registrations(self):
        dialog = self.open_dialog(_large_review(), 1920, 1200 - 48)
        self.assertIn("未判定 170件", dialog.triage_label.text())
        self.assertIn("親科目確定後に再計算", dialog.status_strip.text())
        _item, _combo, _check, status = dialog._subaccount_rows[0]
        self.assertEqual(status.text(), "親科目の確認待ち（登録要否は未判定）")

    def test_counts_name_what_they_count(self):
        dialog = self.open_dialog(_large_review(), 1920, 1200 - 48)
        strip = dialog.status_strip.text()
        self.assertIn("人が判断する回数（目安）", strip)
        self.assertIn("未確認の行 500 / 500", strip)
        self.assertNotIn("表示中", strip + dialog.triage_label.text())
        self.assertIn("この画面の確認行 全500件", dialog.progress_label.text())
        self.assertIn("税区分 11種類：別の確認画面", dialog.triage_label.text())

    def test_finished_category_reads_as_done(self):
        review = CompanyMappingUpdateReview(
            company_setting_id="c", source_path=None, context_path=None,
            items=(_account("現金", exact="現金"),), logical_journal_count=1,
        )
        dialog = self.open_dialog(review, 1920, 1200 - 48)
        _combo, check = dialog.account_controls["現金"]
        check.setChecked(True)
        self.assertEqual(dialog.tabs.tabText(dialog.category_tabs["accounts"]), "科目 ✓完了")


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class BulkDialogLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # As in the app, the dialog has a parent (an unparented instance
        # deleted from Python can crash PySide on teardown).
        cls.owner = QWidget()

    def dialog(self):
        return BulkCandidateDialog("科目", self.rows(), self.owner)

    def rows(self):
        return [
            BulkRow(0, "現金", "", "現金", "現金", "EXACT", "名前が同じ", 5),
            BulkRow(1, "売上Y", "", "売上高", "6121 売上高", "SIMILAR", "文字が似ている", 900),
            BulkRow(2, "通信Y", "", "通信費", "7001 通信費", "EXACT", "名前が同じ", 40, "貸借が逆です"),
        ]

    def test_only_same_name_rows_without_warning_start_ticked_and_sorting_keeps_identity(self):
        dialog = self.dialog()
        self.assertEqual([row.index for row in dialog.selected()], [0])
        dialog.table.sortByColumn(2, Qt.SortOrder.AscendingOrder)
        for table_row in range(dialog.table.rowCount()):
            tick = dialog.table.item(table_row, 0)
            source = dialog.table.item(table_row, 2).text()
            self.assertEqual(dialog.rows[tick.data(Qt.ItemDataRole.UserRole)].source, source)
        self.assertEqual([row.index for row in dialog.selected()], [0])

    def test_selection_is_reviewed_before_it_is_applied(self):
        dialog = self.dialog()
        self.assertEqual(dialog.pages.currentIndex(), 0)
        dialog.next_button.click()
        self.assertEqual(dialog.pages.currentIndex(), 1)
        self.assertEqual(dialog.review_table.rowCount(), 1)
        self.assertIn("まだ保存はされません", dialog.review_summary.text())
        self.assertEqual(dialog.apply_button.text(), "この1件を確認済みにする")
        self.assertEqual(dialog.result(), 0)  # nothing accepted until the second click

    def test_filter_hides_rows_but_does_not_change_the_selection(self):
        dialog = self.dialog()
        dialog.kind_filter.setCurrentIndex(dialog.kind_filter.findData("文字が似ている"))
        hidden = [dialog.table.isRowHidden(row) for row in range(dialog.table.rowCount())]
        self.assertEqual(hidden.count(False), 1)
        self.assertEqual([row.index for row in dialog.selected()], [0])


if __name__ == "__main__":
    unittest.main()
