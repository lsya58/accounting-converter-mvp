"""Regression: company A READY-only output (2,480 journals / 6,102 rows, Windows EXE, 2026-11-11) as imported into
and re-exported from real JDL with 「決算整理を含む」 (private data only; skipped without it).

The output was written before voucher 1240 became BLOCK (2026-11-11): the round-trip record of these files is kept
as it was (FAIL), and the files no longer pass the READY-only verification against the current diagnosis.

The audit's journal scope names the source file, so the source is checked under the name the EXE read
(バディーズCSV.txt, same bytes as source.txt) in a temporary copy. Nothing in data/private is written.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path("data/private/yayoi_buddies")
SOURCE = ROOT / "source.txt"
SOURCE_NAME_IN_EXE = "バディーズCSV.txt"
FOLDER = ROOT / "ready_only_2480"
CANDIDATE = FOLDER / "BUDDIES_READY_ONLY_2480_20250801-20260731_JDL_IMPORT.csv"
REEXPORT = FOLDER / "BUDDIES_READY_ONLY_2480_JDL_REEXPORT.csv"
STORE = ROOT / "pilot2" / "verification_20261110" / "store_copy"
COMPANY = "company-f92affc1f3ed43c8aee36380ab612f9d"
SHA256 = {
    SOURCE: "7ab406cb9d0c88b3ecac07e55d2586808bdd4e2368df058aeb014e623d0c14a8",
    CANDIDATE: "2032c1450bf51debe485d7b7bd2459f6eef24f4d52d63737e78718b4e56af45b",
    REEXPORT: "95ef5e4fb40e327a7facda6d97900da0442216c0e99ad6c1735daa91fdacd79b",
}


@unittest.skipUnless(all(path.exists() for path in (SOURCE, CANDIDATE, REEXPORT, STORE)), "private data is not present")
class ReadyOnly2480ReexportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import json

        from accounting_converter.application import yayoi_ready_only as ro
        from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
        from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
        from accounting_converter.tools.yayoi_roundtrip_check import check

        cls._directory = tempfile.TemporaryDirectory()
        source = Path(cls._directory.name) / SOURCE_NAME_IN_EXE
        shutil.copyfile(SOURCE, source)
        resolved = CompanySettingStore(STORE / "companies", ConversionProfileStore(STORE / "profiles")).resolve(COMPANY)
        cls.verification = ro.verify_ready_only_output(source, CANDIDATE, resolved.profile, resolved.context, COMPANY)
        manifest = json.loads(ro.manifest_path_for(CANDIDATE).read_text(encoding="utf-8"))
        ids = ro.ready_ids_from_manifest(manifest, source, resolved.profile)
        cls.result = check(source, resolved.profile, resolved.context, CANDIDATE, REEXPORT, journal_ids=ids,
                           company_setting_id=COMPANY)

    @classmethod
    def tearDownClass(cls):
        cls._directory.cleanup()

    def test_files_are_the_verified_ones_and_no_longer_the_current_diagnosis(self):
        for path, digest in SHA256.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest, path.name)
        # The four files are still bound to each other and to the source ...
        checks = self.verification["checks"]
        for key in ("schema_and_mode", "source_sha256", "output_sha256", "excluded_list_sha256", "audit_bound",
                    "counts_add_up", "follow_up_notes", "csv_rows"):
            self.assertTrue(checks[key], key)
        self.assertEqual(self.verification["audit_verdict"], "PASS")
        # ... but since voucher 1240's written tax 0 is BLOCK (EXPLICIT_TAX_ZERO_UNVERIFIED), this 2,480 output is not
        # what the app would write now: it fails closed (2026-11-11). The record stays as it was.
        self.assertEqual(self.verification["verdict"], "FAIL")
        self.assertFalse(checks["current_diagnosis_matches"])
        self.assertFalse(checks["ready_rows_equal"])

    def test_source_to_candidate_and_audit(self):
        result = self.result
        self.assertEqual((result["source"], result["candidate"]),
                         ({"journals": 2480, "physical_rows": 6102}, {"journals": 2480, "physical_rows": 6102}))
        source = result["source_vs_candidate"]
        for key in ("lines_account_subaccount_amount_tax_date", "row_descriptions", "journal_structure"):
            self.assertEqual(source[key], {"missing": 0, "extra": 0}, key)
        audit = result["information_not_in_jdl"]
        self.assertEqual((audit["verdict"], audit["expected_journals"], audit["expected_values"]), ("PASS", 1176, 2397))

    def test_the_nine_closing_rows_are_read_and_kept_as_month13(self):
        closing = self.result["closing_entries"]
        self.assertEqual(closing["verdict"], "PASS", closing)
        self.assertEqual(closing["journals"], 6)
        self.assertEqual(closing["rows_expected"], {"20261331": 9})
        self.assertEqual(closing["candidate_rows"], {"20261331": 9})
        self.assertEqual(closing["reexport_rows"], {"20261331": 9})

    def test_the_one_yen_tax_change_of_voucher_1240_stays_unexplained(self):
        comparison = self.result["candidate_vs_reexport"]
        self.assertEqual((comparison["journals"], comparison["physical_rows"]), ([2480, 2480], [6102, 6102]))
        self.assertEqual(comparison["classification_counts"], {
            "EVIDENCED_DESCRIPTION_TRAILING_SPACE_REMOVED": 588,
            "EXPECTED_JDL_CANONICAL_NORMALIZATION": 28785,
            "UNEXPECTED_CHANGE": 1})
        self.assertEqual(comparison["first_failures"],
                         [{"row": 2766, "field": "credit_tax_amount", "classification": "UNEXPECTED_CHANGE"}])
        self.assertFalse(comparison["strict_passed"])
        self.assertFalse(comparison["passed_with_evidenced_information_loss"])
        self.assertEqual(self.result["verdict_jdl_roundtrip"], "FAIL")
        self.assertEqual(self.result["verdict"], "FAIL")
        self.assertNotIn("description_trailing_space_loss", self.result)  # no acceptance path while it fails


if __name__ == "__main__":
    unittest.main()
