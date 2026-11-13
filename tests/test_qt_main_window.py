"""メイン画面の骨格 (Phase 3A): left navigation, pages, home, and the entries into the existing screens.

Skipped without PySide6 (run on Windows). Every navigation item and entry button is pressed with a real mouse click
(QTest), never by calling the slot. Modal dialogs are replaced by recorders so a test never waits on a screen.
Set ACCOUNTING_CONVERTER_SCREENSHOT_DIR to save a PNG of every page (QT_SCALE_FACTOR gives 125/150/200%).
"""
from __future__ import annotations

from tests import _appdata_guard  # noqa: F401  (keeps tests away from the real application data)

import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QShortcut
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QScrollArea

    from accounting_converter.ui import home_view as hv
    from accounting_converter.ui.view_models import FileRecognition, RecognizedFormat
    from accounting_converter.ui_qt import main_window as mw

    PYSIDE6_AVAILABLE = True
except ModuleNotFoundError:
    PYSIDE6_AVAILABLE = False

COMPANY = "company-yayoi"


def listing(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class MainWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from accounting_converter.ui_qt.theme import APP_STYLE_SHEET

        cls.app = QApplication.instance() or QApplication([])
        cls._previous_sheet = cls.app.styleSheet()
        cls.app.setStyleSheet(APP_STYLE_SHEET)

    @classmethod
    def tearDownClass(cls):
        cls.app.setStyleSheet(cls._previous_sheet)

    # ---------------------------------------------------------------- helpers
    def _window(self, directory, write=False, select=True):
        from tests.test_unmigrated_view import Env

        env = Env(directory, write=write)
        window = mw.AccountingConverterMainWindow(env.controller)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.home_task.shutdown)
        window.resize(1024, 700)
        window.show()
        QApplication.processEvents()
        if select:
            index = window.company_combo.findData(COMPANY)
            self.assertGreaterEqual(index, 0)
            window.company_combo.setCurrentIndex(index)           # the user's own selection path
            window._select_input(env.run.source)                  # the path the drop zone and file picker share
            self._idle(window)
        return env, window

    def _idle(self, window, timeout_ms=120000):
        from tests.test_qt_components import wait_until

        self.assertTrue(wait_until(lambda: not window.home_task.busy, timeout_ms))
        QApplication.processEvents()

    def _click(self, widget):
        self.assertTrue(widget.isVisible(), widget.accessibleName() or widget.text())
        self.assertTrue(widget.isEnabled(), widget.accessibleName() or widget.text())
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        QApplication.processEvents()

    def _value(self, window, label):
        return window.home_page.metric_cards[label].value.text()

    # ---------------------------------------------------------------- navigation
    def test_every_navigation_item_is_clicked_and_keeps_the_company_and_source(self):
        with tempfile.TemporaryDirectory() as directory:
            env, window = self._window(directory)
            state = window.controller.state
            selected = (state.selected_company_setting_id, state.selected_file, state.file_recognition)
            self.assertEqual(selected[0], COMPANY)
            before = listing(Path(directory))
            for key, label in hv.NAV_ITEMS:
                with self.subTest(page=label):
                    self._click(window.nav.buttons[key])
                    self.assertEqual(window.current_page(), key)
                    self.assertIs(window.stack.currentWidget(), window.pages[key])
                    self.assertTrue(window.nav.buttons[key].isChecked())
                    self.assertEqual(sum(b.isChecked() for b in window.nav.buttons.values()), 1)
                    state = window.controller.state
                    self.assertEqual((state.selected_company_setting_id, state.selected_file, state.file_recognition),
                                     selected)
                    self.assertEqual(window.company_combo.currentData(), COMPANY)
                    self.assertIn(env.run.source.name, window.context_file_label.text())
            self._click(window.nav.buttons[hv.NAV_HOME])
            self._idle(window)
            self.assertEqual(listing(Path(directory)), before)          # switching pages wrote nothing

    def test_keyboard_shortcuts_and_arrow_keys_move_between_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            _env, window = self._window(directory, select=False)
            shortcuts = {s.key().toString(): s for s in window.findChildren(QShortcut)}
            for number, (key, _label) in enumerate(hv.NAV_ITEMS, start=1):
                self.assertIn(f"Ctrl+{number}", shortcuts)
                shortcuts[f"Ctrl+{number}"].activated.emit()
                self.assertEqual(window.current_page(), key)
            self.assertIn("Ctrl+O", shortcuts)
            self.assertIn("F5", shortcuts)
            window.show_page(hv.NAV_HOME)
            window.nav.buttons[hv.NAV_HOME].setFocus()
            QTest.keyClick(window.nav.buttons[hv.NAV_HOME], Qt.Key.Key_Down)
            self.assertEqual(window.current_page(), hv.NAV_IMPORT)
            QTest.keyClick(window.nav.buttons[hv.NAV_IMPORT], Qt.Key.Key_Up)
            self.assertEqual(window.current_page(), hv.NAV_HOME)
            if window.nav.buttons[hv.NAV_HOME].hasFocus():          # focus follows a page switched by shortcut
                window.show_page(hv.NAV_OUTPUT)
                self.assertTrue(window.nav.buttons[hv.NAV_OUTPUT].hasFocus())
            for key, label in hv.NAV_ITEMS:
                button = window.nav.buttons[key]
                # exclusive group (like radio buttons): Tab reaches the current item, Up/Down move (tested above)
                self.assertTrue(button.focusPolicy() & Qt.FocusPolicy.ClickFocus)
                self.assertTrue(button.accessibleName().startswith(label))
                self.assertIn("Ctrl+", button.toolTip())
            self.assertTrue(window.company_combo.accessibleName())

    # ---------------------------------------------------------------- home
    def test_home_shows_the_production_counts_and_never_a_completed_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            env, window = self._window(directory)
            d2 = env.overview()
            self.assertEqual(self._value(window, "元仕訳"), f"{d2['total']:,}")
            self.assertEqual(self._value(window, "変換可能"), f"{d2['ready']:,}")
            self.assertEqual(self._value(window, "BLOCK"), f"{d2['blocked']:,}")
            self.assertEqual(self._value(window, "承認済み"), "0")
            self.assertEqual(self._value(window, "移行全体"), "未完了")
            self.assertIn("＝", window.home_page.counts_label.text())
            self.assertTrue(window.home_page.action_buttons)
            self.assertFalse(list(Path(directory).rglob("*migration_tracker*")))   # never created by viewing
            # a next-action button only switches the page
            target = window.home_page.presentation.next_actions[0].target
            self._click(window.home_page.action_buttons[0])
            self.assertEqual(window.current_page(), target)

    def test_home_with_a_ready_only_run_still_says_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            _env, window = self._window(directory, write=True)
            self.assertEqual(self._value(window, "移行全体"), "未完了")
            self.assertIn("管理表は未作成", window.home_page.metric_cards["移行全体"].hint.text())
            self.assertFalse(list(Path(directory).rglob("*migration_tracker*")))

    def test_home_without_a_source_and_a_stale_result_is_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            env, window = self._window(directory, select=False)
            self.assertEqual(self._value(window, "元仕訳"), "—")
            self.assertEqual(window.home_page.presentation.next_actions[-1].target, hv.NAV_IMPORT)
            index = window.company_combo.findData(COMPANY)
            window.company_combo.setCurrentIndex(index)
            window._select_input(env.run.source)
            self.assertTrue(window.home_task.busy)                  # background, the window stays responsive
            key = window.home_request_key()
            window._on_home_finished(("home", "another-company", key[2], key[3]), {"total": 1})   # foreign result
            self.assertNotEqual(window.home_page.presentation.metrics[0].value, "1")
            self._idle(window)
            self.assertEqual(self._value(window, "元仕訳"), f"{env.overview()['total']:,}")

    # ---------------------------------------------------------------- the existing screens stay reachable
    def test_each_existing_screen_opens_from_its_page(self):
        from accounting_converter.ui_qt import migration_status_dialog, ready_only_dialog, resolution_center

        with tempfile.TemporaryDirectory() as directory:
            _env, window = self._window(directory)
            opened = []

            def recorder(name):
                def exec_(dialog):
                    opened.append(name)
                    return QDialog.DialogCode.Rejected
                return exec_

            entries = (
                (hv.NAV_DIAGNOSIS, window.readiness_main_button, resolution_center.ResolutionCenterDialog, "準備状況"),
                (hv.NAV_REVIEW, window.migration_status_button, migration_status_dialog.MigrationStatusDialog, "D0D2"),
                (hv.NAV_OUTPUT, window.ready_only_button, ready_only_dialog.ReadyOnlyConversionDialog, "READY-only"),
                (hv.NAV_SETTINGS, window.settings_button, mw.SettingsDialog, "設定"),
            )
            for page, button, dialog_class, name in entries:
                with self.subTest(name), mock.patch.object(dialog_class, "exec", recorder(name)):
                    window.show_page(page)
                    QApplication.processEvents()
                    self._click(button)
                    self.assertEqual(opened[-1], name)
                    self.assertEqual(window.controller.state.selected_company_setting_id, COMPANY)
            # 対応の確認: the existing confirmation flow (dialogs replaced; the handler must not fail silently)
            window.show_page(hv.NAV_REVIEW)
            QApplication.processEvents()
            with mock.patch.object(mw.CompanyMappingUpdateDialog, "exec", recorder("対応の確認")), \
                    mock.patch.object(mw.TaxMappingConfirmationDialog, "exec", recorder("税区分")), \
                    mock.patch.object(mw.JdlTaxContextConfirmationDialog, "exec", recorder("税設定")), \
                    mock.patch.object(mw.QMessageBox, "information"), mock.patch.object(mw.QMessageBox, "warning") as warn:
                self._click(window.settings_action)
                self.assertFalse(warn.called)
            for button in (window.copy_guidance_button, window.copy_diagnostics_button, window.convert_button,
                           window.drop_zone.choose_button):
                self.assertTrue(button.text())                        # the old entries still exist
            self.assertEqual(window.controller.state.selected_company_setting_id, COMPANY)

    def test_the_d2_list_still_works_when_opened_from_the_review_page(self):
        from accounting_converter.ui_qt import migration_status_dialog
        from tests.test_qt_components import wait_until

        with tempfile.TemporaryDirectory() as directory:
            env, window = self._window(directory)
            seen = {}

            def exec_(dialog):
                dialog.tabs.setCurrentIndex(1)
                self.assertTrue(wait_until(lambda: not dialog.task.busy, 120000))
                seen["rows"] = dialog.tracker_table.rowCount()
                seen["blocked"] = dialog.metric_blocked.value.text()
                dialog.task.shutdown()
                return QDialog.DialogCode.Rejected

            window.show_page(hv.NAV_REVIEW)
            with mock.patch.object(migration_status_dialog.MigrationStatusDialog, "exec", exec_):
                self._click(window.migration_status_button)
            self.assertEqual(seen["rows"], env.overview()["blocked"])
            self.assertEqual(seen["blocked"], f"{env.overview()['blocked']:,}")

    def test_yayoi_only_functions_are_not_offered_for_other_formats(self):
        with tempfile.TemporaryDirectory() as directory:
            _env, window = self._window(directory)
            for fmt in (RecognizedFormat.MONEYFORWARD, RecognizedFormat.JDL):
                with self.subTest(fmt):
                    state = replace(window.controller.state,
                                    file_recognition=FileRecognition(fmt, "テスト", 10, None, None))
                    window.controller.state = state
                    window._render(state)
                    window.show_page(hv.NAV_OUTPUT)
                    QApplication.processEvents()
                    self.assertFalse(window.ready_only_button.isVisible())
                    self.assertTrue(window.ready_only_scope_label.isVisible())
                    window.show_page(hv.NAV_REVIEW)
                    QApplication.processEvents()
                    self.assertFalse(window.migration_status_button.isEnabled())
                    self.assertIn("弥生のデータでだけ", window.decision_status_label.text())
                    window.show_page(hv.NAV_DIAGNOSIS)
                    QApplication.processEvents()
                    self.assertFalse(window.readiness_main_button.isVisible())
                    self.assertTrue(window.readiness_scope_label.isVisible())
                    self.assertEqual(window.home_page.metric_cards["税理士の判断"].value.text(), "対象外")
                    self.assertEqual(window.home_page.metric_cards["移行全体"].value.text(), "対象外")
                    self.assertFalse(window.home_task.busy)            # no Yayoi diagnosis for another format
            window.show_page(hv.NAV_REVIEW)
            self.assertEqual(window.settings_action.text(), "JDL移行内容の確認を開く")

    # ---------------------------------------------------------------- layout: 1024 x 700 (and QT_SCALE_FACTOR)
    def test_every_page_fits_1024_by_700_without_sideways_scrolling(self):
        shots = os.environ.get("ACCOUNTING_CONVERTER_SCREENSHOT_DIR")
        with tempfile.TemporaryDirectory() as directory:
            _env, window = self._window(directory)
            self.assertEqual((window.minimumWidth(), window.minimumHeight()), (1024, 700))
            window.resize(1024, 700)
            for key, label in hv.NAV_ITEMS:
                with self.subTest(page=label):
                    window.show_page(key)
                    QApplication.processEvents()
                    page = window.pages[key]
                    scroll = page if isinstance(page, QScrollArea) else page.findChild(QScrollArea)
                    self.assertIsNotNone(scroll)
                    self.assertFalse(scroll.horizontalScrollBar().isVisible())
                    self.assertLessEqual(scroll.widget().width(), scroll.viewport().width())
                    for button in scroll.widget().findChildren(mw.QPushButton):
                        if not button.isVisible():
                            continue
                        corner = button.mapTo(window, QPoint(button.width(), button.height()))
                        self.assertLessEqual(corner.x(), window.width(), button.text())
                        self.assertGreaterEqual(button.width(), button.minimumSizeHint().width(), button.text())
                    if shots:
                        scale = os.environ.get("QT_SCALE_FACTOR", "1")
                        Path(shots).mkdir(parents=True, exist_ok=True)
                        window.grab().save(str(Path(shots) / f"{key}_x{scale}.png"))
            self.assertLessEqual(window.nav.width(), 220)


if __name__ == "__main__":
    unittest.main()
