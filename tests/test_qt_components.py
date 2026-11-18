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
        cls._previous_sheet = cls.app.styleSheet()
        cls.app.setStyleSheet(APP_STYLE_SHEET)

    @classmethod
    def tearDownClass(cls):
        cls.app.setStyleSheet(cls._previous_sheet)

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
        def cleanup():                              # never leave a thread running past the test
            try:
                task.shutdown()
            except RuntimeError:                    # released and deleted by the test itself: nothing left to join
                pass

        self.addCleanup(cleanup)
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

    def test_release_never_blocks_and_the_thread_is_joined_after_the_job_ends(self):
        import time
        from PySide6.QtCore import QCoreApplication, QEvent

        task, got = self._task()
        gate, deleted, busy = threading.Event(), [], []
        task.busy_changed.connect(busy.append)
        task.destroyed.connect(lambda *_: deleted.append(1))
        task.start("k", lambda: gate.wait(10) and "late result")
        started = time.monotonic()
        task.release()                                      # the owner closes while the job runs
        self.assertLess(time.monotonic() - started, 0.5)    # returned at once (no wait on the GUI thread)
        self.assertTrue(task.busy)
        self.assertIn(task, ui._RUNNING)                    # kept alive: the running thread is never destroyed
        busy.clear()
        gate.set()
        self.assertTrue(wait_until(lambda: not task.busy))
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()
        self.assertEqual(got["done"], [])                   # the owner receives nothing after release
        self.assertEqual(busy, [])
        self.assertNotIn(task, ui._RUNNING)
        self.assertEqual(deleted, [1])                      # deleted only after the thread was joined

    def test_an_idle_release_deletes_and_exit_joins_every_running_thread(self):
        from PySide6.QtCore import QCoreApplication, QEvent

        idle, _ = self._task()
        deleted = []
        idle.destroyed.connect(lambda *_: deleted.append(1))
        idle.release()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertEqual(deleted, [1])
        running, _ = self._task()
        gate = threading.Event()
        running.start("k", lambda: gate.wait(10))
        running.release()
        threading.Timer(0.2, gate.set).start()
        deleted_running = []
        running.destroyed.connect(lambda *_: deleted_running.append(1))
        ui.shutdown_running_tasks()                         # application exit: joined (never terminate())
        self.assertFalse(running.busy)
        self.assertNotIn(running, ui._RUNNING)
        running.release()                                   # a second release is harmless (no double release)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertEqual(deleted_running, [1])              # deleted once, even though it was joined by shutdown

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
