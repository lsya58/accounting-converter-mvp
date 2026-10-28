from __future__ import annotations

import json
import unittest
from pathlib import Path


class MfToJdlRealReadyBatchEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = (
            Path(__file__).parent
            / "evidence"
            / "e2e"
            / "mf_to_jdl_real_ready_batch_13j"
        )
        self.manifest = json.loads(
            (self.root / "manifest.json").read_text(encoding="utf-8")
        )

    def test_real_round_trip_is_verified(self) -> None:
        self.assertEqual(
            self.manifest["evidence_id"],
            "EVID-MF-JDL-REAL-READY-BATCH-13J-ROUNDTRIP-001",
        )
        self.assertEqual(
            self.manifest["system_evidence_status"],
            "VERIFIED_BY_REAL_IMPORT_AND_REEXPORT",
        )
        self.assertEqual(self.manifest["human_jdl_import"], "PASS")
        self.assertEqual(self.manifest["strict_semantic_comparison"], "PASS")

    def test_round_trip_invariants_are_frozen(self) -> None:
        self.assertEqual(self.manifest["logical_journal_count"], 13)
        self.assertEqual(self.manifest["physical_row_count"], 14)
        self.assertEqual(self.manifest["raw_diff_count"], 75)
        self.assertEqual(self.manifest["canonical_normalization_count"], 75)
        self.assertEqual(self.manifest["unexpected_diff_count"], 0)
        self.assertEqual(self.manifest["silent_loss_count"], 0)
        for key, value in self.manifest.items():
            if key.endswith("_mismatch_count"):
                self.assertEqual(value, 0, key)
        self.assertEqual(self.manifest["pattern_results"]["P05"], "5/5 PASS")
        self.assertEqual(self.manifest["pattern_results"]["P06"], "2/2 PASS")
        self.assertEqual(self.manifest["pattern_results"]["P07"], "2/2 PASS")
        self.assertEqual(
            self.manifest["pattern_results"]["P01_TO_P07"], "13/13 PASS"
        )

    def test_human_replacement_and_private_boundary_are_frozen(self) -> None:
        self.assertEqual(
            self.manifest["human_confirmed_description_replacement_count"], 1
        )
        self.assertEqual(
            self.manifest[
                "human_confirmed_description_replacement_affected_journal_count"
            ],
            2,
        )
        self.assertFalse(self.manifest["raw_customer_data_tracked"])
        self.assertEqual(
            {path.name for path in self.root.iterdir()},
            {"README.md", "manifest.json"},
        )
        self.assertFalse(tuple(self.root.glob("*.csv")))


if __name__ == "__main__":
    unittest.main()
