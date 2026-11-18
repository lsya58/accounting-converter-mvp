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


def _run(state_, file="a.csv", *, usable=True, sha="0" * 64, history=()):
    return {"file": file, "state": state_, "usable": usable, "output_sha256": sha, "history": history,
            "counts": {"output_journals": 2479, "output_rows": 6100}, "created_at": "2026-11-11T10:07:28.1+00:00"}


class RunIdentityTest(unittest.TestCase):
    """READY-only outputs are told apart by the SHA-256 of their bytes, never by their file names, and a recorded
    real-JDL result applies only to the exact company / source / output / period / JDL conditions it was made for."""
    SOURCE = "7ab406cb9d0c88b3ecac07e55d2586808bdd4e2368df058aeb014e623d0c14a8"
    OLD = "2032c1450bf51debe485d7b7bd2459f6eef24f4d52d63737e78718b4e56af45b"
    NEW = "0aed42158f009cae151a5922b3c12db7742550f7fe0afb09843f6e2c67d7d178"
    COMPANY_A = "company-f92affc1f3ed43c8aee36380ab612f9d"

    def manifest(self, output=None, **changes):
        base = {"source": {"sha256": self.SOURCE, "period": ["2025-08-01", "2026-07-31"]},
                "output": {"sha256": output or self.NEW}, "company_setting_id": self.COMPANY_A,
                "settings": {"jdl_product": "JDL IBEX 出納帳", "jdl_version": "35.5",
                             "tax_processing_mode": "TAXABLE_TAX_EXCLUDED", "taxation_method": "STANDARD",
                             "input_tax_credit_method": "PROPORTIONAL", "rounding": ["CEILING", "HALF_UP"],
                             "voucher_row_limit": 16}}
        for key, value in changes.items():
            if key == "settings":
                base["settings"] = {**base["settings"], **value}
            elif key == "period":
                base["source"] = {**base["source"], "period": value}
            else:
                base[key] = value
        return base

    def lookup(self, output=None, *, source=None, company=None, manifest=None):
        from accounting_converter.ui import run_history as rh

        output = output or self.NEW
        return rh.recorded_results(source or self.SOURCE, output,
                                   manifest=manifest if manifest is not None else self.manifest(output),
                                   company_setting_id=company or self.COMPANY_A)

    def test_recorded_results_follow_the_bytes(self):
        from accounting_converter.ui import run_history as rh

        old, new = self.lookup(self.OLD), self.lookup(self.NEW)
        self.assertEqual(rh.e2e_text(old), "実機E2E FAIL（2026-11-11）")
        self.assertEqual(rh.e2e_text(new), "実機E2E 未実施（既存再Exportとの部分集合照合 PASS）")
        self.assertEqual([(r.kind, r.verdict, r.e2e_done) for r in old], [("E2E_ROUNDTRIP", "FAIL", True)])
        self.assertEqual([(r.kind, r.verdict, r.e2e_done) for r in new], [("SUBSET_RECONCILIATION", "PASS", False)])
        # the old FAIL and the new PASS are never mixed up, whatever the files are called
        self.assertNotEqual({r.verdict for r in old}, {r.verdict for r in new})

    def test_no_record_is_unconfirmed_not_a_pass(self):
        from accounting_converter.ui import run_history as rh

        unknown = self.lookup("f" * 64)
        self.assertEqual(unknown, ())
        self.assertEqual(rh.e2e_text(unknown), "実機での確認記録なし（未確認）")
        self.assertNotIn("PASS", rh.e2e_text(unknown))

    def test_a_record_never_applies_to_another_company_source_period_or_setting(self):
        cases = {
            "another company": dict(company="company-other", manifest=self.manifest(company_setting_id="company-other")),
            "manifest names another company": dict(manifest=self.manifest(company_setting_id="company-other")),
            "another source (argument)": dict(source="e" * 64),
            "manifest names another source": dict(manifest={**self.manifest(), "source": {
                "sha256": "e" * 64, "period": ["2025-08-01", "2026-07-31"]}}),
            "another period": dict(manifest=self.manifest(period=["2025-08-01", "2026-06-30"])),
            "64-row setting": dict(manifest=self.manifest(settings={"voucher_row_limit": 64})),
            "another tax setting": dict(manifest=self.manifest(settings={"input_tax_credit_method": "INDIVIDUAL"})),
            "another rounding": dict(manifest=self.manifest(settings={"rounding": ["FLOOR", "HALF_UP"]})),
            "another JDL version": dict(manifest=self.manifest(settings={"jdl_version": "36.0"})),
            "manifest names other bytes": dict(manifest=self.manifest(output="a" * 64)),
            "no manifest": dict(manifest={}),
            "no setting recorded": dict(manifest={**self.manifest(), "settings": {}}),
        }
        for name, kwargs in cases.items():
            for output in (self.OLD, self.NEW):
                with self.subTest(name, output=output[:6]):
                    if "manifest" in kwargs and kwargs["manifest"] and "output" in kwargs["manifest"] \
                            and name != "manifest names other bytes":
                        kwargs = {**kwargs, "manifest": {**kwargs["manifest"], "output": {"sha256": output}}}
                    self.assertEqual(self.lookup(output, **kwargs), ())

    def test_different_output_bytes_with_the_same_name_or_counts_get_nothing(self):
        # one changed byte = another SHA-256 = no record, however similar the name and counts
        self.assertEqual(self.lookup("0aed42158f009cae151a5922b3c12db7742550f7fe0afb09843f6e2c67d7d179"), ())

    def test_the_table_is_not_evidence_and_the_conversion_never_reads_it(self):
        from pathlib import Path

        from accounting_converter.ui import run_history as rh

        for record in (r for results in rh.RECORDED_RESULTS.values() for r in results):
            self.assertEqual(record.basis, "MANUAL_TRANSCRIPTION_OF_DOCS")
            self.assertTrue(record.reference.startswith("docs/"))
            self.assertTrue(record.company_setting_id and record.source_period and record.jdl_conditions)
        root = Path("src/accounting_converter")
        users = sorted(p.as_posix() for p in root.rglob("*.py") if "run_history" in p.read_text(encoding="utf-8")
                       and p.name != "run_history.py")
        self.assertEqual(users, ["src/accounting_converter/ui/controllers.py", "src/accounting_converter/ui/home_view.py"])
        for path in root.rglob("*.py"):
            if path.parts[2] in ("application", "adapters", "domain", "profiles", "infrastructure"):
                self.assertNotIn("run_history", path.read_text(encoding="utf-8"), str(path))

    def test_the_table_shows_unused_outputs_as_reference_with_their_own_history(self):
        from accounting_converter.ui import run_history as rh

        # the 2,479 bytes saved under the 2,480 name still show the 2,479 history (and vice versa)
        swapped = overview(runs=(
            _run("NO_TRACKER", "BUDDIES_READY_ONLY_2480_x.csv", sha=self.NEW, history=self.lookup(self.NEW)),
            _run("OUTDATED", "BUDDIES_READY_ONLY_2479_x.csv", usable=False, sha=self.OLD, history=self.lookup(self.OLD)),
            _run("NO_TRACKER", "unrecorded.csv", sha="c" * 64),
        ))
        rows = hv.run_rows(swapped)
        self.assertEqual(len(rows[0]), len(hv.RUN_COLUMNS))
        self.assertIn("未実施", rows[0][6])
        self.assertNotIn("参考", rows[0][6])
        self.assertIn("FAIL", rows[1][6])
        self.assertTrue(rows[1][6].startswith("【参考・現在は使わない出力】"))      # not a current result
        self.assertEqual(rows[2][6], "実機での確認記録なし（未確認）")
        self.assertIn("一致", rows[0][5])
        self.assertIn("旧い出力", rows[1][5])
        self.assertEqual(rows[0][4], self.NEW[:12] + "…")
        self.assertEqual((rows[0][1], rows[0][2]), ("2,479", "6,100"))
        self.assertEqual(rows[1][7], "—")
        cards = dict(hv.run_cards(swapped))
        self.assertIn("新しいEvidenceではありません", " ".join(cards["BUDDIES_READY_ONLY_2480_x.csv"]))
        self.assertIn("会社設定 " + self.COMPANY_A, " ".join(cards["BUDDIES_READY_ONLY_2480_x.csv"]))
        self.assertIn("行数 16", " ".join(cards["BUDDIES_READY_ONLY_2480_x.csv"]))


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
        self.assertEqual([a.priority for a in home.next_actions][:3], [3, 4, 5])
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

    def test_while_diagnosing_nothing_is_guessed(self):
        home = hv.build_home(state(), yayoi_busy=True)
        for label in ("変換可能", "BLOCK", "税理士の判断", "承認済み"):
            self.assertEqual(metric(home, label).value, "—", label)
        self.assertEqual(home.message[0], "info")
        self.assertIn("保存はしません", home.message[1])

    def test_an_undiagnosed_count_is_named_undiagnosed_never_zero(self):
        for kwargs, word in (({}, "未診断"), ({"yayoi_busy": True}, "診断中"), ({"yayoi_error": "x"}, "診断できません")):
            home = hv.build_home(state(), **kwargs)
            for label in ("変換可能", "BLOCK", "税理士の判断", "承認済み"):
                with self.subTest(word=word, label=label):
                    self.assertEqual(metric(home, label).value, "—")
                    self.assertNotIn("0", metric(home, label).value)
                    self.assertEqual(metric(home, label).hint, word)

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

    def test_settings_and_journals_are_counted_separately_never_summed(self):
        """Company A: 2 税区分 settings (件) and 22 journals for the accountant (仕訳). The nav never says 24."""
        home = hv.build_home(state(pending_tax_confirmations=2), yayoi=overview(accountant_journals=22))
        self.assertEqual((home.review_settings, home.review_journals), (2, 22))
        label, description = hv.review_nav_text(home.review_settings, home.review_journals)
        self.assertEqual(label, "要確認\n設定2件・判断22仕訳")
        self.assertNotIn("24", label + description)
        self.assertIn("合計していません", description)
        self.assertIn("2件（科目・補助・税区分の設定の数）", description)
        self.assertIn("22仕訳（仕訳の数）", description)
        self.assertEqual(home.next_actions[0].priority, 2)
        self.assertIn("税区分 2件", home.next_actions[0].text)
        self.assertIn("設定の数", home.next_actions[0].text)
        before = hv.build_home(state(pending_tax_confirmations=2), yayoi_busy=True)    # diagnosis not finished
        self.assertIsNone(before.review_journals)
        self.assertIn("未診断", hv.review_nav_text(before.review_settings, before.review_journals)[1])
        self.assertEqual(hv.review_nav_text(0, 0)[0], "要確認")
        mf = hv.build_home(state(RecognizedFormat.MONEYFORWARD, pending_account_confirmations=1))
        self.assertEqual((mf.review_settings, mf.review_journals), (1, 0))

    def test_next_actions_are_ordered_by_priority_and_no_button_repeats(self):
        cases = (
            hv.build_home(state(pending_tax_confirmations=2), yayoi=overview(accountant_journals=22)),
            hv.build_home(state(pending_tax_confirmations=2), yayoi=overview(runs=(_run("NO_TRACKER"),))),
            hv.build_home(state(), yayoi=overview(runs=(_run("NO_TRACKER"), _run("NO_TRACKER", "b.csv")))),
            hv.build_home(state(company=False, file=False)),
            hv.build_home(state(RecognizedFormat.MONEYFORWARD, conversion_available=True,
                                selected_output_file=Path("/out/x.csv"))),
        )
        for home in cases:
            with self.subTest([a.text for a in home.next_actions]):
                priorities = [a.priority for a in home.next_actions]
                self.assertEqual(priorities, sorted(priorities))
                buttons = [a.button for a in home.next_actions if a.button]
                self.assertEqual(len(buttons), len(set(buttons)))
                for action in home.next_actions:
                    if action.target:
                        self.assertTrue(action.button.startswith(("要確認", "変換診断", "出力・照合", "データ取込", "設定")))
        company_a = cases[0]
        self.assertEqual([a.button for a in company_a.next_actions],
                         ["要確認で設定を確認", "変換診断で理由を見る", "要確認で税理士の判断を見る", "出力・照合へ"])

    def test_several_usable_outputs_ask_for_a_choice(self):
        home = hv.build_home(state(), yayoi=overview(runs=(_run("NO_TRACKER"), _run("NO_TRACKER", "b.csv")),
                                                     runs_found=2))
        self.assertIn("複数", metric(home, "移行全体").hint)
        self.assertEqual(metric(home, "移行全体").value, "未完了")
        texts = " ".join(a.text for a in home.next_actions)
        self.assertIn("2件あります", texts)
        self.assertNotIn("READYの仕訳だけを出力できます", texts)

    def test_an_outdated_output_is_listed_but_never_used(self):
        runs = (_run("OUTDATED", "old.csv", usable=False), _run("NO_TRACKER", "new.csv"))
        home = hv.build_home(state(), yayoi=overview(runs=runs, runs_found=1, run_state="NO_TRACKER"))
        self.assertEqual(metric(home, "移行全体").value, "未完了")
        self.assertIn("使えない出力 1件", metric(home, "移行全体").hint)
        self.assertTrue(any("old.csv" in n and "削除はしません" in n for n in home.notes))
        self.assertTrue(any("new.csv" in a.text for a in home.next_actions))

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

    def test_runs_are_classified_by_content_and_only_the_current_one_is_used(self):
        import json
        import shutil

        from accounting_converter.application import yayoi_ready_only as ro
        from tests.test_unmigrated_view import Env, listing

        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory, write=True)
            output = env.run.output
            sidecars = (ro.manifest_path_for(output), ro.excluded_list_path_for(output), ro.audit_path_for(output))

            def copy_as(name, edit_manifest=None, edit_csv=None):
                target = output.with_name(name)
                shutil.copyfile(output, target)
                for path in sidecars:
                    if path.exists():
                        shutil.copyfile(path, target.with_name(target.name + path.name[len(output.name):]))
                if edit_manifest:
                    manifest_path = ro.manifest_path_for(target)
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    edit_manifest(manifest)
                    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
                if edit_csv:
                    target.write_bytes(edit_csv(target.read_bytes()))

            copy_as("older_plan.csv", edit_manifest=lambda m: m.update(plan_fingerprint="0" * 64))
            copy_as("tampered.csv", edit_csv=lambda data: data + b"\r\n")
            before = listing(Path(directory))
            seen = env.controller.home_yayoi_overview(COMPANY, env.run.source)
            self.assertEqual(listing(Path(directory)), before)            # read-only
            by_file = {run["file"]: run for run in seen["runs"]}
            self.assertEqual(by_file[output.name]["state"], "NO_TRACKER")
            self.assertTrue(by_file[output.name]["usable"])
            self.assertEqual(by_file["older_plan.csv"]["state"], "OUTDATED")
            self.assertFalse(by_file["older_plan.csv"]["usable"])
            self.assertEqual(by_file["tampered.csv"]["state"], "REJECTED")
            self.assertFalse(by_file["tampered.csv"]["usable"])
            self.assertEqual((seen["runs_found"], seen["run_state"]), (1, "NO_TRACKER"))
            self.assertEqual(seen["run_output"], str(output))
            # the same bytes as the valid run get the same (empty) recorded history: identity is the content
            self.assertEqual(by_file[output.name]["output_sha256"], by_file["older_plan.csv"]["output_sha256"])
            home = hv.build_home(state(journals=seen["total"]), yayoi=seen)
            self.assertEqual(metric(home, "移行全体").value, "未完了")
            self.assertIn("使えない出力 2件", metric(home, "移行全体").hint)
            self.assertFalse(list(Path(directory).rglob("*migration_tracker*")))

    def test_a_later_setting_change_makes_the_same_output_outdated_and_changes_nothing_on_disk(self):
        import dataclasses

        from tests.test_unmigrated_view import Env, listing

        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory, write=True)
            plan = env.overview()["plan"]
            source = env.run.source
            before = listing(Path(directory))
            now = env.controller._classify_ready_only_runs(COMPANY, source, plan)
            self.assertEqual([(r["state"], r["usable"]) for r in now], [("NO_TRACKER", True)])
            # a company / period / setting change alters the diagnosis fingerprint (profile, settings and rows are in it)
            for change in ({"profile_updated_at": "2099-01-01T00:00:00+00:00"},
                           {"settings": {**plan.settings, "voucher_row_limit": 64}},
                           {"company_setting_id": "company-other"}):
                with self.subTest(change=list(change)):
                    later = env.controller._classify_ready_only_runs(COMPANY, source, dataclasses.replace(plan, **change))
                    self.assertEqual([(r["state"], r["usable"]) for r in later], [("OUTDATED", False)])
                    self.assertIn("現在の正式診断と異なる", later[0]["problems"][0])
                    self.assertEqual(listing(Path(directory)), before)      # nothing deleted, rewritten or created
            # and the original judgement comes back when the diagnosis is the same again (nothing was remembered)
            again = env.controller._classify_ready_only_runs(COMPANY, source, plan)
            self.assertEqual([(r["state"], r["usable"]) for r in again], [("NO_TRACKER", True)])
            # another company never finds this run at all
            other = env.controller._classify_ready_only_runs("company-other", source, plan)
            self.assertEqual([(r["state"], r["usable"]) for r in other], [("NOT_THIS_SOURCE", False)])
            self.assertEqual(listing(Path(directory)), before)
            # the test run has no recorded real-JDL result: unconfirmed, whatever its name or counts
            self.assertEqual(now[0]["history"], ())

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
