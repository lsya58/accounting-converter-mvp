"""JDL往復照合カード (Phase 1): BackgroundTask, request-key binding, states, no-overwrite summary, release.

Skipped without PySide6 (run on Windows, offscreen). A recording controller stands in for the check; the check
itself is tested in test_jdl_roundtrip_review. The Windows native file dialogs are not shown here.
"""
from __future__ import annotations

from tests import _appdata_guard  # noqa: F401  (keeps tests away from the real application data)

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QFileDialog

    from accounting_converter.ui_qt import components as ui
    from accounting_converter.ui_qt.roundtrip_card import RoundTripCard

    PYSIDE6_AVAILABLE = True
except ModuleNotFoundError:
    PYSIDE6_AVAILABLE = False

from accounting_converter.application import jdl_roundtrip_review as rr

COMPANY = "company-b"


def review(state, **values):
    base = dict(counts={"source": {"journals": 80, "physical_rows": 86}, "candidate": {"journals": 80, "physical_rows": 86}},
                reexport={"journals": [80, 80], "physical_rows": [86, 86], "missing_rows": 0, "extra_rows": 0,
                          "unexplained_differences": 0, "canonical_normalizations": 454, "evidenced_information_loss": 0},
                existing_verdict={rr.PASS: "PASS", rr.PENDING: "NORMALIZATION_ACCEPTANCE_PENDING"}.get(state, "FAIL"))
    base.update(values)
    return rr.RoundTripReview(state, COMPANY, rr.ROUTE_YAYOI_IMPORT, **base)


class Controller:
    def __init__(self, result=None, supported=True, reason=None, error=None):
        self.result, self.supported, self.reason, self.error = result, supported, reason, error
        self.gate = threading.Event()
        self.gate.set()
        self.calls = []

    def jdl_roundtrip_route(self, company_id):
        return self.supported, self.reason

    def jdl_roundtrip_period(self, company_id):
        return None  # 弥生 (Phase 1): no fiscal year to choose

    def jdl_roundtrip_review(self, company_id, source, candidate, reexport):
        self.calls.append((company_id, source, candidate, reexport))
        self.gate.wait(30)
        if self.error is not None:
            raise self.error
        return self.result


class _CardBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.txt"
        self.candidate = self.root / "jdl.csv"
        self.reexport = self.root / "reexport.csv"
        for path in (self.source, self.candidate, self.reexport):
            path.write_bytes(path.name.encode())
        self.company = COMPANY
        self.locks = []

    def _card(self, controller, *, files=True):
        card = RoundTripCard(
            controller, base_key=lambda: ("home", self.company, str(self.source)),
            selection=lambda: (self.company, "会社B（合成）", self.source), lock_selection=self.locks.append)
        self.addCleanup(card.deleteLater)
        self.addCleanup(card.release)
        if files:
            card.candidate, card.reexport = self.candidate, self.reexport
        card.refresh()
        return card

    def _wait(self, card):
        from tests.test_qt_components import wait_until

        self.assertTrue(wait_until(lambda: not card.task.busy, 30000))
        QApplication.processEvents()



@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class RoundTripCardTest(_CardBase):
    def test_unsupported_company_and_missing_files_cannot_run(self):
        controller = Controller(supported=False, reason="ROUTE_NOT_YAYOI_IMPORT_FORMAT")
        card = self._card(controller)
        self.assertFalse(card.run_button.isEnabled())
        self.assertIn("未対応", card.scope_label.text())
        self.assertFalse(card.run())
        self.assertEqual(controller.calls, [])
        card = self._card(Controller(review(rr.PASS)), files=False)
        self.assertFalse(card.run_button.isEnabled())
        self.assertFalse(card.save_button.isEnabled())
        self.assertIn("同じフォルダ", card.guidance.text())
        self.assertIn(".audit.json", card.guidance.text())

    def test_pass_is_shown_after_the_background_run_and_the_selection_is_locked_meanwhile(self):
        controller = Controller(review(rr.PASS))
        controller.gate.clear()
        card = self._card(controller)
        self.assertTrue(card.run())
        self.assertTrue(card.task.busy)
        self.assertFalse(card.run_button.isEnabled())
        self.assertFalse(card.candidate_button.isEnabled())
        self.assertEqual(self.locks, [True])
        self.assertFalse(card.run())                                   # one run at a time
        controller.gate.set()
        self._wait(card)
        self.assertEqual(self.locks, [True, False])
        self.assertEqual(len(controller.calls), 1)
        self.assertEqual(card.badge.text().split(" ", 1)[1], "PASS")
        self.assertEqual(card.message.level, "success")
        self.assertGreater(card.counts.rowCount(), 0)
        self.assertTrue(card.save_button.isEnabled())

    def test_a_result_for_another_selection_is_dropped(self):
        controller = Controller(review(rr.PASS))
        controller.gate.clear()
        card = self._card(controller)
        self.assertTrue(card.run())
        self.company = "company-other"                                  # the selection changed meanwhile
        controller.gate.set()
        self._wait(card)
        self.assertIsNone(card.current_review())
        self.assertIn("対象が変わった", card.message.text())
        self.assertNotIn("PASS", card.badge.text())
        self.assertEqual(self.locks, [True, False])

    def test_errors_and_pending_are_never_shown_as_pass(self):
        card = self._card(Controller(error=RuntimeError("synthetic")))
        self.assertTrue(card.run())
        self._wait(card)
        self.assertEqual(card.current_review().state, rr.READ_ERROR)
        self.assertIn("読取エラー", card.badge.text())
        self.assertEqual(card.message.level, "error")
        self.assertNotIn("synthetic", card.reasons.text())             # only the exception type is shown
        for state, words, level in ((rr.PENDING, "PENDING", "warning"), (rr.FAIL, "FAIL", "error"),
                                    (rr.READ_ERROR, "読取エラー", "error"), (rr.NOT_RUN, "未照合", "warning")):
            with self.subTest(state=state):
                card = self._card(Controller(review(state)))
                self.assertTrue(card.run())
                self._wait(card)
                self.assertIn(words, card.badge.text())
                self.assertEqual(card.message.level, level)
                self.assertFalse(card.current_review().is_pass)
                if state in (rr.PENDING, rr.READ_ERROR):
                    self.assertIn("合格ではありません", card.message.text())

    def test_first_twenty_details_are_labelled_as_a_sample(self):
        failures = tuple({"row": i, "field": "debit_amount", "classification": "UNEXPECTED_CHANGE", "category": "AMOUNT"}
                         for i in range(1, 21))
        result = review(rr.FAIL, first_failures=failures,
                        reexport={"journals": [80, 80], "physical_rows": [86, 86], "missing_rows": 0, "extra_rows": 0,
                                  "unexplained_differences": 57, "canonical_normalizations": 0})
        card = self._card(Controller(result))
        self.assertTrue(card.run())
        self._wait(card)
        self.assertEqual(card.failures.rowCount(), 20)
        self.assertIn("最初の20件", card.failures_heading.text())
        self.assertIn("全57件のうち20件", card.failures_heading.text())
        self.assertEqual(card.failures.item(0, 1).text(), "金額差")

    def test_summary_is_saved_once_and_never_over_an_existing_file(self):
        card = self._card(Controller(review(rr.PASS)))
        self.assertTrue(card.run())
        self._wait(card)
        existing = self.root / "summary.json"
        existing.write_bytes(b"previous")
        calls = []

        def dialog(*args, **kwargs):
            calls.append((args, kwargs))
            return str(target), ""

        target = existing
        with mock.patch.object(QFileDialog, "getSaveFileName", dialog):
            card._save()
            self.assertEqual(existing.read_bytes(), b"previous")
            self.assertIn("上書きしません", card.message.text())
            target = self.root / "new_summary"
            card._save()
        options = calls[-1][1].get("options", calls[-1][0][5] if len(calls[-1][0]) > 5 else None)
        self.assertTrue(options & QFileDialog.Option.DontConfirmOverwrite)
        saved = json.loads((self.root / "new_summary.json").read_text(encoding="utf-8"))
        self.assertEqual((saved["schema"], saved["state"]), (rr.SUMMARY_SCHEMA, rr.PASS))
        self.assertEqual(card.message.level, "success")

    def test_release_while_running_drops_the_result_without_blocking(self):
        controller = Controller(review(rr.PASS))
        controller.gate.clear()
        card = self._card(controller)
        self.assertTrue(card.run())
        task = card.task
        card.release()
        self.assertTrue(task.released)
        self.assertEqual(self.locks[-1], False)                         # the window's selector is given back
        controller.gate.set()
        from tests.test_qt_components import wait_until

        self.assertTrue(wait_until(lambda: task not in ui._RUNNING, 30000))
        QApplication.processEvents()
        self.assertIsNone(card.current_review())


class MfController(Controller):
    """A Money Forward pilot company (Phase 2): a fiscal year end is offered, the period is passed on."""

    def __init__(self, result=None, fiscal_year_end="05-31"):
        super().__init__(result)
        self.fiscal_year_end = fiscal_year_end

    def jdl_roundtrip_period(self, company_id):
        return self.fiscal_year_end

    def jdl_roundtrip_review(self, company_id, source, candidate, reexport, *, period_end=None):
        self.calls.append((company_id, source, candidate, reexport, period_end))
        self.gate.wait(30)
        return self.result


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class MoneyForwardCardTest(_CardBase):
    """Phase 2 on the same card: the fiscal year is chosen on screen, the re-export is optional."""

    def _mf_card(self, controller, *, reexport=True):
        card = self._card(controller)
        if not reexport:
            card.reexport = None
        card.refresh()
        return card

    def test_the_year_must_be_chosen_and_no_default_is_selected(self):
        from datetime import date

        controller = MfController(review(rr.PASS, regeneration={"byte_identical": True}))
        card = self._mf_card(controller)
        self.assertFalse(card.period_combo.isHidden())
        self.assertIsNone(card.period_combo.currentData())               # no default year
        self.assertIsNone(card.selected_period_end())
        self.assertFalse(card.run_button.isEnabled())
        self.assertFalse(card.run())
        self.assertIn("決算期", card.scope_label.text())
        self.assertIn("税理士の承認ではありません", card.guidance.text())
        self.assertNotIn(".audit.json", card.guidance.text())
        index = card.period_combo.findData("2026-05-31")
        self.assertGreater(index, 0)
        self.assertEqual(card.period_combo.itemText(index), "FY2026-05（2025-06-01〜2026-05-31）")
        card.period_combo.setCurrentIndex(index)
        self.assertEqual(card.selected_period_end(), date(2026, 5, 31))
        self.assertTrue(card.run_button.isEnabled())
        self.assertTrue(card.run())
        self._wait(card)
        self.assertEqual(controller.calls[-1][-1], date(2026, 5, 31))      # the chosen year is passed on
        self.assertEqual(card.current_review().state, rr.PASS)
        self.assertIn("過去に使った設定", card.message.text())
        card.period_combo.setCurrentIndex(card.period_combo.findData("2027-05-31"))
        self.assertIsNone(card.current_review())                          # another year: the result is not shown

    def test_without_a_reexport_only_the_regeneration_runs_and_it_is_not_a_pass(self):
        controller = MfController(review(rr.NOT_RUN, reasons=("REEXPORT_NOT_SELECTED",),
                                         regeneration={"byte_identical": True}, reexport={}))
        card = self._mf_card(controller, reexport=False)
        card.period_combo.setCurrentIndex(card.period_combo.findData("2027-05-31"))
        self.assertIn("再現だけ", card.reexport_label.text())
        self.assertTrue(card.run())
        self._wait(card)
        self.assertIsNone(controller.calls[-1][3])
        self.assertFalse(card.current_review().is_pass)
        self.assertIn("未照合", card.badge.text())

    def test_a_yayoi_company_has_no_year_to_choose(self):
        card = self._card(Controller(review(rr.PASS)))
        self.assertTrue(card.period_combo.isHidden())
        self.assertIn(".audit.json", card.guidance.text())


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class MainWindowRoundTripTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_output_page_has_the_card_and_a_journal_report_company_is_not_offered(self):
        from accounting_converter.ui_qt import main_window as mw
        from tests.test_unmigrated_view import Env

        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory, write=False)
            window = mw.AccountingConverterMainWindow(env.controller)
            self.addCleanup(window.deleteLater)
            self.addCleanup(window.home_task.shutdown)
            index = window.company_combo.findData("company-yayoi")
            window.company_combo.setCurrentIndex(index)
            window._select_input(env.run.source)
            card = window.roundtrip_card
            card.refresh()
            self.assertIn("未対応", card.scope_label.text())               # 仕訳日記帳 (company A form): Phase 3
            self.assertFalse(card.run_button.isEnabled())
            with mock.patch.object(card, "release", wraps=card.release) as released:
                window.close()
            self.assertTrue(released.called)


if __name__ == "__main__":
    unittest.main()
