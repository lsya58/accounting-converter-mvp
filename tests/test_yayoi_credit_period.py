import unittest
from datetime import date
from decimal import Decimal

from accounting_converter.application import yayoi_credit_period as cp
from accounting_converter.application.yayoi_review import candidate_semantic
from accounting_converter.domain.journal import (
    JournalEntry, JournalLine, Side, SourceReference, TaxInfo,
)


def entry(day, credit):
    ref = SourceReference("t", 1, "1")
    tax = TaxInfo(category=f"課対仕入10%｜区分記載｜{credit}", tax_amount=None,
                  metadata={"yayoi_purchase_credit": credit})
    return JournalEntry("e", ref, day, [
        JournalLine(Side.DEBIT, "A", Decimal(1000), ref, tax_info=tax),
        JournalLine(Side.CREDIT, "B", Decimal(1000), ref)])


class CreditPeriodTest(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(cp.applicable_ratio(date(2023, 9, 30)), None)
        self.assertEqual(cp.applicable_ratio(date(2023, 10, 1)), 80)
        self.assertEqual(cp.applicable_ratio(date(2026, 9, 30)), 80)
        self.assertEqual(cp.applicable_ratio(date(2026, 10, 1)), 70)
        self.assertEqual(cp.applicable_ratio(date(2028, 10, 1)), 50)
        self.assertEqual(cp.applicable_ratio(date(2030, 10, 1)), 30)
        self.assertEqual(cp.applicable_ratio(date(2031, 10, 1)), None)

    def test_mismatch_detection(self):
        self.assertFalse(cp.period_mismatch(entry(date(2026, 9, 30), "80%経過措置")))
        self.assertTrue(cp.period_mismatch(entry(date(2026, 10, 1), "80%経過措置")))
        self.assertFalse(cp.period_mismatch(entry(date(2026, 10, 1), "70%経過措置")))
        self.assertTrue(cp.period_mismatch(entry(date(2026, 9, 30), "70%経過措置")))

    def test_non_transitional_rows_ignored(self):
        for credit in ("100%", "控除不可", ""):
            self.assertFalse(cp.period_mismatch(entry(date(2027, 1, 1), credit)))

    def test_70_percent_has_no_jdl_candidate(self):
        self.assertIsNone(candidate_semantic("課対仕入10%｜区分記載｜70%経過措置"))
        self.assertIsNone(candidate_semantic("課対仕入10%｜適格｜70%経過措置"))
        self.assertIsNotNone(candidate_semantic("課対仕入10%｜区分記載｜80%経過措置"))
        self.assertIsNotNone(candidate_semantic("課対仕入10%｜適格｜100%"))
        self.assertIsNotNone(candidate_semantic("課対仕入8%（軽）｜適格｜100%"))
        self.assertIsNone(candidate_semantic("課対仕入10%｜区分記載｜控除不可"))


if __name__ == "__main__":
    unittest.main()
