from __future__ import annotations

import csv
import io
import tempfile
import unittest
from pathlib import Path

from accounting_converter.adapters.input.moneyforward.observed_parser import MoneyForwardObservedParser
from accounting_converter.domain.journal_identity import stable_journal_identity
from accounting_converter.profiles.known_formats import MONEYFORWARD_JOURNAL_EXPORT_HEADER


def row(number: str, *, amount: str = "1100", description: str = "TEST") -> tuple[str, ...]:
    return (
        number, "2026/05/18",
        "仕入高", "", "", "", "課税仕入 10%", "", amount,
        "未払金", "", "", "", "対象外", "", amount,
        description, "", "",
    )


def write(path: Path, rows) -> Path:
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\n").writerows((MONEYFORWARD_JOURNAL_EXPORT_HEADER, *rows))
    path.write_bytes(buffer.getvalue().encode("cp932"))
    return path


def identity(path: Path) -> str:
    (entry,) = MoneyForwardObservedParser().parse_path(path)
    return stable_journal_identity(entry)


class StableJournalIdentityTest(unittest.TestCase):
    def test_file_name_and_transaction_number_do_not_change_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = identity(write(root / "仕訳帳_20261009_1130.csv", [row("1")]))
            renamed = identity(write(root / "仕訳帳_20261101_0900.csv", [row("1")]))
            renumbered = identity(write(root / "other.csv", [row("57")]))
        self.assertEqual(len(first), 64)
        self.assertEqual(first, renamed)
        self.assertEqual(first, renumbered)

    def test_content_changes_change_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = identity(write(root / "a.csv", [row("1")]))
            amount = identity(write(root / "b.csv", [row("1", amount="1200")]))
            description = identity(write(root / "c.csv", [row("1", description="OTHER")]))
        self.assertNotEqual(base, amount)
        self.assertNotEqual(base, description)


if __name__ == "__main__":
    unittest.main()
