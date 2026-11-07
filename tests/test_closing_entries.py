"""Yayoi 本決 -> JDL 決算整理仕訳 (month-13 date), only in the proven scope and shapes. Synthetic data only."""
from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import unittest
from dataclasses import replace
from functools import partial
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from accounting_converter.adapters.output.jdl import JdlTaxRounding
from accounting_converter.application import closing_entries as ce
from accounting_converter.application.first_release_workflow import FirstReleaseReadiness
from accounting_converter.application.yayoi_jdl_workflow import (
    YayoiJournalReportJdlWorkflow,
    audit_path_for,
    verify_non_retained_audit,
)
from tests import test_yayoi_jdl_workflow as base
from tests.test_yayoi_jdl_workflow import OUTSIDE, YAYOI
from tests.test_yayoi_journal_report_parser import build, detail
from tests.test_yayoi_scoped_workflow import assess, make

YEAR_END = "令和08年07月31日"
JULY = ("令和08年07月01日", "令和08年07月31日")


def closing(day=YEAR_END, kind="本決", rows=1, credit_rows=0, voucher=1):
    out = [detail(day, voucher, debit=(YAYOI["fee"], "", OUTSIDE, 1000 * (1 + credit_rows), None),
                  credit=(YAYOI["cash"], "", OUTSIDE, 1000, None), description="決算1", number=voucher, closing=kind)]
    for k in range(2, rows + 1):
        out.append(detail(day, voucher, debit=(YAYOI["fee"], "", OUTSIDE, 1000, None),
                          credit=(YAYOI["cash"], "", OUTSIDE, 1000, None), description=f"決算{k}", number=voucher, closing=kind))
    for k in range(credit_rows):
        out.append(detail(day, voucher, credit=(YAYOI["cash"], "", OUTSIDE, 1000, None), description=f"決算C{k}",
                          number=voucher, closing=kind))
    return out


def fixture(directory, rows, **context_kwargs):
    with patch.object(base, "build", partial(build, period=JULY)):
        return make(directory, rows, **context_kwargs)


class ClosingTest(unittest.TestCase):
    def test_year_end_closing_is_written_with_the_month_13_date_and_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            f = fixture(directory, closing(rows=2))  # B2 対象外
            assessment, resolved = assess(f)
            self.assertEqual(assessment.blocker_counts(), {})
            workflow = YayoiJournalReportJdlWorkflow()
            output = Path(directory) / "out" / "jdl.csv"
            output.parent.mkdir()
            prepared = workflow.prepare(input_path=f.source, output_path=output, profile=resolved.profile,
                                        context=resolved.context, company_setting_validated=resolved.available)
            self.assertIs(prepared.summary.readiness, FirstReleaseReadiness.READY, prepared.summary.blocking_reasons)
            result = workflow.execute(prepared)
            self.assertEqual(result.status.value, "SUCCESS", [v.rule_id for v in result.validation_results])
            data = [r for r in csv.reader(io.StringIO(output.read_bytes().decode("cp932"))) if r and r[0].isdigit()]
            self.assertEqual([r[2] for r in data], ["20261331", "20261331"])
            self.assertEqual([r[0] for r in data], ["1110", "1101"])
            audit = json.loads(audit_path_for(output).read_text(encoding="utf-8"))
            record = audit["journals"][0]["closing_entry"]
            self.assertEqual((record["yayoi_closing"], record["source_date"], record["jdl_date"], record["evidence_id"]),
                             ("本決", "2026-07-31", "20261331", ce.EVIDENCE_ID))
            self.assertEqual(verify_non_retained_audit(f.source, output, resolved.profile, resolved.context)["verdict"], "PASS")

    def test_everything_unproven_stays_blocked(self):
        cases = {
            "interim 中決": (closing(kind="中決"), {}),
            "not the observed year end": (closing(day="令和08年07月30日"), {}),
            "B1C3 shape (4 rows) not imported": (closing(credit_rows=3), {}),
            "other rounding": (closing(), {"purchase": JdlTaxRounding.FLOOR}),
            "other row limit": (closing(), {"limit": 20}),
        }
        for name, (rows, settings) in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                assessment, _ = assess(fixture(directory, rows, **settings))
                self.assertIn("SYSTEM_EVIDENCE:CLOSING_ENTRY_REPRESENTATION", assessment.blocker_counts())
                self.assertEqual(assessment.ready_journals, 0)

    def test_the_b1c2_shape_of_journal_7531_is_proven(self):
        with tempfile.TemporaryDirectory() as directory:
            f = fixture(directory, closing(credit_rows=2))  # B1C2: 1 debit row with a credit, 2 credit-only rows
            assessment, resolved = assess(f)
            self.assertEqual(assessment.blocker_counts(), {})
            marked = ce.mark_closing(f.entries, resolved.profile, resolved.context)[0]
            self.assertEqual(marked.metadata[ce.EVIDENCE_KEY], ce.B1C2_EVIDENCE_ID)
            self.assertEqual(ce.audit_record(f.entries[0], resolved.profile, resolved.context)["evidence_id"],
                             ce.B1C2_EVIDENCE_ID)

    def test_an_ordinary_journal_keeps_its_date(self):
        with tempfile.TemporaryDirectory() as directory:
            f = fixture(directory, closing(kind=""))
            assessment, resolved = assess(f)
            self.assertEqual(assessment.blocker_counts(), {})
            self.assertEqual(ce.mark_closing(f.entries, resolved.profile, resolved.context)[0].metadata.get(ce.JDL_DATE_KEY), None)

    def test_the_output_stage_refuses_a_forged_closing_date(self):
        from accounting_converter.adapters.output.jdl.preflight import JdlOutputPreflight, jdl_ibex_35_5_output_profile

        with tempfile.TemporaryDirectory() as directory:
            f = fixture(directory, closing(kind=""))
            resolved = f.resolved()
            forged = replace(f.entries[0], metadata={**f.entries[0].metadata, ce.JDL_DATE_KEY: "20261331"})
            result = JdlOutputPreflight(resolved.context).evaluate([forged], jdl_ibex_35_5_output_profile())
            self.assertIn("JDL-OUT-CLOSING-DATE", [v.rule_id for v in result.validation_results])


if __name__ == "__main__":
    unittest.main()
