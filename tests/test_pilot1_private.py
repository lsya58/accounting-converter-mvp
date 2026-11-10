"""Regression: Yayoi company A Pilot-1 (207 journals / 465 rows) as imported into and re-exported from
real JDL on 2026-11-10 (private data only; skipped without it)."""
from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PILOT = Path("data/private/yayoi_buddies/pilot1")
STORE = PILOT / "verification_20261110" / "store_copy"
SOURCE = PILOT / "YAYOI_PILOT1_20251201_20251230.txt"
CANDIDATE = PILOT / "BUDDIES_PILOT1_20251201-1230_JDL_IMPORT.csv"
REEXPORT = PILOT / "BUDDIES_PILOT1_20251201-1230_JDL_REEXPORT.csv"
COMPANY = "company-f92affc1f3ed43c8aee36380ab612f9d"


@unittest.skipUnless(STORE.exists() and REEXPORT.exists(), "private data is not present")
class Pilot1RoundTripRegressionTest(unittest.TestCase):
    def setUp(self):
        from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
        from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore

        profiles = ConversionProfileStore(STORE / "profiles")
        self.resolved = CompanySettingStore(STORE / "companies", profiles).resolve(COMPANY)

    def test_the_app_still_writes_the_imported_bytes(self):
        from accounting_converter.application.jdl_description_trailing_space import EVIDENCE
        from accounting_converter.application.yayoi_jdl_workflow import YayoiJdlWorkflow

        self.assertEqual(hashlib.sha256(CANDIDATE.read_bytes()).hexdigest(), EVIDENCE.candidate_sha256)
        self.assertEqual(hashlib.sha256(REEXPORT.read_bytes()).hexdigest(), EVIDENCE.reexport_sha256)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "regenerated.csv"
            workflow = YayoiJdlWorkflow()
            prepared = workflow.prepare(input_path=SOURCE, output_path=output, profile=self.resolved.profile,
                                        context=self.resolved.context, company_setting_validated=self.resolved.available)
            self.assertEqual(workflow.execute(prepared).status.value, "SUCCESS")
            self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), EVIDENCE.candidate_sha256)

    def test_round_trip_is_exact_except_the_evidenced_trailing_spaces_pending_acceptance(self):
        from accounting_converter.tools.yayoi_roundtrip_check import check

        result = check(SOURCE, self.resolved.profile, self.resolved.context, CANDIDATE, REEXPORT,
                       company_setting_id=COMPANY)
        self.assertEqual(result["source"], {"journals": 207, "physical_rows": 465})
        self.assertEqual(result["candidate"], {"journals": 207, "physical_rows": 465})
        source = result["source_vs_candidate"]
        self.assertTrue(all(source[k] for k in ("journals_equal", "physical_rows_equal", "debit_total_equal",
                                                "credit_total_equal", "tax_total_equal")), source)
        for key in ("lines_account_subaccount_amount_tax_date", "row_descriptions", "journal_structure"):
            self.assertEqual(source[key], {"missing": 0, "extra": 0}, key)
        comparison = result["candidate_vs_reexport"]
        self.assertEqual((comparison["journals"], comparison["physical_rows"]), ([207, 207], [465, 465]))
        self.assertEqual(comparison["unexplained_differences"], 0)
        self.assertEqual(comparison["classification_counts"], {
            "EVIDENCED_DESCRIPTION_TRAILING_SPACE_REMOVED": 45, "EXPECTED_JDL_CANONICAL_NORMALIZATION": 2199})
        loss = result["description_trailing_space_loss"]
        self.assertTrue(loss["this_round_is_the_evidence_round"])
        self.assertEqual((loss["rows_count"], loss["journals_count"], loss["source_alignment"]), (45, 44, "PASS"))
        self.assertEqual(loss["removed_totals"], {"half_width_space": 62, "ideographic_space": 1})
        self.assertEqual(loss["acceptance"], {"state": "NOT_RECORDED"})
        audit = result["information_not_in_jdl"]
        self.assertEqual((audit["verdict"], audit["audit_found_by"], audit["expected_journals"],
                          audit["expected_values"]), ("PASS", "OUTPUT_SHA256", 95, 171))
        self.assertEqual(result["verdict"], "NORMALIZATION_ACCEPTANCE_PENDING")


if __name__ == "__main__":
    unittest.main()
