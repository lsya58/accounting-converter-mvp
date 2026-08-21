import unittest
from datetime import date
from decimal import Decimal

from accounting_converter.domain.journal import (
    JournalEntry,
    JournalLine,
    Side,
    SourceReference,
)


class JournalEntryTests(unittest.TestCase):
    def test_balanced_simple_journal(self) -> None:
        source = SourceReference("sample.csv", row_number=1, source_journal_id="J1")
        entry = JournalEntry(
            id="J1",
            source_reference=source,
            date=date(2026, 8, 21),
            lines=[
                JournalLine(Side.DEBIT, "旅費交通費", Decimal("1000"), source),
                JournalLine(Side.CREDIT, "現金", Decimal("1000"), source),
            ],
        )

        self.assertTrue(entry.is_balanced())
        self.assertFalse(entry.is_compound())

    def test_compound_journal(self) -> None:
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

        self.assertTrue(entry.is_balanced())
        self.assertTrue(entry.is_compound())


if __name__ == "__main__":
    unittest.main()
