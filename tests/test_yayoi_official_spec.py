from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from accounting_converter.domain.journal import Side
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.profiles.yayoi_official import (
    DocumentedSpecificationStatus,
    yayoi_accounting_05_official_import_spec,
)

from tests.support.yayoi_official_parser import YayoiOfficialImportTestParser


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "yayoi"


class YayoiOfficialSpecificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = yayoi_accounting_05_official_import_spec()
        self.parser = YayoiOfficialImportTestParser(self.spec)

    def test_official_documented_spec_has_25_columns_and_flags(self) -> None:
        self.assertEqual(self.spec.column_count, 25)
        self.assertEqual(
            self.spec.column_names,
            (
                "識別フラグ",
                "伝票No.",
                "決算",
                "取引日付",
                "借方勘定科目",
                "借方補助科目",
                "借方部門",
                "借方税区分",
                "借方金額",
                "借方税金額",
                "貸方勘定科目",
                "貸方補助科目",
                "貸方部門",
                "貸方税区分",
                "貸方金額",
                "貸方税金額",
                "摘要",
                "番号",
                "期日",
                "タイプ",
                "生成元",
                "仕訳メモ",
                "付箋1",
                "付箋2",
                "調整",
            ),
        )
        self.assertEqual(
            self.spec.identifier_flags,
            ("2000", "2111", "2110", "2100", "2101"),
        )
        self.assertIn(
            DocumentedSpecificationStatus.OFFICIAL_DOCUMENTED,
            self.spec.statuses,
        )
        self.assertIn(
            DocumentedSpecificationStatus.REAL_DATA_VERIFICATION_PENDING,
            self.spec.statuses,
        )
        self.assertFalse(self.spec.is_formal_format_profile)
        self.assertNotIsInstance(self.spec, FormatProfile)

    def test_fixture_rows_are_25_columns_without_customer_data(self) -> None:
        fixture = FIXTURE_DIR / "official_import_demo.csv"
        rows = fixture.read_text(encoding="utf-8").splitlines()

        for row in rows:
            self.assertEqual(len(row.split(",")), 25)
        text = fixture.read_text(encoding="utf-8")
        self.assertIn("架空", text)
        self.assertNotIn("株式会社", text)

    def test_parser_converts_official_fixture_to_journal_entries(self) -> None:
        entries = self.parser.parse_path(FIXTURE_DIR / "official_import_demo.csv")

        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0].metadata["identifier_flags"], ("2000",))
        self.assertEqual(entries[1].metadata["identifier_flags"], ("2111",))
        self.assertEqual(
            entries[2].metadata["identifier_flags"],
            ("2110", "2100", "2101"),
        )
        self.assertTrue(all(entry.is_balanced() for entry in entries))

    def test_single_journal_preserves_sub_account_department_tax_and_empty_fields(self) -> None:
        entries = self.parser.parse_path(FIXTURE_DIR / "official_import_demo.csv")
        first = entries[0]
        debit = next(line for line in first.lines if line.side is Side.DEBIT)
        credit = next(line for line in first.lines if line.side is Side.CREDIT)

        self.assertEqual(debit.account, "売掛金")
        self.assertEqual(debit.sub_account, "PayPay")
        self.assertEqual(debit.department, "店舗A")
        self.assertEqual(debit.tax_info.category, "課税売上10%")
        self.assertEqual(debit.tax_info.tax_amount, Decimal("100"))
        self.assertEqual(credit.account, "売上高")
        self.assertIsNone(credit.sub_account)
        self.assertEqual(credit.department, "営業部")
        self.assertEqual(first.description, "架空売上")

    def test_multi_line_voucher_becomes_one_compound_journal_candidate(self) -> None:
        entries = self.parser.parse_path(FIXTURE_DIR / "official_import_demo.csv")
        compound = entries[2]

        self.assertTrue(compound.is_compound())
        self.assertEqual(len(compound.lines), 3)
        self.assertEqual(compound.debit_total(), Decimal("1000"))
        self.assertEqual(compound.credit_total(), Decimal("1000"))
        self.assertEqual(
            [line.account for line in compound.lines],
            ["旅費交通費", "消耗品費", "現金"],
        )
        self.assertEqual(compound.lines[1].tax_info.category, "課税仕入10%")
        self.assertEqual(compound.lines[1].tax_info.tax_amount, Decimal("36"))

    def test_parser_rejects_bad_column_count_without_silent_failure(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected 25"):
            self.parser.parse_text("2000,too,few\n")

    def test_parser_rejects_unclosed_multi_line_voucher_without_silent_failure(self) -> None:
        fixture_text = (FIXTURE_DIR / "official_import_demo.csv").read_text(
            encoding="utf-8"
        )
        broken = "\n".join(fixture_text.splitlines()[2:4])

        with self.assertRaisesRegex(ValueError, "not closed"):
            self.parser.parse_text(broken)


if __name__ == "__main__":
    unittest.main()
