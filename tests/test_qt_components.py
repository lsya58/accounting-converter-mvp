"""Shared UI components (ui_qt/components.py). Skipped where PySide6 is not installed; run it on Windows."""
from __future__ import annotations

from tests import _appdata_guard  # noqa: F401  (keeps tests away from the real application data)

import os
import threading
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from accounting_converter.ui_qt import components as ui
    from accounting_converter.ui_qt.theme import APP_STYLE_SHEET

    PYSIDE6_AVAILABLE = True
except ModuleNotFoundError:
    PYSIDE6_AVAILABLE = False


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class ComponentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(APP_STYLE_SHEET)

    def test_every_status_has_a_symbol_words_and_an_accessible_name(self):
        for key, status in ui.STATUSES.items():
            badge = ui.StatusBadge(key)
            self.assertTrue(badge.text().startswith(status.symbol + " "), key)
            self.assertIn(status.text, badge.text())
            self.assertEqual(badge.accessibleName(), status.text)
            self.assertEqual(badge.property("tone"), status.tone)
        self.assertEqual(len({s.symbol + s.text for s in ui.STATUSES.values()}), len(ui.STATUSES))
        self.assertEqual(ui.STATUSES["READY"].tone, "ready")
        self.assertEqual(ui.STATUSES["BLOCK"].tone, "block")
        self.assertEqual(ui.STATUSES["MANUAL_ENTERED"].text, "入力済み（照合待ち）")   # never "done"

    def test_button_kinds_are_named_focusable_and_never_default(self):
        for kind, name in ui.BUTTON_KINDS.items():
            button = ui.make_button("実行する…", kind, description="説明", shortcut="Ctrl+R")
            self.assertEqual(button.objectName(), name)
            self.assertEqual(button.accessibleName(), "実行する")
            self.assertEqual(button.accessibleDescription(), "説明")
            self.assertIn("Ctrl+R", button.toolTip())
            self.assertFalse(button.autoDefault())
            self.assertEqual(button.focusPolicy(), ui.Qt.FocusPolicy.StrongFocus)
        with self.assertRaises(ValueError):
            ui.make_button("x", "loud")

    def test_banners_messages_and_cards(self):
        banner = ui.ModeBanner("trial", "SPLIT-V1")
        self.assertIn("試算", banner.text())
        self.assertIn("保存していません", banner.accessibleName())
        banner.set_mode("view")
        self.assertIn("閲覧のみ", banner.text())
        bar = ui.MessageBar()
        self.assertFalse(bar.isVisibleTo(None) and bar.isVisible())
        for level in ("info", "success", "warning", "error"):
            bar.show_message(level, "何も保存していません\n次に…")
            self.assertEqual(bar.level, level)
            self.assertIn("何も保存していません", bar.text())
        bar.clear_message()
        self.assertEqual(bar.text(), "")
        card = ui.MetricCard("READY", "2,479", "変換できる仕訳", "ready")
        self.assertEqual(card.accessibleName(), "READY 2,479")
        card.set_value("2,498", tone="block")
        self.assertEqual(card.property("tone"), "block")
        detail = ui.DetailCard("弥生での処理")
        detail.set_lines(["税区分「課対仕入10%」", ""])
        self.assertIn("課対仕入10%", detail.plain_text())
        section, body = ui.collapsible_text("詳細・Evidence")
        body.setText("EVID-X")
        self.assertFalse(section.is_expanded())

    def test_the_table_sorts_numbers_and_dates_by_value_and_is_read_only(self):
        table = ui.JournalTable(("元の行", "日付", "金額"), name="仕訳一覧", numeric=(0, 2))
        table.set_rows([[("1,000", 1000), ("2026-01-02", "2026-01-02"), ("200", 200)],
                        [("200", 200), ("2025-12-31", "2025-12-31"), ("1,000", 1000)]])
        table.sortItems(0)
        self.assertEqual([table.item(r, 0).text() for r in range(2)], ["200", "1,000"])   # not "1,000" < "200"
        table.sortItems(1)
        self.assertEqual(table.item(0, 1).text(), "2025-12-31")
        self.assertFalse(table.item(0, 0).flags() & ui.Qt.ItemFlag.ItemIsEditable)
        self.assertEqual(table.accessibleName(), "仕訳一覧")
        self.assertTrue(table.item(0, 0).textAlignment() & int(ui.Qt.AlignmentFlag.AlignRight))


def wait_until(predicate, timeout_ms=10000) -> bool:
    """PySide6 has no QTest.qWaitFor: process events until `predicate` holds."""
    waited = 0
    while not predicate():
        if waited >= timeout_ms:
            return False
        QTest.qWait(20)
        waited += 20
    return True


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class BackgroundTaskTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _task(self):
        task = ui.BackgroundTask()
        self.addCleanup(task.shutdown)              # never leave a thread running past the test
        got = {"done": [], "failed": []}
        task.finished.connect(lambda key, result: got["done"].append((key, result)))
        task.failed.connect(lambda key, error: got["failed"].append((key, type(error).__name__)))
        return task, got

    def test_the_job_runs_off_the_ui_thread_and_comes_back_with_its_key(self):
        task, got = self._task()
        main = threading.get_ident()
        self.assertTrue(task.start(("company", "sha", "A"), lambda: threading.get_ident()))
        self.assertFalse(task.start(("company", "sha", "B"), lambda: 0))            # one job at a time
        self.assertTrue(wait_until(lambda: not task.busy))
        self.assertEqual(len(got["done"]), 1)
        key, worker_thread = got["done"][0]
        self.assertEqual(key, ("company", "sha", "A"))
        self.assertNotEqual(worker_thread, main)

    def test_a_stale_result_is_dropped_and_errors_are_delivered(self):
        task, got = self._task()
        gate = threading.Event()
        task.start("old", lambda: gate.wait(5) and "old result")
        task.invalidate()                                   # e.g. the selection changed
        gate.set()
        self.assertTrue(wait_until(lambda: not task.busy))
        self.assertEqual((got["done"], task.dropped), ([], 1))

        def boom():
            raise RuntimeError("synthetic")

        task.start("new", boom)
        self.assertTrue(wait_until(lambda: not task.busy))
        self.assertEqual(got["failed"], [("new", "RuntimeError")])

    def test_shutdown_joins_a_running_job_and_ignores_its_result(self):
        task, got = self._task()
        gate = threading.Event()
        task.start("k", lambda: gate.wait(5) and 1)
        gate.set()
        task.shutdown()
        QTest.qWait(50)
        self.assertFalse(task.busy)
        self.assertEqual(got["done"], [])


if __name__ == "__main__":
    unittest.main()
