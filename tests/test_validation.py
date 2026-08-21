import unittest
from datetime import date
from decimal import Decimal

from accounting_converter.application.validation_pipeline import ValidationPipeline
from accounting_converter.domain.journal import (
    JournalEntry,
    JournalLine,
    Side,
    SourceReference,
)
from accounting_converter.domain.validation import (
    BalanceRule,
    Severity,
    UnsupportedCompoundStructureRule,
)


class ValidationTests(unittest.TestCase):
    def test_balance_error_blocks_export(self) -> None:
        source = SourceReference("sample.csv", row_number=1, source_journal_id="J1")
        entry = JournalEntry(
            id="J1",
            source_reference=source,
            date=date(2026, 8, 21),
            lines=[
                JournalLine(Side.DEBIT, "旅費交通費", Decimal("1000"), source),
                JournalLine(Side.CREDIT, "現金", Decimal("900"), source),
            ],
        )
        pipeline = ValidationPipeline([BalanceRule()])
        results = pipeline.validate([entry])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].severity, Severity.ERROR)
        self.assertFalse(pipeline.can_export(results))

    def test_compound_is_error_when_not_supported(self) -> None:
        source = SourceReference("sample.csv", row_number=1, source_journal_id="J2")
        entry = JournalEntry(
            id="J2",
            source_reference=source,
            date=date(2026, 8, 21),
            lines=[
                JournalLine(Side.DEBIT, "旅費交通費", Decimal("600"), source),
                JournalLine(Side.DEBIT, "消耗品費", Decimal("400"), source),
                JournalLine(Side.CREDIT, "現金", Decimal("1000"), source),
            ],
        )
        pipeline = ValidationPipeline([
            BalanceRule(),
            UnsupportedCompoundStructureRule(compound_supported=False),
        ])
        results = pipeline.validate([entry])

        self.assertTrue(any(r.rule_id == "VR-15" for r in results))
        self.assertFalse(pipeline.can_export(results))


if __name__ == "__main__":
    unittest.main()
