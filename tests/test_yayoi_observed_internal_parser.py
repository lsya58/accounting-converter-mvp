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

    def test_parse_observed_2111_single_record(self) -> None:
        row = self._row(flag="2111")

        entries = self.parser.parse_text(self._csv_text([row]))

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].metadata["identifier_flags"], ("2111",))
        self.assertTrue(entries[0].is_balanced())
        self.assertFalse(entries[0].is_compound())
        self.assertFalse(entries[0].metadata["production_adapter"])

    def test_parse_observed_multi_record_voucher_group(self) -> None:
        rows = [
            self._row(flag="2110", voucher="9", debit_amount="1000", credit_account="", credit_amount="0", description=""),
            self._row(flag="2100", voucher="9", debit_amount="2000", credit_account="", credit_amount="0", description=""),
            self._row(flag="2101", voucher="9", debit_account="", debit_amount="0", credit_amount="3000"),
        ]

        entries = self.parser.parse_text(self._csv_text(rows))

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].metadata["identifier_flags"], ("2110", "2100", "2101"))
        self.assertEqual(entries[0].metadata["grouping_basis"], "OBSERVED_MULTI_RECORD_SEQUENCE")
        self.assertTrue(entries[0].is_compound())
        self.assertTrue(entries[0].is_balanced())
        self.assertEqual(len(entries[0].lines), 3)
        self.assertEqual(sum(1 for line in entries[0].lines if line.side is Side.DEBIT), 2)
        self.assertEqual(sum(1 for line in entries[0].lines if line.side is Side.CREDIT), 1)
        self.assertFalse(entries[0].metadata["production_adapter"])

    def test_unclosed_multi_record_voucher_blocks(self) -> None:
        row = self._row(flag="2110")

        with self.assertRaisesRegex(
            YayoiObservedSingleRecordParserError,
            "not closed by 2101",
        ):
            self.parser.parse_text(self._csv_text([row]))

    def test_multi_record_voucher_mismatched_voucher_blocks(self) -> None:
        rows = [
            self._row(flag="2110", voucher="9", debit_amount="1000", credit_account="", credit_amount="0", description=""),
            self._row(flag="2100", voucher="10", debit_amount="2000", credit_account="", credit_amount="0", description=""),
            self._row(flag="2101", voucher="9", debit_account="", debit_amount="0", credit_amount="3000"),
        ]

        with self.assertRaisesRegex(
            YayoiObservedSingleRecordParserError,
            "inconsistent voucher number",
        ):
            self.parser.parse_text(self._csv_text(rows))

    def test_multi_record_voucher_mismatched_date_blocks(self) -> None:
        rows = [
            self._row(flag="2110", date_value="H.31/01/15", debit_amount="1000", credit_account="", credit_amount="0", description=""),
            self._row(flag="2100", date_value="H.31/01/16", debit_amount="2000", credit_account="", credit_amount="0", description=""),
            self._row(flag="2101", date_value="H.31/01/15", debit_account="", debit_amount="0", credit_amount="3000"),
        ]

        with self.assertRaisesRegex(
            YayoiObservedSingleRecordParserError,
            "inconsistent date",
        ):
            self.parser.parse_text(self._csv_text(rows))

    def test_multi_record_voucher_unbalanced_blocks(self) -> None:
        rows = [
            self._row(flag="2110", debit_amount="1000", credit_account="", credit_amount="0", description=""),
            self._row(flag="2100", debit_amount="2000", credit_account="", credit_amount="0", description=""),
            self._row(flag="2101", debit_account="", debit_amount="0", credit_amount="2999"),
        ]

        with self.assertRaisesRegex(
            YayoiObservedSingleRecordParserError,
            "not balanced",
        ):
            self.parser.parse_text(self._csv_text(rows))

    def test_multi_record_voucher_unexpected_middle_flag_blocks(self) -> None:
        rows = [
            self._row(flag="2110", debit_amount="1000", credit_account="", credit_amount="0", description=""),
            self._row(flag="2111", debit_amount="2000", credit_account="", credit_amount="0", description=""),
            self._row(flag="2101", debit_account="", debit_amount="0", credit_amount="3000"),
        ]

        with self.assertRaisesRegex(
            YayoiObservedSingleRecordParserError,
            "unexpected flag",
        ):
            self.parser.parse_text(self._csv_text(rows))

    def test_multi_record_voucher_multiple_middle_rows_blocks_until_observed(self) -> None:
        rows = [
            self._row(flag="2110", voucher="9", debit_amount="1000", credit_account="", credit_amount="0", description=""),
            self._row(flag="2100", voucher="9", debit_amount="1000", credit_account="", credit_amount="0", description=""),
            self._row(flag="2100", voucher="9", debit_amount="1000", credit_account="", credit_amount="0", description=""),
            self._row(flag="2101", voucher="9", debit_account="", debit_amount="0", credit_amount="3000"),
        ]

        with self.assertRaisesRegex(
            YayoiObservedSingleRecordParserError,
            "unsupported flag sequence",
        ):
            self.parser.parse_text(self._csv_text(rows))

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
        flag: str = "2000",
        voucher: str = "1",
        date_value: str = "H.31/01/15",
        debit_account: str = "架空借方科目",
        debit_sub_account: str = "",
        debit_department: str = "",
        debit_amount: str = "1000",
        credit_account: str = "架空貸方科目",
        credit_sub_account: str = "",
        credit_department: str = "",
        credit_amount: str = "1000",
        description: str = "架空摘要",
    ) -> tuple[str, ...]:
        row = [""] * self.spec.column_count
        row[0] = flag
        row[1] = voucher
        row[3] = date_value
        row[4] = debit_account
        row[5] = debit_sub_account
        row[6] = debit_department
        row[7] = "架空税区分"
        row[8] = debit_amount
        row[9] = "74"
        row[10] = credit_account
        row[11] = credit_sub_account
        row[12] = credit_department
        row[13] = "架空対象外"
        row[14] = credit_amount
        row[15] = "0"
        row[16] = description
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
