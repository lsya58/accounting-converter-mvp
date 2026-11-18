"""READYのみ変換 dialog (skipped where PySide6 is not installed; run it on Windows). Synthetic data."""
from __future__ import annotations

from tests import _appdata_guard  # noqa: F401  (keeps tests away from the real application data)

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication

    from accounting_converter.ui_qt.ready_only_dialog import ReadyOnlyConversionDialog

    PYSIDE6_AVAILABLE = True
except ModuleNotFoundError:
    PYSIDE6_AVAILABLE = False


class _Controller:
    """The real plan / write on a synthetic company (tests.test_yayoi_ready_only fixture)."""

    def __init__(self, run):
        self.run = run
        self.writes = 0

    def plan_yayoi_ready_only(self, company_id, source_path):
        return self.run.plan()

    def execute_yayoi_ready_only(self, company_id, source_path, plan, confirmation, output_path):
        from accounting_converter.application import yayoi_ready_only as ro

        self.writes += 1
        prepared = ro.prepare_ready_only(plan, confirmation, input_path=self.run.source, output_path=Path(output_path),
                                         profile=self.run.resolved.profile, context=self.run.resolved.context,
                                         company_setting_validated=True)
        if prepared.summary.readiness.value != "READY":
            return None, tuple(prepared.summary.blocking_reasons)
        return ro.execute_ready_only(prepared, plan, confirmation), ()


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class ReadyOnlyDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self, directory):
        from tests.test_yayoi_ready_only import Run

        controller = _Controller(Run(directory))
        dialog = ReadyOnlyConversionDialog(controller, "company-yayoi", controller.run.source)
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        return dialog, controller

    def test_counts_list_and_warning_are_shown_and_writing_needs_every_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            dialog, _ = self._dialog(directory)
            self.assertIn("全件移行ではありません", dialog.windowTitle())
            self.assertIn("全件移行ではありません", dialog.banner.text())
            text = dialog.counts.text()
            for part in ("入力 3仕訳", "変換対象（READY） 2仕訳", "除外（未移行のまま残る） 1仕訳"):
                self.assertIn(part, text)
            self.assertEqual(dialog.table.rowCount(), 1)
            self.assertEqual(dialog.table.item(0, 1).text(), "2026-05-10")
            self.assertIn("1仕訳はJDLに取り込まれない", dialog.ack_partial.text())
            self.assertFalse(dialog.write_button.isEnabled())
            dialog.ack_partial.setChecked(True)
            dialog.ack_duplicate.setChecked(True)
            self.assertFalse(dialog.write_button.isEnabled())
            dialog.ack_follow_up.setChecked(True)
            self.assertFalse(dialog.write_button.isEnabled())  # no name yet
            dialog.confirmed_by.setText("架空の確認者")
            self.assertTrue(dialog.write_button.isEnabled())
            dialog.ack_duplicate.setChecked(False)
            self.assertFalse(dialog.write_button.isEnabled())

    def test_the_result_says_how_many_are_not_migrated(self):
        with tempfile.TemporaryDirectory() as directory:
            dialog, controller = self._dialog(directory)
            for box in (dialog.ack_partial, dialog.ack_duplicate, dialog.ack_follow_up):
                box.setChecked(True)
            dialog.confirmed_by.setText("架空の確認者")
            output = Path(directory) / "ro.csv"
            dialog.write(output)
            self.assertTrue(output.exists())
            status = dialog.status.text()
            self.assertIn("全件移行ではありません", status)
            self.assertIn("変換済み 2仕訳", status)
            self.assertIn("未移行 1仕訳", status)
            self.assertFalse(dialog.write_button.isEnabled())  # one run per dialog

    # ---------------------------------------------------------------- Phase 5A: the final confirmation (UI only)
    def test_the_target_and_what_is_missing_are_shown_before_anything_is_acknowledged(self):
        with tempfile.TemporaryDirectory() as directory:
            dialog, _ = self._dialog(directory)
            self.assertIn("company-yayoi", dialog.target.text())               # no store: the id, never a guess
            self.assertIn(Path(dialog.source_path).name, dialog.target.text())
            self.assertIn("BLOCKの仕訳は出力に含まれません", dialog.counts.text())
            self.assertIn("出力するには", dialog.status.text())
            self.assertIn("確認者の名前を入力してください", dialog.status.text())
            for box in (dialog.ack_partial, dialog.ack_duplicate, dialog.ack_follow_up):
                box.setChecked(True)
            self.assertNotIn("すべて確認してください", dialog.status.text())
            dialog.confirmed_by.setText("   ")                                 # blank is not a name
            self.assertFalse(dialog.write_button.isEnabled())
            dialog.confirmed_by.setText("架空の確認者")
            self.assertIn("出力できます", dialog.status.text())
            self.assertFalse(dialog.write_button.autoDefault())                # Enter never starts the output

    def test_an_existing_file_is_refused_before_the_final_question_and_left_unchanged(self):
        from unittest import mock

        from accounting_converter.ui_qt import ready_only_dialog as rod

        with tempfile.TemporaryDirectory() as directory:
            dialog, controller = self._dialog(directory)
            for box in (dialog.ack_partial, dialog.ack_duplicate, dialog.ack_follow_up):
                box.setChecked(True)
            dialog.confirmed_by.setText("架空の確認者")
            existing = Path(directory) / "old_ready_only.csv"
            existing.write_bytes(b"previous output")
            with mock.patch.object(rod.QFileDialog, "getSaveFileName", return_value=(str(existing), "")), \
                    mock.patch.object(rod.QMessageBox, "question",
                                      side_effect=AssertionError("never asked for an existing file")):
                dialog._write()
            self.assertIn("上書きしません", dialog.status.text())
            self.assertEqual(existing.read_bytes(), b"previous output")
            self.assertEqual(controller.writes, 0)
            self.assertIsNone(dialog.result)                                   # an old file is never the result
            # the write step refuses as well (the check is not only in the screen)
            dialog.write(existing)
            self.assertIn("上書きしません", dialog.status.text())
            self.assertEqual(existing.read_bytes(), b"previous output")

    def test_cancelling_writes_nothing_and_a_failure_names_its_cause(self):
        from unittest import mock

        from accounting_converter.ui_qt import ready_only_dialog as rod

        with tempfile.TemporaryDirectory() as directory:
            dialog, controller = self._dialog(directory)
            for box in (dialog.ack_partial, dialog.ack_duplicate, dialog.ack_follow_up):
                box.setChecked(True)
            dialog.confirmed_by.setText("架空の確認者")
            before = sorted(p.name for p in Path(directory).rglob("*"))
            target = Path(directory) / "new.csv"
            with mock.patch.object(rod.QFileDialog, "getSaveFileName", return_value=("", "")):
                dialog._write()
            self.assertIn("出力しませんでした", dialog.status.text())
            with mock.patch.object(rod.QFileDialog, "getSaveFileName", return_value=(str(target), "")), \
                    mock.patch.object(rod.QMessageBox, "question", return_value=rod.QMessageBox.StandardButton.No):
                dialog._write()
            self.assertIn("出力しませんでした", dialog.status.text())
            self.assertEqual(sorted(p.name for p in Path(directory).rglob("*")), before)
            self.assertEqual(controller.writes, 0)

            def broken(*args):
                raise PermissionError("denied")

            controller.execute_yayoi_ready_only = broken
            with mock.patch.object(rod, "log_local_exception"):
                dialog.write(target)
            self.assertIn("PermissionError", dialog.status.text())
            self.assertIsNone(dialog.result)
            self.assertTrue(dialog.write_button.isEnabled())                   # still not written: can retry

    def test_nothing_is_offered_when_all_journals_are_ready(self):
        from tests.test_yayoi_ready_only import Run
        from tests.test_yayoi_scoped_workflow import sales_voucher

        with tempfile.TemporaryDirectory() as directory:
            controller = _Controller(Run(directory, sales_voucher(3)))
            dialog = ReadyOnlyConversionDialog(controller, "company-yayoi", controller.run.source)
            self.addCleanup(dialog.deleteLater)
            self.addCleanup(dialog.close)
            for box in (dialog.ack_partial, dialog.ack_duplicate, dialog.ack_follow_up):
                box.setChecked(True)
            dialog.confirmed_by.setText("x")
            self.assertFalse(dialog.write_button.isEnabled())
            self.assertIn("通常の全件変換", dialog.problems.text())


if __name__ == "__main__":
    unittest.main()
