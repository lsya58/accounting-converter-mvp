from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from accounting_converter.application.moneyforward_roundtrip import (
    MoneyForwardJdlRoundTripComparator,
    MoneyForwardRoundTripClassification,
)
from accounting_converter.profiles.jdl_official import (
    jdl_ibex_cashbook_official_journal_import_spec,
)


class MoneyForwardJdlRoundTripComparatorTests(unittest.TestCase):
    def test_exact_rows_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = self._write(root / "candidate.csv", [self._row()])
            reexport = self._write(root / "reexport.csv", [self._row()])
            report = MoneyForwardJdlRoundTripComparator().compare(candidate, reexport)

        self.assertTrue(report.passed)
        self.assertEqual(report.classification_counts, {"EXACT_PRESERVED": 1})

    def test_known_jdl_management_values_are_explicit_normalizations(self) -> None:
        before = self._row()
        after = self._row()
        after[1] = "42"
        after[5] = "現金正式"
        after[15] = "売上高正式"
        after[26] = "0"
        after[28] = "0"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = self._write(root / "candidate.csv", [before])
            reexport = self._write(root / "reexport.csv", [after])
            report = MoneyForwardJdlRoundTripComparator().compare(candidate, reexport)

        self.assertTrue(report.passed)
        self.assertEqual(
            report.classification_counts,
            {"EXPECTED_JDL_CANONICAL_NORMALIZATION": 5},
        )

    def test_tax_change_and_missing_row_fail(self) -> None:
        changed = self._row()
        changed[19] = "別税区分"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = self._write(
                root / "candidate.csv", [self._row(), self._row(date_value="20260102")]
            )
            reexport = self._write(root / "reexport.csv", [changed])
            report = MoneyForwardJdlRoundTripComparator().compare(candidate, reexport)

        self.assertFalse(report.passed)
        self.assertEqual(
            report.classification_counts,
            {"MISSING_ROW": 1, "UNEXPECTED_CHANGE": 2},
        )
        self.assertTrue(
            any(
                item.classification
                is MoneyForwardRoundTripClassification.UNEXPECTED_CHANGE
                and item.field == "credit_tax_category"
                for item in report.differences
            )
        )

    @staticmethod
    def _write(path: Path, rows: list[list[str]]) -> Path:
        header = jdl_ibex_cashbook_official_journal_import_spec().column_names
        with path.open("w", encoding="cp932", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\r\n")
            writer.writerow(header)
            writer.writerows(rows)
        return path

    @staticmethod
    def _row(*, date_value: str = "20260101") -> list[str]:
        return [
            "1111", "", date_value,
            "111", "現金", "", "", "", "", "", "", "1000", "0",
            "612", "売上高", "", "", "", "売上", "10%", "", "1000", "0",
            "TEST", "", "", "", "", "", "",
        ]
