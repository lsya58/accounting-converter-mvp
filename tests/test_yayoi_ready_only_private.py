"""Regression: READY-only output of Yayoi company A's 2,514 journals (private data only; skipped without it).

Output goes to a temporary directory that is deleted afterwards; the saved settings are a private copy."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SOURCE = Path("data/private/yayoi_buddies/source.txt")
STORE = Path("data/private/yayoi_buddies/pilot2/verification_20261110/store_copy")
PILOTS = (
    (Path("data/private/yayoi_buddies/pilot1/BUDDIES_PILOT1_20251201-1230_JDL_IMPORT.csv"), b"20251201", b"20251230"),
    (Path("data/private/yayoi_buddies/pilot2/BUDDIES_PILOT2_20260501-0529_JDL_IMPORT.csv"), b"20260501", b"20260529"),
)
COMPANY = "company-f92affc1f3ed43c8aee36380ab612f9d"
# BLOCK33 of docs/development/yayoi_buddies_block33_plan.md, plus 7519 (本決 with negative amounts, which the JDL
# output refuses; READY until the diagnosis checked amounts the way the output does).
EXCLUDED_ROWS = [425, 462, 503, 565, 1031, 1094, 1287, 1739, 1805, 2329, 2384, 2986, 3032, 3109, 3482, 3558, 3569,
                 3605, 4012, 4117, 4163, 4700, 4873, 5426, 5445, 5545, 6075, 6100, 6594, 6621, 7246, 7265, 7420, 7519]


def _data_rows(path: Path):
    return [line for line in path.read_bytes().split(b"\r\n") if line[:1].isdigit()]


@unittest.skipUnless(SOURCE.exists() and STORE.exists(), "private data is not present")
class CompanyAReadyOnlyTest(unittest.TestCase):
    def test_2480_written_34_listed_and_the_pilot_rows_unchanged(self):
        from accounting_converter.application import yayoi_ready_only as ro
        from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
        from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
        from accounting_converter.tools.yayoi_roundtrip_check import check

        resolved = CompanySettingStore(STORE / "companies", ConversionProfileStore(STORE / "profiles")).resolve(COMPANY)
        plan = ro.plan_ready_only(SOURCE, resolved.profile, resolved.context, COMPANY)
        self.assertTrue(plan.available, plan.problems)
        self.assertEqual((plan.total_journals, plan.ready_count, plan.excluded_count), (2514, 2480, 34))
        self.assertEqual([item.source_row for item in plan.excluded], EXCLUDED_ROWS)
        self.assertIn("HUMAN:NEGATIVE_AMOUNT", plan.excluded[-1].blockers)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "ready_only.csv"
            confirmation = ro.ReadyOnlyConfirmation(plan.fingerprint, plan.ready_count, plan.excluded_count, "試験",
                                                    True, True, True)
            prepared = ro.prepare_ready_only(plan, confirmation, input_path=SOURCE, output_path=output,
                                             profile=resolved.profile, context=resolved.context,
                                             company_setting_validated=resolved.available)
            result = ro.execute_ready_only(prepared, plan, confirmation)
            self.assertEqual((result.status, result.output_journals, result.output_vouchers, result.output_rows),
                             ("SUCCESS", 2480, 2480, 6102))
            self.assertEqual(ro.verify_ready_only_output(SOURCE, output, resolved.profile, resolved.context,
                                                         COMPANY)["verdict"], "PASS")
            report = check(SOURCE, resolved.profile, resolved.context, output, None,
                           journal_ids=frozenset(plan.ready_ids))
            self.assertEqual(report["verdict"], "SOURCE_TO_CSV_PASS_REEXPORT_PENDING")
            self.assertEqual(report["information_not_in_jdl"]["verdict"], "PASS")
            rows = _data_rows(output)
            for pilot, first, last in PILOTS:
                if pilot.exists():
                    self.assertEqual([r for r in rows if first <= r.split(b",")[2] <= last], _data_rows(pilot))


if __name__ == "__main__":
    unittest.main()
