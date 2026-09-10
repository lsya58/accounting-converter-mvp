from __future__ import annotations

import csv
import tempfile
import unittest
from io import StringIO
from pathlib import Path

from accounting_converter.diagnostics.yayoi_csv import (
    YayoiObservedSingleRecordParser,
    YayoiObservedSingleRecordParserError,
)
from accounting_converter.domain.journal import Side
from accounting_converter.profiles.yayoi_official import (
    yayoi_accounting_05_official_import_spec,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "yayoi"


class YayoiObservedSingleRecordParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = yayoi_accounting_05_official_import_spec()
        self.parser = YayoiObservedSingleRecordParser(self.spec)

    def test_parse_synthetic_multi_2000_records_to_common_journal_model(self) -> None:
        entries = self.parser.parse_path(
            FIXTURE_DIR / "ae19_observed_multi_synthetic.txt"
        )

        self.assertEqual(len(entries), 4)
        self.assertTrue(all(entry.metadata["production_adapter"] is False for entry in entries))
        self.assertTrue(all(entry.metadata["identifier_flags"] == ("2000",) for entry in entries))
        self.assertTrue(all(entry.is_balanced() for entry in entries))
        self.assertTrue(all(not entry.is_compound() for entry in entries))
        self.assertEqual(
            [line.side for line in entries[0].lines],
            [Side.DEBIT, Side.CREDIT],
        )
        self.assertIsNone(entries[0].description)
        self.assertIn(",", entries[3].description)
        self.assertIn('"', entries[3].description)

    def test_parse_debit_sub_account_and_blank_credit_sub_account(self) -> None:
        row = self._row(
            debit_sub_account="架空銀行補助",
            credit_sub_account="",
        )

        entries = self.parser.parse_text(self._csv_text([row]))

        self.assertEqual(len(entries), 1)
        debit, credit = entries[0].lines
        self.assertEqual(debit.sub_account, "架空銀行補助")
        self.assertIsNone(credit.sub_account)
        self.assertTrue(entries[0].is_balanced())
        self.assertFalse(entries[0].metadata["production_adapter"])

    def test_parse_subaccount_synthetic_fixture(self) -> None:
        entries = self.parser.parse_path(
            FIXTURE_DIR / "ae19_observed_subaccount_synthetic.txt"
        )

        self.assertEqual(len(entries), 1)
        debit, credit = entries[0].lines
        self.assertEqual(debit.sub_account, "架空補助A")
        self.assertIsNone(credit.sub_account)
        self.assertTrue(entries[0].is_balanced())

    def test_parse_debit_department_and_blank_credit_department(self) -> None:
        row = self._row(
            debit_department="架空部門A",
            credit_department="",
        )

        entries = self.parser.parse_text(self._csv_text([row]))

        self.assertEqual(len(entries), 1)
        debit, credit = entries[0].lines
        self.assertEqual(debit.department, "架空部門A")
        self.assertIsNone(credit.department)
        self.assertTrue(entries[0].is_balanced())
        self.assertFalse(entries[0].metadata["production_adapter"])

    def test_parse_department_synthetic_fixture(self) -> None:
        entries = self.parser.parse_path(
            FIXTURE_DIR / "ae19_observed_department_synthetic.txt"
        )

        self.assertEqual(len(entries), 1)
        debit, credit = entries[0].lines
        self.assertEqual(debit.department, "架空部門A")
        self.assertIsNone(credit.department)
        self.assertTrue(entries[0].is_balanced())

    def test_parse_credit_sub_account_and_credit_department(self) -> None:
        row = self._row(
            credit_sub_account="架空貸方補助",
            credit_department="架空貸方部門",
        )

        entries = self.parser.parse_text(self._csv_text([row]))

        self.assertEqual(len(entries), 1)
        debit, credit = entries[0].lines
        self.assertIsNone(debit.sub_account)
        self.assertIsNone(debit.department)
        self.assertEqual(credit.sub_account, "架空貸方補助")
        self.assertEqual(credit.department, "架空貸方部門")
        self.assertTrue(entries[0].is_balanced())
        self.assertFalse(entries[0].metadata["production_adapter"])

    def test_unknown_flag_blocks_without_silent_fallback(self) -> None:
        row = list(self._row())
        row[0] = "2999"

        with self.assertRaisesRegex(
            YayoiObservedSingleRecordParserError,
            "unsupported identifier flag",
        ):
            self.parser.parse_text(self._csv_text([tuple(row)]))

    def test_bad_column_count_blocks(self) -> None:
        row = self._row()[:-1]

        with self.assertRaisesRegex(
            YayoiObservedSingleRecordParserError,
            "expected 25",
        ):
            self.parser.parse_text(self._csv_text([row]))

    def test_unparseable_date_blocks(self) -> None:
        row = list(self._row())
        row[3] = "31/01/15"

        with self.assertRaisesRegex(
            YayoiObservedSingleRecordParserError,
            "unsupported date format",
        ):
            self.parser.parse_text(self._csv_text([tuple(row)]))

    def test_unparseable_amount_blocks(self) -> None:
        row = list(self._row())
        row[8] = "not-amount"

        with self.assertRaisesRegex(
            YayoiObservedSingleRecordParserError,
            "invalid DEBIT_amount",
        ):
            self.parser.parse_text(self._csv_text([tuple(row)]))

    def test_unbalanced_record_blocks(self) -> None:
        row = list(self._row())
        row[14] = "999"

        with self.assertRaisesRegex(
            YayoiObservedSingleRecordParserError,
            "not balanced",
        ):
            self.parser.parse_text(self._csv_text([tuple(row)]))

    def test_parser_requires_cp932_bytes_for_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "utf8.txt"
            path.write_text(self._csv_text([self._row()]), encoding="utf-8")

            with self.assertRaisesRegex(
                YayoiObservedSingleRecordParserError,
                "requires cp932",
            ):
                self.parser.parse_path(path)

    def _row(
        self,
        debit_sub_account: str = "",
        credit_sub_account: str = "",
        debit_department: str = "",
        credit_department: str = "",
    ) -> tuple[str, ...]:
        row = [""] * self.spec.column_count
        row[0] = "2000"
        row[1] = "1"
        row[3] = "H.31/01/15"
        row[4] = "架空借方科目"
        row[5] = debit_sub_account
        row[6] = debit_department
        row[7] = "架空税区分"
        row[8] = "1000"
        row[9] = "74"
        row[10] = "架空貸方科目"
        row[11] = credit_sub_account
        row[12] = credit_department
        row[13] = "架空対象外"
        row[14] = "1000"
        row[15] = "0"
        row[16] = "架空摘要"
        row[19] = "0"
        row[22] = "0"
        row[23] = "0"
        row[24] = "no"
        return tuple(row)

    def _csv_text(self, rows: list[tuple[str, ...]]) -> str:
        handle = StringIO()
        writer = csv.writer(handle, lineterminator="\r\n")
        writer.writerows(rows)
        return handle.getvalue()


if __name__ == "__main__":
    unittest.main()
