"""freee 試験診断 on the データ取込 page (E5A): real clicks, read-only, no output, the main flow untouched.

Skipped without PySide6 (run on Windows). The file dialog and the modal are replaced by recorders (mock.patch), so a
test never waits on a dialog.
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
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFileDialog

    from accounting_converter.ui import freee_trial_view as fv
    from accounting_converter.ui import home_view as hv
    from accounting_converter.ui.view_models import RecognizedFormat
    from accounting_converter.ui_qt import freee_trial_dialog as fd
    from accounting_converter.ui_qt import main_window as mw

    PYSIDE6_AVAILABLE = True
except ModuleNotFoundError:
    PYSIDE6_AVAILABLE = False

from accounting_converter.adapters.input.freee.journal_csv import NEW_CSV_97_HEADER, OLD_CSV_29_HEADER
from tests.test_freee_e5a import six_new_rows, six_old_rows
from tests.test_freee_journal_csv import _csv

COMPANY = "company-yayoi"


def listing(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class FreeeTrialPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from accounting_converter.ui_qt.theme import APP_STYLE_SHEET

        cls.app = QApplication.instance() or QApplication([])
        cls._previous_sheet = cls.app.styleSheet()
        cls.app.setStyleSheet(APP_STYLE_SHEET)

    @classmethod
    def tearDownClass(cls):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()
        cls.app.setStyleSheet(cls._previous_sheet)

    def _window(self, directory):
        from tests.test_qt_components import wait_until
        from tests.test_unmigrated_view import Env

        env = Env(directory, write=False)
        window = mw.AccountingConverterMainWindow(env.controller)
        self.addCleanup(window.deleteLater)
        tasks = (window.home_task, window.reasons_task, window.mapping_task)
        for task in tasks:
            self.addCleanup(task.shutdown)
        window.resize(1024, 700)
        window.show()
        QApplication.processEvents()
        window.company_combo.setCurrentIndex(window.company_combo.findData(COMPANY))
        window._select_input(env.run.source)
        self.assertTrue(wait_until(lambda: not any(task.busy for task in tasks), 180000))
        QApplication.processEvents()
        window.show_page(hv.NAV_IMPORT)
        QApplication.processEvents()
        return env, window

    def _click(self, widget):
        self.assertTrue(widget.isVisible(), widget.accessibleName() or widget.text())
        self.assertTrue(widget.isEnabled(), widget.accessibleName() or widget.text())
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        QApplication.processEvents()

    def _run_trial(self, window, path):
        shown = []

        def exec_(dialog):
            shown.append(dialog)
            return 0

        with mock.patch.object(QFileDialog, "getOpenFileName", return_value=(str(path), "")), \
                mock.patch.object(fd.FreeeTrialDiagnosisDialog, "exec", exec_):
            window.freee_trial_button.ensurePolished()
            window.page_scroll(hv.NAV_IMPORT).ensureWidgetVisible(window.freee_trial_button)
            QApplication.processEvents()
            self._click(window.freee_trial_button)
        self.assertEqual(len(shown), 1)
        self.addCleanup(shown[0].deleteLater)
        return shown[0]

    def _state(self, window):
        state = window.controller.state
        return (state.selected_file, state.selected_company_setting_id, state.file_recognition,
                state.conversion_available)

    def test_import_page_separates_formal_and_trial_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            _env, window = self._window(directory)
            text = window.import_scope_label.text()
            self.assertIn("正式対応", text)
            self.assertIn("試験対応・診断のみ", text)
            self.assertIn("試験対応・診断のみ", window.freee_trial_card.accessibleName())
            self.assertIn("正式READYではありません", window.freee_trial_note.text())

    def test_trial_diagnosis_shows_counts_ready_zero_and_output_disabled_without_touching_anything(self):
        for name, header, rows, label in (
            ("new.csv", NEW_CSV_97_HEADER, six_new_rows(), fv.VARIANT_LABELS[fv.FreeeJournalVariant.NEW_CSV]),
            ("old.csv", OLD_CSV_29_HEADER, six_old_rows(), fv.VARIANT_LABELS[fv.FreeeJournalVariant.OLD_CSV]),
        ):
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                env, window = self._window(directory)
                source = Path(directory) / "freee_input" / name
                source.parent.mkdir()
                source.write_bytes(_csv(header, rows))
                before_files = listing(Path(directory))
                before_state = self._state(window)
                dialog = self._run_trial(window, source)
                cards = {k: c.value.text() for k, c in dialog.metric_cards.items()}
                self.assertEqual(cards, {"CSV形式": label, "読み取った仕訳": "6仕訳", "正常に解析できた仕訳": "6仕訳",
                                         "未対応の仕訳": "0仕訳", "JDL向け正式READY": "0"})
                self.assertFalse(dialog.output_button.isEnabled())
                self.assertEqual(dialog.mode_banner.mode, "view")
                self.assertEqual(set(dialog.tables), {"reasons", "tax", "retention", "journals"})
                journals = dialog.tables["journals"]
                self.assertEqual([journals.item(r, 0).text() for r in range(journals.rowCount())],
                                 ["1", "2", "3", "4", "5", "6"])               # file order first
                retention = dialog.tables["retention"]
                self.assertEqual(retention.item(0, 0).text(), fv.RETENTION_LABELS[fv.RetentionStatus.RETAINED])
                self.assertIn("正式READYではありません", dialog.note.text())
                self.assertEqual(window.freee_trial_message.level, "info")
                # read-only: no file written or changed, the main flow / company selection untouched
                self.assertEqual(listing(Path(directory)), before_files)
                self.assertEqual(self._state(window), before_state)
                self.assertEqual(window.controller.state.selected_file, env.run.source)
                dialog.show()
                QApplication.processEvents()
                self._click(dialog.copy_button)
                copied = QApplication.clipboard().text()
                self.assertIn("JDL向け正式READY: 0", copied)
                self.assertNotIn("合成", copied)

    def test_unknown_header_is_rejected_in_the_dialog(self):
        with tempfile.TemporaryDirectory() as directory:
            _env, window = self._window(directory)
            source = Path(directory) / "other.csv"
            source.write_bytes("取引No,取引日,借方勘定科目\n1,2026/04/01,現金\n".encode("cp932"))
            dialog = self._run_trial(window, source)
            self.assertFalse(dialog.view.readable)
            self.assertEqual(dialog.metric_cards["JDL向け正式READY"].value.text(), "0")
            self.assertEqual(dialog.tables, {})
            self.assertFalse(dialog.output_button.isEnabled())
            self.assertEqual(dialog.headline.level, "error")
            self.assertEqual(window.freee_trial_message.level, "warning")

    def test_freee_csv_in_the_main_flow_stays_unsupported_with_a_hint(self):
        with tempfile.TemporaryDirectory() as directory:
            _env, window = self._window(directory)
            source = Path(directory) / "freee.csv"
            source.write_bytes(_csv(NEW_CSV_97_HEADER, six_new_rows()))
            before = listing(Path(directory))
            window._select_input(source)
            QApplication.processEvents()
            state = window.controller.state
            self.assertIs(state.file_recognition.format, RecognizedFormat.UNKNOWN)
            self.assertFalse(state.conversion_available)
            self.assertIn("試験診断する", window.recognition_label.text())
            self.assertEqual(listing(Path(directory)), before)


if __name__ == "__main__":
    unittest.main()
