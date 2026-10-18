from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from accounting_converter.tools.generate_2d2c_taxable_no_subaccount_probe import (
    compare_reexport,
)


class JdlTwoDebitTwoCreditTaxableNoSubaccountEvidenceTests(unittest.TestCase):
    ROOT = Path(__file__).parent / "evidence/e2e/jdl_2d2c_taxable_no_subaccount"

    def test_hashes_and_strict_roundtrip(self) -> None:
        expected = {}
        for line in (self.ROOT / "SHA256SUMS").read_text("ascii").splitlines():
            digest, name = line.split("  ", 1)
            expected[name] = digest
        self.assertEqual(
            {
                name: hashlib.sha256((self.ROOT / name).read_bytes()).hexdigest()
                for name in expected
            },
            expected,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate.csv"
            reexport = root / "reexport.csv"
            manifest = root / "manifest.json"
            candidate.write_bytes((self.ROOT / "generated_jdl.csv").read_bytes())
            reexport.write_bytes((self.ROOT / "jdl_reexport.csv").read_bytes())
            manifest.write_text(
                json.dumps(
                    {
                        "probe_case": "compound_2d2c_taxable_no_subaccount",
                        "candidate_sha256": hashlib.sha256(
                            candidate.read_bytes()
                        ).hexdigest(),
                        "NOT_FOR_PRODUCTION": True,
                    }
                ),
                encoding="utf-8",
            )
            result = compare_reexport(candidate, manifest, reexport)
        self.assertTrue(result["comparison_pass"])
        self.assertEqual(result["mismatch_field_categories"], [])
        self.assertEqual(result["evidence_level"], "VERIFIED_BY_REAL_IMPORT")


if __name__ == "__main__":
    unittest.main()
