from __future__ import annotations

import json
import unittest
from pathlib import Path


class MfSales10EvidenceScopeTest(unittest.TestCase):
    def test_real_roundtrip_is_exact_and_not_production_activated(self) -> None:
        path = Path(__file__).parent / "evidence/e2e/mf_tax_sales10_excluded_proportional_cash/manifest.json"
        evidence = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(evidence["status"], "VERIFIED_BY_REAL_IMPORT_AND_REEXPORT")
        self.assertFalse(evidence["production_activation"])
        self.assertEqual(evidence["shape"], "1D1C")
        self.assertEqual(
            (evidence["debit_account_code"], evidence["debit_subaccount_code"],
             evidence["credit_account_code"], evidence["credit_subaccount_code"],
             evidence["trade_partner"]),
            ("1111", "", "6121", "", False),
        )
        self.assertEqual(evidence["credit_tax"], ["売　上", "10%", "外税", "100"])
        self.assertEqual(evidence["rejected_current_context_literal"], "売一種")
        self.assertEqual(evidence["current_482_exact_matches"], 0)
        self.assertEqual(evidence["strict_result"]["unexpected_diff"], 0)


if __name__ == "__main__":
    unittest.main()
