"""Regression: Yayoi company A Pilot-2 (174 journals / 434 rows, 2026-05-01..05-29) as imported into and
re-exported from real JDL on 2026-11-10 (private data only; skipped without it)."""
from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PILOT = Path("data/private/yayoi_buddies/pilot2")
STORE = PILOT / "verification_20261110" / "store_copy"
SOURCE = PILOT / "YAYOI_PILOT2_20260501_20260529.txt"
CANDIDATE = PILOT / "BUDDIES_PILOT2_20260501-0529_JDL_IMPORT.csv"
REEXPORT = PILOT / "BUDDIES_PILOT2_20260501-0529_JDL_REEXPORT.csv"
COMPANY = "company-f92affc1f3ed43c8aee36380ab612f9d"


@unittest.skipUnless(STORE.exists() and REEXPORT.exists(), "private data is not present")
class Pilot2RoundTripRegressionTest(unittest.TestCase):
    def setUp(self):
        from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
        from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore

        profiles = ConversionProfileStore(STORE / "profiles")
        self.resolved = CompanySettingStore(STORE / "companies", profiles).resolve(COMPANY)

    def test_the_app_still_writes_the_imported_bytes(self):
        from accounting_converter.application.jdl_description_trailing_space import EVIDENCE_PILOT2 as evidence
        from accounting_converter.application.yayoi_jdl_workflow import YayoiJdlWorkflow

        self.assertEqual(hashlib.sha256(CANDIDATE.read_bytes()).hexdigest(), evidence.candidate_sha256)
        self.assertEqual(hashlib.sha256(REEXPORT.read_bytes()).hexdigest(), evidence.reexport_sha256)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "regenerated.csv"
            workflow = YayoiJdlWorkflow()
            prepared = workflow.prepare(input_path=SOURCE, output_path=output, profile=self.resolved.profile,
                                        context=self.resolved.context, company_setting_validated=self.resolved.available)
            self.assertEqual(workflow.execute(prepared).status.value, "SUCCESS")
            self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), evidence.candidate_sha256)

    def test_exact_except_the_evidenced_trailing_spaces_pending_acceptance(self):
        from accounting_converter.application import jdl_description_trailing_space as trailing
        from accounting_converter.tools.yayoi_roundtrip_check import check

        result = check(SOURCE, self.resolved.profile, self.resolved.context, CANDIDATE, REEXPORT,
                       company_setting_id=COMPANY)
        self.assertEqual((result["source"], result["candidate"]),
                         ({"journals": 174, "physical_rows": 434}, {"journals": 174, "physical_rows": 434}))
        source = result["source_vs_candidate"]
        self.assertTrue(all(source[k] for k in ("journals_equal", "physical_rows_equal", "debit_total_equal",
                                                "credit_total_equal", "tax_total_equal")), source)
        for key in ("lines_account_subaccount_amount_tax_date", "row_descriptions", "journal_structure"):
            self.assertEqual(source[key], {"missing": 0, "extra": 0}, key)
        comparison = result["candidate_vs_reexport"]
        self.assertEqual(comparison["unexplained_differences"], 0)
        self.assertEqual(comparison["classification_counts"], {
            "EVIDENCED_DESCRIPTION_TRAILING_SPACE_REMOVED": 48, "EXPECTED_JDL_CANONICAL_NORMALIZATION": 2059})
        loss = result["description_trailing_space_loss"]
        self.assertEqual((loss["rows_count"], loss["journals_count"], loss["source_alignment"]), (48, 44, "PASS"))
        self.assertEqual(loss["removed_totals"], {"half_width_space": 64, "ideographic_space": 0})
        self.assertEqual({e["evidence_id"]: e["rows"] for e in loss["evidence_entries"]}, {
            trailing.EVIDENCE.evidence_id: 47, trailing.EVIDENCE_PILOT2.evidence_id: 1})
        self.assertEqual(loss["acceptance"], {"state": "NOT_RECORDED"})
        audit = result["information_not_in_jdl"]
        self.assertEqual((audit["verdict"], audit["expected_journals"], audit["expected_values"]), ("PASS", 70, 137))
        self.assertEqual(result["verdict"], "NORMALIZATION_ACCEPTANCE_PENDING")


if __name__ == "__main__":
    unittest.main()
