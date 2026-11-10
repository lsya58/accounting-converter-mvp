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

    def test_exact_scoped_numeric_subaccount_normalization_passes(self) -> None:
        before = self._row()
        before[13:18] = ["3181", "未払金", "未払金", "0001", "SYNTHETIC-SUBACCOUNT"]
        after = list(before)
        after[16] = "1"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = self._write(root / "candidate.csv", [before])
            reexport = self._write(
                root / "reexport.csv",
                [after],
                preamble=("// company", "// 出力期間 ： 20260101 ～ 20260101"),
            )
            report = MoneyForwardJdlRoundTripComparator(
                numeric_subaccount_normalizations=frozenset({
                    ("CREDIT", "3181", "0001", "SYNTHETIC-SUBACCOUNT")
                })
            ).compare(candidate, reexport)

        self.assertTrue(report.passed)
        self.assertEqual(
            report.classification_counts,
            {"EXPECTED_JDL_CANONICAL_NORMALIZATION": 1},
        )

    def test_numeric_subaccount_normalization_is_not_generalized(self) -> None:
        before = self._row()
        before[13:18] = ["3181", "未払金", "未払金", "0001", "SYNTHETIC-SUBACCOUNT"]
        after = list(before)
        after[16] = "1"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = self._write(root / "candidate.csv", [before])
            reexport = self._write(root / "reexport.csv", [after])
            report = MoneyForwardJdlRoundTripComparator().compare(candidate, reexport)

        self.assertFalse(report.passed)
        self.assertEqual(report.classification_counts, {"UNEXPECTED_CHANGE": 1})

    def test_trailing_space_removal_is_evidenced_loss_only_when_enabled(self) -> None:
        from accounting_converter.application.jdl_description_trailing_space import EVIDENCES

        observed = frozenset().union(*(item.observed_suffixes for item in EVIDENCES))

        cases = [("TEST  ", "TEST"), ("TEST ", "TEST"), ("TEST\u3000", "TEST"), ("TEST   ", "TEST")]
        for before_text, after_text in cases:
            before, after = self._row(), self._row()
            before[23], after[23] = before_text, after_text
            with self.subTest(before=before_text), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                candidate = self._write(root / "candidate.csv", [before])
                reexport = self._write(root / "reexport.csv", [after])
                enabled = MoneyForwardJdlRoundTripComparator(
                    description_trailing_space_suffixes=observed).compare(candidate, reexport)
                disabled = MoneyForwardJdlRoundTripComparator().compare(candidate, reexport)
            self.assertTrue(enabled.passed)
            self.assertEqual(enabled.information_loss_rows, (1,))
            self.assertEqual(enabled.classification_counts, {"EVIDENCED_DESCRIPTION_TRAILING_SPACE_REMOVED": 1})
            self.assertFalse(disabled.passed)
            self.assertEqual(disabled.classification_counts, {"UNEXPECTED_CHANGE": 1})

    def test_other_space_changes_are_never_the_trailing_space_evidence(self) -> None:
        from accounting_converter.application.jdl_description_trailing_space import EVIDENCES

        observed = frozenset().union(*(item.observed_suffixes for item in EVIDENCES))

        cases = [
            (" TEST", "TEST"),            # leading
            ("TE ST", "TEST"),            # inner
            ("TEST    ", "TEST"),         # four half-width spaces: not observed
            ("TEST     ", "TEST"),        # five
            ("TEST\u3000\u3000\u3000", "TEST"),  # three ideographic spaces
            ("TEST   ", "TEST "),         # three, only two removed
            ("TEST   ", "TEST  "),        # three, only one removed
            ("TE   ST   ", "TEST"),       # inner spaces removed as well
            (" TEST   ", "TEST"),         # leading space removed as well
            ("TEST \t ", "TEST"),         # tab inside the run
            ("TEST\t", "TEST"),           # tab
            ("TEST \u3000", "TEST"),      # mixed run: not observed
            ("TEST\u3000\u3000", "TEST"),  # two ideographic spaces: not observed
            ("TEST  ", "TEST "),          # only part of the run removed
            ("  ", ""),                   # nothing left
            ("TEST ", "TESX"),            # text changed too
            ("TEST", "TEST "),            # space added
        ]
        for before_text, after_text in cases:
            before, after = self._row(), self._row()
            before[23], after[23] = before_text, after_text
            with self.subTest(before=before_text, after=after_text), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                candidate = self._write(root / "candidate.csv", [before])
                reexport = self._write(root / "reexport.csv", [after])
                report = MoneyForwardJdlRoundTripComparator(
                    description_trailing_space_suffixes=observed).compare(candidate, reexport)
            self.assertFalse(report.passed)
            self.assertEqual(report.information_loss_rows, ())
            self.assertEqual(report.classification_counts, {"UNEXPECTED_CHANGE": 1})

    def test_trailing_space_evidence_does_not_hide_another_column_change(self) -> None:
        from accounting_converter.application.jdl_description_trailing_space import EVIDENCES

        observed = frozenset().union(*(item.observed_suffixes for item in EVIDENCES))

        before, after = self._row(), self._row()
        before[23], after[23] = "TEST ", "TEST"
        after[19] = "別税区分"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = MoneyForwardJdlRoundTripComparator(
                description_trailing_space_suffixes=observed).compare(
                self._write(root / "c.csv", [before]), self._write(root / "r.csv", [after]))
        self.assertFalse(report.passed)
        self.assertEqual(report.classification_counts,
                         {"EVIDENCED_DESCRIPTION_TRAILING_SPACE_REMOVED": 1, "UNEXPECTED_CHANGE": 1})

    @staticmethod
    def _write(
        path: Path,
        rows: list[list[str]],
        *,
        preamble: tuple[str, ...] = (),
    ) -> Path:
        header = jdl_ibex_cashbook_official_journal_import_spec().column_names
        with path.open("w", encoding="cp932", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\r\n")
            for value in preamble:
                writer.writerow([value])
            if preamble:
                writer.writerow([])
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
