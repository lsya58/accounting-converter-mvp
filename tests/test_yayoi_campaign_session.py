"""Session-level check of an Evidence campaign (duplicates, strays, hand-entered examples). Synthetic only."""
from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from accounting_converter.profiles.jdl_official import jdl_ibex_cashbook_official_journal_import_spec
from accounting_converter.tools import generate_yayoi_evidence_campaign as gen
from accounting_converter.tools.yayoi_campaign_session import check_session
from accounting_converter.tools.yayoi_probe_check import manifest_path_for
from tests.test_yayoi_evidence_campaign import ACCOUNTS, buddies_like_context

HEADER = jdl_ibex_cashbook_official_journal_import_spec().column_names


def write(path: Path, rows) -> None:
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n").writerows((HEADER, *rows))
    path.write_bytes(buffer.getvalue().encode("cp932"))


def manual_row(marker: str, amount: str = "1080") -> list[str]:
    row = [""] * 30
    row[0], row[2], row[3], row[8], row[9], row[10], row[11] = "1111", "20260628", "8681", "仕　入", "8%", "内税", amount
    row[13], row[21], row[23] = "1111", amount, marker
    return row


class SessionCheckTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        ctx = buddies_like_context()
        names = {item.target_master_code: item.mapping_value for item in ctx.account_master}
        profile = gen._synthetic_profile(ctx)
        self.probes, self.rows = [], []
        for batch, cases in (
            ("A1", [gen.structural_case("SH-A", "t", [], (("NO", "S10"), ("NO", "S10")), ACCOUNTS)]),
            ("A3", [gen.structural_case("ROWS-3", "t", [], (("NO", "NO"),) * 3, ACCOUNTS)]),
        ):
            entries = [gen._entry(case, i, date(2026, 6, 28), names, profile, ctx) for i, case in enumerate(cases)]
            rows = [list(row) for row in gen.serialize(entries, ctx)]
            path = self.root / f"{batch}_NOT_FOR_PRODUCTION.csv"
            write(path, rows)
            manifest_path_for(path).write_text(json.dumps({"batch": batch, "cases": [
                {"case": case.case_id, "journal_index": i, "physical_rows": len(case.rows), "pending_evidence_id": "P"}
                for i, case in enumerate(cases)]}), encoding="utf-8")
            self.probes.append(path)
            self.rows += rows

    def tearDown(self):
        self._tmp.cleanup()

    def run_check(self, reexport_rows, expected_manual=("BM-RED8",)):
        path = self.root / "reexport.csv"
        write(path, reexport_rows)
        return check_session(path, self.probes, "BM-", list(expected_manual))

    def test_clean_session_with_hand_entered_example(self):
        result = self.run_check(self.rows + [manual_row("BM-RED8")])
        self.assertTrue(result["session_clean"])
        self.assertEqual(result["batches"]["A1"]["verdicts"], {"SH-A": "PASS"})
        self.assertEqual(result["manual_examples_found"], ["BM-RED8"])
        self.assertEqual(result["manual_examples_tax_literals"]["BM-RED8"][0]["debit"], ["仕　入", "8%", "内税"])

    def test_duplicate_import_is_detected(self):
        result = self.run_check(self.rows + self.rows[:2] + [manual_row("BM-RED8")])
        self.assertFalse(result["session_clean"])
        self.assertEqual(result["batches"]["A1"]["verdicts"]["SH-A"], "DUPLICATE")
        self.assertIn("SH-A", result["duplicate_markers"])

    def test_stray_journal_and_missing_example_are_reported(self):
        stray = manual_row("他の仕訳", "500")
        result = self.run_check(self.rows + [stray], expected_manual=("BM-RED8", "BM-EXPORT"))
        self.assertFalse(result["session_clean"])
        self.assertEqual(result["unexplained_reexport_journals"], 1)
        self.assertEqual(result["manual_examples_missing"], ["BM-EXPORT", "BM-RED8"])

    def test_a_rejected_file_shows_as_failed_cases_not_as_a_clean_session_of_others(self):
        result = self.run_check(self.rows[:2] + [manual_row("BM-RED8")])  # A3 never imported
        self.assertEqual(result["batches"]["A3"]["verdicts"], {"ROWS-3": "FAIL"})
        self.assertEqual(result["batches"]["A1"]["verdicts"], {"SH-A": "PASS"})


if __name__ == "__main__":
    unittest.main()


class GroupBObservationTest(unittest.TestCase):
    def row(self, marker, debit, credit, amount, debit_tax=("", "", ""), credit_tax=("", "", ""), tax="0"):
        row = [""] * 30
        row[0], row[2], row[3], row[13], row[11], row[21], row[23] = "1111", "20260628", debit, credit, amount, amount, marker
        row[8:11], row[18:21], row[12], row[22] = list(debit_tax), list(credit_tax), tax, "0"
        return row

    def test_only_entered_examples_are_used_and_pending_ones_are_never_observed(self):
        from accounting_converter.tools.yayoi_campaign_session import observed_group_b

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reexport.csv"
            write(path, [
                self.row("BM-EXPORT", "1111", "6121", "11000", credit_tax=("輸出売", "", "")),
                self.row("", "8471", "1111", "1100", debit_tax=("仕　入", "10%免80", "内税"), tax="80"),  # marker missing
                self.row("BM-NODED10", "8471", "1111", "1100", debit_tax=("仕　入", "10%", "内税"), tax="100"),
            ])
            observed = observed_group_b(path, "20260628")
        self.assertEqual(observed["BM-EXPORT"]["jdl_tax_scope"], "輸出売")
        self.assertEqual(observed["BM-TRANS80"]["identified_by"], "content_without_marker")
        self.assertEqual(observed["BM-TRANS80"]["jdl_tax_category"], "10%免80")
        self.assertEqual(observed["BM-RED8"]["status"], "MISSING")
        self.assertEqual(observed["BM-NODED10"]["status"], "PENDING_NOT_ENTERED_AS_INTENDED")
        self.assertTrue(observed["BM-NODED10"]["present_in_reexport"])
        self.assertEqual(observed["BM-CLOSING"]["status"], "PENDING_NOT_ENTERED_AS_INTENDED")


class PassedSettlesTest(SessionCheckTest):
    def test_only_cases_that_passed_settle_their_conditions(self):
        from accounting_converter.tools.yayoi_campaign_session import passed_settles

        for probe, settles in zip(self.probes, (["KEY:A"], ["KEY:ROWS"])):
            manifest = json.loads(manifest_path_for(probe).read_text(encoding="utf-8"))
            for case in manifest["cases"]:
                case["settles"] = settles
            manifest_path_for(probe).write_text(json.dumps(manifest), encoding="utf-8")
        reexport = self.root / "reexport.csv"
        write(reexport, self.rows[:2])  # only the A1 journal came back; A3 was rejected
        settled, summary = passed_settles([(reexport, self.probes)])
        self.assertEqual(settled, {"KEY:A"})
        self.assertEqual(summary, {"A1": "1/1", "A3": "0/1"})
