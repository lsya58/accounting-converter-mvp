"""Save dialogs never ask the OS "replace?" question and refuse an existing export once (all three screens).

Skipped without PySide6 (run on Windows, offscreen). The Windows NATIVE dialog is not shown here: the tests
check the option passed to QFileDialog and what the screen does with the chosen path. Synthetic data only.
"""
from __future__ import annotations

from tests import _appdata_guard  # noqa: F401  (keeps tests away from the real application data)

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    from accounting_converter.ui_qt import file_dialogs as fd

    PYSIDE6_AVAILABLE = True
except ModuleNotFoundError:
    PYSIDE6_AVAILABLE = False

COMPANY = "company-yayoi"
MESSAGE = "既存のファイルは上書きしません。別の名前を選択してください。"


def listing(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class _Recorder:
    """Stands in for QFileDialog.getSaveFileName and records how it was called."""

    def __init__(self, chosen):
        self.chosen = chosen
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return str(self.chosen) if self.chosen else "", ""

    def options(self):
        args, kwargs = self.calls[-1]
        return kwargs.get("options", args[5] if len(args) > 5 else None)


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class ExportDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _recorder(self, chosen):
        recorder = _Recorder(chosen)
        patcher = mock.patch.object(QFileDialog, "getSaveFileName", recorder)
        patcher.start()
        self.addCleanup(patcher.stop)
        return recorder

    # ---------------------------------------------------------------- the helper
    def test_helper_turns_off_the_os_question_and_reports_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = self._recorder("")
            self.assertEqual(fd.choose_new_file(None, "t", "CSV (*.csv)"), (None, ()))
            self.assertTrue(recorder.options() & QFileDialog.Option.DontConfirmOverwrite)
            target = Path(directory) / "out"
            (Path(directory) / "out.csv.audit.json").write_text("{}", encoding="utf-8")
            recorder.chosen = target
            path, existing = fd.choose_new_file(
                None, "t", "CSV (*.csv)", suffix=".csv",
                related_paths=lambda p: (p, p.with_name(p.name + ".audit.json")))
            self.assertEqual(path, Path(directory) / "out.csv")            # suffix added before the check
            self.assertEqual(existing, ("out.csv.audit.json",))
            self.assertTrue(recorder.options() & QFileDialog.Option.DontConfirmOverwrite)

    # ---------------------------------------------------------------- READY-only
    def _ready_only(self, directory):
        from accounting_converter.ui_qt.ready_only_dialog import ReadyOnlyConversionDialog
        from tests.test_qt_ready_only_dialog import _Controller
        from tests.test_yayoi_ready_only import Run

        controller = _Controller(Run(directory))
        dialog = ReadyOnlyConversionDialog(controller, COMPANY, controller.run.source)
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        for box in (dialog.ack_partial, dialog.ack_duplicate, dialog.ack_follow_up):
            box.setChecked(True)
        dialog.confirmed_by.setText("架空の確認者")
        return dialog, controller

    def test_ready_only_refuses_a_companion_file_once_without_the_final_question(self):
        with tempfile.TemporaryDirectory() as directory:
            dialog, controller = self._ready_only(directory)
            target = Path(directory) / "new_ready.csv"
            (Path(directory) / "new_ready.csv.excluded.csv").write_bytes(b"previous list")  # only a companion file
            before = listing(Path(directory))
            recorder = self._recorder(target)
            with mock.patch.object(QMessageBox, "question",
                                   side_effect=AssertionError("no final question for an existing file")):
                dialog._write()
            self.assertTrue(recorder.options() & QFileDialog.Option.DontConfirmOverwrite)
            self.assertEqual(len(recorder.calls), 1)
            self.assertIn(MESSAGE, dialog.status.text())
            self.assertIn("new_ready.csv.excluded.csv", dialog.status.text())
            self.assertEqual(controller.writes, 0)
            self.assertEqual(listing(Path(directory)), before)
            self.assertFalse(target.exists())
            dialog.write(target)                                              # the write step still refuses
            self.assertEqual(listing(Path(directory)), before)

    # ---------------------------------------------------------------- main window
    def _main_window(self, directory):
        from accounting_converter.ui_qt import main_window as mw
        from tests.test_unmigrated_view import Env

        env = Env(directory, write=False)
        window = mw.AccountingConverterMainWindow(env.controller)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.home_task.shutdown)
        return env, window

    def test_main_window_refuses_an_existing_csv_or_audit_record_once_and_keeps_the_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            env, window = self._main_window(directory)
            out_dir = Path(directory) / "out"
            out_dir.mkdir()
            (out_dir / "old.csv").write_bytes(b"previous csv")
            (out_dir / "audit_only.csv.audit.json").write_bytes(b"{}")
            (out_dir / "pending_only.csv.audit.json.pending").write_bytes(b"{}")
            before = listing(Path(directory))
            for chosen, name in ((out_dir / "old.csv", "old.csv"), (out_dir / "old", "old.csv"),
                                 (out_dir / "audit_only.csv", "audit_only.csv.audit.json"),
                                 (out_dir / "pending_only.csv", "pending_only.csv.audit.json.pending")):
                with self.subTest(chosen=chosen.name):
                    previous = window.controller.state.selected_output_file
                    recorder = self._recorder(chosen)
                    with mock.patch.object(QMessageBox, "warning") as warned:
                        window._choose_output()
                    self.assertTrue(recorder.options() & QFileDialog.Option.DontConfirmOverwrite)
                    self.assertEqual(warned.call_count, 1)                       # said once
                    self.assertIn(MESSAGE, warned.call_args.args[2])
                    self.assertIn(name, warned.call_args.args[2])
                    self.assertEqual(window.controller.state.selected_output_file, previous)  # choice kept
                    self.assertEqual(listing(Path(directory)), before)
            new = out_dir / "new"
            self._recorder(new)
            with mock.patch.object(QMessageBox, "warning") as warned:
                window._choose_output()
            self.assertFalse(warned.called)
            self.assertEqual(window.controller.state.selected_output_file, out_dir / "new.csv")
            self.assertEqual(listing(Path(directory)), before)                    # choosing writes nothing

    # ---------------------------------------------------------------- unmigrated list
    def test_unmigrated_list_refuses_an_existing_file_once(self):
        from accounting_converter.ui_qt.migration_status_dialog import MigrationStatusDialog
        from tests.test_unmigrated_view import Env

        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory, write=False)
            dialog = MigrationStatusDialog(env.controller, COMPANY, env.run.source)
            self.addCleanup(dialog.deleteLater)
            self.addCleanup(dialog.task.shutdown)
            existing = Path(directory) / "sheet.csv"
            existing.write_bytes(b"previous sheet")
            recorder = self._recorder(existing)
            with mock.patch.object(QMessageBox, "warning") as warned:
                dialog._export()
            self.assertTrue(recorder.options() & QFileDialog.Option.DontConfirmOverwrite)
            self.assertEqual(warned.call_count, 1)
            self.assertIn(MESSAGE, warned.call_args.args[2])
            self.assertEqual(existing.read_bytes(), b"previous sheet")


if __name__ == "__main__":
    unittest.main()
