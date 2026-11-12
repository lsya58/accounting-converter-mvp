"""D2 / Phase 3: tracking the journals a READY-only run left out (application/migration_tracker). Synthetic only."""
from __future__ import annotations

import copy
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from accounting_converter.application import migration_tracker as mt
from accounting_converter.application import yayoi_ready_only as ro
from tests.test_yayoi_ready_only import COMPANY, Run, _edit_manifest

ENTRY = {"jdl_vouchers": "501", "jdl_date": "2026-05-10", "entered_by": "架空入力者", "entered_at": "2026-11-20T10:00"}
REC = {"matched_jdl_vouchers": "501", "checked_by": "架空照合者", "checked_at": "2026-11-21T10:00",
       "method_reference": "照合メモ（架空）"}
NOT_NEEDED = {"approved_by": "架空税理士", "approved_at": "2026-11-21", "reason": "重複入力のため",
              "reference": "確認書（架空）"}


class Env:
    def __init__(self, directory):
        self.run = Run(directory)
        self.plan, self.result = self.run.write()
        self.root = Path(directory)

    def args(self):
        return (self.run.source, self.run.output, self.run.resolved.profile, self.run.resolved.context, COMPANY)

    def create(self):
        return mt.create_tracker(*self.args(), created_by="架空担当")

    def check(self, tracker):
        return mt.check(tracker, *self.args())

    def reexport(self):
        path = self.root / "reexport.csv"
        path.write_bytes(b"synthetic re-export")
        return path


class CreateTest(unittest.TestCase):
    def test_every_excluded_journal_is_tracked_and_every_source_journal_accounted_for(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            tracker = env.create()
            self.assertEqual([j["source_row"] for j in tracker["journals"]], [e.source_row for e in env.plan.excluded])
            self.assertTrue(all(j["status"] == mt.NOT_STARTED for j in tracker["journals"]))
            self.assertTrue(all(len(j["journal_sha256"]) == 64 for j in tracker["journals"]))
            result = env.check(tracker)
            self.assertEqual(result["verdict"], "PASS", result["problems"])
            self.assertEqual((result["counts"]["source_journals"], result["counts"]["ready_only_output"],
                              result["counts"]["tracked"]), (3, 2, 1))
            table = mt.journal_table(tracker, env.run.source, env.run.output)
            self.assertEqual(len(table), 3)
            self.assertFalse(any("行方不明" in row["where"] for row in table))

    def test_a_tampered_manifest_or_another_company_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            with self.assertRaises(mt.TrackerError):
                mt.create_tracker(env.run.source, env.run.output, env.run.resolved.profile, env.run.resolved.context,
                                  "company-other", created_by="x")
            _edit_manifest(env.run.output, lambda m: m.update(not_migrated_journals=0))
            with self.assertRaisesRegex(mt.TrackerError, "検証に失敗"):
                env.create()
            with self.assertRaises(mt.TrackerError):
                mt.create_tracker(*env.args(), created_by=" ")


class StatusTest(unittest.TestCase):
    def test_planned_or_entered_is_never_reconciled(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            tracker = env.create()
            row = tracker["journals"][0]["source_row"]
            with self.assertRaises(mt.TrackerError):  # not reachable from NOT_STARTED
                mt.set_status(tracker, row, mt.RECONCILED, by="x", jdl_entry=ENTRY, reconciliation=REC,
                              reexport_path=env.reexport())
            mt.set_status(tracker, row, mt.MANUAL_ENTRY_PLANNED, by="x")
            with self.assertRaises(mt.TrackerError):
                mt.set_status(tracker, row, mt.RECONCILED, by="x", reconciliation=REC, reexport_path=env.reexport())
            with self.assertRaises(mt.TrackerError):  # entered needs the JDL voucher, date and who
                mt.set_status(tracker, row, mt.MANUAL_ENTERED_UNRECONCILED, by="x", jdl_entry={"jdl_vouchers": "501"})
            mt.set_status(tracker, row, mt.MANUAL_ENTERED_UNRECONCILED, by="x", jdl_entry=ENTRY)
            final = mt.final_reconciliation(tracker, env.check(tracker))
            self.assertEqual(final["verdict"], "MIGRATION_INCOMPLETE")
            self.assertIn(row, final["open_journals"])
            with self.assertRaises(mt.TrackerError):  # no re-export file
                mt.set_status(tracker, row, mt.RECONCILED, by="x", reconciliation=REC)
            with self.assertRaises(mt.TrackerError):  # vouchers do not match the recorded entry
                mt.set_status(tracker, row, mt.RECONCILED, by="x", reconciliation={**REC, "matched_jdl_vouchers": "502"},
                              reexport_path=env.reexport())
            mt.set_status(tracker, row, mt.RECONCILED, by="x", reconciliation=REC, reexport_path=env.reexport())
            journal = tracker["journals"][0]
            self.assertEqual(len(journal["reconciliation"]["jdl_reexport_sha256"]), 64)
            self.assertEqual(journal["final_checker"], "架空照合者")
            with self.assertRaises(mt.TrackerError):  # closed: only reopen
                mt.set_status(tracker, row, mt.PLANNING, by="x")
            mt.reopen(tracker, row, by="x", reason="照合の誤り（架空）")
            self.assertEqual(journal["status"], mt.PLANNING)
            self.assertEqual(env.check(tracker)["verdict"], "PASS")

    def test_not_required_needs_an_explicit_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            tracker = env.create()
            row = tracker["journals"][0]["source_row"]
            for broken in (None, {**NOT_NEEDED, "approved_by": ""}, {**NOT_NEEDED, "reference": " "}):
                with self.subTest(broken), self.assertRaises(mt.TrackerError):
                    mt.set_status(tracker, row, mt.NOT_REQUIRED, by="x", not_required=broken)
            mt.set_status(tracker, row, mt.NOT_REQUIRED, by="x", not_required=NOT_NEEDED)
            self.assertEqual(env.check(tracker)["verdict"], "PASS")

    def test_fields_are_limited_and_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            tracker = env.create()
            row = tracker["journals"][0]["source_row"]
            mt.update_fields(tracker, row, by="x", plan="JDLで手入力", owner="架空担当", evidence_ids=["EVID-X"],
                             manual_entry_required=True)
            with self.assertRaises(mt.TrackerError):
                mt.update_fields(tracker, row, by="x", status=mt.RECONCILED)
            self.assertEqual(tracker["journals"][0]["history"][-1]["event"], "FIELDS")
            data = list(csv.reader(io.StringIO(mt.to_csv(tracker).decode("utf-8-sig"))))
            self.assertEqual(tuple(data[0]), mt.CSV_HEADER)
            self.assertEqual(data[1][0], str(row))
            self.assertEqual(data[1][7], "未対応")
            self.assertEqual(data[1][12], "必要")


class IntegrityTest(unittest.TestCase):
    def test_hand_edited_reconciliation_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            tracker = env.create()
            tracker["journals"][0]["status"] = mt.RECONCILED
            result = env.check(tracker)
            self.assertEqual(result["verdict"], "FAIL")
            found = result["problems"]["journal_history"][0]["problems"]
            self.assertIn("STATUS_NOT_IN_HISTORY", found)
            self.assertIn("RECONCILED_WITHOUT_EVIDENCE", found)
            tracker = env.create()
            tracker["journals"][0]["history"][0]["by"] = "別人"
            self.assertIn("HISTORY_TAMPERED", env.check(tracker)["problems"]["journal_history"][0]["problems"])

    def test_missing_duplicate_and_ready_overlap_are_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            base = env.create()
            missing = copy.deepcopy(base)
            missing["journals"] = []
            problems = env.check(missing)["problems"]
            row = base["journals"][0]["source_row"]
            self.assertEqual(problems["excluded_not_tracked"], [row])
            self.assertEqual(problems["missing_from_both"], [row])
            doubled = copy.deepcopy(base)
            doubled["journals"].append(copy.deepcopy(base["journals"][0]))
            self.assertEqual(env.check(doubled)["problems"]["duplicates_in_tracker"], [row])
            overlap = copy.deepcopy(base)
            ready_row = env.plan.ready_rows[0]
            overlap["journals"].append({**copy.deepcopy(base["journals"][0]), "source_row": ready_row})
            problems = env.check(overlap)["problems"]
            self.assertEqual(problems["ready_and_tracked"], [ready_row])
            self.assertEqual(problems["tracked_not_excluded"], [ready_row])

    def test_the_same_journal_processed_twice_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            tracker = env.create()
            row = tracker["journals"][0]["source_row"]
            mt.set_status(tracker, row, mt.MANUAL_ENTERED_UNRECONCILED, by="x", jdl_entry=ENTRY)
            journal = tracker["journals"][0]
            # a second "entered" event forged into the chain
            event = {k: v for k, v in journal["history"][-1].items() if k not in ("sha256", "prev")}
            mt._event(journal, event)
            self.assertIn("ENTERED_MORE_THAN_ONCE", env.check(tracker)["problems"]["journal_history"][0]["problems"])

    def test_a_changed_source_or_output_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            tracker = env.create()
            env.run.output.write_bytes(env.run.output.read_bytes() + b"\r\n")
            result = env.check(tracker)
            self.assertIn("output_sha256", result["problems"]["baseline"])
            self.assertTrue(result["problems"]["ready_only_run"])
            other = env.check({**tracker, "company_id": "company-other"})
            self.assertEqual(other["problems"]["company"], ["company-other"])


class FinalReconciliationTest(unittest.TestCase):
    def _proofs(self, env, tracker):
        base = tracker["baseline"]
        passed = {"candidate_sha256": base["output_sha256"], "source_sha256": base["source_sha256"],
                  "manifest_sha256": base["manifest_sha256"], "company_id": COMPANY, "reexport_sha256": "e" * 64,
                  "verdict": "PASS"}
        balance = {"checked_by": "架空", "checked_at": "2026-11-30T12:00", "reference": "試算表（架空）",
                   "company_id": COMPANY, "period_start": base["period"][0], "period_end": base["period"][1],
                   "tracker_state_sha256": mt.tracker_state_sha256(tracker)}
        return passed, balance

    def _close_all(self, env, tracker):
        row = tracker["journals"][0]["source_row"]
        mt.set_status(tracker, row, mt.MANUAL_ENTERED_UNRECONCILED, by="x", jdl_entry=ENTRY)
        mt.set_status(tracker, row, mt.RECONCILED, by="x", reconciliation=REC, reexport_path=env.reexport())

    def test_complete_only_when_every_part_is_proven(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            tracker = env.create()
            final = mt.final_reconciliation(tracker, env.check(tracker))
            self.assertEqual(final["verdict"], "MIGRATION_INCOMPLETE")
            self.assertEqual(len(final["reasons"]), 3)
            passed, balance = self._proofs(env, tracker)
            self.assertEqual(mt.final_reconciliation(tracker, env.check(tracker), roundtrip=passed,
                                                     trial_balance=balance)["verdict"],
                             "MIGRATION_INCOMPLETE")  # one journal still open
            self._close_all(env, tracker)
            integrity = env.check(tracker)
            passed, balance = self._proofs(env, tracker)
            self.assertEqual(mt.final_reconciliation(tracker, integrity, roundtrip=passed, trial_balance=balance)["verdict"],
                             "MIGRATION_COMPLETE")
            bad = {**integrity, "verdict": "FAIL"}
            self.assertEqual(mt.final_reconciliation(tracker, bad, roundtrip=passed, trial_balance=balance)["verdict"],
                             "MIGRATION_INCOMPLETE")

    def test_a_round_trip_of_another_file_company_or_verdict_never_completes(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            tracker = env.create()
            self._close_all(env, tracker)
            integrity = env.check(tracker)
            passed, balance = self._proofs(env, tracker)
            for change in ({"verdict": "NORMALIZATION_ACCEPTANCE_PENDING"}, {"verdict": "FAIL"},
                           {"candidate_sha256": "0" * 64},   # an older / other CSV
                           {"source_sha256": "0" * 64}, {"manifest_sha256": "0" * 64},
                           {"company_id": "company-other"}, {"reexport_sha256": ""}):
                with self.subTest(change):
                    self.assertEqual(mt.final_reconciliation(tracker, integrity, roundtrip={**passed, **change},
                                                             trial_balance=balance)["verdict"], "MIGRATION_INCOMPLETE")
            self.assertEqual(mt.final_reconciliation(tracker, integrity, trial_balance=balance)["verdict"],
                             "MIGRATION_INCOMPLETE")

    def test_the_trial_balance_record_must_name_who_when_company_period_document_and_this_state(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            tracker = env.create()
            self._close_all(env, tracker)
            integrity = env.check(tracker)
            passed, balance = self._proofs(env, tracker)
            changes = [{k: ""} for k in ("checked_by", "checked_at", "reference", "company_id", "period_start", "period_end")]
            changes += [{"company_id": "company-other"}, {"period_end": "2099-01-01"},
                        {"tracker_state_sha256": "0" * 64}, {"checked_at": "2000-01-01T00:00"},
                        {"checked_at": "not a date"}]
            for change in changes:
                with self.subTest(change):
                    result = mt.final_reconciliation(tracker, integrity, roundtrip=passed, trial_balance={**balance, **change})
                    self.assertEqual(result["verdict"], "MIGRATION_INCOMPLETE")
            self.assertEqual(mt.final_reconciliation(tracker, integrity, roundtrip=passed, trial_balance=balance)["verdict"],
                             "MIGRATION_COMPLETE")
            # an older trial-balance record cannot be reused once any journal changes afterwards
            mt.reopen(tracker, tracker["journals"][0]["source_row"], by="x", reason="やり直し")
            self.assertEqual(mt.final_reconciliation(tracker, env.check(tracker), roundtrip=passed,
                                                     trial_balance=balance)["verdict"], "MIGRATION_INCOMPLETE")

    def test_reconciliation_is_bound_to_its_journal_and_to_the_entry_time(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            tracker = env.create()
            row = tracker["journals"][0]["source_row"]
            mt.set_status(tracker, row, mt.MANUAL_ENTERED_UNRECONCILED, by="x", jdl_entry=ENTRY)
            for checked_at in ("2026-11-19T10:00", "not a date"):  # before the entry / invalid
                with self.subTest(checked_at), self.assertRaises(mt.TrackerError):
                    mt.set_status(tracker, row, mt.RECONCILED, by="x", reconciliation={**REC, "checked_at": checked_at},
                                  reexport_path=env.reexport())
            mt.set_status(tracker, row, mt.RECONCILED, by="x", reconciliation=REC, reexport_path=env.reexport())
            journal = tracker["journals"][0]
            self.assertEqual(journal["reconciliation"]["bound_journal_sha256"], journal["journal_sha256"])
            journal["reconciliation"]["bound_journal_sha256"] = "0" * 64  # evidence moved to another journal
            self.assertIn("RECONCILIATION_NOT_BOUND_TO_THIS_JOURNAL",
                          env.check(tracker)["problems"]["journal_history"][0]["problems"])

    def test_the_tracker_round_trips_through_its_file_and_the_ready_only_run_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            before = {p.name: p.read_bytes() for p in ro.run_paths(env.run.output) if p.exists()}
            tracker = env.create()
            path = env.root / "tracker.json"
            mt.save(tracker, path)
            self.assertEqual(mt.load(path), json.loads(json.dumps(tracker)))
            self.assertEqual(env.check(mt.load(path))["verdict"], "PASS")
            self.assertEqual({p.name: p.read_bytes() for p in ro.run_paths(env.run.output) if p.exists()}, before)
            self.assertEqual(env.run.verify()["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
