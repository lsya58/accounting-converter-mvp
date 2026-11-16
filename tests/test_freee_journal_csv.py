"""freee会計 仕訳帳CSV reader / diagnosis (DIAGNOSE_ONLY), and the freee JDL9 / 弥生25 spec comparison.

Fixtures are SYNTHETIC: column NAMES are the headers observed in the real 2026-11-15 freee export
(product vocabulary, no customer data); every VALUE below is invented ("合成…"). The private
originals are only read — never copied, rewritten or required — by the opt-in RealEvidenceTest.
"""
from __future__ import annotations

import contextlib
from collections import Counter
import csv
import hashlib
import io
import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

from accounting_converter.adapters.input.base import InputAdapter
from accounting_converter.adapters.input.freee import journal_csv
from accounting_converter.adapters.input.freee.journal_csv import (
    BLANK_SIDE_NEW_ALL_EMPTY,
    BLANK_SIDE_OLD_ZERO_PLACEHOLDER,
    BLANK_SIDES_KEY,
    NEW_CSV_97_HEADER,
    OLD_CSV_29_HEADER,
    UNOBSERVED_VALUES_KEY,
    FreeeIssue,
    FreeeJournalCsvParser,
    FreeeJournalVariant,
)
from accounting_converter.application import freee_diagnosis
from accounting_converter.application.freee_diagnosis import diagnose_parse_result, tax_hint
from accounting_converter.application.freee_other_export_diagnosis import (
    FREEE_JDL9_HEADER,
    YAYOI25_COLUMNS,
    diagnose_freee_jdl9,
    diagnose_freee_yayoi25,
    jdl30_columns_absent_from_freee_jdl9,
)
from accounting_converter.domain.conversion_direction import (
    DirectionNotProductionError,
    DirectionStage,
    direction_for,
    require_production,
)
from accounting_converter.domain.journal import JournalEntry, JournalLine, Side, SourceReference
from accounting_converter.domain.journal_identity import JOURNAL_CONTENT_IDENTITY_KEY
from accounting_converter.domain.journal_rows import (
    LINE_COUNTERPARTY_KEY,
    ROW_ORDER_KEY,
    journal_physical_rows,
    physical_row_shape,
)
from accounting_converter.domain.source_information import (
    SourceFieldScope,
    closing_adjustment_marker,
    legacy_source_fields,
    source_fields,
)

OLD_FINGERPRINT = "28cae0314652f1d9d591c0548f4f32b121fe4d0f64e86841457ca159e33f0476"
NEW_FINGERPRINT = "b0f895b32b7f93397e75e92ea25697392d4204e8099174163dbe8b8515a2bd8c"
SYNTHETIC_ID_1, SYNTHETIC_ID_2, SYNTHETIC_ID_3 = "8800000001", "8800000002", "8800000003"
SYNTHETIC_CREATOR = "synthetic-user@example.invalid"


def _csv(header, rows, encoding="utf-8", newline="\n") -> bytes:
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator=newline).writerows((header, *rows))
    return buffer.getvalue().encode(encoding)


def _row(header, **values) -> tuple[str, ...]:
    unknown = set(values) - set(header)
    assert not unknown, unknown
    return tuple(values.get(name, "") for name in header)


def _new(no, journal_id, line, lines, day="2026-04-01", **values):
    base = {
        "No": no, "取引日": day, "決算整理仕訳": "0", "期末日取引フラグ": "0", "作成者": SYNTHETIC_CREATOR,
        "消費税経理処理方法": "税込経理", "登録した方法": "振替伝票", "承認状況(仕訳承認)": "なし",
        "振替伝票ID": f"77{journal_id}", "仕訳ID": journal_id, "仕訳番号": f"5{journal_id[-4:]}",
        "仕訳行番号": str(line), "仕訳行数": str(lines), "レコード番号": no, "取引支払日": day,
    }
    base.update(values)
    return _row(NEW_CSV_97_HEADER, **base)


def _new_side(prefix, account, amount, category="対象外", tax="0", rate="0", **extra):
    values = {
        f"{prefix}勘定科目": account, f"{prefix}決算書表示名": account, f"{prefix}金額": amount,
        f"{prefix}税区分": category, f"{prefix}税金額": tax, f"{prefix}内税・外税": "内税",
        f"{prefix}税率": rate, f"{prefix}軽減税率有無": "0",
    }
    values.update({f"{prefix}{key}": value for key, value in extra.items()})
    return values


def new_rows(no_offset=0):
    n = lambda k: str(k + no_offset)  # noqa: E731 - display number shifts on re-export
    return (
        # purchase 10%: explicit tax 100, counterparty / item / memo tags
        _new(n(1), SYNTHETIC_ID_1, 1, 1,
             **_new_side("借方", "合成費用", "1100", "課対仕入10%", "100", "10",
                         取引先名="合成取引先", 品目="合成品目", メモ="合成メモ", 備考="合成備考A"),
             **_new_side("貸方", "合成現金", "1100", 備考="合成備考A")),
        # compound 1D2C: row 2 has an all-blank debit side
        _new(n(2), SYNTHETIC_ID_2, 1, 2, "2026-04-02",
             **_new_side("借方", "合成現金", "2200", 備考="合成備考B"),
             **_new_side("貸方", "合成売上", "1100", "課税売上10%", "100", "10", 備考="合成備考B")),
        _new(n(2), SYNTHETIC_ID_2, 2, 2, "2026-04-02",
             **_new_side("貸方", "合成雑収入", "1100", "課税売上10%", "100", "10")),
        # closing adjustment; display name differs from the account
        _new(n(3), SYNTHETIC_ID_3, 1, 1, "2026-12-31", 決算整理仕訳="1", 期末日取引フラグ="1",
             **_new_side("借方", "合成費用", "300"),
             **{**_new_side("貸方", "合成貯蔵品", "300"), "貸方決算書表示名": "合成表示名"}),
    )


def _old(no, serial, day="2026/04/01", **values):
    base = {"": no, "取引日": day, "決算整理仕訳": "0", "仕訳番号": serial, "承認状況": "なし",
            "作成者": SYNTHETIC_CREATOR}
    base.update(values)
    return _row(OLD_CSV_29_HEADER, **base)


def old_rows(no_offset=0):
    n = lambda k: str(k + no_offset)  # noqa: E731
    return (
        _old(n(1), "50001", 借方勘定科目="合成費用", 借方金額="1100", 借方税区分="課対仕入10%", 借方品目="合成品目",
             借方メモ="合成メモ", 借方取引先="合成取引先", 貸方勘定科目="合成現金", 貸方金額="1100", 貸方税区分="対象外",
             摘要="合成取引先 合成品目 合成メモ 合成備考A"),
        _old(n(2), "50002", "2026/04/02", 借方勘定科目="合成現金", 借方金額="2200", 借方税区分="対象外",
             貸方勘定科目="合成売上", 貸方金額="1100", 貸方税区分="課税売上10%", 摘要="合成備考B"),
        # observed empty-side representation of the 旧CSV: "" / "0" / 対象外
        _old(n(2), "50002", "2026/04/02", 借方勘定科目="", 借方金額="0", 借方税区分="対象外",
             貸方勘定科目="合成雑収入", 貸方金額="1100", 貸方税区分="課税売上10%"),
        _old(n(3), "50003", "2026/12/31", 決算整理仕訳="1", 借方勘定科目="合成費用", 借方金額="300", 借方税区分="対象外",
             貸方勘定科目="合成貯蔵品", 貸方金額="300", 貸方税区分="対象外", 摘要="合成決算"),
    )


def parse(header, rows, **kwargs):
    return FreeeJournalCsvParser().parse_bytes(_csv(header, rows, **kwargs), "synthetic.csv")


def codes(result):
    return {issue.code for issue in result.issues}


class ObservedHeaderTest(unittest.TestCase):
    def test_observed_headers_are_pinned(self):
        self.assertEqual(len(OLD_CSV_29_HEADER), 29)
        self.assertEqual(len(NEW_CSV_97_HEADER), 97)
        self.assertEqual(journal_csv.header_fingerprint(OLD_CSV_29_HEADER), OLD_FINGERPRINT)
        self.assertEqual(journal_csv.header_fingerprint(NEW_CSV_97_HEADER), NEW_FINGERPRINT)
        self.assertEqual(OLD_CSV_29_HEADER[0], "")  # the 旧CSV display-number column has no name
        self.assertEqual(NEW_CSV_97_HEADER[0], "No")  # not "No." as the public-help fragments suggested
        self.assertNotIn("摘要", NEW_CSV_97_HEADER)  # the 新CSV has per-side 備考 instead
        # Observed is not verified: meanings and the JDL round trip are not.
        self.assertEqual(journal_csv.VERIFIED_HEADER_FINGERPRINTS, frozenset())

    def test_variant_identification(self):
        self.assertIs(parse(NEW_CSV_97_HEADER, new_rows()).header.variant, FreeeJournalVariant.NEW_CSV)
        self.assertIs(parse(OLD_CSV_29_HEADER, old_rows()).header.variant, FreeeJournalVariant.OLD_CSV)
        self.assertTrue(parse(NEW_CSV_97_HEADER, new_rows()).header.observed)
        self.assertTrue(parse(OLD_CSV_29_HEADER, old_rows()).header.observed)
        # the E2 guess (public-help fragments) and a header mixing both variants are never guessed
        fragment = ("No.", "取引日", "借方勘定科目", "借方金額", "貸方勘定科目", "貸方金額", "摘要")
        mixed = OLD_CSV_29_HEADER + ("仕訳ID",)
        for header in (fragment, mixed):
            with self.subTest(header=header[:2]):
                result = parse(header, [("1",) * len(header)])
                self.assertFalse(result.file_readable)
                self.assertIn(FreeeIssue.VARIANT_UNKNOWN, codes(result))
                self.assertEqual(result.entries, ())

    def test_encodings_and_newlines(self):
        for encoding, newline in (("utf-8", "\n"), ("utf-8-sig", "\r\n"), ("cp932", "\r\n")):
            with self.subTest(encoding=encoding):
                result = parse(NEW_CSV_97_HEADER, new_rows(), encoding=encoding, newline=newline)
                self.assertTrue(result.file_readable)
                self.assertEqual(result.header.encoding, encoding)
                self.assertEqual(result.header.newline, "LF" if newline == "\n" else "CRLF")
                self.assertEqual(len(result.entries), 3)
        utf16 = FreeeJournalCsvParser().parse_bytes(_csv(NEW_CSV_97_HEADER, new_rows(), "utf-16"))
        self.assertIn(FreeeIssue.ENCODING_UNKNOWN, codes(utf16))

    def test_unknown_or_missing_column_is_read_but_not_observed(self):
        header = NEW_CSV_97_HEADER + ("合成の新しい列",)
        rows = [row + ("値",) for row in new_rows()]
        result = parse(header, rows)
        self.assertTrue(result.file_readable)
        self.assertFalse(result.header.observed)
        self.assertEqual(result.header.unknown_columns, ("合成の新しい列",))
        kept = [v for e in result.entries for v in source_fields(e) if not v.known]
        self.assertEqual({(v.field, v.value) for v in kept}, {("合成の新しい列", "値")})
        blockers = diagnose_parse_result(result).journal_blockers
        self.assertTrue(all("SYSTEM_EVIDENCE:UNKNOWN_SOURCE_COLUMN" in c for c in blockers.values()))
        self.assertTrue(all("SYSTEM_EVIDENCE:FREEE_HEADER_NOT_OBSERVED" in c for c in blockers.values()))
        # 旧CSV with an optional item unchecked: fewer columns, still read, not observed
        drop = OLD_CSV_29_HEADER.index("借方部門")
        old = parse(OLD_CSV_29_HEADER[:drop] + OLD_CSV_29_HEADER[drop + 1:],
                    [row[:drop] + row[drop + 1:] for row in old_rows()])
        self.assertTrue(old.file_readable)
        self.assertEqual(old.header.missing_observed_columns, ("借方部門",))
        self.assertFalse(old.header.observed)


class NewCsvTest(unittest.TestCase):
    def setUp(self):
        self.result = parse(NEW_CSV_97_HEADER, new_rows())
        self.entries = {e.source_reference.source_journal_id: e for e in self.result.entries}

    def test_all_rows_accepted(self):
        self.assertEqual(self.result.issues, ())
        self.assertEqual((self.result.data_rows, self.result.accepted_rows), (4, 4))
        self.assertEqual(self.result.rejected_journals, 0)

    def test_explicit_tax_columns(self):
        purchase = self.entries[SYNTHETIC_ID_1]
        debit, credit = purchase.lines
        self.assertEqual((debit.tax_info.category, debit.tax_info.tax_amount, debit.tax_info.rate),
                         ("課対仕入10%", Decimal("100"), Decimal("10")))
        self.assertIs(debit.tax_info.reduced_rate, False)
        self.assertEqual(debit.tax_info.metadata["freee_tax_inclusion_raw"], "内税")
        self.assertIsNone(debit.tax_info.tax_inclusion)  # raw only: JDL 税入力方法 mapping unverified
        self.assertEqual(credit.tax_info.tax_amount, Decimal("0"))  # explicit zero, not blank
        self.assertFalse(credit.tax_info.metadata["tax_amount_blank"])
        self.assertEqual(purchase.metadata[journal_csv.TAX_ACCOUNTING_METHOD_KEY], "税込経理")

    def test_blank_tax_amount_is_not_zero_and_not_computed(self):
        rows = list(new_rows())
        rows[0] = rows[0][:NEW_CSV_97_HEADER.index("借方税金額")] + ("",) + rows[0][NEW_CSV_97_HEADER.index("借方税金額") + 1:]
        result = parse(NEW_CSV_97_HEADER, rows)
        line = result.entries[0].lines[0]
        self.assertIsNone(line.tax_info.tax_amount)
        self.assertTrue(line.tax_info.metadata["tax_amount_blank"])
        diagnosis = diagnose_parse_result(result)
        self.assertIn("SYSTEM_EVIDENCE:FREEE_TAX_AMOUNT_ABSENT", diagnosis.journal_blockers[result.entries[0].id])
        self.assertEqual(diagnosis.tax["tax_amount_blank"], 1)

    def test_compound_keeps_the_blank_debit_row(self):
        compound = self.entries[SYNTHETIC_ID_2]
        self.assertEqual(len(compound.metadata[ROW_ORDER_KEY]), 2)
        self.assertEqual([(l.side, l.amount) for l in compound.lines],
                         [(Side.DEBIT, Decimal("2200")), (Side.CREDIT, Decimal("1100")), (Side.CREDIT, Decimal("1100"))])
        self.assertEqual(compound.metadata[BLANK_SIDES_KEY], ((compound.metadata[ROW_ORDER_KEY][1], "DEBIT", BLANK_SIDE_NEW_ALL_EMPTY),))
        self.assertEqual(physical_row_shape(journal_physical_rows(compound)), (1, 2, 2))
        self.assertEqual(compound.id, f"freee:NEW_CSV:{SYNTHETIC_ID_2}")
        self.assertTrue(compound.is_balanced())

    def test_tags_closing_and_display_name(self):
        purchase = self.entries[SYNTHETIC_ID_1]
        self.assertEqual(purchase.lines[0].metadata[LINE_COUNTERPARTY_KEY], "合成取引先")
        fields = {(v.field, v.scope) for v in source_fields(purchase)}
        self.assertIn(("借方品目", SourceFieldScope.DEBIT), fields)
        self.assertIn(("借方メモ", SourceFieldScope.DEBIT), fields)
        self.assertIn(("仕訳ID", SourceFieldScope.ROW), fields)
        self.assertEqual(purchase.description, "合成備考A")
        closing = self.entries[SYNTHETIC_ID_3]
        self.assertEqual(closing_adjustment_marker(closing), "1")
        self.assertIsNone(closing_adjustment_marker(purchase))  # "0" is not a marker
        self.assertEqual(closing.metadata[journal_csv.PERIOD_END_FLAG_KEY], "1")
        credit = closing.lines[1]
        self.assertEqual(credit.account, "合成貯蔵品")  # never replaced by the display name
        self.assertEqual(credit.metadata[journal_csv.LINE_DISPLAY_NAME_KEY], "合成表示名")

    def test_display_number_is_not_an_identity(self):
        shifted = parse(NEW_CSV_97_HEADER, new_rows(no_offset=4))
        for a, b in zip(self.result.entries, shifted.entries):
            self.assertEqual(a.id, b.id)
            self.assertEqual(a.metadata[JOURNAL_CONTENT_IDENTITY_KEY], b.metadata[JOURNAL_CONTENT_IDENTITY_KEY])
            self.assertNotEqual(a.metadata[journal_csv.DISPLAY_NUMBER_KEY], b.metadata[journal_csv.DISPLAY_NUMBER_KEY])

    def test_structure_rejections(self):
        rows = new_rows()
        index = NEW_CSV_97_HEADER.index
        cases = {
            "line number": (2, "仕訳行番号", "3", FreeeIssue.LINE_NUMBERING_INCONSISTENT),
            "line count": (2, "仕訳行数", "3", FreeeIssue.JOURNAL_ID_INCONSISTENT),
            "voucher id": (2, "振替伝票ID", "999", FreeeIssue.JOURNAL_ID_INCONSISTENT),
            "date": (2, "取引日", "2026-04-03", FreeeIssue.MULTIPLE_DATES),
            "closing": (2, "決算整理仕訳", "1", FreeeIssue.CLOSING_MIXED),
            "method": (2, "消費税経理処理方法", "税抜経理", FreeeIssue.TAX_ACCOUNTING_METHOD_MIXED),
            "slash date": (0, "取引日", "2026/04/01", FreeeIssue.DATE_FORMAT_UNVERIFIED),
            "amount": (0, "借方金額", "1,100", FreeeIssue.AMOUNT_FORMAT_UNVERIFIED),
            "side": (0, "借方勘定科目", "", FreeeIssue.SIDE_WITHOUT_ACCOUNT_OR_AMOUNT),
            "missing id": (0, "仕訳ID", "", FreeeIssue.JOURNAL_NUMBER_MISSING),
        }
        for name, (row_index, column, value, issue) in cases.items():
            with self.subTest(name):
                changed = list(rows)
                row = list(changed[row_index])
                row[index(column)] = value
                if column == "取引日" and name == "slash date":
                    row[index("取引支払日")] = value
                changed[row_index] = tuple(row)
                result = parse(NEW_CSV_97_HEADER, changed)
                self.assertIn(issue, codes(result))
                self.assertEqual(result.accepted_rows + result.rejected_rows, result.data_rows)  # nothing vanishes

    def test_journal_id_reused_out_of_sequence(self):
        rows = new_rows()
        result = parse(NEW_CSV_97_HEADER, (rows[0], rows[3], rows[0]))
        self.assertIn(FreeeIssue.JOURNAL_NUMBER_REUSED, codes(result))
        self.assertEqual(len(result.entries), 1)
        self.assertEqual(result.rejected_rows, 2)

    def test_unobserved_values_block(self):
        index = NEW_CSV_97_HEADER.index
        row = list(new_rows()[0])
        row[index("借方内税・外税")] = "外税"
        row[index("借方部門")] = "合成部門"
        result = parse(NEW_CSV_97_HEADER, [tuple(row)])
        entry = result.entries[0]
        self.assertEqual(set(entry.metadata[UNOBSERVED_VALUES_KEY]), {"借方内税・外税", "借方部門"})
        blockers = diagnose_parse_result(result).journal_blockers[entry.id]
        self.assertIn("SYSTEM_EVIDENCE:FREEE_VALUE_UNOBSERVED", blockers)
        self.assertIn("HUMAN:DEPARTMENT_MAPPING", blockers)

    def test_unobserved_shapes_and_tax_categories_block(self):
        two_by_two = (
            _new("1", SYNTHETIC_ID_1, 1, 2, **_new_side("借方", "合成費用", "600"), **_new_side("貸方", "合成現金", "600")),
            _new("1", SYNTHETIC_ID_1, 2, 2, **_new_side("借方", "合成費用", "400"), **_new_side("貸方", "合成現金", "400")),
        )
        blank_credit = (
            _new("1", SYNTHETIC_ID_2, 1, 2, **_new_side("借方", "合成費用", "600"), **_new_side("貸方", "合成現金", "1000")),
            _new("1", SYNTHETIC_ID_2, 2, 2, **_new_side("借方", "合成費用", "400")),
        )
        for name, rows in (("2D2C", two_by_two), ("2D1C blank credit", blank_credit)):
            with self.subTest(name):
                result = parse(NEW_CSV_97_HEADER, rows)
                self.assertEqual(result.accepted_rows, 2)  # read and kept, never dropped
                blockers = diagnose_parse_result(result).journal_blockers[result.entries[0].id]
                self.assertIn("SYSTEM_EVIDENCE:FREEE_JOURNAL_SHAPE_UNOBSERVED", blockers)
        reduced = list(new_rows()[0])
        reduced[NEW_CSV_97_HEADER.index("借方税区分")] = "課対仕入8%(軽)"
        result = parse(NEW_CSV_97_HEADER, [tuple(reduced)])
        self.assertIn("借方税区分", result.entries[0].metadata[UNOBSERVED_VALUES_KEY])
        self.assertIn("SYSTEM_EVIDENCE:FREEE_VALUE_UNOBSERVED",
                      diagnose_parse_result(result).journal_blockers[result.entries[0].id])

    def test_tax_consistency_and_side_descriptions(self):
        index = NEW_CSV_97_HEADER.index
        row = list(new_rows()[0])
        row[index("借方税率")] = "8"
        row[index("貸方税金額")] = "5"
        row[index("貸方備考")] = "合成の別備考"
        result = parse(NEW_CSV_97_HEADER, [tuple(row)])
        entry = result.entries[0]
        self.assertIsNone(journal_physical_rows(entry))  # 借方備考 != 貸方備考: never merged
        blockers = diagnose_parse_result(result).journal_blockers[entry.id]
        self.assertIn("SYSTEM_EVIDENCE:FREEE_TAX_RATE_INCONSISTENT", blockers)
        self.assertIn("SYSTEM_EVIDENCE:FREEE_TAX_AMOUNT_ON_UNTAXED_CATEGORY", blockers)
        self.assertIn("SYSTEM_EVIDENCE:FREEE_ROW_DESCRIPTION_INCONSISTENT", blockers)


class OldCsvTest(unittest.TestCase):
    def setUp(self):
        self.result = parse(OLD_CSV_29_HEADER, old_rows())
        self.entries = {e.source_reference.source_journal_id: e for e in self.result.entries}

    def test_zero_placeholder_is_a_blank_side_and_the_row_stays(self):
        self.assertEqual(self.result.issues, ())
        self.assertEqual(self.result.accepted_rows, 4)
        compound = self.entries["50002"]
        self.assertEqual(compound.id, "freee:OLD_CSV:50002")
        self.assertEqual(len(compound.metadata[ROW_ORDER_KEY]), 2)
        self.assertEqual(compound.metadata[BLANK_SIDES_KEY][0][1:], ("DEBIT", BLANK_SIDE_OLD_ZERO_PLACEHOLDER))
        self.assertFalse(any(line.amount == 0 for line in compound.lines))
        self.assertEqual(physical_row_shape(journal_physical_rows(compound)), (1, 2, 2))

    def test_no_tax_amount_and_nothing_inferred(self):
        diagnosis = diagnose_parse_result(self.result)
        for line in self.entries["50001"].lines:
            self.assertIsNone(line.tax_info.tax_amount)
            self.assertIsNone(line.tax_info.rate)
            self.assertFalse(line.tax_info.metadata["tax_amount_column_present"])
        blockers = diagnosis.journal_blockers["freee:OLD_CSV:50001"]
        self.assertIn("SYSTEM_EVIDENCE:FREEE_TAX_AMOUNT_ABSENT", blockers)
        self.assertIn("SYSTEM_EVIDENCE:FREEE_TAX_INCLUSION_UNKNOWN", blockers)
        self.assertIn("HUMAN:FREEE_TAX_ACCOUNTING_METHOD_UNKNOWN", blockers)
        self.assertEqual(diagnosis.tax["tax_amount_column_absent"], 7)
        self.assertEqual(closing_adjustment_marker(self.entries["50003"]), "1")

    def test_unobserved_tax_category_without_rate_column_blocks(self):
        rows = list(old_rows())
        row = list(rows[0])
        row[OLD_CSV_29_HEADER.index("借方税区分")] = "課対仕入8%(軽)"  # 旧CSV has no 税率 column to catch it
        rows[0] = tuple(row)
        result = parse(OLD_CSV_29_HEADER, rows)
        diagnosis = diagnose_parse_result(result)
        self.assertIn("SYSTEM_EVIDENCE:FREEE_VALUE_UNOBSERVED", diagnosis.journal_blockers["freee:OLD_CSV:50001"])
        self.assertEqual(diagnosis.unobserved_value_columns, Counter({"借方税区分": 1}))

    def test_composed_description_and_counterparty(self):
        purchase = self.entries["50001"]
        self.assertEqual(purchase.lines[0].metadata[LINE_COUNTERPARTY_KEY], "合成取引先")
        self.assertEqual(purchase.description, "合成取引先 合成品目 合成メモ 合成備考A")
        compound = self.entries["50002"]
        self.assertEqual(compound.description, "合成備考B")
        self.assertEqual([row.description for row in journal_physical_rows(compound)], ["合成備考B", ""])

    def test_display_number_is_not_an_identity(self):
        shifted = parse(OLD_CSV_29_HEADER, old_rows(no_offset=4))
        self.assertEqual([e.id for e in self.result.entries], [e.id for e in shifted.entries])
        self.assertEqual([e.metadata[JOURNAL_CONTENT_IDENTITY_KEY] for e in self.result.entries],
                         [e.metadata[JOURNAL_CONTENT_IDENTITY_KEY] for e in shifted.entries])

    def test_other_blank_shapes_are_rejected(self):
        index = OLD_CSV_29_HEADER.index
        base = list(old_rows()[2])
        cases = {
            "taxed zero": {"借方税区分": "課税売上10%"},
            "fully blank": {"借方金額": "", "借方税区分": ""},
            "zero with item": {"借方品目": "合成品目"},
        }
        for name, change in cases.items():
            with self.subTest(name):
                row = list(base)
                for column, value in change.items():
                    row[index(column)] = value
                rows = list(old_rows())
                rows[2] = tuple(row)
                result = parse(OLD_CSV_29_HEADER, rows)
                self.assertIn(FreeeIssue.SIDE_WITHOUT_ACCOUNT_OR_AMOUNT, codes(result))
                self.assertNotIn("50002", {e.source_reference.source_journal_id for e in result.entries})
        both = list(base)
        both[index("貸方勘定科目")], both[index("貸方金額")], both[index("貸方税区分")] = "", "0", "対象外"
        result = parse(OLD_CSV_29_HEADER, (old_rows()[1], tuple(both)))
        self.assertIn(FreeeIssue.EMPTY_ROW, codes(result))

    def test_serial_and_date_checks(self):
        index = OLD_CSV_29_HEADER.index
        rows = list(old_rows())
        row = list(rows[2])
        row[index("仕訳番号")] = "59999"
        rows[2] = tuple(row)
        self.assertIn(FreeeIssue.JOURNAL_ID_INCONSISTENT, codes(parse(OLD_CSV_29_HEADER, rows)))
        rows = list(old_rows())
        row = list(rows[3])
        row[index("仕訳番号")] = "50001"
        rows[3] = tuple(row)
        reused = parse(OLD_CSV_29_HEADER, rows)
        self.assertIn(FreeeIssue.JOURNAL_NUMBER_REUSED, codes(reused))
        self.assertEqual({e.source_reference.source_journal_id for e in reused.entries}, {"50002"})
        rows = list(old_rows())
        row = list(rows[0])
        row[index("取引日")] = "2026-04-01"
        rows[0] = tuple(row)
        self.assertIn(FreeeIssue.DATE_FORMAT_UNVERIFIED, codes(parse(OLD_CSV_29_HEADER, rows)))

    def test_file_level_rejections(self):
        self.assertIn(FreeeIssue.NO_DATA_ROWS, codes(parse(OLD_CSV_29_HEADER, [])))
        short = parse(OLD_CSV_29_HEADER, [old_rows()[0][:-1]])
        self.assertIn(FreeeIssue.COLUMN_COUNT_MISMATCH, codes(short))
        self.assertEqual(short.entries, ())
        no_serial = tuple(name for name in OLD_CSV_29_HEADER if name != "仕訳番号")
        self.assertIn(FreeeIssue.REQUIRED_COLUMN_MISSING, codes(parse(no_serial, [("x",) * len(no_serial)])))


class FreeeDiagnosisTest(unittest.TestCase):
    def diagnosis(self, header=NEW_CSV_97_HEADER, rows=None):
        rows = new_rows() if rows is None and header is NEW_CSV_97_HEADER else (rows or old_rows())
        return diagnose_parse_result(parse(header, rows))

    def test_never_ready(self):
        for header in (NEW_CSV_97_HEADER, OLD_CSV_29_HEADER):
            diagnosis = self.diagnosis(header)
            self.assertEqual(diagnosis.direction_stage, DirectionStage.DIAGNOSE_ONLY.value)
            self.assertFalse(diagnosis.ready_allowed)
            self.assertEqual(diagnosis.formal_ready, 0)
            for blockers in diagnosis.journal_blockers.values():
                self.assertIn("SYSTEM_EVIDENCE:FREEE_SOURCE_FORMAT_UNVERIFIED", blockers)
                self.assertIn("SYSTEM_IMPLEMENTATION:DIRECTION_NOT_PRODUCTION", blockers)
                self.assertIn("HUMAN:ACCOUNT_MAPPING", blockers)
                self.assertIn("HUMAN:TAX_MAPPING", blockers)
                self.assertNotIn("SYSTEM_EVIDENCE:FREEE_HEADER_NOT_OBSERVED", blockers)
                # the fixtures stay inside what the sample showed: no "unobserved" blocker hides a real gap
                self.assertNotIn("SYSTEM_EVIDENCE:FREEE_VALUE_UNOBSERVED", blockers)
                self.assertNotIn("SYSTEM_EVIDENCE:FREEE_JOURNAL_SHAPE_UNOBSERVED", blockers)

    def test_verified_header_alone_does_not_make_ready(self):
        result = parse(NEW_CSV_97_HEADER, new_rows())
        with mock.patch.object(journal_csv, "VERIFIED_HEADER_FINGERPRINTS", frozenset({result.header.fingerprint})):
            self.assertTrue(result.header.verified)
            diagnosis = diagnose_parse_result(result)
        self.assertEqual(diagnosis.formal_ready, 0)

    def test_inventory(self):
        report = self.diagnosis().to_dict()
        self.assertTrue(report["format"]["header_observed"])
        self.assertFalse(report["format"]["header_verified"])
        self.assertEqual(report["tax_amounts"], {"tax_amount_explicit_nonzero": 3, "tax_amount_explicit_zero": 4})
        self.assertEqual(report["tax_inclusion_raw"], {"内税": 7})
        self.assertEqual(report["tax_accounting_methods"], {"税込経理": 3})
        self.assertEqual(report["blank_sides"], {BLANK_SIDE_NEW_ALL_EMPTY: 1})
        self.assertEqual(report["structure"]["compound_journals"], 1)
        self.assertEqual(report["closing"], {"closing_marker_journals": 1, "period_end_flag=0": 2, "period_end_flag=1": 1})
        self.assertEqual(report["shapes"], {"1D1C/1rows": 2, "1D2C/2rows": 1})
        info = report["information_without_jdl_column"]
        self.assertEqual(info["借方品目"]["class"], "NO_JDL_COLUMN")
        self.assertEqual(info["借方取引先名"]["class"], "NEEDS_HUMAN_TRANSFORMATION")
        self.assertEqual(info["仕訳ID"]["class"], "SOURCE_IDENTIFIER")
        self.assertEqual(info["作成者"]["class"], "PERSONAL_DATA")
        blockers = self.diagnosis().journal_blockers
        self.assertIn("HUMAN:ACCOUNT_DISPLAY_NAME_DIFFERS", blockers[f"freee:NEW_CSV:{SYNTHETIC_ID_3}"])
        self.assertIn("SYSTEM_EVIDENCE:FREEE_CLOSING_MARKER_UNVERIFIED", blockers[f"freee:NEW_CSV:{SYNTHETIC_ID_3}"])
        self.assertIn("SYSTEM_EVIDENCE:FREEE_TAX_INCLUSION_MAPPING_UNVERIFIED", blockers[f"freee:NEW_CSV:{SYNTHETIC_ID_1}"])
        self.assertIn("SYSTEM_EVIDENCE:FREEE_TAX_ACCOUNTING_METHOD_UNMAPPED", blockers[f"freee:NEW_CSV:{SYNTHETIC_ID_1}"])

    def test_report_carries_no_customer_values(self):
        for header in (NEW_CSV_97_HEADER, OLD_CSV_29_HEADER):
            text = json.dumps(self.diagnosis(header).to_dict(), ensure_ascii=False)
            for value in ("合成", SYNTHETIC_CREATOR, "example.invalid", SYNTHETIC_ID_1, "50001", "1100", "2200"):
                self.assertNotIn(value, text)

    def test_cli_reads_only(self):
        from accounting_converter.tools import freee_journal_diagnose
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "synthetic.csv"
            source.write_bytes(_csv(NEW_CSV_97_HEADER, new_rows()))
            before = {p: p.read_bytes() for p in Path(directory).rglob("*")}
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = freee_journal_diagnose.main(["--source", str(source)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.getvalue())["formal_ready"], 0)
            self.assertEqual(before, {p: p.read_bytes() for p in Path(directory).rglob("*")})

    def test_reader_is_not_an_input_adapter_and_not_registered(self):
        from accounting_converter.infrastructure.adapter_registry import production_adapter_registry
        self.assertFalse(issubclass(FreeeJournalCsvParser, InputAdapter))
        registry = production_adapter_registry()
        vendors = {registration.format_identity.vendor.lower() for registration in registry._inputs.values()}
        self.assertFalse(any("freee" in vendor for vendor in vendors))

    def test_tax_hints(self):
        self.assertEqual(tax_hint("課税売上8%(軽)").__dict__,
                         {"kind": "SALES_TAXABLE", "rate": "8", "reduced": True, "deduction_ratio": None, "allocation": None})
        self.assertEqual(tax_hint("共対仕入(控50)10%").allocation, "共通対応")
        self.assertEqual(tax_hint("共対仕入(控50)10%").deduction_ratio, "50")
        self.assertEqual(tax_hint("非課売上").kind, "NON_TAXABLE_SALES")
        self.assertEqual(tax_hint("不課税").kind, "OUT_OF_SCOPE")
        self.assertEqual(tax_hint("特定課税仕入").kind, "UNKNOWN")


# ----------------------------------------------------------------------------- freee JDL9 / 弥生25

def _cp932(rows) -> bytes:
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    return buffer.getvalue().encode("cp932")


def jdl9_rows():
    return [
        ["＜仕訳一覧＞"], list(FREEE_JDL9_HEADER),
        ["20260401", "8001", "8999", "", "", "2200", "合成複合", "0", "0"],
        ["20260401", "8999", "8002", "", "", "1100", "合成複合", "11", "10"],
        ["20260401", "8999", "8003", "", "", "1100", "", "11", "10"],
        ["20261331", "8004", "8005", "0009", "", "300", "合成決算", "0", "0"],
        ["＜仕訳一覧終了＞"],
    ]


def yayoi25(flag, closing="", day="2026/04/01", debit=("合成費用", "", "対象外", "1100", ""),
            credit=("合成現金", "", "対象外", "1100", ""), description="合成摘要", type_="0"):
    return [flag, "", closing, day, debit[0], debit[1], "", debit[2], debit[3], debit[4],
            credit[0], credit[1], "", credit[2], credit[3], credit[4], description, "", day, type_, "", "", "0", "0", "no"]


def yayoi_rows():
    return [
        yayoi25("2000", debit=("合成費用", "", "課対仕入10%", "1100", "")),
        yayoi25("2110", credit=("合成売上", "", "課税売上10%", "1100", ""), debit=("合成現金", "合成現金", "対象外", "2200", ""), type_="3"),
        yayoi25("2101", debit=("", "", "対象外", "0", ""), credit=("合成雑収入", "", "課税売上10%", "1100", ""),
                description="", type_="3"),
        yayoi25("2000", "本決", "2026/12/31", description="合成" * 20),
    ]


class FreeeOtherExportTest(unittest.TestCase):
    def test_jdl9_structure(self):
        report = diagnose_freee_jdl9(_cp932(jdl9_rows())).to_dict()
        self.assertTrue(report["readable"])
        self.assertEqual(report["formal_ready"], 0)
        self.assertFalse(report["target_import_verified"])
        self.assertEqual(report["issues"], {})
        self.assertEqual(report["counts"]["data_rows"], 4)
        self.assertEqual(report["counts"]["rows_dated_month_13"], 1)
        self.assertEqual(report["counts"]["rows_with_blank_description"], 1)
        self.assertEqual(report["values"]["課区/税区"], {"0/0": 2, "11/10": 2})
        self.assertIn("COMPOUND_EXPANDED_VIA_RELAY_ACCOUNT", report["differences"])
        self.assertIn("CODES_FROM_FREEE_EXPORT_SETTINGS", report["differences"])
        text = json.dumps(report, ensure_ascii=False)
        for value in ("合成", "8001", "8999", "0009", "2200"):
            self.assertNotIn(value, text)

    def test_jdl9_rejections(self):
        rows = jdl9_rows()
        self.assertFalse(diagnose_freee_jdl9(_cp932(rows[1:])).readable)  # title record missing
        changed = [rows[0], list(FREEE_JDL9_HEADER[:-1]) + ["合成"], *rows[2:]]
        self.assertIn("HEADER_NOT_OBSERVED", diagnose_freee_jdl9(_cp932(changed)).issues)
        bad_date = [*rows[:2], ["20260231", *rows[2][1:]], *rows[3:]]
        self.assertEqual(diagnose_freee_jdl9(_cp932(bad_date)).issues["DATE_NOT_CALENDAR"], 1)
        self.assertIn("NOT_CP932_CSV", diagnose_freee_jdl9("＜仕訳一覧＞\n".encode("utf-16")).issues)

    def test_jdl30_columns_missing_in_jdl9(self):
        missing = set(jdl30_columns_absent_from_freee_jdl9())
        self.assertTrue({"識別フラグ", "伝番", "借方金額", "貸方金額", "借方消費税", "借方税入力方法", "借方課区"} <= missing)
        self.assertNotIn("日付", missing)
        self.assertNotIn("摘要", missing)

    def test_yayoi25_structure(self):
        report = diagnose_freee_yayoi25(_cp932(yayoi_rows())).to_dict()
        self.assertTrue(report["readable"])
        self.assertEqual(report["issues"], {})
        counts = report["counts"]
        self.assertEqual(counts["taxed_sides"], 3)
        self.assertEqual(counts["taxed_sides_with_blank_tax_amount"], 3)
        self.assertEqual(counts["blank_debit_sides"], 1)
        self.assertEqual(counts["rows_due_date_equals_transaction_date"], 4)
        self.assertEqual(counts["rows_description_over_official_length"], 1)
        self.assertEqual(report["values"]["決算"], {"(空欄)": 3, "本決": 1})
        self.assertEqual(report["values"]["タイプ"], {"0": 2, "3": 2})
        self.assertNotIn("rows_type_outside_existing_reader_contract", counts)
        self.assertIn("NOT_FED_TO_EXISTING_YAYOI_READER", report["differences"])
        self.assertNotIn("合成", json.dumps(report, ensure_ascii=False))

    def test_yayoi25_rejections(self):
        rows = yayoi_rows()
        self.assertIn("COMPOUND_CONTINUATION_WITHOUT_START", diagnose_freee_yayoi25(_cp932([rows[2]])).issues)
        self.assertIn("COMPOUND_NOT_CLOSED", diagnose_freee_yayoi25(_cp932([rows[1], rows[0]])).issues)
        self.assertIn("HEADER_ROW_UNOBSERVED", diagnose_freee_yayoi25(_cp932([list(YAYOI25_COLUMNS), *rows])).issues)
        self.assertIn("COLUMN_COUNT_MISMATCH", diagnose_freee_yayoi25(_cp932([rows[0][:-1]])).issues)
        blank = list(rows[2])
        blank[5] = "合成補助"
        self.assertIn("BLANK_ACCOUNT_WITH_VALUES", diagnose_freee_yayoi25(_cp932([rows[1], blank])).issues)

    def test_cli_reads_only(self):
        from accounting_converter.tools import freee_other_export_diagnose
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "synthetic.csv"
            source.write_bytes(_cp932(jdl9_rows()))
            before = source.read_bytes()
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = freee_other_export_diagnose.main(["--format", "jdl9", "--source", str(source)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.getvalue())["formal_ready"], 0)
            self.assertEqual(before, source.read_bytes())
            self.assertEqual([p.name for p in Path(directory).iterdir()], ["synthetic.csv"])


# ----------------------------------------------------------------------------- real Evidence (opt-in, read-only)

PRIVATE = Path(__file__).resolve().parents[1] / "data" / "private"
REAL_FILES = {
    "仕訳帳（旧）CSV （2026年01月~2026年12月） (1).csv": "2ef65d4cf8f9978112334d764e083fecf6f11de0d5fce22a5f48846ef2cabb12",
    "仕訳帳（新）CSV （2026年01月~2026年12月）.csv": "ab275c39673b909d1e502189badbd42b453a28836ea2f045ef1dac22e702bbd7",
    "仕訳帳 JDLインポート形式 （2026年01月~2026年12月）.csv": "87bb6f796159ef031d610b65405d1ac32dd6c5cb145812a4c845287ba11ffcdd",
    "仕訳帳 弥生会計インポート形式 （2026年01月~2026年12月）.csv": "3fe600ab483daba4c12b532aae3599afcc33f09100dd991aa89e899eacf9c45d",
}


@unittest.skipUnless(all((PRIVATE / name).is_file() for name in REAL_FILES), "private freee Evidence not present")
class RealEvidenceTest(unittest.TestCase):
    """Reads the private originals (bytes only, never written) and checks what the docs claim."""

    def setUp(self):
        self.raw = {name: (PRIVATE / name).read_bytes() for name in REAL_FILES}
        for name, digest in REAL_FILES.items():
            self.assertEqual(hashlib.sha256(self.raw[name]).hexdigest(), digest, name)

    def test_journal_csvs(self):
        for name, variant in (("仕訳帳（旧）CSV （2026年01月~2026年12月） (1).csv", FreeeJournalVariant.OLD_CSV),
                              ("仕訳帳（新）CSV （2026年01月~2026年12月）.csv", FreeeJournalVariant.NEW_CSV)):
            with self.subTest(variant=variant):
                result = FreeeJournalCsvParser().parse_bytes(self.raw[name], name)
                self.assertIs(result.header.variant, variant)
                self.assertTrue(result.header.observed)
                self.assertEqual((result.data_rows, result.accepted_rows, len(result.entries), result.issues), (7, 7, 6, ()))
                self.assertEqual(sum(l.amount for e in result.entries for l in e.lines if l.side is Side.DEBIT), 53500)
                self.assertEqual(sum(len(e.metadata[BLANK_SIDES_KEY]) for e in result.entries), 1)
                diagnosis = diagnose_parse_result(result)
                self.assertEqual(diagnosis.formal_ready, 0)
                self.assertEqual(diagnosis.closing["closing_marker_journals"], 1)
                if variant is FreeeJournalVariant.NEW_CSV:
                    taxes = [l.tax_info.tax_amount for e in result.entries for l in e.lines]
                    self.assertEqual(sum(taxes), 4500)
                    self.assertEqual(diagnosis.tax_accounting_methods, {"税込経理": 6})
                text = json.dumps(diagnosis.to_dict(), ensure_ascii=False)
                self.assertNotIn("@", text)
                self.assertNotIn("FREEE-TEST", text)

    def test_other_exports(self):
        jdl = diagnose_freee_jdl9(self.raw["仕訳帳 JDLインポート形式 （2026年01月~2026年12月）.csv"])
        self.assertTrue(jdl.readable)
        self.assertEqual((jdl.counts["data_rows"], jdl.counts["rows_dated_month_13"]), (8, 1))
        yayoi = diagnose_freee_yayoi25(self.raw["仕訳帳 弥生会計インポート形式 （2026年01月~2026年12月）.csv"])
        self.assertTrue(yayoi.readable)
        self.assertEqual(yayoi.counts["taxed_sides"], yayoi.counts["taxed_sides_with_blank_tax_amount"])
        self.assertEqual(yayoi.values["決算"]["本決"], 1)


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
