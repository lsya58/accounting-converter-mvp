from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from accounting_converter.tools.generate_trade_partner_probe import compare_reexport


class MfJdlTradePartnerEvidenceTests(unittest.TestCase):
    ROOT = Path(__file__).parent / "evidence/e2e/mf_to_jdl_trade_partner_1d1c"

    def test_tracked_artifact_hashes_are_stable(self) -> None:
        expected = {}
        for line in (self.ROOT / "SHA256SUMS").read_text(encoding="ascii").splitlines():
            digest, name = line.split("  ", 1)
            expected[name] = digest
        actual = {
            name: hashlib.sha256((self.ROOT / name).read_bytes()).hexdigest()
            for name in expected
        }
        self.assertEqual(actual, expected)

    def test_real_import_reexport_strict_semantic_comparison_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for source, target in (
                ("generated_jdl.csv", "trade_partner_1d1c_with_subaccount.csv"),
                ("jdl_reexport.csv", "reexport.csv"),
            ):
                (root / target).write_bytes((self.ROOT / source).read_bytes())
            candidate_hash = hashlib.sha256(
                (root / "trade_partner_1d1c_with_subaccount.csv").read_bytes()
            ).hexdigest()
            (root / "trade_partner_1d1c_with_subaccount.manifest.json").write_text(
                json.dumps({
                    "probe_case": "trade_partner_1d1c_with_subaccount_description_rev2",
                    "candidate_sha256": candidate_hash,
                    "NOT_FOR_PRODUCTION": True,
                }),
                encoding="utf-8",
            )
            result = compare_reexport(root, root / "reexport.csv")
        self.assertTrue(result["comparison_pass"])
        self.assertEqual(result["mismatched_field_count"], 0)
        self.assertEqual(result["round_trip_status"], "VERIFIED_BY_REAL_IMPORT")


if __name__ == "__main__":
    unittest.main()
