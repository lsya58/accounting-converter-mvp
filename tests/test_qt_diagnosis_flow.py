"""UI Phase 4B: the ways into 変換診断 (page and the dialog inside 対応の確認), unsaved choices, and re-diagnosis.

Real clicks on the main window with synthetic data (skipped where PySide6 is not installed; run it on Windows).
Nothing here saves a setting, records an approval or writes an output: every screen that could is replaced.
"""
from __future__ import annotations

from tests import _appdata_guard  # noqa: F401  (keeps tests away from the real application data)

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_qt_settings_mapping_pages import PYSIDE6_AVAILABLE, PagesTestBase, listing, recorder

if PYSIDE6_AVAILABLE:
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

    from accounting_converter.application.company_mapping_update import (
        CompanyMappingUpdateItem, CompanyMappingUpdateReview,
    )
    from accounting_converter.ui import home_view as hv
    from accounting_converter.ui_qt import main_window as mw
    from accounting_converter.ui_qt import resolution_center


class DiagnosisEntriesTest(PagesTestBase):
    def test_every_page_way_into_the_diagnosis_is_a_page_switch_that_saves_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            _env, window = self._window(directory)
            before = listing(Path(directory))
            ways = (
                (hv.NAV_REVIEW, window.review_to_diagnosis),          # 要確認 → 変換診断 (new in 4B)
                (hv.NAV_IMPORT, window.import_next_button),
            )
            for page, button in ways:
                with self.subTest(button.text()):
                    self._page(window, page)
                    self._click(button)
                    self.assertEqual(window.current_page(), hv.NAV_DIAGNOSIS)
                    self.assertEqual(window.nav.current, hv.NAV_DIAGNOSIS)   # the left nav follows the page
            self._idle(window)
            self.assertIsNotNone(window.reasons_panel.report)
            # from the diagnosis: READY-only output and D0 / D2 are reached through the pages that own them
            self._click(window.reasons_to_output)
            self.assertEqual(window.current_page(), hv.NAV_OUTPUT)
            opened = []
            from accounting_converter.ui_qt.ready_only_dialog import ReadyOnlyConversionDialog
            from accounting_converter.ui_qt.migration_status_dialog import MigrationStatusDialog

            with mock.patch.object(ReadyOnlyConversionDialog, "exec", recorder(opened, "ready-only")):
                self._click(window.ready_only_button)
            self._page(window, hv.NAV_DIAGNOSIS)
            self._click(window.reasons_to_review)
            self.assertEqual(window.current_page(), hv.NAV_REVIEW)
            with mock.patch.object(MigrationStatusDialog, "exec", recorder(opened, "D0/D2")):
                self._click(window.migration_status_button)
            self.assertEqual(opened, ["ready-only", "D0/D2"])
            self.assertEqual(listing(Path(directory)), before)

    def test_a_reason_button_opens_the_confirmation_at_the_tab_it_names(self):
        with tempfile.TemporaryDirectory() as directory:
            _env, window = self._window(directory)
            calls = []
            with mock.patch.object(window, "_confirm_current_csv", lambda **kw: calls.append(kw)), \
                    mock.patch.object(window, "_after_saved_change", lambda: calls.append("rediagnose")):
                for action, expected in (("ACCOUNTS_TAB", {"only": "mapping", "initial_tab": "accounts"}),
                                         ("SUBACCOUNTS_TAB", {"only": "mapping", "initial_tab": "subaccounts"}),
                                         ("DESCRIPTION_TAB", {"only": "mapping", "initial_tab": "descriptions"}),
                                         ("TAX_REVIEW", {"only": "tax"}), ("ROW_LIMIT", {})):
                    calls.clear()
                    item = mock.Mock(action=action)
                    window._reason_action(item)
                    self.assertEqual(calls, [expected, "rediagnose"], action)   # always re-diagnosed afterwards


class ReDiagnosisTest(PagesTestBase):
    def test_the_page_never_runs_the_same_diagnosis_twice_and_never_shows_an_old_one_as_current(self):
        with tempfile.TemporaryDirectory() as directory:
            env, window = self._window(directory)
            calls = []
            original = env.controller.company_resolution_report

            def counted(*args):
                calls.append(args)
                return original(*args)

            env.controller.company_resolution_report = counted
            self._click(window.nav.buttons[hv.NAV_DIAGNOSIS])
            running = window.reasons_task._current
            self.assertIsNotNone(running)
            self.assertEqual(window.reasons_panel.state, "loading")    # 診断中, never 0件
            window._render(window.controller.state)                  # a re-render while it runs
            window._start_reasons()
            self.assertEqual(window.reasons_task._current, running)   # the same run continues
            self.assertFalse(window._reasons_pending)
            self._idle(window)
            self.assertEqual(len(calls), 1)
            self.assertEqual(window.reasons_panel.state, "report")
            # a forced re-diagnosis (after a save) clears the previous result first
            window._start_reasons(force=True)
            self.assertEqual(window.reasons_panel.state, "loading")
            self.assertIsNone(window.reasons_panel.report)
            self._idle(window)
            self.assertEqual(len(calls), 2)

    def test_a_result_started_before_the_input_changed_is_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            env, window = self._window(directory)
            self._click(window.nav.buttons[hv.NAV_DIAGNOSIS])
            first_key = window.reasons_task._current
            self.assertTrue(window.reasons_task.busy)
            stat = env.run.source.stat()
            os.utime(env.run.source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))  # the CSV changed
            window._render(window.controller.state)
            self._idle(window)
            self.assertNotEqual(window._reasons_key, first_key)
            self.assertEqual(window._reasons_key, window._current_reasons_key())
            self.assertGreaterEqual(window.reasons_task.dropped, 1)

    def test_a_failure_shows_its_cause_and_is_not_retried_silently(self):
        with tempfile.TemporaryDirectory() as directory:
            env, window = self._window(directory)
            calls = []

            def broken(*args):
                calls.append(args)
                raise OSError("unreadable source")

            env.controller.company_resolution_report = broken
            with mock.patch.object(mw, "log_local_exception"):
                self._page(window, hv.NAV_DIAGNOSIS)
                self.assertEqual(window.reasons_panel.state, "error")
                self.assertEqual(window.reasons_message.level, "error")
                self.assertIn("OSError", window.reasons_message.text())
                window._render(window.controller.state)
                self._page(window, hv.NAV_HOME)
                self._page(window, hv.NAV_DIAGNOSIS)
                self._idle(window)
                self.assertEqual(len(calls), 1)                      # shown, not re-run behind the user's back
                self.assertEqual(window.reasons_panel.state, "error")
                self._click(window.reasons_refresh_button)          # the user retries
                self._idle(window)
                self.assertEqual(len(calls), 2)


class MappingDialogEntryTest(PagesTestBase):
    """対応の確認 → 変換診断（理由別）: kept as a dialog ON the confirmation dialog, so its unsaved choices stay."""

    class Recorder:
        instances = []

        def __init__(self, controller, company_id, source_path, callbacks=None, parent=None, *,
                     unsaved_changes=False):
            self.unsaved_changes, self.callbacks, self.goto = unsaved_changes, callbacks, None
            type(self).instances.append(self)

        def exec(self):
            return QDialog.DialogCode.Accepted

    def _dialog(self):
        account = CompanyMappingUpdateItem("ACCOUNT:p:", "ACCOUNT", "p", None, ("t1", "t2"))
        review = CompanyMappingUpdateReview("c", None, None, (account,), 2, source_is_yayoi=True)
        dialog = mw.CompanyMappingUpdateDialog(object(), review)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_the_entry_keeps_the_unsaved_choices_and_tells_the_diagnosis_about_them(self):
        type(self).Recorder.instances = []
        dialog = self._dialog()
        self.assertEqual(dialog.readiness_button.text(), "変換診断（理由別）…")
        self.assertIn("未保存の変更は残り", dialog.readiness_button.toolTip())
        with mock.patch.object(resolution_center, "ResolutionCenterDialog", self.Recorder):
            dialog.readiness_button.click()
            self.assertFalse(self.Recorder.instances[-1].unsaved_changes)
            _key, _combo, check = dialog.controls[0]
            check.setChecked(True)                                    # an unsaved confirmation
            state = dialog._review_state()
            dialog.readiness_button.click()
            self.assertTrue(self.Recorder.instances[-1].unsaved_changes)
            self.assertEqual(dialog._review_state(), state)          # still there, still unsaved
            # a tab action from the diagnosis returns to the tab in the SAME dialog
            with mock.patch.object(self.Recorder, "exec",
                                   lambda recorder: setattr(recorder, "goto", "descriptions") or 1):
                dialog.readiness_button.click()
            self.assertEqual(dialog.tabs.currentIndex(), dialog.category_tabs["descriptions"])
            self.assertEqual(dialog._review_state(), state)
        # leaving the confirmation still asks before the unsaved choice is discarded (cancel keeps it)
        with mock.patch.object(mw.QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel) as asked:
            dialog.reject()
        self.assertTrue(asked.called)
        self.assertEqual(dialog._review_state(), state)

    def test_an_mf_confirmation_has_no_diagnosis_entry(self):
        review = CompanyMappingUpdateReview("c", None, None, (), 1)
        dialog = mw.CompanyMappingUpdateDialog(object(), review)
        self.addCleanup(dialog.deleteLater)
        self.assertIsNone(dialog.readiness_button)


if __name__ == "__main__":
    unittest.main()
