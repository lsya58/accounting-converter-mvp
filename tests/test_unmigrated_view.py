"""D2 without file picking: unmigrated journals from the diagnosis, run discovery, opening and starting a tracker.
Synthetic data only; the saved settings and the READY-only run are never changed by viewing."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from accounting_converter.application import migration_tracker as mt
from accounting_converter.application import unmigrated_view as uv
from accounting_converter.application import yayoi_ready_only as ro
from accounting_converter.infrastructure.application_preferences import ApplicationPreferencesStore
from accounting_converter.ui.controllers import AccountingConverterController
from tests.test_approval_ledger import rows as approval_rows, store_digest
from tests.test_noncredit_approval import evidence_covers_test_company
from tests.test_yayoi_ready_only import COMPANY, Run, _edit_manifest
from tests.test_yayoi_scoped_workflow import sales_voucher

ENTRY = {"jdl_vouchers": "501", "jdl_date": "2026-05-10", "entered_by": "架空入力者", "entered_at": "2026-11-20T10:00"}


def controller_for(run, root):
    return AccountingConverterController(profile_store=run.fixture.profiles, company_store=run.fixture.companies,
                                         preferences_store=ApplicationPreferencesStore(Path(root) / "prefs.json"))


class Env:
    """A READY-only run whose CSV sits next to the source (where the app looks first)."""

    def __init__(self, directory, rows=None, write=True):
        self.root = Path(directory)
        self.run = Run(directory, rows)
        self.run.output = self.root / "ready_only.csv"
        self.controller = controller_for(self.run, directory)
        if write:
            self.run.write()

    def overview(self):
        return self.controller.unmigrated_overview(COMPANY, self.run.source)

    def args(self):
        return (self.run.source, self.run.output, self.run.resolved.profile, self.run.resolved.context, COMPANY)


def listing(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class OverviewTest(unittest.TestCase):
    def test_the_unmigrated_journals_are_listed_with_no_output_and_no_tracker(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory, write=False)
            before = listing(env.root)
            data = env.overview()
            self.assertEqual((data["total"], data["ready"], data["blocked"]), (3, 2, 1))
            row = data["rows"][0]
            self.assertEqual((row.voucher, row.status, row.status_code), ("2", uv.NO_TRACKER_STATUS, None))
            self.assertTrue(row.reasons and row.codes and row.next_steps)
            self.assertEqual(listing(env.root), before)               # nothing was written to produce the list

    def test_each_row_says_what_the_accountant_and_what_the_team_must_do(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory, rows=approval_rows() + sales_voucher(3, voucher=10), write=False)
            data = env.overview()
            by_voucher = {r.voucher: r for r in data["rows"]}
            self.assertEqual(set(by_voucher), {"1", "2", "3", "4"})        # the READY voucher 10 is not listed
            self.assertIn("伝票分割の承認（SPLIT-V1）", by_voucher["1"].accountant)
            self.assertTrue(any(a.startswith("控除不可の承認（NONCREDIT-") for a in by_voucher["2"].accountant))
            self.assertEqual(len(by_voucher["3"].accountant), 2)           # both approvals
            self.assertEqual(by_voucher["4"].accountant, ())               # the 1-yen journal: no approval releases it
            self.assertTrue(by_voucher["4"].technical)
            for r in data["rows"]:
                self.assertEqual(r.status, uv.NO_TRACKER_STATUS)
                self.assertIn("手入力だけでは移行完了になりません", r.next_steps[-1])
            csv_bytes = uv.rows_csv(data["rows"])
            self.assertTrue(csv_bytes.startswith(b"\xef\xbb\xbf"))
            self.assertIn("元の行".encode(), csv_bytes)

    def test_viewing_never_changes_ready_block_the_settings_or_the_run(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            before = listing(env.root)
            counts = (env.overview()["ready"], env.overview()["blocked"])
            env.controller.find_ready_only_runs(COMPANY, env.run.source, [env.root])
            env.controller.open_migration_run(COMPANY, env.run.source, env.run.output)
            self.assertEqual(listing(env.root), before)
            self.assertEqual(counts, (2, 1))
            self.assertEqual(env.run.verify()["verdict"], "PASS")


class DiscoveryTest(unittest.TestCase):
    def _find(self, env, folders=None):
        return env.controller.find_ready_only_runs(COMPANY, env.run.source, folders or [env.root])

    def test_the_apps_own_run_next_to_the_source_is_found_for_this_company_and_source(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            found = self._find(env)
            self.assertEqual([(c.output.name, c.accepted) for c in found], [("ready_only.csv", True)])
            self.assertEqual(found[0].counts["excluded_journals"], 1)

    def test_other_company_changed_source_missing_csv_and_look_alikes_are_not_offered(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            _edit_manifest(env.run.output, lambda m: m.update(company_setting_id="company-other"))
            self.assertEqual((self._find(env)[0].accepted, self._find(env)[0].reason), (False, "別の会社の出力です"))
            _edit_manifest(env.run.output, lambda m: m.update(company_setting_id=COMPANY, source={**m["source"], "sha256": "0" * 64}))
            self.assertIn("元データと一致しません", self._find(env)[0].reason)
            _edit_manifest(env.run.output, lambda m: m.update(schema="other"))
            self.assertIn("READY-only出力の記録ではありません", self._find(env)[0].reason)
            env.run.output.unlink()
            self.assertIn("出力CSVがありません", self._find(env)[0].reason)
            # a CSV / JSON with a similar name but not the app's `<csv>.ready_only.json` pair is never considered
            (env.root / "ready_only_copy.csv").write_bytes(b"x")
            (env.root / "ready_only.json").write_text("{}", encoding="utf-8")
            (env.root / "ready_only.csv.old.ready_only.txt").write_text("{}", encoding="utf-8")
            self.assertEqual([c.manifest.name for c in self._find(env)], ["ready_only.csv.ready_only.json"])

    def test_an_unreadable_manifest_is_reported_not_skipped_silently(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            ro.manifest_path_for(env.run.output).write_text("not json", encoding="utf-8")
            self.assertEqual((self._find(env)[0].accepted, self._find(env)[0].reason), (False, "manifestを読めません"))


class OpenAndStartTest(unittest.TestCase):
    def test_a_verified_run_without_a_tracker_is_open_for_viewing_only(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            state = env.controller.open_migration_run(COMPANY, env.run.source, env.run.output)
            self.assertEqual(state["state"], "NO_TRACKER")
            self.assertFalse(mt.tracker_path_for(env.run.output).exists())

    def test_starting_needs_an_explicit_confirmation_and_creates_one_tracker_next_to_the_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            with self.assertRaises(ValueError):
                env.controller.start_migration_tracking(COMPANY, env.run.source, env.run.output, "架空担当")
            self.assertFalse(mt.tracker_path_for(env.run.output).exists())
            path = env.controller.start_migration_tracking(COMPANY, env.run.source, env.run.output, "架空担当",
                                                           explicitly_confirmed=True)
            self.assertEqual(path, mt.tracker_path_for(env.run.output))
            state = env.controller.open_migration_run(COMPANY, env.run.source, env.run.output)
            self.assertEqual((state["state"], state["final"]["verdict"]), ("TRACKED", "MIGRATION_INCOMPLETE"))
            rows = uv.build_rows(env.overview()["plan"], (), state["tracker"])
            self.assertEqual([r.status for r in rows], ["未対応"])         # nothing starts as migrated
            self.assertEqual((env.overview()["ready"], env.overview()["blocked"]), (2, 1))

    def test_an_existing_tracker_is_never_overwritten_or_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            path = env.controller.start_migration_tracking(COMPANY, env.run.source, env.run.output, "x", explicitly_confirmed=True)
            tracker = mt.load(path)
            row = tracker["journals"][0]["source_row"]
            mt.set_status(tracker, row, mt.MANUAL_ENTRY_PLANNED, by="x")
            mt.save(tracker, path)
            saved = path.read_bytes()
            with self.assertRaisesRegex(mt.TrackerError, "上書き・初期化はしません"):
                env.controller.start_migration_tracking(COMPANY, env.run.source, env.run.output, "y", explicitly_confirmed=True)
            self.assertEqual(path.read_bytes(), saved)
            state = env.controller.open_migration_run(COMPANY, env.run.source, env.run.output)
            self.assertEqual(state["tracker"]["journals"][0]["status"], mt.MANUAL_ENTRY_PLANNED)   # kept as it was
            leftover = path.with_name(path.name + ".tmp")
            path.unlink()
            leftover.write_text("x", encoding="utf-8")
            with self.assertRaises(FileExistsError):                      # a leftover temp file stops it, not replaced
                env.controller.start_migration_tracking(COMPANY, env.run.source, env.run.output, "y", explicitly_confirmed=True)
            self.assertEqual(leftover.read_text(encoding="utf-8"), "x")

    def test_a_run_that_does_not_verify_gets_no_tracker_and_a_plain_explanation(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            _edit_manifest(env.run.output, lambda m: m.update(not_migrated_journals=0))
            state = env.controller.open_migration_run(COMPANY, env.run.source, env.run.output)
            self.assertEqual(state["state"], "REJECTED")
            self.assertTrue(any("改変" in p for p in state["problems"]), state["problems"])
            with self.assertRaises(mt.TrackerError):
                env.controller.start_migration_tracking(COMPANY, env.run.source, env.run.output, "x", explicitly_confirmed=True)
            self.assertFalse(mt.tracker_path_for(env.run.output).exists())

    def test_a_changed_output_or_source_is_rejected_and_the_old_tracker_is_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            path = env.controller.start_migration_tracking(COMPANY, env.run.source, env.run.output, "x", explicitly_confirmed=True)
            saved = path.read_bytes()
            env.run.output.write_bytes(env.run.output.read_bytes() + b"\r\n")           # the CSV changed afterwards
            state = env.controller.open_migration_run(COMPANY, env.run.source, env.run.output)
            self.assertEqual((state["state"], state["tracker"]), ("REJECTED", None))
            self.assertTrue(any("出力CSV" in p for p in state["problems"]))
            self.assertEqual(path.read_bytes(), saved)                     # and the tracker file is left alone

    def test_a_tracker_of_another_company_or_another_run_is_refused_and_left_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            path = env.controller.start_migration_tracking(COMPANY, env.run.source, env.run.output, "x", explicitly_confirmed=True)
            tracker = json.loads(path.read_text(encoding="utf-8"))
            tracker["company_id"] = "company-other"
            path.write_text(json.dumps(tracker), encoding="utf-8")
            saved = path.read_bytes()
            state = env.controller.open_migration_run(COMPANY, env.run.source, env.run.output)
            self.assertEqual((state["state"], state["tracker"]), ("TRACKER_MISMATCH", None))
            self.assertIn("使いません", state["problems"][0])
            self.assertEqual(path.read_bytes(), saved)
            tracker["company_id"] = COMPANY                                # a tracker of another run (different baseline)
            tracker["baseline"]["output_sha256"] = "0" * 64
            path.write_text(json.dumps(tracker), encoding="utf-8")
            self.assertEqual(env.controller.open_migration_run(COMPANY, env.run.source, env.run.output)["state"],
                             "TRACKER_MISMATCH")
            path.write_text(json.dumps({"schema": "yayoi-jdl-ready-only-v1"}), encoding="utf-8")   # the manifest, not a tracker
            self.assertEqual(env.controller.open_migration_run(COMPANY, env.run.source, env.run.output)["state"],
                             "TRACKER_INVALID")

    def test_a_manually_edited_status_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            path = env.controller.start_migration_tracking(COMPANY, env.run.source, env.run.output, "x", explicitly_confirmed=True)
            tracker = json.loads(path.read_text(encoding="utf-8"))
            tracker["journals"][0]["status"] = mt.RECONCILED           # "reconciled" without any evidence
            path.write_text(json.dumps(tracker), encoding="utf-8")
            state = env.controller.open_migration_run(COMPANY, env.run.source, env.run.output)
            self.assertEqual((state["state"], state["tracker"]), ("TRACKER_MISMATCH", None))
            self.assertTrue(any("journal_history" in p for p in state["problems"]))


if __name__ == "__main__":
    unittest.main()
