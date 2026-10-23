from __future__ import annotations

import json
import unittest
from pathlib import Path


class JdlToJdlRealBatchEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = (
            Path(__file__).parent
            / "evidence"
            / "e2e"
            / "jdl_to_jdl_real_batch"
        )
        self.manifest = json.loads(
            (self.root / "manifest.json").read_text(encoding="utf-8")
        )

    def test_real_import_and_accounting_review_are_separate_states(self) -> None:
        self.assertEqual(
            self.manifest["evidence_id"],
            "EVID-JDL-TO-JDL-REAL-BATCH-1158-IMPORT-001",
        )
        self.assertEqual(
            self.manifest["system_evidence_status"], "VERIFIED_BY_REAL_IMPORT"
        )
        self.assertEqual(
            self.manifest["accounting_review_status"],
            "HUMAN_ACCOUNTING_REVIEW_PENDING",
        )

    def test_batch_invariants_are_frozen(self) -> None:
        self.assertEqual(self.manifest["logical_journal_count"], 1158)
        self.assertEqual(self.manifest["physical_row_count"], 1271)
        self.assertEqual(self.manifest["tax_row_counts"]["total"], 544)
        self.assertEqual(self.manifest["canonical_normalization_count"], 8)
        self.assertEqual(self.manifest["description_replacement_count"], 2)
        self.assertEqual(self.manifest["unexpected_diff_count"], 0)
        self.assertEqual(self.manifest["silent_loss_count"], 0)
        self.assertEqual(self.manifest["formal_output_audit"], "PASS")
        self.assertEqual(self.manifest["strict_reparse"], "PASS")
        self.assertEqual(self.manifest["human_jdl_import"], "PASS")

    def test_evidence_folder_contains_no_customer_csv(self) -> None:
        self.assertFalse(self.manifest["raw_customer_data_tracked"])
        self.assertEqual(
            {path.name for path in self.root.iterdir()},
            {"README.md", "manifest.json"},
        )
        self.assertFalse(tuple(self.root.glob("*.csv")))


if __name__ == "__main__":
    unittest.main()
