from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

from accounting_converter.adapters.input.moneyforward import MONEYFORWARD_OBSERVED_HEADER
from accounting_converter.application.moneyforward_ready_batch import (
    MoneyForwardReadyBatchAuditor,
)


class MoneyForwardReadyBatchAuditorTests(unittest.TestCase):
    def test_audit_groups_unsupported_patterns_without_private_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._write(
                Path(directory) / "source.csv",
                [
                    self._row("1", "2026/1/1"),
                    self._row("2", "2026/1/2", debit_amount="600", credit_amount="1000"),
                    self._row("2", "2026/1/2", debit="普通預金", debit_amount="400", credit="", credit_amount=""),
                ],
            )
            audit = MoneyForwardReadyBatchAuditor().audit(
                MoneyForwardReadyBatchAuditor().read(source)
            )

        self.assertEqual(audit.logical_journal_count, 2)
        self.assertEqual(audit.evidence_backed_count, 1)
        self.assertEqual(audit.unsupported_count, 1)
        self.assertEqual(len(audit.blocker_patterns), 1)
        self.assertEqual(
            audit.blocker_patterns[0].blocker_code,
            "MF-JDL-EVIDENCE-SCOPE-UNSUPPORTED-SHAPE-TAX-COMBINATION",
        )

    def test_candidates_exclude_unsupported_and_long_description_dates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._write(
                Path(directory) / "source.csv",
                [
                    self._row("1", "2026/1/1"),
                    self._row("2", "2026/1/2", description="A" * 33),
                    self._row("3", "2026/1/3"),
                ],
            )
            audit = MoneyForwardReadyBatchAuditor().audit(
                MoneyForwardReadyBatchAuditor().read(source)
            )

        self.assertEqual(
            [(item.start_date, item.end_date) for item in audit.batch_candidates],
            [(date(2026, 1, 3), date(2026, 1, 3)), (date(2026, 1, 1), date(2026, 1, 1))],
        )

    def test_extract_preserves_selected_journal_semantics_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._write(
                root / "source.csv",
                [self._row("1", "2026/1/1"), self._row("2", "2026/1/2")],
            )
            before = source.read_bytes()
            output = root / "candidate.csv"
            candidate = MoneyForwardReadyBatchAuditor().extract_candidate(
                source,
                output,
                start_date=date(2026, 1, 2),
                end_date=date(2026, 1, 2),
            )

            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(candidate.journal_count, 1)
            self.assertEqual(len(MoneyForwardReadyBatchAuditor().read(output)), 1)
            with self.assertRaises(FileExistsError):
                MoneyForwardReadyBatchAuditor().extract_candidate(
                    source,
                    output,
                    start_date=date(2026, 1, 2),
                    end_date=date(2026, 1, 2),
                )

    def test_extract_blocks_date_range_with_unsupported_journal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._write(
                root / "source.csv",
                [
                    self._row("1", "2026/1/1", debit_amount="600", credit_amount="1000"),
                    self._row("1", "2026/1/1", debit="普通預金", debit_amount="400", credit="", credit_amount=""),
                ],
            )
            with self.assertRaises(ValueError):
                MoneyForwardReadyBatchAuditor().extract_candidate(
                    source,
                    root / "candidate.csv",
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 1, 1),
                )

    @staticmethod
    def _write(path: Path, rows: list[list[str]]) -> Path:
        with path.open("w", encoding="cp932", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\r\n", quoting=csv.QUOTE_ALL)
            writer.writerow(MONEYFORWARD_OBSERVED_HEADER)
            writer.writerows(rows)
        return path

    @staticmethod
    def _row(
        number: str,
        value_date: str,
        *,
        debit: str = "現金",
        debit_amount: str = "1000",
        credit: str = "売上高",
        credit_amount: str = "1000",
        description: str = "TEST",
    ) -> list[str]:
        return [
            number,
            value_date,
            debit,
            "",
            "",
            "",
            "対象外" if debit else "",
            "",
            debit_amount,
            credit,
            "",
            "",
            "",
            "対象外" if credit else "",
            "",
            credit_amount,
            description,
            "",
            "",
        ]
