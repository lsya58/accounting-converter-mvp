"""freee E5A: the six-journal synthetic fixture, the trial diagnosis view and the field-retention inventory.

The six journals have the SHAPES of the 2026-11-15 real freee export (EVID-FREEE-JOURNAL-CSV-REAL-EXPORT-20261115-001):
課税売上10% / 課税仕入10% / 受取利息（非課売上・表示名が異なる） / 複合仕訳（1D2C・2行目の借方が空欄） /
売掛金の計上と付加情報（取引先・品目・メモ・備考） / 決算整理. Every VALUE is invented ("合成…", amounts, IDs); the
private originals are never read here (the opt-in RealEvidenceTest in test_freee_journal_csv does that).
"""
from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from accounting_converter.adapters.input.freee import journal_csv
from accounting_converter.adapters.input.freee.journal_csv import (
    NEW_CSV_97_HEADER,
    NONBLANK_COLUMNS_KEY,
    OLD_CSV_29_HEADER,
    FreeeIssue,
    FreeeJournalVariant,
)
from accounting_converter.application.freee_diagnosis import (
    DIRECTION_KEY,
    diagnose_freee_journal_csv,
    diagnose_parse_result,
    field_retention,
)
from accounting_converter.application.freee_other_export_diagnosis import FREEE_JDL9_HEADER
from accounting_converter.domain.conversion_direction import (
    DirectionNotProductionError,
    DirectionStage,
    KNOWN_DIRECTIONS,
    require_production,
)
from accounting_converter.domain.information_retention import RetentionInventory, RetentionStatus
from accounting_converter.domain.journal import Side
from accounting_converter.domain.journal_rows import LINE_COUNTERPARTY_KEY
from accounting_converter.domain.source_information import closing_adjustment_marker, source_fields
from accounting_converter.ui import freee_trial_view as fv
from tests.test_freee_journal_csv import SYNTHETIC_CREATOR, _csv, _new, _new_side, _old, _row, parse

IDS = ("8810000001", "8810000002", "8810000003", "8810000004", "8810000005", "8810000006")
SECRET_VALUES = ("合成", SYNTHETIC_CREATOR, "example.invalid", *IDS, "11000", "22000", "33000")


def six_new_rows():
    return (
        # 1 課税売上10%
        _new("1", IDS[0], 1, 1, "2026-04-01",
             **_new_side("借方", "合成現金", "11000", 備考="合成備考1"),
             **_new_side("貸方", "合成売上高", "11000", "課税売上10%", "1000", "10", 備考="合成備考1")),
        # 2 課税仕入10%
        _new("2", IDS[1], 1, 1, "2026-04-02",
             **_new_side("借方", "合成仕入高", "5500", "課対仕入10%", "500", "10", 備考="合成備考2"),
             **_new_side("貸方", "合成現金", "5500", 備考="合成備考2")),
        # 3 受取利息: 非課売上, 決算書表示名 differs from the account (never replaced)
        _new("3", IDS[2], 1, 1, "2026-04-03",
             **_new_side("借方", "合成普通預金", "100"),
             **{**_new_side("貸方", "合成受取利息", "100", "非課売上"), "貸方決算書表示名": "合成事業主借"}),
        # 4 複合仕訳 1D2C over two rows; the debit side of row 2 is all blank
        _new("4", IDS[3], 1, 2, "2026-04-04",
             **_new_side("借方", "合成現金", "22000", 備考="合成備考4"),
             **_new_side("貸方", "合成売上高", "11000", "課税売上10%", "1000", "10", 備考="合成備考4")),
        _new("4", IDS[3], 2, 2, "2026-04-04",
             **_new_side("貸方", "合成仮受金", "11000")),
        # 5 売掛金の計上と付加情報
        _new("5", IDS[4], 1, 1, "2026-04-05",
             **_new_side("借方", "合成売掛金", "33000", 取引先名="合成取引先", 品目="合成品目", メモ="合成メモ",
                         備考="合成備考5"),
             **_new_side("貸方", "合成売上高", "33000", "課税売上10%", "3000", "10", 備考="合成備考5")),
        # 6 決算整理
        _new("6", IDS[5], 1, 1, "2026-12-31", 決算整理仕訳="1", 期末日取引フラグ="1",
             **_new_side("借方", "合成仕入高", "2000"),
             **{**_new_side("貸方", "合成貯蔵品", "2000"), "貸方決算書表示名": "合成商品"}),
    )


def six_old_rows():
    return (
        _old("1", "60001", "2026/04/01", 借方勘定科目="合成現金", 借方金額="11000", 借方税区分="対象外",
             貸方勘定科目="合成売上高", 貸方金額="11000", 貸方税区分="課税売上10%", 摘要="合成備考1"),
        _old("2", "60002", "2026/04/02", 借方勘定科目="合成仕入高", 借方金額="5500", 借方税区分="課対仕入10%",
             貸方勘定科目="合成現金", 貸方金額="5500", 貸方税区分="対象外", 摘要="合成備考2"),
        _old("3", "60003", "2026/04/03", 借方勘定科目="合成普通預金", 借方金額="100", 借方税区分="対象外",
             貸方勘定科目="合成受取利息", 貸方金額="100", 貸方税区分="非課売上"),
        _old("4", "60004", "2026/04/04", 借方勘定科目="合成現金", 借方金額="22000", 借方税区分="対象外",
             貸方勘定科目="合成売上高", 貸方金額="11000", 貸方税区分="課税売上10%", 摘要="合成備考4"),
        _old("4", "60004", "2026/04/04", 借方勘定科目="", 借方金額="0", 借方税区分="対象外",
             貸方勘定科目="合成仮受金", 貸方金額="11000", 貸方税区分="対象外"),
        _old("5", "60005", "2026/04/05", 借方勘定科目="合成売掛金", 借方金額="33000", 借方税区分="対象外",
             借方取引先="合成取引先", 借方品目="合成品目", 借方メモ="合成メモ",
             貸方勘定科目="合成売上高", 貸方金額="33000", 貸方税区分="課税売上10%",
             摘要="合成取引先 合成品目 合成メモ 合成備考5"),
        _old("6", "60006", "2026/12/31", 決算整理仕訳="1", 借方勘定科目="合成仕入高", 借方金額="2000",
             借方税区分="対象外", 貸方勘定科目="合成貯蔵品", 貸方金額="2000", 貸方税区分="対象外", 摘要="合成決算"),
    )


VARIANTS = (
    (FreeeJournalVariant.NEW_CSV, NEW_CSV_97_HEADER, six_new_rows),
    (FreeeJournalVariant.OLD_CSV, OLD_CSV_29_HEADER, six_old_rows),
)


def nonblank_cells(header, rows) -> int:
    return sum(1 for row in rows for value in row if value)


class SixJournalFixtureTest(unittest.TestCase):
    def test_variant_and_counts(self):
        for variant, header, rows in VARIANTS:
            with self.subTest(variant=variant):
                result = parse(header, rows())
                self.assertIs(result.header.variant, variant)
                self.assertTrue(result.header.observed)
                self.assertEqual((result.data_rows, result.accepted_rows, len(result.entries), result.issues),
                                 (7, 7, 6, ()))
                debit = sum(l.amount for e in result.entries for l in e.lines if l.side is Side.DEBIT)
                credit = sum(l.amount for e in result.entries for l in e.lines if l.side is Side.CREDIT)
                self.assertEqual((debit, credit), (73600, 73600))

    def test_compound_journal_stays_one_journal(self):
        for variant, header, rows in VARIANTS:
            with self.subTest(variant=variant):
                entries = parse(header, rows()).entries
                compound = [e for e in entries if len(e.lines) > 2]
                self.assertEqual(len(compound), 1)
                entry = compound[0]
                self.assertEqual([l.side for l in entry.lines], [Side.DEBIT, Side.CREDIT, Side.CREDIT])
                self.assertEqual(entry.metadata[journal_csv.ROW_ORDER_KEY], (5, 6))
                self.assertEqual(len(entry.metadata[journal_csv.BLANK_SIDES_KEY]), 1)
                view = fv.present(diagnose_parse_result(parse(header, rows())), "synthetic.csv")
                row = next(r for r in view.journal_rows if r[0] == "4")
                self.assertIn("複合仕訳", row[3])
                self.assertEqual(row[1], "5, 6")

    def test_closing_adjustment_is_identified_and_not_interpreted(self):
        for variant, header, rows in VARIANTS:
            with self.subTest(variant=variant):
                diagnosis = diagnose_parse_result(parse(header, rows()))
                closing = [e for e in diagnosis.parse.entries if closing_adjustment_marker(e) is not None]
                self.assertEqual(len(closing), 1)
                self.assertEqual(closing[0].date.isoformat(), "2026-12-31")   # no 13月 date is invented
                self.assertIn("SYSTEM_EVIDENCE:FREEE_CLOSING_MARKER_UNVERIFIED", diagnosis.journal_blockers[closing[0].id])
                self.assertEqual(sum(1 for j in diagnosis.journals if j.closing), 1)
                retention = diagnosis.retention.fields["決算整理仕訳"]
                self.assertIs(retention.status, RetentionStatus.TARGET_DESTINATION_UNCONFIRMED)

    def test_new_csv_tax_is_explicit(self):
        diagnosis = diagnose_parse_result(parse(NEW_CSV_97_HEADER, six_new_rows()))
        taxes = [l.tax_info.tax_amount for e in diagnosis.parse.entries for l in e.lines]
        self.assertEqual(sum(taxes), 5500)
        self.assertEqual(dict(diagnosis.tax_categories), {"対象外": 8, "課税売上10%": 3, "課対仕入10%": 1, "非課売上": 1})
        view = fv.present(diagnosis, "synthetic.csv")
        self.assertTrue(any("明示された税額" in line for line in view.tax_lines))
        self.assertTrue(any("税込経理 6仕訳" in line for line in view.tax_lines))

    def test_old_csv_tax_unknown_is_never_guessed(self):
        diagnosis = diagnose_parse_result(parse(OLD_CSV_29_HEADER, six_old_rows()))
        for entry in diagnosis.parse.entries:
            for line in entry.lines:
                self.assertIsNone(line.tax_info.tax_amount)        # never computed from 10%
                self.assertIsNone(line.tax_info.rate)              # never derived from the name
                self.assertIsNone(line.tax_info.tax_inclusion)
            blockers = diagnosis.journal_blockers[entry.id]
            self.assertIn("HUMAN:FREEE_TAX_ACCOUNTING_METHOD_UNKNOWN", blockers)
            if any(l.tax_info.category in {"課税売上10%", "課対仕入10%"} for l in entry.lines):
                self.assertIn("SYSTEM_EVIDENCE:FREEE_TAX_AMOUNT_ABSENT", blockers)
                self.assertIn("SYSTEM_EVIDENCE:FREEE_TAX_INCLUSION_UNKNOWN", blockers)
        view = fv.present(diagnosis, "synthetic.csv")
        self.assertTrue(any("税額の列がありません" in line and "推測・計算しません" in line for line in view.tax_lines))
        self.assertTrue(any("列なし（不明）" in line for line in view.tax_lines))
        self.assertNotIn("税金額", diagnosis.retention.fields)

    def test_unobserved_tax_category_is_flagged(self):
        rows = list(six_new_rows())
        rows[1] = _new("2", IDS[1], 1, 1, "2026-04-02",
                       **_new_side("借方", "合成仕入高", "5400", "課対仕入8%(軽)", "400", "8", 備考="合成備考2"),
                       **_new_side("貸方", "合成現金", "5400", 備考="合成備考2"))
        diagnosis = diagnose_parse_result(parse(NEW_CSV_97_HEADER, rows))
        entry = diagnosis.parse.entries[1]
        self.assertIn("SYSTEM_EVIDENCE:FREEE_VALUE_UNOBSERVED", diagnosis.journal_blockers[entry.id])
        self.assertIs(diagnosis.retention.fields["借方税区分"].status, RetentionStatus.MEANING_UNCONFIRMED)
        view = fv.present(diagnosis, "synthetic.csv")
        row = next(r for r in view.tax_rows if r[0] == "課対仕入8%(軽)")
        self.assertIn("観測していない税区分", row[2])


class InformationRetentionTest(unittest.TestCase):
    def test_every_nonblank_cell_is_accounted_for(self):
        for variant, header, rows in VARIANTS:
            with self.subTest(variant=variant):
                data = rows()
                diagnosis = diagnose_parse_result(parse(header, data))
                cells = sum(n for e in diagnosis.parse.entries for _c, n in e.metadata[NONBLANK_COLUMNS_KEY])
                self.assertEqual(cells, nonblank_cells(header, data))
                listed = sum(item.values for item in diagnosis.retention.fields.values())
                self.assertEqual(listed, cells)
                columns_with_values = {header[i] for row in data for i, value in enumerate(row) if value}
                self.assertEqual(set(diagnosis.retention.fields), columns_with_values)

    def test_additional_information_is_kept_and_classified(self):
        for variant, header, rows in VARIANTS:
            with self.subTest(variant=variant):
                diagnosis = diagnose_parse_result(parse(header, rows()))
                entry = diagnosis.parse.entries[4]                      # 売掛金 with 取引先・品目・メモ
                kept = {(v.field, v.value) for v in source_fields(entry)}
                self.assertIn(("借方品目", "合成品目"), kept)
                self.assertIn(("借方メモ", "合成メモ"), kept)
                self.assertEqual(entry.lines[0].metadata[LINE_COUNTERPARTY_KEY], "合成取引先")
                self.assertIn("HUMAN:COUNTERPARTY_POLICY", diagnosis.journal_blockers[entry.id])
                self.assertIn("HUMAN:NON_RETAINED_INFORMATION", diagnosis.journal_blockers[entry.id])
                fields = diagnosis.retention.fields
                self.assertIs(fields["借方品目"].status, RetentionStatus.UNSUPPORTED)
                self.assertIs(fields["借方メモ"].status, RetentionStatus.UNSUPPORTED)
                partner = "借方取引先名" if variant is FreeeJournalVariant.NEW_CSV else "借方取引先"
                self.assertIs(fields[partner].status, RetentionStatus.TARGET_DESTINATION_UNCONFIRMED)
                self.assertIs(fields["借方勘定科目"].status, RetentionStatus.RETAINED)
                self.assertIs(fields["作成者"].status, RetentionStatus.AUDIT_ONLY)
                self.assertEqual(fields["借方品目"].journals, 1)
                self.assertEqual(fields["借方勘定科目"].journals, 6)

    def test_display_name_and_unknown_or_unobserved_columns_are_meaning_unconfirmed(self):
        diagnosis = diagnose_parse_result(parse(NEW_CSV_97_HEADER, six_new_rows()))
        self.assertEqual(diagnosis.retention.fields["貸方決算書表示名"].reason, "ACCOUNT_DISPLAY_NAME_DIFFERS")
        self.assertIs(diagnosis.retention.fields["借方決算書表示名"].status, RetentionStatus.AUDIT_ONLY)
        self.assertIs(diagnosis.retention.fields["借方内税・外税"].status, RetentionStatus.MEANING_UNCONFIRMED)
        # a department value (never observed) and an extra column
        header = NEW_CSV_97_HEADER + ("合成の新しい列",)
        rows = [row + ("",) for row in six_new_rows()]
        rows[0] = _row(header, **{**dict(zip(header, rows[0])), "借方部門": "合成部門", "合成の新しい列": "合成値"})
        diagnosis = diagnose_parse_result(parse(header, rows))
        fields = diagnosis.retention.fields
        self.assertEqual((fields["借方部門"].status, fields["借方部門"].reason),
                         (RetentionStatus.MEANING_UNCONFIRMED, "VALUE_UNOBSERVED"))
        self.assertEqual((fields["合成の新しい列"].status, fields["合成の新しい列"].reason),
                         (RetentionStatus.MEANING_UNCONFIRMED, "UNKNOWN_SOURCE_COLUMN"))
        self.assertIn(("合成の新しい列", "合成値"),
                      {(v.field, v.value) for v in source_fields(diagnosis.parse.entries[0]) if not v.known})
        view = fv.present(diagnosis, "synthetic.csv")
        self.assertTrue(any("観測済みのヘッダーと列の構成が異なります" == m.hint for m in view.metrics))

    def test_retention_table_says_it_counts_columns_not_retained_values(self):
        diagnosis = diagnose_parse_result(parse(OLD_CSV_29_HEADER, six_old_rows()))
        view = fv.present(diagnosis, "synthetic.csv")
        self.assertIn("値のある列の名前と件数の集計", fv.RETENTION_NOTE)
        self.assertIn("出力できることを示すものではありません", fv.RETENTION_NOTE)
        self.assertIn(fv.RETENTION_NOTE, view.plain_text())
        # 決算整理仕訳: 6 journals have a value, but only "1" is kept as a marker (1 journal)
        self.assertEqual(diagnosis.retention.fields["決算整理仕訳"].journals, 6)
        self.assertEqual(sum(1 for j in diagnosis.journals if j.closing), 1)
        self.assertIn("「0」は印なし", fv.RETENTION_REASON_LABELS["CLOSING_MARKER_JDL_UNVERIFIED"])

    def test_field_retention_table_is_total(self):
        for variant, header, _rows in VARIANTS:
            for column in header:
                status, reason = field_retention(variant, column)
                self.assertIsInstance(status, RetentionStatus)
                self.assertIn(reason, fv.RETENTION_REASON_LABELS, (variant, column, reason))

    def test_inventory_merge_keeps_the_doubt(self):
        inventory = RetentionInventory()
        inventory.add("x", RetentionStatus.RETAINED, "A", journals=1, values=2)
        inventory.add("x", RetentionStatus.MEANING_UNCONFIRMED, "B", journals=1, values=1)
        inventory.add("x", RetentionStatus.RETAINED, "A", journals=1, values=1)
        item = inventory.fields["x"]
        self.assertEqual((item.status, item.reason, item.journals, item.values),
                         (RetentionStatus.MEANING_UNCONFIRMED, "B", 3, 4))


class RejectionTest(unittest.TestCase):
    def test_unknown_headers_are_rejected_without_guessing(self):
        mixed = NEW_CSV_97_HEADER + ("摘要",)
        e2_guess = ("No.",) + NEW_CSV_97_HEADER[1:]
        cases = {
            "mixed markers": (mixed, [row + ("合成",) for row in six_new_rows()]),
            "E2 guessed header": (e2_guess, list(six_new_rows())),
            "freee JDL9": (FREEE_JDL9_HEADER, [("20260401",) * len(FREEE_JDL9_HEADER)]),
            "yayoi-like": (("識別フラグ", "伝票No", "決算", "取引日付"), [("2000", "1", "", "2026/04/01")]),
        }
        for name, (header, rows) in cases.items():
            with self.subTest(name):
                result = parse(header, rows)
                self.assertFalse(result.file_readable)
                self.assertEqual(result.entries, ())
                self.assertIn(FreeeIssue.VARIANT_UNKNOWN, {i.code for i in result.issues})
                diagnosis = diagnose_parse_result(result)
                self.assertEqual((diagnosis.journals_read, diagnosis.journals_parsed, diagnosis.formal_ready), (0, 0, 0))
                view = fv.present(diagnosis, "x.csv")
                self.assertFalse(view.readable)
                self.assertFalse(view.output_enabled)
                self.assertIn("読み込みを中止しました", view.headline)
                self.assertTrue(any("ヘッダーと判定できません" in p for p in view.file_problems))
                self.assertEqual(view.metrics[-1].value, "0")

    def test_encoding_date_and_amount_validation(self):
        bad = {
            "utf-16": (b"\xff\xfe" + "No".encode("utf-16-le"), "ENCODING_UNKNOWN"),
        }
        for name, (raw, code) in bad.items():
            result = journal_csv.FreeeJournalCsvParser().parse_bytes(raw)
            self.assertEqual([i.code.value for i in result.issues], [code])
            self.assertIn("文字コード", fv.present(diagnose_parse_result(result), name).file_problems[0])
        # Shift-JIS is read (and reported), never guessed into something else
        sjis = journal_csv.FreeeJournalCsvParser().parse_bytes(_csv(NEW_CSV_97_HEADER, six_new_rows(), encoding="cp932"))
        self.assertEqual((sjis.header.encoding, len(sjis.entries)), ("cp932", 6))
        self.assertIn("Shift-JIS", fv.present(diagnose_parse_result(sjis), "s.csv").format_lines[0])
        rows = list(six_new_rows())
        rows[0] = _row(NEW_CSV_97_HEADER, **{**dict(zip(NEW_CSV_97_HEADER, rows[0])), "取引日": "2026/04/01"})
        rows[1] = _row(NEW_CSV_97_HEADER, **{**dict(zip(NEW_CSV_97_HEADER, rows[1])), "借方金額": "5,500"})
        diagnosis = diagnose_parse_result(parse(NEW_CSV_97_HEADER, rows))
        self.assertEqual((diagnosis.journals_read, diagnosis.journals_parsed, diagnosis.journals_rejected), (6, 4, 2))
        view = fv.present(diagnosis, "x.csv")
        self.assertEqual([r[0] for r in view.rejected_rows], ["1", "2"])
        self.assertIn("取引日の形式", view.rejected_rows[0][2])
        self.assertIn("整数として読めません", view.rejected_rows[1][2])
        self.assertIn("2仕訳は解析できませんでした", view.headline)
        self.assertEqual([m.value for m in view.metrics[1:]], ["6仕訳", "4仕訳", "2仕訳", "0"])
        self.assertEqual([r[2] for r in view.journal_rows].count("未対応（解析できません）"), 2)

    def test_rejected_compound_journal_counts_all_its_rows(self):
        rows = list(six_new_rows())
        rows[4] = _row(NEW_CSV_97_HEADER, **{**dict(zip(NEW_CSV_97_HEADER, rows[4])), "取引日": "2026-04-05"})
        diagnosis = diagnose_parse_result(parse(NEW_CSV_97_HEADER, rows))
        self.assertEqual((diagnosis.journals_rejected, diagnosis.parse.rejected_rows), (1, 2))
        self.assertEqual(diagnosis.journals_read, 6)
        rejected = [j for j in diagnosis.journals if not j.parsed]
        self.assertEqual((rejected[0].display_number, rejected[0].reasons), ("4", ("MULTIPLE_DATES",)))


class TrialViewTest(unittest.TestCase):
    def test_parsed_is_not_formal_ready_and_output_is_disabled(self):
        for variant, header, rows in VARIANTS:
            with self.subTest(variant=variant):
                diagnosis = diagnose_parse_result(parse(header, rows()))
                view = fv.present(diagnosis, "synthetic.csv")
                self.assertTrue(view.readable)
                self.assertEqual([m.label for m in view.metrics],
                                 ["CSV形式", "読み取った仕訳", "正常に解析できた仕訳", "未対応の仕訳", "JDL向け正式READY"])
                self.assertEqual([m.value for m in view.metrics[1:]], ["6仕訳", "6仕訳", "0仕訳", "0"])
                self.assertEqual(view.metrics[0].value, fv.VARIANT_LABELS[variant])
                self.assertEqual(view.formal_ready, 0)
                self.assertFalse(view.output_enabled)
                self.assertIn("正式READYではありません", view.notes[0])
                self.assertTrue(all("正式READYではありません" in row[2] for row in view.journal_rows))
                self.assertEqual(view.reason_rows[0][1], fv.REASON_LABELS["SYSTEM_IMPLEMENTATION:DIRECTION_NOT_PRODUCTION"])
                self.assertEqual(view.reason_rows[0][2], "6仕訳")
                for _owner, text, _count in view.reason_rows:
                    self.assertNotIn(":", text)                     # every code has a Japanese label
                self.assertEqual([label for label, _n in view.retention_counts], list(fv.retention_order_labels()))

    def test_verified_header_or_production_stage_patch_alone_cannot_enable_output(self):
        result = parse(NEW_CSV_97_HEADER, six_new_rows())
        with mock.patch.object(journal_csv, "VERIFIED_HEADER_FINGERPRINTS", frozenset({result.header.fingerprint})):
            view = fv.present(diagnose_parse_result(result), "synthetic.csv")
        self.assertEqual((view.formal_ready, view.output_enabled), (0, False))
        with self.assertRaises(DirectionNotProductionError):
            require_production(DIRECTION_KEY)

    def test_view_and_report_carry_no_customer_values(self):
        for variant, header, rows in VARIANTS:
            with self.subTest(variant=variant):
                diagnosis = diagnose_parse_result(parse(header, rows()))
                texts = (fv.present(diagnosis, "synthetic.csv").plain_text(),
                         json.dumps(diagnosis.to_dict(), ensure_ascii=False))
                for text in texts:
                    for value in SECRET_VALUES + ("60001", "5500"):
                        self.assertNotIn(value, text)

    def test_detect_variant_reads_only_the_header(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {
                "new.csv": _csv(NEW_CSV_97_HEADER, six_new_rows()),
                "old.csv": _csv(OLD_CSV_29_HEADER, six_old_rows(), newline="\r\n"),
                "mf.csv": "取引No,取引日,借方勘定科目\n1,2026/04/01,現金\n".encode("cp932"),
                "bin.csv": b"\x00\x01",
            }
            for name, raw in files.items():
                (root / name).write_bytes(raw)
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            self.assertIs(fv.detect_freee_variant(root / "new.csv"), FreeeJournalVariant.NEW_CSV)
            self.assertIs(fv.detect_freee_variant(root / "old.csv"), FreeeJournalVariant.OLD_CSV)
            self.assertIsNone(fv.detect_freee_variant(root / "mf.csv"))
            self.assertIsNone(fv.detect_freee_variant(root / "bin.csv"))
            self.assertIsNone(fv.detect_freee_variant(root / "missing.csv"))
            diagnosis = diagnose_freee_journal_csv(root / "new.csv")
            self.assertEqual(diagnosis.journals_parsed, 6)
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})

    def test_scope_lines_separate_formal_and_trial(self):
        self.assertIn("正式対応", fv.SCOPE_LINES[0])
        self.assertIn("弥生", fv.SCOPE_LINES[0])
        self.assertIn("Money Forward", fv.SCOPE_LINES[0])
        self.assertIn("試験対応・診断のみ", fv.SCOPE_LINES[1])
        self.assertIn("freee", fv.SCOPE_LINES[1])


class ExistingDirectionsUnchangedTest(unittest.TestCase):
    def test_direction_stages(self):
        stages = {d.key: d.stage for d in KNOWN_DIRECTIONS}
        self.assertEqual(stages[DIRECTION_KEY], DirectionStage.DIAGNOSE_ONLY)
        for key in ("moneyforward_journal_19->jdl_ibex_cashbook_35_5",
                    "yayoi_journal_report_generic->jdl_ibex_cashbook_35_5", "yayoi_import_25->jdl_ibex_cashbook_35_5"):
            self.assertIs(stages[key], DirectionStage.PRODUCTION)
        self.assertEqual(sum(1 for d in KNOWN_DIRECTIONS if d.stage is DirectionStage.PRODUCTION), 3)

    def test_freee_is_not_in_the_production_registry(self):
        from accounting_converter.infrastructure.adapter_registry import production_adapter_registry

        registry = production_adapter_registry()
        names = json.dumps([type(a).__module__ for a in getattr(registry, "adapters", ())] + [repr(registry)])
        self.assertNotIn("freee", names)


if __name__ == "__main__":
    unittest.main()
