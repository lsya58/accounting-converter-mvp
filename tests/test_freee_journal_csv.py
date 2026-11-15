"""freee会計 仕訳帳CSV reader / diagnosis (DIAGNOSE_ONLY), on SYNTHETIC data only.

The CSVs below are written by hand from fragments of freee's public help (column NAMES only; see
docs/research/freee_journal_csv_public_spec.md). They are not freee exports: the real column set,
order, 摘要 column and tax representation are unverified. The tests pin the fail-closed behaviour,
not freee's format.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

from accounting_converter.adapters.input.base import InputAdapter
from accounting_converter.adapters.input.freee import journal_csv
from accounting_converter.adapters.input.freee.journal_csv import (
    FreeeIssue,
    FreeeJournalCsvParser,
    FreeeJournalVariant,
)
from accounting_converter.application import freee_diagnosis
from accounting_converter.application.freee_diagnosis import diagnose_parse_result, tax_hint
from accounting_converter.domain.conversion_direction import (
    DirectionNotProductionError,
    DirectionStage,
    direction_for,
    require_production,
)
from accounting_converter.domain.journal import JournalEntry, JournalLine, Side, SourceReference
from accounting_converter.domain.journal_rows import LINE_COUNTERPARTY_KEY, journal_physical_rows, physical_row_shape
from accounting_converter.domain.source_information import (
    SourceFieldScope,
    closing_adjustment_marker,
    legacy_source_fields,
    source_fields,
)

NEW_HEADER = (
    "No.", "取引日", "管理番号",
    "借方勘定科目", "借方決算書表示名", "借方金額", "借方税区分", "借方税金額", "借方取引先名", "借方品目", "借方部門",
    "貸方勘定科目", "貸方決算書表示名", "貸方金額", "貸方税区分", "貸方税金額", "貸方取引先名", "貸方品目", "貸方部門",
    "摘要",
)
OLD_HEADER = (
    "No.", "取引日",
    "借方勘定科目", "借方金額", "借方税区分", "借方取引先", "借方メモタグ",
    "貸方勘定科目", "貸方金額", "貸方税区分", "貸方取引先", "貸方メモタグ",
    "摘要", "決算整理仕訳", "仕訳番号", "作成日時",
)


def _csv(header, rows, encoding="utf-8") -> bytes:
    buffer = io.StringIO(newline="")
    import csv
    csv.writer(buffer, lineterminator="\r\n").writerows((header, *rows))
    return buffer.getvalue().encode(encoding)


def _new_rows():
    return (
        # 1: 1D1C purchase 10%, 1100 incl. 100 tax, partner, item
        ("1", "2025/04/01", "", "消耗品費", "消耗品費", "1100", "課対仕入10%", "100", "合成商店", "文具", "",
         "現金", "現金", "1100", "対象外", "", "", "", "", "合成摘要A"),
        # 2: 2D1C over two physical rows; bank 口座 whose display name differs
        ("2", "2025/04/02", "M-2", "旅費交通費", "旅費交通費", "2200", "課対仕入10%", "200", "", "", "営業",
         "合成銀行普通", "普通預金", "3300", "対象外", "", "", "", "", "合成摘要B"),
        ("2", "2025/04/02", "M-2", "通信費", "通信費", "1100", "課対仕入(控80)10%", "80", "", "", "",
         "", "", "", "", "", "", "", "", "合成摘要B"),
        # 3: sales 10%
        ("3", "2025/04/03", "", "売掛金", "売掛金", "11000", "対象外", "", "合成顧客", "", "",
         "売上高", "売上高", "11000", "課税売上10%", "1000", "合成顧客", "", "", "合成摘要C"),
    )


class FreeeReaderTest(unittest.TestCase):
    def parse(self, raw: bytes):
        return FreeeJournalCsvParser().parse_bytes(raw, file_name="synthetic.csv")

    def test_new_csv_in_every_documented_encoding(self):
        for encoding, expected in (("utf-8", "utf-8"), ("utf-8-sig", "utf-8-sig"), ("cp932", "cp932")):
            with self.subTest(encoding=encoding):
                result = self.parse(_csv(NEW_HEADER, _new_rows(), encoding))
                self.assertTrue(result.file_readable, result.issues)
                self.assertEqual(result.header.variant, FreeeJournalVariant.NEW_CSV)
                self.assertEqual(result.header.encoding, expected)
                self.assertEqual(len(result.entries), 3)
                self.assertFalse(result.header.verified)
                self.assertEqual(result.header.unknown_columns, ())
                self.assertIn("摘要", result.header.assumed_columns)

    def test_common_model_content(self):
        result = self.parse(_csv(NEW_HEADER, _new_rows()))
        first, compound, sales = result.entries
        self.assertEqual(first.date, date(2025, 4, 1))
        debit = next(line for line in first.lines if line.side is Side.DEBIT)
        self.assertEqual((debit.account, debit.amount), ("消耗品費", Decimal("1100")))
        self.assertEqual(debit.tax_info.category, "課対仕入10%")
        self.assertEqual(debit.tax_info.tax_amount, Decimal("100"))
        self.assertIsNone(debit.tax_info.tax_inclusion)  # never guessed
        self.assertIsNone(debit.sub_account)  # never derived
        self.assertEqual(debit.metadata[LINE_COUNTERPARTY_KEY], "合成商店")
        # compound: two physical rows -> the neutral row semantics hold
        rows = journal_physical_rows(compound)
        self.assertIsNotNone(rows)
        self.assertEqual(physical_row_shape(rows), (2, 1, 2))
        self.assertTrue(compound.is_balanced())
        self.assertEqual({line.department for line in compound.lines} - {None}, {"営業"})
        fields = {(value.field, value.value, value.scope) for value in source_fields(compound)}
        self.assertIn(("管理番号", "M-2", SourceFieldScope.ROW), fields)
        self.assertEqual(len(sales.lines), 2)
        self.assertEqual(len({entry.metadata["source_journal_content_sha256"] for entry in result.entries}), 3)

    def test_content_identity_ignores_file_name_and_journal_number(self):
        raw = _csv(NEW_HEADER, _new_rows()[:1])
        renumbered = _csv(NEW_HEADER, (("99",) + _new_rows()[0][1:],))
        a = FreeeJournalCsvParser().parse_bytes(raw, "a.csv").entries[0]
        b = FreeeJournalCsvParser().parse_bytes(renumbered, "b.csv").entries[0]
        self.assertEqual(a.metadata["source_journal_content_sha256"], b.metadata["source_journal_content_sha256"])

    def test_old_csv_closing_marker_and_missing_tax_amount(self):
        rows = (
            ("1", "2026/03/31", "減価償却費", "50000", "対象外", "", "",
             "減価償却累計額", "50000", "対象外", "", "", "合成決算", "1", "X1", "2026-04-10 10:00"),
            ("2", "2026/03/15", "仕入高", "5500", "課対仕入10%", "合成仕入先", "合成タグ",
             "買掛金", "5500", "対象外", "合成仕入先", "", "合成仕入", "", "X2", "2026-03-15 09:00"),
        )
        result = self.parse(_csv(OLD_HEADER, rows, "cp932"))
        self.assertTrue(result.file_readable, result.issues)
        self.assertEqual(result.header.variant, FreeeJournalVariant.OLD_CSV)
        closing, purchase = result.entries
        self.assertEqual(closing_adjustment_marker(closing), "1")
        self.assertIsNone(closing_adjustment_marker(purchase))
        diagnosis = diagnose_parse_result(result)
        self.assertIn("SYSTEM_EVIDENCE:FREEE_CLOSING_MARKER_UNVERIFIED", diagnosis.journal_blockers[closing.id])
        self.assertIn("SYSTEM_EVIDENCE:FREEE_TAX_AMOUNT_ABSENT", diagnosis.journal_blockers[purchase.id])
        self.assertIn("HUMAN:COUNTERPARTY_POLICY", diagnosis.journal_blockers[purchase.id])
        self.assertIn("HUMAN:NON_RETAINED_INFORMATION", diagnosis.journal_blockers[purchase.id])  # メモタグ

    def test_unknown_column_is_kept_and_blocks(self):
        header = NEW_HEADER + ("借方セグメント9",)
        rows = tuple(row + ("合成値",) for row in _new_rows())
        result = self.parse(_csv(header, rows))
        self.assertEqual(result.header.unknown_columns, ("借方セグメント9",))
        kept = [value for value in source_fields(result.entries[0]) if not value.known]
        self.assertEqual([(value.field, value.value) for value in kept], [("借方セグメント9", "合成値")])
        diagnosis = diagnose_parse_result(result)
        self.assertTrue(all("SYSTEM_EVIDENCE:UNKNOWN_SOURCE_COLUMN" in codes for codes in diagnosis.journal_blockers.values()))

    def test_file_level_rejections(self):
        cases = {
            FreeeIssue.REQUIRED_COLUMN_MISSING: _csv(NEW_HEADER[1:], (row[1:] for row in _new_rows())),
            FreeeIssue.COLUMN_COUNT_MISMATCH: _csv(NEW_HEADER, (_new_rows()[0][:-1],)),
            FreeeIssue.DUPLICATE_COLUMN: _csv(NEW_HEADER + ("摘要",), (row + ("x",) for row in _new_rows())),
            FreeeIssue.NO_DATA_ROWS: _csv(NEW_HEADER, ()),
            FreeeIssue.ENCODING_UNKNOWN: b"\xff\xfeN\x00o\x00",
        }
        for code, raw in cases.items():
            with self.subTest(code=code):
                result = self.parse(raw)
                self.assertFalse(result.file_readable)
                self.assertEqual(result.entries, ())
                self.assertIn(code, {issue.code for issue in result.issues})
                self.assertEqual(diagnose_parse_result(result).journal_blockers, {})

    def test_journal_level_rejections_do_not_drop_silently(self):
        base = _new_rows()
        cases = {
            FreeeIssue.JOURNAL_NUMBER_REUSED: (base[0], base[3], replace_number(base[0], "1")),
            FreeeIssue.DATE_FORMAT_UNVERIFIED: (with_value(base[0], 1, "2025-04-01"),),
            FreeeIssue.AMOUNT_FORMAT_UNVERIFIED: (with_value(with_value(base[0], 5, "1,100"), 13, "1,100"),),
            FreeeIssue.UNBALANCED: (with_value(base[0], 13, "1000"),),
            FreeeIssue.SIDE_WITHOUT_ACCOUNT_OR_AMOUNT: (with_value(base[0], 3, ""),),
            FreeeIssue.MULTIPLE_DATES: (base[1], with_value(base[2], 1, "2025/04/03")),
        }
        for code, rows in cases.items():
            with self.subTest(code=code):
                result = self.parse(_csv(NEW_HEADER, rows))
                self.assertTrue(result.file_readable)
                self.assertIn(code, {issue.code for issue in result.issues})
                self.assertGreater(result.rejected_journals, 0)
                self.assertEqual(result.rejected_rows + sum(len(set(e.metadata["physical_row_numbers"])) for e in result.entries),
                                 result.data_rows)

    def test_ambiguous_variant_is_read_but_blocks(self):
        result = self.parse(_csv(NEW_HEADER + ("仕訳番号",), (row + ("1",) for row in _new_rows())))
        self.assertTrue(result.file_readable)
        self.assertEqual(result.header.variant, FreeeJournalVariant.UNKNOWN)
        self.assertIn(FreeeIssue.VARIANT_AMBIGUOUS, {issue.code for issue in result.issues})
        diagnosis = diagnose_parse_result(result)
        self.assertEqual(len(diagnosis.journal_blockers), 3)
        self.assertTrue(all("SYSTEM_EVIDENCE:FREEE_VARIANT_UNKNOWN" in c for c in diagnosis.journal_blockers.values()))
        self.assertEqual(diagnosis.formal_ready, 0)

    def test_reader_is_not_an_input_adapter_and_not_registered(self):
        from accounting_converter.infrastructure.adapter_registry import production_adapter_registry
        self.assertFalse(issubclass(FreeeJournalCsvParser, InputAdapter))
        registry = production_adapter_registry()
        vendors = {registration.format_identity.vendor.lower() for registration in registry._inputs.values()}
        self.assertFalse(any("freee" in vendor for vendor in vendors))
        self.assertEqual(journal_csv.VERIFIED_HEADER_FINGERPRINTS, frozenset())


def replace_number(row, number):
    return (number,) + tuple(row[1:])


def with_value(row, index, value):
    values = list(row)
    values[index] = value
    return tuple(values)


class FreeeDiagnosisTest(unittest.TestCase):
    def diagnosis(self):
        return diagnose_parse_result(FreeeJournalCsvParser().parse_bytes(_csv(NEW_HEADER, _new_rows()), "synthetic.csv"))

    def test_never_ready(self):
        diagnosis = self.diagnosis()
        self.assertEqual(diagnosis.direction_stage, DirectionStage.DIAGNOSE_ONLY.value)
        self.assertFalse(diagnosis.ready_allowed)
        self.assertEqual(diagnosis.formal_ready, 0)
        for codes in diagnosis.journal_blockers.values():
            self.assertIn("SYSTEM_EVIDENCE:FREEE_SOURCE_FORMAT_UNVERIFIED", codes)
            self.assertIn("SYSTEM_IMPLEMENTATION:DIRECTION_NOT_PRODUCTION", codes)
            self.assertIn("HUMAN:ACCOUNT_MAPPING", codes)

    def test_verified_header_alone_does_not_make_ready(self):
        result = FreeeJournalCsvParser().parse_bytes(_csv(NEW_HEADER, _new_rows()), "synthetic.csv")
        with mock.patch.object(journal_csv, "VERIFIED_HEADER_FINGERPRINTS", frozenset({result.header.fingerprint})):
            self.assertTrue(result.header.verified)
            diagnosis = diagnose_parse_result(result)
        self.assertEqual(diagnosis.formal_ready, 0)
        self.assertTrue(all("SYSTEM_IMPLEMENTATION:DIRECTION_NOT_PRODUCTION" in c for c in diagnosis.journal_blockers.values()))

    def test_blockers_and_inventory(self):
        diagnosis = self.diagnosis()
        report = diagnosis.to_dict()
        compound = diagnosis.journal_blockers["freee:synthetic.csv:2"]
        self.assertIn("HUMAN:ACCOUNT_DISPLAY_NAME_DIFFERS", compound)  # 合成銀行普通 vs 普通預金
        self.assertIn("HUMAN:DEPARTMENT_MAPPING", compound)
        self.assertIn("SYSTEM_EVIDENCE:FREEE_TAX_INCLUSION_UNKNOWN", compound)
        self.assertNotIn("SYSTEM_EVIDENCE:FREEE_TAX_AMOUNT_ABSENT", compound)
        self.assertEqual(report["information_without_jdl_column"]["借方品目"]["class"], "NO_JDL_COLUMN")
        self.assertEqual(report["information_without_jdl_column"]["借方取引先名"]["class"], "NEEDS_HUMAN_TRANSFORMATION")
        self.assertEqual(report["information_without_jdl_column"]["貸方決算書表示名"]["class"], "MAPPING_AID")
        self.assertEqual(report["tax_categories"]["課対仕入(控80)10%"]["hint"]["deduction_ratio"], "80")
        self.assertEqual(report["shapes"], {"1D1C/1rows": 2, "2D1C/2rows": 1})
        self.assertEqual(report["journals_simple_1d1c_or_shape_with_jdl_row_evidence"], 3)

    def test_report_carries_no_customer_values(self):
        text = json.dumps(self.diagnosis().to_dict(), ensure_ascii=False)
        for value in ("合成商店", "合成顧客", "合成摘要", "消耗品費", "合成銀行普通", "営業", "文具", "M-2", "11000"):
            self.assertNotIn(value, text)

    def test_cli_reads_only(self):
        from accounting_converter.tools import freee_journal_diagnose
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "synthetic.csv"
            source.write_bytes(_csv(NEW_HEADER, _new_rows(), "cp932"))
            before = {p: p.read_bytes() for p in Path(directory).rglob("*")}
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = freee_journal_diagnose.main(["--source", str(source)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.getvalue())["formal_ready"], 0)
            self.assertEqual(before, {p: p.read_bytes() for p in Path(directory).rglob("*")})

    def test_tax_hints(self):
        self.assertEqual(tax_hint("課税売上8%(軽)").__dict__,
                         {"kind": "SALES_TAXABLE", "rate": "8", "reduced": True, "deduction_ratio": None, "allocation": None})
        self.assertEqual(tax_hint("共対仕入(控50)10%").allocation, "共通対応")
        self.assertEqual(tax_hint("共対仕入(控50)10%").deduction_ratio, "50")
        self.assertEqual(tax_hint("非課売上").kind, "NON_TAXABLE_SALES")
        self.assertEqual(tax_hint("不課税").kind, "OUT_OF_SCOPE")
        self.assertEqual(tax_hint("特定課税仕入").kind, "UNKNOWN")


class ConversionDirectionTest(unittest.TestCase):
    def test_only_production_directions_allow_ready(self):
        self.assertTrue(require_production("moneyforward_journal_19->jdl_ibex_cashbook_35_5").ready_allowed)
        for key in (freee_diagnosis.DIRECTION_KEY, "freee_jdl_kaikeinet->jdl_ibex_cashbook_35_5",
                    "jdl_ibex_cashbook->moneyforward", "pca->jdl", ""):
            with self.subTest(key=key):
                self.assertFalse(direction_for(key).ready_allowed)
                with self.assertRaises(DirectionNotProductionError):
                    require_production(key)
        self.assertIs(direction_for("never-registered").stage, DirectionStage.NOT_STARTED)


class LegacySourceFieldsTest(unittest.TestCase):
    def test_reads_existing_keys_without_changing_the_entry(self):
        line = JournalLine(Side.DEBIT, "A", Decimal("1"), SourceReference("f", 2, "1"),
                           metadata={"moneyforward_trade_partner": "P"})
        entry = JournalEntry("e", SourceReference("f", 2, "1"), date(2025, 1, 1), [line], metadata={
            "moneyforward_tags": ({"row_number": 2, "value": "T"},),
            "moneyforward_memos": ({"row_number": 2, "value": ""},),
            "yayoi_optional_values": ((3, "付箋1", "1"),),
        })
        before = (dict(entry.metadata), dict(line.metadata))
        found = {(v.field, v.value, v.scope) for v in legacy_source_fields(entry)}
        self.assertEqual(found, {("タグ", "T", SourceFieldScope.ROW), ("取引先", "P", SourceFieldScope.DEBIT),
                                 ("付箋1", "1", SourceFieldScope.ROW)})
        self.assertEqual(before, (entry.metadata, line.metadata))


if __name__ == "__main__":
    unittest.main()
