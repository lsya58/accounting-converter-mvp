from __future__ import annotations

import unittest
from decimal import Decimal

from accounting_converter.tools.generate_yayoi_new_account_probes import cases, NEW_CODES


class NewAccountProbeTests(unittest.TestCase):
    def test_exact_twelve_case_allocation_and_balance(self) -> None:
        batch = cases("1111", "3181")
        self.assertEqual(len(batch), 12)
        self.assertEqual(len({item.case_id for item in batch}), 12)
        self.assertEqual({line.account for case in batch for row in case.rows for line in row if line and line.account in NEW_CODES}, NEW_CODES)
        self.assertTrue(all(case.shape == (1, 1, 1) for case in batch))
        for case in batch:
            debit, credit = case.rows[0]
            self.assertEqual(debit.amount, credit.amount)
            self.assertLessEqual(len(case.case_id), 32)
            case.case_id.encode("cp932", errors="strict")
        by_id = {item.case_id: item for item in batch}
        self.assertEqual(by_id["NA-S10-6122-FLOOR"].rows[0][1].explicit_tax, Decimal("100"))
        self.assertEqual(by_id["NA-S10-6124-COMPANY"].rows[0][1].explicit_tax, Decimal("101"))
        self.assertEqual(by_id["NA-P10-8672-COMPANY"].rows[0][0].explicit_tax, Decimal("101"))
