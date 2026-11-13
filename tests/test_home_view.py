"""ホーム画面 (Phase 3A): the presentation (pure data) and the read-only controller overview it shows."""
from __future__ import annotations

from tests import _appdata_guard  # noqa: F401  (keeps tests away from the real application data)

import tempfile
import unittest
from pathlib import Path

from accounting_converter.ui import home_view as hv
from accounting_converter.ui.view_models import AppState, CompanyOption, FileRecognition, RecognizedFormat

COMPANY = "company-yayoi"


def state(fmt=RecognizedFormat.YAYOI, *, company=True, file=True, journals=2514, **kwargs) -> AppState:
    companies = (CompanyOption(COMPANY, "会社A", "弥生", "利用できます"),)
    return AppState(
        companies=companies,
        selected_company_setting_id=COMPANY if company else None,
        selected_file=Path("/data/source.txt") if file else None,
        file_recognition=FileRecognition(fmt, "テスト形式", journals, "2025-06-01", "2026-05-31") if file else None,
        **kwargs,
    )


def overview(**changes) -> dict:
    """What controller.home_yayoi_overview returns for company A today (2,514 = 2,479 + 35, no approval)."""
    base = {"total": 2514, "ready": 2479, "blocked": 35, "accountant_journals": 20, "pending_items": 4,
            "approvals_in_force": 0, "ledger_error": None, "runs_found": 0, "runs_rejected": 0, "run_state": None,
            "run_output": None, "verdict": None, "final_reasons": ()}
    return {**base, **changes}


def metric(presentation, label):
    return {m.label: m for m in (*presentation.metrics, presentation.migration)}[label]


class HomePresentationTest(unittest.TestCase):
    def test_company_a_counts_are_shown_exactly_and_the_migration_is_not_complete(self):
        home = hv.build_home(state(), yayoi=overview())
        self.assertEqual(metric(home, "元仕訳").value, "2,514")
        self.assertEqual(metric(home, "変換可能").value, "2,479")
        self.assertEqual(metric(home, "BLOCK").value, "35")
        self.assertEqual(metric(home, "税理士の判断").value, "20")
        self.assertEqual(metric(home, "承認済み").value, "0")
        self.assertEqual(metric(home, "移行全体").value, "未完了")
        self.assertIn("未移行 35仕訳", metric(home, "移行全体").hint)
        self.assertIn("READY-only出力が見つかっていません", metric(home, "移行全体").hint)
        targets = [a.target for a in home.next_actions]
        self.assertEqual(targets[:3], ["diagnosis", "review", "output"])
        self.assertTrue(all(a.button for a in home.next_actions if a.target))
        self.assertIn("会社: 会社A", home.company_lines)
        self.assertTrue(any("2025-06-01 〜 2026-05-31" in line for line in home.company_lines))
        self.assertTrue(home.yayoi)

    def test_completion_is_never_inferred(self):
        for changes in ({}, {"blocked": 0, "ready": 2514}, {"run_state": "NO_TRACKER", "runs_found": 1},
                        {"run_state": "TRACKED", "runs_found": 1, "verdict": "MIGRATION_INCOMPLETE"},
                        {"run_state": "REJECTED", "runs_found": 1}, {"run_state": "TRACKER_MISMATCH"},
                        {"run_state": "TRACKER_INVALID"}):
            with self.subTest(changes):
                self.assertEqual(metric(hv.build_home(state(), yayoi=overview(**changes)), "移行全体").value, "未完了")
        complete = hv.build_home(state(), yayoi=overview(run_state="TRACKED", verdict="MIGRATION_COMPLETE"))
        self.assertEqual(metric(complete, "移行全体").value, "完了")
        self.assertEqual(metric(hv.build_home(state()), "移行全体").value, "未完了")   # before the diagnosis
        failed = hv.build_home(state(), yayoi_error="ValueError: x")
        self.assertEqual(metric(failed, "移行全体").value, "未完了")
        self.assertEqual(failed.message[0], "error")
        self.assertIn("何も保存していません", failed.message[1])

    def test_several_outputs_for_the_same_source_are_not_reported_as_none(self):
        home = hv.build_home(state(), yayoi=overview(runs_found=2))
        self.assertIn("複数", metric(home, "移行全体").hint)
        self.assertEqual(metric(home, "移行全体").value, "未完了")
        texts = " ".join(a.text for a in home.next_actions)
        self.assertIn("2件あります", texts)
        self.assertNotIn("READYの仕訳だけを出力できます", texts)

    def test_while_diagnosing_nothing_is_guessed(self):
        home = hv.build_home(state(), yayoi_busy=True)
        for label in ("変換可能", "BLOCK", "税理士の判断", "承認済み"):
            self.assertEqual(metric(home, label).value, "—", label)
        self.assertEqual(home.message[0], "info")
        self.assertIn("保存はしません", home.message[1])

    def test_no_source_and_no_company(self):
        home = hv.build_home(state(file=False))
        self.assertTrue(all(m.value == "—" for m in home.metrics))
        self.assertEqual(home.next_actions[0].target, "import")
        self.assertFalse(home.yayoi)
        nothing = hv.build_home(state(company=False, file=False))
        self.assertEqual([a.target for a in nothing.next_actions], ["settings", "import"])
        self.assertIn("会社: 未選択", nothing.company_lines)

    def test_other_formats_never_show_yayoi_functions_as_usable(self):
        for fmt in (RecognizedFormat.MONEYFORWARD, RecognizedFormat.JDL):
            with self.subTest(fmt):
                home = hv.build_home(state(fmt, journals=482), yayoi=overview())   # a Yayoi result is ignored
                self.assertFalse(home.yayoi)
                self.assertEqual(metric(home, "税理士の判断").value, "対象外")
                self.assertEqual(metric(home, "承認済み").value, "対象外")
                self.assertEqual(metric(home, "移行全体").value, "対象外")
                self.assertEqual(metric(home, "元仕訳").value, "482")
                self.assertEqual(metric(home, "変換可能").value, "—")       # not computed yet: not guessed
                self.assertFalse(any("READY" in a.text for a in home.next_actions))
        ready = hv.build_home(state(RecognizedFormat.MONEYFORWARD, journals=378,
                                    formal_ready_summary=(378, 378)))
        self.assertEqual((metric(ready, "変換可能").value, metric(ready, "BLOCK").value), ("378", "0"))

    def test_unknown_format_says_what_happened(self):
        home = hv.build_home(state(RecognizedFormat.UNKNOWN, journals=None))
        self.assertEqual(home.message[0], "error")
        self.assertIn("変更していません", home.message[1])
        self.assertFalse(home.yayoi)

    def test_pending_confirmations_come_first_and_count_on_the_navigation(self):
        home = hv.build_home(state(pending_account_confirmations=2, pending_tax_confirmations=1), yayoi=overview())
        self.assertEqual(home.next_actions[0].target, "review")
        self.assertIn("3件", home.next_actions[0].text)
        self.assertEqual(home.review_count, 3 + 20)

    def test_an_unreadable_ledger_is_reported_not_counted_as_zero(self):
        home = hv.build_home(state(), yayoi=overview(ledger_error="承認台帳が改変されています（1行目）"))
        self.assertEqual(metric(home, "承認済み").value, "—")
        self.assertIn("改変", metric(home, "承認済み").hint)

    def test_navigation_items(self):
        self.assertEqual([label for _, label in hv.NAV_ITEMS],
                         ["ホーム", "データ取込", "変換診断", "要確認", "出力・照合", "設定"])


class ControllerOverviewTest(unittest.TestCase):
    """controller.home_yayoi_overview: the D2 numbers, read-only (no tracker, no ledger line, no setting)."""

    def test_same_numbers_as_d2_and_nothing_written(self):
        from tests.test_unmigrated_view import Env, listing

        for write in (False, True):
            with self.subTest(ready_only_written=write), tempfile.TemporaryDirectory() as directory:
                env = Env(directory, write=write)
                before = listing(Path(directory))
                seen = env.controller.home_yayoi_overview(COMPANY, env.run.source)
                d2 = env.overview()
                self.assertEqual((seen["total"], seen["ready"], seen["blocked"]), (d2["total"], d2["ready"], d2["blocked"]))
                self.assertEqual(seen["total"], seen["ready"] + seen["blocked"])
                self.assertEqual(seen["approvals_in_force"], 0)
                self.assertIsNone(seen["ledger_error"])
                self.assertIsNone(seen["verdict"])
                self.assertEqual(seen["run_state"], "NO_TRACKER" if write else None)
                self.assertEqual(listing(Path(directory)), before)          # read-only
                self.assertFalse(list(Path(directory).rglob("*migration_tracker*")))
                home = hv.build_home(state(journals=seen["total"]), yayoi=seen)
                self.assertEqual(metric(home, "移行全体").value, "未完了")

    def test_a_recorded_approval_is_counted_and_reading_writes_nothing(self):
        from accounting_converter.application import approval_ledger as al
        from tests.test_approval_ledger import Env as ApprovalEnv
        from tests.test_approval_ledger import store_digest
        from tests.test_noncredit_approval import evidence_covers_test_company
        from tests.test_qt_migration_status_dialog import controller_for

        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = ApprovalEnv(directory)
            controller = controller_for(env.fixture, env.root)
            first = controller.home_yayoi_overview(COMPANY, env.source)
            self.assertEqual(first["approvals_in_force"], 0)
            self.assertGreater(first["pending_items"], 0)
            env.ledger = controller._approval_ledger(COMPANY)            # the ledger the app reads by default
            env.record("SPLIT-V1", al.APPROVED)                          # test setup only (the CLI route in use)
            ledger_bytes = env.ledger.path.read_bytes()
            digest = store_digest(env.root)
            seen = controller.home_yayoi_overview(COMPANY, env.source)
            self.assertEqual(seen["approvals_in_force"], 1)
            self.assertEqual((seen["ready"], seen["blocked"]), (first["ready"], first["blocked"]))   # not applied
            self.assertEqual(store_digest(env.root), digest)
            self.assertEqual(env.ledger.path.read_bytes(), ledger_bytes)
            env.record("SPLIT-V1", al.REVOKED)
            self.assertEqual(controller.home_yayoi_overview(COMPANY, env.source)["approvals_in_force"], 0)


if __name__ == "__main__":
    unittest.main()
