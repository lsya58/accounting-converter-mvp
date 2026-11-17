"""設定ページ・対応の確認 (Phase 3C): real clicks, view-versus-save, stale results, deep links.

Skipped without PySide6 (run on Windows). Buttons are pressed with a real mouse click (QTest), never by calling the
slot. Modal screens are replaced by recorders so a test never waits on a dialog; a screen that really saves is
simulated through the controller's own explicit-confirmation method, never by the page."""
from __future__ import annotations

from tests import _appdata_guard  # noqa: F401  (keeps tests away from the real application data)

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QFrame, QScrollArea

    from accounting_converter.application.company_mapping_update import (
        CompanyMappingUpdateItem,
        CompanyMappingUpdateReview,
    )
    from accounting_converter.ui import home_view as hv
    from accounting_converter.ui import mapping_review_view as mv
    from accounting_converter.ui import settings_view as sv
    from accounting_converter.ui_qt import components as ui_components
    from accounting_converter.ui_qt import main_window as mw
    from accounting_converter.ui_qt.pages.mapping_review import MappingReviewPanel
    from tests.test_settings_and_mapping_views import Field, Review, facts, item

    PYSIDE6_AVAILABLE = True
except ModuleNotFoundError:
    PYSIDE6_AVAILABLE = False

COMPANY = "company-yayoi"


def listing(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def recorder(opened, name, result=None):
    def exec_(dialog):
        opened.append(name)
        return result if result is not None else QDialog.DialogCode.Rejected
    return exec_


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class PagesTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from accounting_converter.ui_qt.theme import APP_STYLE_SHEET

        cls.app = QApplication.instance() or QApplication([])
        cls._previous_sheet = cls.app.styleSheet()
        cls.app.setStyleSheet(APP_STYLE_SHEET)

    @classmethod
    def tearDownClass(cls):
        # deleteLater() needs an event loop and unittest has none: deliver the deferred deletes of this module's
        # windows and dialogs before the app-wide sheet is touched (which walks every widget that is still alive).
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()
        cls.app.setStyleSheet(cls._previous_sheet)

    def _window(self, directory, select=True, size=(1024, 700)):
        from tests.test_unmigrated_view import Env

        env = Env(directory, write=False)
        window = mw.AccountingConverterMainWindow(env.controller)
        self.addCleanup(window.deleteLater)
        for task in (window.home_task, window.reasons_task, window.mapping_task):
            self.addCleanup(task.shutdown)
        window.resize(*size)
        window.show()
        QApplication.processEvents()
        if select:
            window.company_combo.setCurrentIndex(window.company_combo.findData(COMPANY))
            window._select_input(env.run.source)
            self._idle(window)
        return env, window

    def _idle(self, window, timeout_ms=180000):
        from tests.test_qt_components import wait_until

        tasks = (window.home_task, window.reasons_task, window.mapping_task)
        self.assertTrue(wait_until(lambda: not any(task.busy for task in tasks), timeout_ms))
        QApplication.processEvents()

    def _click(self, widget):
        self.assertTrue(widget.isVisible(), widget.accessibleName() or widget.text())
        self.assertTrue(widget.isEnabled(), widget.accessibleName() or widget.text())
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        QApplication.processEvents()

    def _page(self, window, key):
        self._click(window.nav.buttons[key])
        self._idle(window)


class SettingsPageTest(PagesTestBase):
    def test_six_sections_in_order_view_only_and_nothing_is_written_by_viewing(self):
        with tempfile.TemporaryDirectory() as directory:
            env, window = self._window(directory)
            before = listing(Path(directory))
            self._page(window, hv.NAV_SETTINGS)
            page = window.settings_page
            cards = [c for c in page.findChildren(QFrame, "card") if c.accessibleName()[:2] in
                     {f"{n}." for n in "123456"}]
            self.assertEqual([c.accessibleName() for c in cards],
                             ["1. 会社の基本情報", "2. 会計ソフト・変換先", "3. 科目・補助科目", "4. 消費税設定",
                              "5. 変換条件", "6. 技術情報・設定履歴"])
            self.assertEqual(page.mode_banner.mode, "view")
            self.assertIn("保存されません", page.mode_banner.text())
            self.assertFalse(page.saved_bar.isVisible())
            self.assertIsNotNone(page.overview)
            self.assertEqual(page.overview.company_name, window.controller.state.companies[0].display_name)
            for key, label in hv.NAV_ITEMS:                       # visiting every page and coming back
                self._page(window, key)
            self._page(window, hv.NAV_SETTINGS)
            self.assertEqual(listing(Path(directory)), before)
            self.assertEqual(window.controller.state.selected_company_setting_id, COMPANY)

    def test_every_setting_button_is_clicked_and_opens_its_existing_screen_without_saving(self):
        with tempfile.TemporaryDirectory() as directory:
            env, window = self._window(directory)
            self._page(window, hv.NAV_SETTINGS)
            page = window.settings_page
            before = listing(Path(directory))
            opened = []
            expected = {
                sv.ACT_TAX_CONTEXT: (mw.JdlTaxContextConfirmationDialog, "税設定"),
                sv.ACT_RENAME_COMPANY: (mw.CompanyRenameDialog, "名前"),
                sv.ACT_ADD_COMPANY: (mw.CompanyAddDialog, "追加"),
            }
            from accounting_converter.ui_qt.voucher_row_limit import VoucherRowLimitDialog

            expected[sv.ACT_ROW_LIMIT] = (VoucherRowLimitDialog, "行数")
            self.assertTrue(set(expected) <= set(page.action_buttons), sorted(page.action_buttons))
            for action, (dialog_class, name) in expected.items():
                with self.subTest(action), mock.patch.object(dialog_class, "exec", recorder(opened, name)):
                    self._click(page.action_buttons[action][0])
                    self.assertEqual(opened[-1], name)
            with self.subTest("master refresh"), mock.patch.object(mw.QFileDialog, "getOpenFileName",
                                                                    return_value=("", "")) as picker:
                self._click(page.action_buttons[sv.ACT_REFRESH_MASTER][0])
                self.assertTrue(picker.called)                    # no file chosen: nothing is planned or saved
            with self.subTest("delete asks first"), mock.patch.object(
                    mw.QMessageBox, "question", return_value=mw.QMessageBox.StandardButton.No) as ask:
                self._click(page.action_buttons[sv.ACT_DELETE_COMPANY][0])
                self.assertTrue(ask.called)
                self.assertIn(COMPANY, {c.company_setting_id for c in window.controller.state.companies})
            self.assertFalse(page.saved_bar.isVisible())            # opened and closed: no change, no notice
            self.assertEqual(listing(Path(directory)), before)
            self.assertFalse(window.reasons_task.busy)               # nothing was diagnosed because of it
            self.assertNotIn(sv.ACT_TRADE_PARTNER, page.action_buttons)   # a Yayoi company has no 取引先 setting

    def test_the_old_settings_dialog_is_still_reachable(self):
        with tempfile.TemporaryDirectory() as directory:
            _env, window = self._window(directory)
            self._page(window, hv.NAV_SETTINGS)
            opened = []
            with mock.patch.object(mw.SettingsDialog, "exec", recorder(opened, "旧設定")):
                self._click(window.settings_button)
            self.assertEqual(opened, ["旧設定"])

    def test_a_saved_change_shows_the_way_to_the_diagnosis_and_does_not_diagnose(self):
        from accounting_converter.ui_qt.voucher_row_limit import VoucherRowLimitDialog

        with tempfile.TemporaryDirectory() as directory:
            env, window = self._window(directory)
            self._page(window, hv.NAV_SETTINGS)
            page = window.settings_page
            keys_before = (window._reasons_key, window.reasons_task.dropped)

            def saving_exec(dialog):                              # the screen's own explicit confirmation
                env.controller.confirm_company_voucher_row_limit(COMPANY, 64, explicitly_confirmed=True)
                dialog.saved = 64
                return QDialog.DialogCode.Accepted

            with mock.patch.object(VoucherRowLimitDialog, "exec", saving_exec):
                self._click(page.action_buttons[sv.ACT_ROW_LIMIT][0])
            self._idle(window)
            self.assertTrue(page.saved_bar.isVisible())
            self.assertIn("変換診断", page.saved_label.text())
            self.assertIn("自動では実行しません", page.saved_label.text())
            row_limit = next(r for s in page.overview.sections for r in s.rows if r.key == "row_limit")
            self.assertIn("64", row_limit.value)
            self.assertEqual((window._reasons_key, window.reasons_task.dropped), keys_before)   # not diagnosed
            self._click(page.to_diagnosis)                         # the explicit way to see the effect
            self.assertEqual(window.current_page(), hv.NAV_DIAGNOSIS)
            self._idle(window)
            self.assertIsNotNone(window._reasons_key)

    def test_switching_company_hides_the_notice_and_an_empty_state_has_no_default_values(self):
        with tempfile.TemporaryDirectory() as directory:
            _env, window = self._window(directory, select=False)
            self._page(window, hv.NAV_SETTINGS)
            page = window.settings_page
            self.assertFalse(page.overview.has_company)
            self.assertIn("会社が選ばれていません", page.message.text())
            self.assertIn(sv.ACT_ADD_COMPANY, page.action_buttons)
            self.assertEqual(page.overview.sections, ())
            page.show_saved(True)
            window.company_combo.setCurrentIndex(window.company_combo.findData(COMPANY))
            self.assertFalse(page.saved_bar.isVisible())
            self._page(window, hv.NAV_SETTINGS)
            self.assertTrue(page.overview.has_company)

    def test_the_mapping_buttons_on_the_settings_page_lead_to_the_review_page(self):
        with tempfile.TemporaryDirectory() as directory:
            _env, window = self._window(directory)
            self._page(window, hv.NAV_SETTINGS)
            self._click(window.settings_page.action_buttons[sv.ACT_MAPPING][0])
            self.assertEqual(window.current_page(), hv.NAV_REVIEW)

    def test_no_horizontal_scroll_and_no_clipped_sections_at_1024_by_700(self):
        with tempfile.TemporaryDirectory() as directory:
            _env, window = self._window(directory)
            self._page(window, hv.NAV_SETTINGS)
            scroll = window.settings_page.scroll
            self.assertEqual(scroll.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.assertLessEqual(scroll.widget().width(), scroll.viewport().width())
            for card in window.settings_page.findChildren(QFrame, "card"):
                self.assertLessEqual(card.geometry().right(), scroll.widget().width())
            for badge in window.settings_page.findChildren(ui_components.StatusBadge):
                self.assertTrue(badge.accessibleName())            # never colour alone: words are the name
                self.assertNotEqual(badge.text().strip(), "")


class MappingPanelTest(PagesTestBase):
    @staticmethod
    def synthetic_view():
        review = Review([
            item(source="売上", already_confirmed=True),
            item(source="雑費"),
            item(source="特殊科目", blocker_code="NO-ACCOUNT", blocker_reason="JDLに同名の科目がありません"),
            item("SUBACCOUNT", "補助A", parent_account="売掛金", available_targets=(), subaccount_targets_by_parent=()),
        ], source_is_yayoi=True, information_fields=(Field("部門", 4), Field("付箋1", 1, "色分け")))
        from accounting_converter.application.moneyforward_profile_setup import (
            TaxMappingSetupItem,
            TaxMappingSetupReview,
        )
        tax = TaxMappingSetupReview(items=(
            TaxMappingSetupItem("課税仕入 10%", "課税仕入10%", human_confirmable=True, action_owner="HUMAN"),
            TaxMappingSetupItem("特殊税", reason="実機の確認がありません"),
        ), context_compatible=True)
        return mv.build_mapping_review(mv.MappingSnapshot(
            review=review, tax_review=tax, saved_tax=(("課税売上 10%", "課税売上10%"),),
            observed_tax=(("課税仕入 10%", 4), ("特殊税", 1), ("課税売上 10%", 8))))

    def test_panel_shows_unconfirmed_first_folds_confirmed_and_separates_the_kinds_of_waiting(self):
        panel = MappingReviewPanel()
        self.addCleanup(panel.deleteLater)
        panel.resize(900, 900)
        panel.show()
        panel.show_view(self.synthetic_view())
        QApplication.processEvents()
        accounts = panel.tables[mv.G_ACCOUNT]
        self.assertEqual(accounts.rowCount(), 2)                      # only the pending ones are in the main table
        states = [accounts.item(r, 0).text() for r in range(accounts.rowCount())]
        self.assertTrue(states[0].startswith("? 未確認"))
        self.assertTrue(states[1].startswith("⊕ JDL側で登録が必要"))
        confirmed = panel.confirmed_tables[mv.G_ACCOUNT]
        self.assertEqual(confirmed.item(0, 1).text(), "売上")
        self.assertFalse(confirmed.isVisible())                         # folded by default
        tax = panel.tables[mv.G_TAX]
        self.assertTrue(any(tax.item(r, 0).text().startswith("⧗") for r in range(tax.rowCount())))   # Evidence不足
        self.assertTrue(any(tax.item(r, 0).text().startswith("? 未確認") for r in range(tax.rowCount())))
        for _ in range(4):
            QApplication.processEvents()
        cards = [c for c in panel.metrics.findChildren(ui_components.MetricCard) if c.isVisible()]
        self.assertEqual(len(cards), 4)
        for card in cards:                                              # nothing is squeezed below its content
            self.assertGreaterEqual(card.height(), card.minimumSizeHint().height())
        for table in (*panel.tables.values(), *panel.confirmed_tables.values()):
            self.assertTrue(table.accessibleName())
            self.assertEqual(table.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.assertIn(mv.G_ACCOUNT, panel.group_buttons)
        self.assertIn(mv.G_SUBACCOUNT, panel.group_buttons)
        self.assertIn(mv.G_TAX, panel.group_buttons)
        self.assertIn(mv.G_RETENTION, panel.group_buttons)
        self.assertNotIn(mv.G_DESCRIPTION, panel.group_buttons)         # nothing for a person to do there
        self.assertEqual(panel.first_group_needing_person(), mv.G_ACCOUNT)

    def test_group_buttons_emit_their_group_and_only_the_review_screens_are_asked_for(self):
        panel = MappingReviewPanel()
        self.addCleanup(panel.deleteLater)
        panel.resize(900, 900)
        panel.show()
        panel.show_view(self.synthetic_view())
        got = []
        panel.open_group.connect(got.append)
        for key in (mv.G_ACCOUNT, mv.G_TAX):
            QTest.mouseClick(panel.group_buttons[key], Qt.MouseButton.LeftButton)
        self.assertEqual(got, [mv.G_ACCOUNT, mv.G_TAX])

    def test_error_idle_and_loading_states_are_messages_not_rows(self):
        panel = MappingReviewPanel()
        self.addCleanup(panel.deleteLater)
        panel.show_error("読み込めませんでした。何も保存していません。")
        self.assertEqual(panel.message.level, "error")
        self.assertEqual(panel.tables, {})
        panel.show_idle("会社を選んでください")
        self.assertEqual(panel.message.level, "info")
        panel.show_loading()
        self.assertEqual(panel.message.level, "info")
        self.assertIn("保存はしません", panel.message.text())

    def test_review_page_loads_the_review_in_the_background_read_only_and_not_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            env, window = self._window(directory)
            forbidden = ("ensure_selected_tax_requirements", "apply_company_mapping_updates",
                         "confirm_company_tax_mapping", "confirm_company_tax_mappings",
                         "confirm_company_tax_context", "confirm_company_voucher_row_limit",
                         "confirm_company_trade_partner_policy", "confirm_yayoi_information_policies",
                         "save_jdl_migration_review", "apply_company_master_refresh", "approve_voucher_split")
            guards = [mock.patch.object(env.controller, name, side_effect=AssertionError(f"{name} was called by viewing"))
                      for name in forbidden]
            for guard in guards:
                guard.start()
                self.addCleanup(guard.stop)
            before = listing(Path(directory))
            self._page(window, hv.NAV_REVIEW)
            panel = window.mapping_panel
            self.assertIsNotNone(panel.view)
            self.assertEqual(window._mapping_key, window.mapping_request_key())
            screen = env.controller.review_company_mapping_updates(COMPANY, env.run.source, include_confirmed=True)
            self.assertEqual(sum(len(g.rows) for g in panel.view.groups if g.key in (mv.G_ACCOUNT, mv.G_SUBACCOUNT)),
                             len(screen.items))
            reviews = []
            original = env.controller.company_mapping_review_snapshot

            def counting(*args, **kwargs):
                reviews.append(args)
                return original(*args, **kwargs)

            with mock.patch.object(env.controller, "company_mapping_review_snapshot", counting):
                for key in (hv.NAV_HOME, hv.NAV_SETTINGS, hv.NAV_REVIEW, hv.NAV_DIAGNOSIS, hv.NAV_REVIEW):
                    self._page(window, key)
                self.assertEqual(reviews, [])                         # same company / source / settings: not read again
                self._click(panel.reload_button)                      # the explicit reload does read again
                self._idle(window)
                self.assertEqual(len(reviews), 1)
            self.assertEqual(listing(Path(directory)), before)         # nothing saved by any of it

    def test_a_result_for_another_company_or_source_is_never_shown(self):
        with tempfile.TemporaryDirectory() as directory:
            env, window = self._window(directory)
            self._page(window, hv.NAV_REVIEW)
            panel = window.mapping_panel
            shown = panel.view
            stale_key = ("mapping", "company-other", (str(env.run.source), 1, 1), None)
            snapshot = env.controller.company_mapping_review_snapshot(COMPANY, env.run.source)
            panel.show_idle("別の選択です")
            window._on_mapping_finished(stale_key, snapshot)
            self.assertIsNone(panel.view)                              # dropped: not rendered over the new state
            window._on_mapping_failed(stale_key, RuntimeError("old"))
            self.assertEqual(panel.message.level, "info")
            self.assertIsNotNone(shown)
            # a selection change during a run drops the running result
            window._mapping_key = None
            window._start_mapping(force=True)
            self.assertTrue(window.mapping_task.busy)
            other = Path(directory) / "other.txt"
            other.write_bytes(env.run.source.read_bytes())
            window._select_input(other)
            self._idle(window)
            self.assertGreaterEqual(window.mapping_task.dropped, 1)
            self.assertEqual(window._mapping_key, window.mapping_request_key())

    def test_deep_links_open_the_exact_screen_and_a_cancelled_screen_diagnoses_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            env, window = self._window(directory)
            self._page(window, hv.NAV_REVIEW)
            window.mapping_panel.show_view(self.synthetic_view())
            QApplication.processEvents()
            calls = []
            reasons_before = (window._reasons_key, window.reasons_task.dropped)
            with mock.patch.object(window, "_confirm_current_csv", lambda **kw: calls.append(kw)):
                self._click(window.mapping_panel.group_buttons[mv.G_ACCOUNT])
                self._click(window.mapping_panel.group_buttons[mv.G_SUBACCOUNT])
                self._click(window.mapping_panel.group_buttons[mv.G_TAX])
                self._click(window.mapping_panel.group_buttons[mv.G_RETENTION])
            self.assertEqual(calls, [
                {"only": "mapping", "initial_tab": "accounts"}, {"only": "mapping", "initial_tab": "subaccounts"},
                {"only": "tax"}, {"only": "mapping", "initial_tab": "other"}])
            self._idle(window)
            self.assertEqual((window._reasons_key, window.reasons_task.dropped), reasons_before)

    def test_the_narrowed_confirmation_flow_skips_the_other_screen(self):
        review = CompanyMappingUpdateReview(
            company_setting_id=COMPANY, source_path=None, context_path=None,
            items=(CompanyMappingUpdateItem("ACCOUNT|x", "ACCOUNT", "x", None, ("a",)),), logical_journal_count=1)
        with tempfile.TemporaryDirectory() as directory:
            env, window = self._window(directory)
            opened = []
            patches = (
                mock.patch.object(env.controller, "review_company_mapping_updates", return_value=review),
                mock.patch.object(mw.CompanyMappingUpdateDialog, "exec", recorder(opened, "mapping")),
                mock.patch.object(mw.TaxMappingConfirmationDialog, "exec", recorder(opened, "tax")),
                mock.patch.object(window, "_refresh_current_csv_readiness"),
            )
            for patch in patches:
                patch.start()
                self.addCleanup(patch.stop)
            window._confirm_current_csv(only="tax")
            self.assertEqual(opened, [])                               # the mapping dialog was skipped
            window._confirm_current_csv(only="mapping", initial_tab="accounts")
            self.assertEqual(opened, ["mapping"])                      # and the tax screen is not chained after it
            window._confirm_current_csv()
            self.assertEqual(opened, ["mapping", "mapping"])           # the default flow is unchanged

    def test_the_mapping_dialog_opens_at_the_requested_tab(self):
        account = CompanyMappingUpdateItem("ACCOUNT:p:", "ACCOUNT", "p", None, ("t",))
        sub = CompanyMappingUpdateItem("SUBACCOUNT:s:p", "SUBACCOUNT", "s", "p", (), subaccount_targets_by_parent=(("t", ("u",)),))
        review = CompanyMappingUpdateReview("c", None, None, (account, sub), 2)
        default = mw.CompanyMappingUpdateDialog(object(), review)
        self.addCleanup(default.deleteLater)
        self.assertEqual(default.tabs.currentIndex(), default.category_tabs["accounts"])
        linked = mw.CompanyMappingUpdateDialog(object(), review, initial_tab="subaccounts")
        self.addCleanup(linked.deleteLater)
        self.assertEqual(linked.tabs.currentIndex(), linked.category_tabs["subaccounts"])
        unknown = mw.CompanyMappingUpdateDialog(object(), review, initial_tab="no-such-tab")
        self.addCleanup(unknown.deleteLater)
        self.assertEqual(unknown.tabs.currentIndex(), unknown.category_tabs["accounts"])

    def test_the_old_entry_button_still_opens_the_whole_flow(self):
        with tempfile.TemporaryDirectory() as directory:
            _env, window = self._window(directory)
            self._page(window, hv.NAV_REVIEW)
            with mock.patch.object(window, "_confirm_current_csv") as flow:
                self._click(window.settings_action)
            flow.assert_called_once_with()                             # no arguments: exactly the previous behaviour


if __name__ == "__main__":
    unittest.main()
