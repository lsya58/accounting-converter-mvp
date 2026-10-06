from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from accounting_converter.adapters.input.moneyforward import (
    MONEYFORWARD_OBSERVED_HEADER,
    MoneyForwardInputAdapter,
    MoneyForwardInputAdapterError,
    MoneyForwardStructuralValidator,
)
from accounting_converter.domain.format_metadata import (
    EvidenceLevel,
    JournalGroupingStrategy,
)
from accounting_converter.domain.journal import Side
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.infrastructure.adapter_registry import (
    AdapterAvailabilityStatus,
    production_adapter_registry,
)
from accounting_converter.profiles.known_formats import (
    moneyforward_cloud_journal_export_observed_schema,
)


class MoneyForwardInputAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = moneyforward_cloud_journal_export_observed_schema()
        self.profile = FormatProfile(
            software="Money Forward",
            product="Money Forward クラウド会計",
            version="UNKNOWN",
            format_id=self.schema.identity.stable_key,
            encoding="cp932",
        )
        self.adapter = MoneyForwardInputAdapter()

    def test_schema_is_exact_observed_identity(self) -> None:
        self.assertEqual(self.schema.identity.evidence_level, EvidenceLevel.OBSERVED)
        self.assertEqual(self.schema.column_count, 19)
        self.assertEqual(self.schema.encoding, "cp932")
        self.assertEqual(
            self.schema.capabilities.journal_grouping_strategy,
            JournalGroupingStrategy.TRANSACTION_NUMBER_CONTIGUOUS,
        )
        self.assertEqual(
            tuple(field.display_name for field in self.schema.fields),
            MONEYFORWARD_OBSERVED_HEADER,
        )

    def test_simple_cp932_lf_19_columns(self) -> None:
        entries = self._read([self._row("1")])

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].date, date(2026, 10, 6))
        self.assertEqual(entries[0].debit_total(), Decimal("1000"))
        self.assertEqual(entries[0].credit_total(), Decimal("1000"))
        self.assertEqual(entries[0].source_reference.source_journal_id, "1")
        self.assertEqual(entries[0].metadata["transaction_number_scope"], "SOURCE_FILE_LOCAL")
        self.assertFalse(entries[0].metadata["production_registry_enabled"])

    def test_supported_compound_shapes(self) -> None:
        shapes = {
            "1D3C": [
                self._row("1", debit_amount="1000", credit_amount="500"),
                self._row(
                    "1", debit_account="", debit_tax="", debit_amount="", credit_amount="300"
                ),
                self._row(
                    "1", debit_account="", debit_tax="", debit_amount="", credit_amount="200"
                ),
            ],
            "3D1C": [
                self._row("1", debit_amount="500", credit_amount="1000"),
                self._row(
                    "1", debit_amount="300", credit_account="", credit_tax="", credit_amount=""
                ),
                self._row(
                    "1", debit_amount="200", credit_account="", credit_tax="", credit_amount=""
                ),
            ],
            "2D2C": [
                self._row("1", debit_amount="600", credit_amount="700"),
                self._row("1", debit_amount="400", credit_amount="300"),
            ],
            "3D3C": [
                self._row("1", debit_amount="500", credit_amount="400"),
                self._row("1", debit_amount="300", credit_amount="300"),
                self._row("1", debit_amount="200", credit_amount="300"),
            ],
        }
        for name, rows in shapes.items():
            with self.subTest(name=name):
                entry = self._read(rows)[0]
                self.assertTrue(entry.is_compound())
                self.assertEqual(entry.debit_total(), Decimal("1000"))
                self.assertEqual(entry.credit_total(), Decimal("1000"))

    def test_both_side_context_fields_are_losslessly_retained(self) -> None:
        row = self._row(
            "1",
            debit_sub="架空借方補助",
            debit_department="架空借方部門",
            debit_partner="架空借方取引先",
            credit_sub="架空貸方補助",
            credit_department="架空貸方部門",
            credit_partner="架空貸方取引先",
        )
        entry = self._read([row])[0]
        debit = next(line for line in entry.lines if line.side is Side.DEBIT)
        credit = next(line for line in entry.lines if line.side is Side.CREDIT)

        self.assertEqual(debit.sub_account, "架空借方補助")
        self.assertEqual(debit.department, "架空借方部門")
        self.assertEqual(debit.metadata["moneyforward_trade_partner"], "架空借方取引先")
        self.assertEqual(credit.sub_account, "架空貸方補助")
        self.assertEqual(credit.department, "架空貸方部門")
        self.assertEqual(credit.metadata["moneyforward_trade_partner"], "架空貸方取引先")

    def test_tax_literals_and_invoice_are_preserved_without_interpretation(self) -> None:
        categories = (
            "課税仕入 10%",
            "課税売上 10%",
            "課税仕入 (軽)8%",
            "課税売上 (軽)8%",
            "非課税仕入",
        )
        for index, category in enumerate(categories, start=1):
            with self.subTest(category=category):
                entry = self._read([
                    self._row(
                        str(index),
                        debit_tax=category,
                        debit_invoice="70%控除" if index == 1 else "",
                    )
                ])[0]
                debit = next(line for line in entry.lines if line.side is Side.DEBIT)
                self.assertEqual(debit.tax_info.category, category)
                expected_invoice = "70%控除" if index == 1 else None
                self.assertEqual(debit.tax_info.invoice_classification, expected_invoice)
                self.assertIsNone(debit.tax_info.tax_amount)

    def test_both_side_tax_values_are_retained(self) -> None:
        entry = self._read([
            self._row(
                "1",
                debit_tax="課税仕入 10%",
                credit_tax="課税売上 10%",
            )
        ])[0]
        self.assertEqual(entry.lines[0].tax_info.category, "課税仕入 10%")
        self.assertEqual(entry.lines[1].tax_info.category, "課税売上 10%")

    def test_tags_memo_description_quotes_and_commas_are_preserved(self) -> None:
        entry = self._read([
            self._row(
                "1",
                description='架空,摘要"A',
                tags="架空タグA|架空タグB",
                memo='架空,メモ"B',
            )
        ])[0]

        self.assertEqual(entry.description, '架空,摘要"A')
        self.assertEqual(entry.metadata["moneyforward_tags"][0]["value"], "架空タグA|架空タグB")
        self.assertEqual(entry.metadata["moneyforward_memos"][0]["value"], '架空,メモ"B')

    def test_large_amount_is_preserved(self) -> None:
        entry = self._read([
            self._row("1", debit_amount="123456789", credit_amount="123456789")
        ])[0]
        self.assertEqual(entry.debit_total(), Decimal("123456789"))

    def test_non_consecutive_transaction_number_reuse_blocks(self) -> None:
        self._assert_blocked([self._row("1"), self._row("2"), self._row("1")])

    def test_group_date_mismatch_blocks(self) -> None:
        self._assert_blocked([
            self._row("1", debit_amount="500", credit_amount="500"),
            self._row("1", date_value="2026/10/07", debit_amount="500", credit_amount="500"),
        ])

    def test_unbalanced_group_blocks(self) -> None:
        self._assert_blocked([self._row("1", debit_amount="1000", credit_amount="999")])

    def test_account_amount_half_filled_blocks(self) -> None:
        self._assert_blocked([self._row("1", debit_amount="")])
        self._assert_blocked([self._row("1", debit_account="")])

    def test_side_metadata_without_account_blocks(self) -> None:
        self._assert_blocked([
            self._row("1", debit_account="", debit_amount="", debit_partner="架空取引先")
        ])

    def test_wrong_columns_and_header_block(self) -> None:
        self._assert_blocked([self._row("1")[:-1]])
        header = list(MONEYFORWARD_OBSERVED_HEADER)
        header[0] = "取引番号"
        self._assert_blocked([self._row("1")], header=tuple(header))

    def test_malformed_csv_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.csv"
            path.write_bytes(b'"unclosed\n')
            with self.assertRaises(MoneyForwardInputAdapterError):
                self.adapter.read(path, self.profile)

    def test_raw_multiline_field_blocks(self) -> None:
        self._assert_blocked([self._row("1", memo="架空1行目\n架空2行目")])

    def test_invalid_date_amount_zero_and_negative_block(self) -> None:
        self._assert_blocked([self._row("1", date_value="2026-10-06")])
        self._assert_blocked([self._row("1", debit_amount="1,000")])
        self._assert_blocked([self._row("1", debit_amount="0", credit_amount="0")])
        self._assert_blocked([self._row("1", debit_amount="-1", credit_amount="-1")])

    def test_multiple_conflicting_descriptions_block(self) -> None:
        self._assert_blocked([
            self._row("1", debit_amount="500", credit_amount="500", description="架空A"),
            self._row("1", debit_amount="500", credit_amount="500", description="架空B"),
        ])

    def test_bom_crlf_utf8_and_non_quote_all_block(self) -> None:
        row = self._row("1")
        for encoding, newline, bom, quote_all in (
            ("cp932", "\n", True, True),
            ("cp932", "\r\n", False, True),
            ("utf-8", "\n", False, True),
            ("cp932", "\n", False, False),
        ):
            with self.subTest(encoding=encoding, newline=repr(newline), bom=bom, quote_all=quote_all):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "input.csv"
                    self._write(path, [row], encoding, newline, bom, quote_all=quote_all)
                    with self.assertRaises(MoneyForwardInputAdapterError):
                        self.adapter.read(path, self.profile)

    def test_structural_validator_returns_error_without_exposing_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.csv"
            self._write(path, [self._row("1", debit_amount="bad")])
            results = MoneyForwardStructuralValidator(self.adapter).validate(path, self.profile)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].rule_id, "MF-OBSERVED-V0-STRUCTURE")
        self.assertNotIn("bad", results[0].message)

    def test_adapter_is_not_registered_for_production(self) -> None:
        lookup = production_adapter_registry().get_exact_input(self.schema.identity)
        self.assertEqual(lookup.status, AdapterAvailabilityStatus.UNAVAILABLE)

    def _read(self, rows: list[tuple[str, ...]]):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.csv"
            self._write(path, rows)
            return self.adapter.read(path, self.profile)

    def _assert_blocked(
        self,
        rows: list[tuple[str, ...]],
        header: tuple[str, ...] = MONEYFORWARD_OBSERVED_HEADER,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.csv"
            self._write(path, rows, header=header)
            with self.assertRaises(MoneyForwardInputAdapterError):
                self.adapter.read(path, self.profile)

    @staticmethod
    def _write(
        path: Path,
        rows: list[tuple[str, ...]],
        encoding: str = "cp932",
        newline: str = "\n",
        bom: bool = False,
        quote_all: bool = True,
        header: tuple[str, ...] = MONEYFORWARD_OBSERVED_HEADER,
    ) -> None:
        output = __import__("io").StringIO(newline="")
        writer = csv.writer(
            output,
            lineterminator=newline,
            quoting=csv.QUOTE_ALL if quote_all else csv.QUOTE_MINIMAL,
        )
        writer.writerow(header)
        writer.writerows(rows)
        raw = output.getvalue().encode(encoding)
        path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + raw)

    @staticmethod
    def _row(
        transaction_number: str,
        date_value: str = "2026/10/06",
        debit_account: str = "架空借方科目",
        debit_sub: str = "",
        debit_department: str = "",
        debit_partner: str = "",
        debit_tax: str = "対象外",
        debit_invoice: str = "",
        debit_amount: str = "1000",
        credit_account: str = "架空貸方科目",
        credit_sub: str = "",
        credit_department: str = "",
        credit_partner: str = "",
        credit_tax: str = "対象外",
        credit_invoice: str = "",
        credit_amount: str = "1000",
        description: str = "架空摘要",
        tags: str = "",
        memo: str = "",
    ) -> tuple[str, ...]:
        return (
            transaction_number, date_value,
            debit_account, debit_sub, debit_department, debit_partner,
            debit_tax, debit_invoice, debit_amount,
            credit_account, credit_sub, credit_department, credit_partner,
            credit_tax, credit_invoice, credit_amount,
            description, tags, memo,
        )


if __name__ == "__main__":
    unittest.main()
