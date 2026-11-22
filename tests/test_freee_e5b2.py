"""freee E5B-2A / 2B: the 税抜経理 consumption-tax row is never a taxable line of its own.

Synthetic fixtures (observed column NAMES, invented values "合成…"). The private originals are only read by
the opt-in E5B2RealEvidenceTest.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import unittest
from collections import Counter
from pathlib import Path

from accounting_converter.adapters.input.freee import journal_csv as jc
from accounting_converter.adapters.input.freee.journal_csv import (
    E5B2A_EVIDENCE_ID,
    E5B2B_EVIDENCE_ID,
    NEW_CSV_97_HEADER,
    OLD_CSV_29_HEADER,
    FreeeJournalCsvParser,
    FreeeJournalVariant,
)
from accounting_converter.application.freee_diagnosis import diagnose_parse_result
from accounting_converter.application.freee_other_export_diagnosis import diagnose_freee_jdl9, diagnose_freee_yayoi25
from accounting_converter.application.freee_tax_lines import (
    BLOCKER_AGGREGATED,
    BLOCKER_JDL_UNVERIFIED,
    BLOCKER_UNDETERMINABLE,
    BLOCKER_UNIDENTIFIED,
    TaxLineStatus,
    classify_tax_lines,
)
from accounting_converter.domain.journal_rows import journal_physical_rows
from accounting_converter.ui import freee_trial_view as fv
from tests.test_freee_e5b import BOTH, CREDIT_ONLY, DEBIT_ONLY, e5b_like_rows
from tests.test_freee_journal_csv import _cp932, _new, _new_side, _old, new_rows, old_rows, parse, yayoi25

SHAPE = "SYSTEM_EVIDENCE:FREEE_JOURNAL_SHAPE_UNOBSERVED"
UNOBSERVED = "SYSTEM_EVIDENCE:FREEE_VALUE_UNOBSERVED"
TAX_AMOUNT_ABSENT = "SYSTEM_EVIDENCE:FREEE_TAX_AMOUNT_ABSENT"
TAX_LINE_CODES = {BLOCKER_AGGREGATED, BLOCKER_JDL_UNVERIFIED, BLOCKER_UNDETERMINABLE, BLOCKER_UNIDENTIFIED}
CODE = "勘定科目ショートカット２（勘定科目コード）"
EXCLUSIVE = {"消費税経理処理方法": "税抜経理"}


def side(prefix, account, amount, category="対象外", rate="0", code="", memo=""):
    """A 税抜経理 side: 税金額 blank (as in E5B-2A / 2B), 内税, optional freee code and 備考."""
    values = _new_side(prefix, account, amount, category, "", rate)
    if code:
        values[f"{prefix}{CODE}"] = code
    if memo:
        values[f"{prefix}備考"] = memo
    return values


def tax_row(prefix, amount, category, rate="10", account=None, code=None, **changes):
    account = account or ("仮払消費税" if prefix == "借方" else "仮受消費税")
    code = code if code is not None else ("181" if prefix == "借方" else "361")
    return {**side(prefix, account, amount, category, rate, code), **changes}


def journal(no, jid, rows, day="2026-11-21", **common):
    return tuple(_new(no, jid, i, len(rows), day, **EXCLUSIVE, **common, **values) for i, values in enumerate(rows, 1))


def sale(no="1", jid="8800000101"):  # E5B-09 form: 1D1C + credit tax row
    return journal(no, jid, [
        {**side("借方", "合成現金", "1100", memo="合成"), **side("貸方", "合成売上", "1000", "課税売上10%", "10", "500", "合成")},
        tax_row("貸方", "100", "課税売上10%"),
    ])


def purchase(no="2", jid="8800000102"):  # E5B-10 form: 1D1C + debit tax row
    return journal(no, jid, [
        {**side("借方", "合成仕入", "500", "課対仕入10%", "10", "610", "合成"), **side("貸方", "合成現金", "550", memo="合成")},
        tax_row("借方", "50", "課対仕入10%"),
    ])


def aggregated_purchase(no="3", jid="8800000103"):  # E5B-01 form: 2D1C + one debit tax row for both lines
    return journal(no, jid, [
        {**side("借方", "合成費用", "300", "課対仕入10%", "10", "710", "合成"), **side("貸方", "合成現金", "550", memo="合成")},
        side("借方", "合成費用B", "200", "課対仕入10%", "10", "705"),
        tax_row("借方", "50", "課対仕入10%"),
    ])


def aggregated_sale(no="4", jid="8800000104"):  # E5B-02 form: 2D2C + one credit tax row
    return journal(no, jid, [
        {**side("借方", "合成現金", "660", memo="合成"), **side("貸方", "合成売上", "800", "課税売上10%", "10", "500", "合成")},
        {**side("借方", "合成売掛金", "440"), **side("貸方", "合成雑収入", "200", "課税売上10%", "10", "590")},
        tax_row("貸方", "100", "課税売上10%"),
    ])


def transitional(no="5", jid="8800000105"):  # E5B-05 form: 控80, non-deductible part left in the base amount
    return journal(no, jid, [
        {**side("借方", "合成費用", "102", "課対仕入（控80）10%", "10", "710", "合成"), **side("貸方", "合成現金", "110", memo="合成")},
        tax_row("借方", "8", "課対仕入（控80）10%"),
    ], day="2026-09-15")


def observed_tax_exclusive_rows():
    return (*sale(), *purchase(), *aggregated_purchase(), *aggregated_sale(), *transitional())


def diagnose(rows, header=NEW_CSV_97_HEADER):
    result = parse(header, rows)
    assert result.issues == (), result.issues
    assert result.accepted_rows == len(rows)
    return result, diagnose_parse_result(result)


class TaxLineIdentifiedTest(unittest.TestCase):
    def setUp(self):
        self.result, self.diagnosis = diagnose(observed_tax_exclusive_rows())

    def test_observed_structures_are_identified(self):
        statuses = {e.id: classify_tax_lines(e) for e in self.result.entries}
        self.assertEqual({c.status for c in statuses.values()}, {TaxLineStatus.IDENTIFIED})
        for entry in self.result.entries:
            classification = statuses[entry.id]
            tax = entry.lines[classification.tax_line]
            self.assertIn(tax.account, {"仮払消費税", "仮受消費税"})
            self.assertTrue(all(entry.lines[i].account.startswith("合成") for i in classification.base_lines))
        self.assertEqual(self.diagnosis.tax_lines, Counter({"IDENTIFIED": 5, "AGGREGATED": 2}))

    def test_tax_row_is_not_counted_as_a_taxable_line(self):
        # 6 base lines (incl. the two aggregated pairs) and 5 tax rows: only the base lines are taxable lines.
        taxed = {name: n for name, n in self.diagnosis.tax_categories.items() if name != "対象外"}
        self.assertEqual(taxed, {"課税売上10%": 3, "課対仕入10%": 3, "課対仕入（控80）10%": 1})
        self.assertEqual(self.diagnosis.tax["separate_tax_lines"], 5)
        report = self.diagnosis.to_dict()
        self.assertEqual(report["tax_lines"], {"AGGREGATED": 2, "IDENTIFIED": 5})
        self.assertEqual(report["tax_amounts"]["separate_tax_lines"], 5)

    def test_still_blocked_and_never_ready(self):
        aggregated = {e.id for e in self.result.entries if classify_tax_lines(e).aggregated}
        self.assertEqual(len(aggregated), 2)
        for entry in self.result.entries:
            blockers = set(self.diagnosis.journal_blockers[entry.id])
            with self.subTest(entry=entry.id):
                self.assertIn(BLOCKER_JDL_UNVERIFIED, blockers)
                self.assertEqual(BLOCKER_AGGREGATED in blockers, entry.id in aggregated)  # never allocated
                self.assertNotIn(BLOCKER_UNIDENTIFIED, blockers)
                self.assertFalse({SHAPE, UNOBSERVED} & blockers)
                self.assertIn(TAX_AMOUNT_ABSENT, blockers)  # base lines: 税金額 blank, never computed
                self.assertIn("HUMAN:TAX_MAPPING", blockers)
                self.assertIn("SYSTEM_IMPLEMENTATION:DIRECTION_NOT_PRODUCTION", blockers)
        self.assertEqual(self.diagnosis.formal_ready, 0)
        self.diagnosis.journal_blockers = {key: () for key in self.diagnosis.journal_blockers}
        self.assertEqual(self.diagnosis.formal_ready, 0)

    def test_amounts_are_not_changed(self):
        entry = self.result.entries[2]  # aggregated purchase: 300 + 200 + 50 = 550
        self.assertEqual(sorted(int(line.amount) for line in entry.lines), [50, 200, 300, 550])
        self.assertTrue(all(line.tax_info is None or line.tax_info.tax_amount is None for line in entry.lines))

    def test_tax_row_has_no_taxed_line_checks_of_its_own(self):
        # A purchase whose base line carried its 税金額 would not need TAX_AMOUNT_ABSENT; the tax row never adds it.
        entry = self.result.entries[1]
        classification = classify_tax_lines(entry)
        self.assertEqual(len(classification.base_lines), 1)
        self.assertNotIn(classification.tax_line, classification.base_lines)


class NotIdentifiedBlocksTest(unittest.TestCase):
    """Anything that is not exactly the observed structure: UNIDENTIFIED (blocks), whatever the account name."""

    def _status(self, rows):
        result, diagnosis = diagnose(rows)
        entry = result.entries[0]
        return classify_tax_lines(entry), set(diagnosis.journal_blockers[entry.id]), diagnosis

    def assert_unidentified(self, rows, reason):
        classification, blockers, diagnosis = self._status(rows)
        self.assertIs(classification.status, TaxLineStatus.UNIDENTIFIED)
        self.assertIn(reason, classification.reasons)
        self.assertIsNone(classification.tax_line)
        self.assertIn(BLOCKER_UNIDENTIFIED, blockers)
        self.assertNotIn("separate_tax_lines", diagnosis.tax)  # nothing is taken out of the taxable lines
        self.assertEqual(diagnosis.formal_ready, 0)

    def _purchase(self, base=None, tax=None):
        base_values = {**side("借方", "合成仕入", "500", "課対仕入10%", "10", "610", "合成"),
                       **side("貸方", "合成現金", "550", memo="合成")}
        return journal("1", "8800000201", [{**base_values, **(base or {})}, tax or tax_row("借方", "50", "課対仕入10%")])

    def test_name_or_code_alone_is_not_enough(self):
        renamed = tax_row("借方", "50", "課対仕入10%", account="合成仮払税")
        self.assert_unidentified(self._purchase(tax=renamed), "TAX_ROW_ACCOUNT_UNOBSERVED")
        other_code = tax_row("借方", "50", "課対仕入10%", code="999")
        self.assert_unidentified(self._purchase(tax=other_code), "TAX_ROW_ACCOUNT_UNOBSERVED")
        # Right name and code, but in the first row (not the last one-sided row).
        first = journal("1", "8800000202", [
            {**tax_row("借方", "50", "課対仕入10%"), **side("貸方", "合成現金", "550", memo="合成")},
            side("借方", "合成仕入", "500", "課対仕入10%", "10", "610"),
        ])
        self.assert_unidentified(first, "TAX_ROW_ACCOUNT_UNOBSERVED")  # the last row is then the ordinary line
        # Right name and code on the wrong side.
        wrong_side = journal("1", "8800000203", [
            {**side("借方", "合成現金", "1100", memo="合成"), **side("貸方", "合成売上", "1000", "課税売上10%", "10", "500", "合成")},
            tax_row("貸方", "100", "課税売上10%", account="仮払消費税", code="181"),
        ])
        self.assert_unidentified(wrong_side, "TAX_ROW_ACCOUNT_UNOBSERVED")

    def test_row_form_conditions(self):
        self.assert_unidentified(self._purchase(tax={**tax_row("借方", "50", "課対仕入10%"), "借方備考": "合成"}),
                                 "TAX_ROW_DESCRIPTION_NOT_BLANK")
        self.assert_unidentified(self._purchase(tax={**tax_row("借方", "50", "課対仕入10%"), "借方税金額": "5"}),
                                 "TAX_ROW_TAX_AMOUNT_NOT_BLANK")
        self.assert_unidentified(self._purchase(base={"借方税金額": "50"}), "OTHER_LINE_TAX_AMOUNT_NOT_BLANK")
        self.assert_unidentified(self._purchase(tax=tax_row("借方", "50", "対象外", rate="0")),
                                 "TAX_ROW_CATEGORY_NOT_TAXED_FOR_ITS_SIDE")
        # Both sides on the last row.
        both = journal("1", "8800000204", [
            {**side("借方", "合成仕入", "500", "課対仕入10%", "10", "610", "合成"), **side("貸方", "合成現金", "500", memo="合成")},
            {**tax_row("借方", "50", "課対仕入10%"), **side("貸方", "合成現金", "50")},
        ])
        self.assert_unidentified(both, "LAST_ROW_NOT_ONE_SIDED")

    def test_amount_relation(self):
        self.assert_unidentified(self._purchase(base={"借方金額": "50", "貸方金額": "100"}), "TAX_ROW_AMOUNT_OUT_OF_RANGE")

    def test_mixed_categories_or_rates_are_unobserved(self):
        mixed = journal("1", "8800000205", [
            {**side("借方", "合成費用", "300", "課対仕入10%", "10", "710", "合成"), **side("貸方", "合成現金", "624", memo="合成")},
            {**side("借方", "合成仕入", "300", "課対仕入8%（軽）", "8", "610"), "借方軽減税率有無": "1"},
            tax_row("借方", "24", "課対仕入8%（軽）", rate="8", 借方軽減税率有無="1"),
        ])
        self.assert_unidentified(mixed, "SAME_SIDE_LINE_WITH_OTHER_TAX")
        purchase_and_sale = journal("1", "8800000206", [
            {**side("借方", "合成仕入", "500", "課対仕入10%", "10", "610", "合成"),
             **side("貸方", "合成売上", "500", "課税売上10%", "10", "500", "合成")},
            {**tax_row("借方", "50", "課対仕入10%")},
            {**side("貸方", "合成現金", "50")},
        ])
        classification, blockers, _ = self._status(purchase_and_sale)
        self.assertIs(classification.status, TaxLineStatus.UNIDENTIFIED)

    def test_second_tax_account_line(self):
        two = journal("1", "8800000207", [
            {**side("借方", "合成仕入", "500", "課対仕入10%", "10", "610", "合成"), **side("貸方", "合成現金", "600", memo="合成")},
            tax_row("借方", "50", "課対仕入10%"),
            tax_row("借方", "50", "課対仕入10%"),
        ])
        self.assert_unidentified(two, "SECOND_TAX_ACCOUNT_LINE")

    def test_tax_exclusive_journal_without_tax_row(self):
        single = journal("1", "8800000208", [
            {**side("借方", "合成仕入", "550", "課対仕入10%", "10", "610", "合成"), **side("貸方", "合成現金", "550", memo="合成")},
        ])
        self.assert_unidentified(single, "SINGLE_ROW_JOURNAL")
        untaxed = journal("1", "8800000209", [
            {**side("借方", "合成預金", "100", memo="合成"), **side("貸方", "合成現金", "100", memo="合成")},
        ])
        self.assert_unidentified(untaxed, "NO_TAXED_LINE_UNOBSERVED")

    def test_unknown_values_and_columns_still_stop(self):
        rows = list(purchase())
        index = NEW_CSV_97_HEADER.index
        row = list(rows[0])
        row[index("借方税区分")] = row[index("借方税区分")].replace("課対仕入10%", "課対仕入（控50）10%")
        _result, diagnosis = diagnose([tuple(row), rows[1]])
        blockers = set(next(iter(diagnosis.journal_blockers.values())))
        self.assertIn(UNOBSERVED, blockers)
        self.assertIn(BLOCKER_UNIDENTIFIED, blockers)  # base and tax row no longer have the same 税区分
        extra = parse((*NEW_CSV_97_HEADER, "合成の新列"), [(*r, "") for r in purchase()])
        blockers = set(next(iter(diagnose_parse_result(extra).journal_blockers.values())))
        self.assertIn("SYSTEM_EVIDENCE:FREEE_HEADER_NOT_OBSERVED", blockers)


class LayoutBindingTest(unittest.TestCase):
    def test_tax_row_layouts_are_bound_to_e5b2_only(self):
        self.assertEqual(jc.evidence_for_tax_line_layout((BOTH, DEBIT_ONLY, DEBIT_ONLY)), (E5B2A_EVIDENCE_ID,))
        self.assertEqual(jc.evidence_for_tax_line_layout((BOTH, BOTH, CREDIT_ONLY)), (E5B2A_EVIDENCE_ID,))
        self.assertEqual(jc.evidence_for_tax_line_layout((BOTH, CREDIT_ONLY)), (E5B2A_EVIDENCE_ID, E5B2B_EVIDENCE_ID))
        self.assertEqual(jc.evidence_for_tax_line_layout((BOTH,)), ())
        # Seen only WITH a tax row: not an observed layout for an ordinary journal.
        for layout in ((BOTH, DEBIT_ONLY, DEBIT_ONLY), (BOTH, BOTH, CREDIT_ONLY)):
            self.assertNotIn(layout, jc.OBSERVED_ROW_LAYOUTS)
        self.assertEqual(jc.E5B2A_OBSERVATION.row_layouts, frozenset())
        self.assertEqual(jc.E5B2B_OBSERVATION.row_layouts, frozenset())
        self.assertEqual(jc.OBSERVED_TAX_LINE_ACCOUNTS, {("DEBIT", "仮払消費税", "181"), ("CREDIT", "仮受消費税", "361")})

    def test_identified_but_unobserved_layout_blocks(self):
        # 1D1C, a credit-only 対象外 row, then the debit tax row: all tax-row conditions hold, layout unseen.
        rows = journal("1", "8800000301", [
            {**side("借方", "合成仕入", "500", "課対仕入10%", "10", "610", "合成"), **side("貸方", "合成現金", "300", memo="合成")},
            side("貸方", "合成預金", "250"),
            tax_row("借方", "50", "課対仕入10%"),
        ])
        result, diagnosis = diagnose(rows)
        entry = result.entries[0]
        self.assertIs(classify_tax_lines(entry).status, TaxLineStatus.IDENTIFIED)
        self.assertIn(SHAPE, diagnosis.journal_blockers[entry.id])

    def test_tax_row_layout_without_tax_row_blocks_as_shape(self):
        # 3D1C under 税込経理 (no tax row): the E5B-2A layout does not make it observed.
        rows = tuple(_new("1", "8800000302", i, 3, "2026-11-21", **values) for i, values in enumerate([
            {**_new_side("借方", "合成費用", "330", "課対仕入10%", "30", "10"), **_new_side("貸方", "合成現金", "660")},
            _new_side("借方", "合成費用B", "220", "課対仕入10%", "20", "10"),
            _new_side("借方", "合成費用C", "110", "課対仕入10%", "10", "10"),
        ], 1))
        result, diagnosis = diagnose(rows)
        self.assertIs(classify_tax_lines(result.entries[0]).status, TaxLineStatus.NOT_APPLICABLE)
        self.assertIn(SHAPE, diagnosis.journal_blockers[result.entries[0].id])


class TaxInclusiveAndOldCsvTest(unittest.TestCase):
    def test_tax_inclusive_tax_account_line_is_an_ordinary_line(self):
        # A user-entered 仮払消費税 line under 税込経理 is not taken out of the taxable lines.
        rows = (
            _new("1", "8800000401", 1, 2, "2026-11-21", **_new_side("借方", "合成仕入", "550", "課対仕入10%", "50", "10"),
                 **_new_side("貸方", "合成現金", "600")),
            _new("1", "8800000401", 2, 2, "2026-11-21", **{**_new_side("借方", "仮払消費税", "50", "課対仕入10%", "", "10"),
                                                            f"借方{CODE}": "181"}),
        )
        result, diagnosis = diagnose(rows)
        self.assertIs(classify_tax_lines(result.entries[0]).status, TaxLineStatus.NOT_APPLICABLE)
        self.assertEqual(diagnosis.tax_categories["課対仕入10%"], 2)
        self.assertNotIn("separate_tax_lines", diagnosis.tax)

    def test_old_csv_tax_row_form_is_undeterminable(self):
        rows = (
            _old("1", "50101", "2026/11/21", 借方勘定科目="合成仕入", 借方金額="500", 借方税区分="課対仕入10%",
                 貸方勘定科目="合成現金", 貸方金額="550", 貸方税区分="対象外", 摘要="合成"),
            _old("1", "50101", "2026/11/21", 借方勘定科目="仮払消費税", 借方金額="50", 借方税区分="課対仕入10%",
                 貸方勘定科目="", 貸方金額="0", 貸方税区分="対象外", 借方勘定科目コード="181"),
        )
        result, diagnosis = diagnose(rows, OLD_CSV_29_HEADER)
        entry = result.entries[0]
        self.assertIs(classify_tax_lines(entry).status, TaxLineStatus.UNDETERMINABLE)
        blockers = set(diagnosis.journal_blockers[entry.id])
        self.assertIn(BLOCKER_UNDETERMINABLE, blockers)
        self.assertIn("HUMAN:FREEE_TAX_ACCOUNTING_METHOD_UNKNOWN", blockers)
        self.assertEqual(diagnosis.tax_lines, Counter({"UNDETERMINABLE": 1}))
        self.assertEqual(diagnosis.formal_ready, 0)
        # Same form with an ordinary account name: still undeterminable (the name decides nothing).
        renamed = (rows[0], _old("1", "50101", "2026/11/21", 借方勘定科目="合成費用B", 借方金額="50", 借方税区分="課対仕入10%",
                                 貸方勘定科目="", 貸方金額="0", 貸方税区分="対象外"))
        result, _ = diagnose(renamed, OLD_CSV_29_HEADER)
        self.assertIs(classify_tax_lines(result.entries[0]).status, TaxLineStatus.UNDETERMINABLE)

    def test_old_csv_cannot_tell_a_tax_row_from_an_ordinary_line(self):
        """Why the 旧CSV blocks: the 税抜経理 tax row (E5B-2B form) and an ordinary 税込経理 second line (E5B-01
        form) are the SAME in the 旧CSV except for account name and amount. Neither is called a tax row."""
        def form(rows):
            return [(r[OLD_CSV_29_HEADER.index("借方税区分")], r[OLD_CSV_29_HEADER.index("貸方勘定科目")] == "",
                     r[OLD_CSV_29_HEADER.index("貸方金額")], r[OLD_CSV_29_HEADER.index("貸方税区分")],
                     r[OLD_CSV_29_HEADER.index("摘要")] == "") for r in rows[1:]]

        tax_exclusive = (
            _old("1", "50201", "2026/11/21", 借方勘定科目="合成仕入", 借方金額="500", 借方税区分="課対仕入10%",
                 貸方勘定科目="合成現金", 貸方金額="550", 貸方税区分="対象外", 摘要="合成"),
            _old("1", "50201", "2026/11/21", 借方勘定科目="仮払消費税", 借方金額="50", 借方税区分="課対仕入10%",
                 貸方勘定科目="", 貸方金額="0", 貸方税区分="対象外", 借方勘定科目コード="181"),
        )
        ordinary = (
            _old("1", "50202", "2026/11/09", 借方勘定科目="合成費用", 借方金額="330", 借方税区分="課対仕入10%",
                 貸方勘定科目="合成現金", 貸方金額="550", 貸方税区分="対象外", 摘要="合成"),
            _old("1", "50202", "2026/11/09", 借方勘定科目="合成費用B", 借方金額="220", 借方税区分="課対仕入10%",
                 貸方勘定科目="", 貸方金額="0", 貸方税区分="対象外"),
        )
        self.assertEqual(form(tax_exclusive), form(ordinary))
        for rows in (tax_exclusive, ordinary):
            result, diagnosis = diagnose(rows, OLD_CSV_29_HEADER)
            entry = result.entries[0]
            classification = classify_tax_lines(entry)
            self.assertIs(classification.status, TaxLineStatus.UNDETERMINABLE)
            self.assertIsNone(classification.tax_line)  # never "identified": no line is taken out
            self.assertNotIn("IDENTIFIED", diagnosis.tax_lines)
            self.assertNotIn("separate_tax_lines", diagnosis.tax)
            self.assertEqual(diagnosis.tax_categories["課対仕入10%"], 2)  # both stay ordinary taxable lines
            self.assertEqual(diagnosis.formal_ready, 0)
        # The 新CSV can tell them apart: the same ordinary form under 税込経理 is NOT_APPLICABLE.
        self.assertIs(classify_tax_lines(parse(NEW_CSV_97_HEADER, e5b_like_rows()[:2]).entries[0]).status,
                      TaxLineStatus.NOT_APPLICABLE)

    def test_old_csv_wording_says_not_confirmed(self):
        label = fv.REASON_LABELS[BLOCKER_UNDETERMINABLE]
        self.assertIn("確定したわけではありません", label)
        _result, diagnosis = diagnose(
            (_old("1", "50203", "2026/11/21", 借方勘定科目="合成仕入", 借方金額="500", 借方税区分="課対仕入10%",
                  貸方勘定科目="合成現金", 貸方金額="550", 貸方税区分="対象外", 摘要="合成"),
             _old("1", "50203", "2026/11/21", 借方勘定科目="合成費用", 借方金額="50", 借方税区分="課対仕入10%",
                  貸方勘定科目="", 貸方金額="0", 貸方税区分="対象外")), OLD_CSV_29_HEADER)
        text = "\n".join(fv._tax_lines(diagnosis))
        self.assertIn("消費税の行とは確定していません", text)
        self.assertNotIn("消費税の行（税抜経理の仮払・仮受消費税）", text)  # no "separate tax line" claim

    def test_new_csv_without_a_method_value_is_undeterminable_not_identified(self):
        rows = tuple(tuple("" if name == "消費税経理処理方法" else value for name, value in zip(NEW_CSV_97_HEADER, row))
                     for row in purchase())
        result, diagnosis = diagnose(rows)
        entry = result.entries[0]
        self.assertIs(classify_tax_lines(entry).status, TaxLineStatus.UNDETERMINABLE)
        self.assertIn(BLOCKER_UNDETERMINABLE, diagnosis.journal_blockers[entry.id])
        self.assertNotIn("separate_tax_lines", diagnosis.tax)

    def test_old_csv_simple_journal_is_not_flagged(self):
        row = _old("1", "50102", "2026/11/21", 借方勘定科目="合成仕入", 借方金額="550", 借方税区分="課対仕入10%",
                   貸方勘定科目="合成現金", 貸方金額="550", 貸方税区分="対象外", 摘要="合成")
        result, diagnosis = diagnose([row], OLD_CSV_29_HEADER)
        self.assertIs(classify_tax_lines(result.entries[0]).status, TaxLineStatus.NOT_APPLICABLE)
        self.assertFalse(TAX_LINE_CODES & set(diagnosis.journal_blockers[result.entries[0].id]))


class RegressionTest(unittest.TestCase):
    """E4 / E5B第1回 forms (税込経理): no tax-row code on the 新CSV, nothing taken out of the taxable lines."""

    def test_new_csv_tax_inclusive_unchanged(self):
        for name, rows, taxed_lines in (("E4", new_rows(), 3), ("E5B1", e5b_like_rows(), 10)):
            with self.subTest(name):
                result, diagnosis = diagnose(rows)
                self.assertEqual({classify_tax_lines(e).status for e in result.entries}, {TaxLineStatus.NOT_APPLICABLE})
                for codes in diagnosis.journal_blockers.values():
                    self.assertFalse(TAX_LINE_CODES & set(codes))
                self.assertEqual(sum(n for k, n in diagnosis.tax_categories.items() if k not in {"対象外", "非課売上"}),
                                 taxed_lines)
                self.assertNotIn("separate_tax_lines", diagnosis.tax)
                self.assertEqual(diagnosis.formal_ready, 0)

    def test_old_csv_tax_inclusive_two_line_form_now_also_undeterminable(self):
        # E4 1D2C (two 課税売上 credits) has the tax-row form in the 旧CSV: it gains UNDETERMINABLE (fail closed);
        # the other journals are unchanged.
        result, diagnosis = diagnose(old_rows(), OLD_CSV_29_HEADER)
        flagged = [e for e in result.entries if BLOCKER_UNDETERMINABLE in diagnosis.journal_blockers[e.id]]
        self.assertEqual([e.metadata[jc.DISPLAY_NUMBER_KEY] for e in flagged], ["2"])


class LabelsAndOtherExportsTest(unittest.TestCase):
    def test_new_codes_have_labels_and_priority(self):
        for code in TAX_LINE_CODES:
            self.assertIn(code, fv.REASON_LABELS)
            self.assertIn(code, fv._MAIN_REASON_PRIORITY)

    def test_view_reports_tax_rows_separately(self):
        _result, diagnosis = diagnose(observed_tax_exclusive_rows())
        lines = fv._tax_lines(diagnosis)
        self.assertTrue(any("消費税の行" in line and "5行" in line for line in lines))
        self.assertTrue(any("税抜経理" in line for line in lines))
        rows = fv._tax_rows(diagnosis)
        self.assertFalse(any("観測していない" in kind for _, _, kind in rows))  # 控80 etc. are observed

    def test_yayoi25_tax_amount_counted(self):
        rows = [yayoi25("2000", day="2026/11/21", debit=("合成仕入", "", "課対仕入10%", "550", "50"))]
        report = diagnose_freee_yayoi25(_cp932(rows)).to_dict()
        self.assertEqual(report["counts"]["taxed_sides_with_tax_amount"], 1)
        self.assertNotIn("taxed_sides_with_blank_tax_amount", report["counts"])


# ----------------------------------------------------------------------------- real Evidence (opt-in, read-only)

E5B_DIR = Path(__file__).resolve().parents[1] / "data" / "private" / "freee_e5b_20261122"
E5B2_FILES = {
    "2a_new": ("after_tax_exclusive_existing/仕訳帳（新）CSV （2026年09月~2026年11月） (1).csv",
               "ab5ca872b004fa478b35f0b57ba081fbd539aa1c4dbeae2ea4abbd2a584aa591"),
    "2b_new": ("after_tax_exclusive_new/仕訳帳（新）CSV （2026年11月~2026年11月）.csv",
               "da516a4522c46a730a21516d0faf7b9d69deba6d5f6ed05703008b3182129d33"),
    "2b_old": ("after_tax_exclusive_new/仕訳帳（旧）CSV （2026年11月~2026年11月）.csv",
               "894837579ac535b066c0ac6dabb1e0cd1c100954557ff8fecb6fa776f6ee5717"),
    "2b_jdl9": ("after_tax_exclusive_new/仕訳帳 JDLインポート形式 （2026年11月~2026年11月）.csv",
                "78e0427d050a221223e3c1198469454a34551d77c121417fce6b3e0fa6ea815d"),
    "2b_yayoi25": ("after_tax_exclusive_new/仕訳帳 弥生会計インポート形式 （2026年11月~2026年11月）.csv",
                   "f758aa09b4f9f69616d53ea6cbfffd1d8ff2aba3616c02e2473ecc470539ecda"),
}


@unittest.skipUnless(all((E5B_DIR / name).is_file() for name, _ in E5B2_FILES.values()),
                     "private freee E5B-2 Evidence not present")
class E5B2RealEvidenceTest(unittest.TestCase):
    """Reads the private originals (bytes only) and checks the registered observations against them."""

    def setUp(self):
        self.raw = {}
        for key, (name, digest) in E5B2_FILES.items():
            self.raw[key] = (E5B_DIR / name).read_bytes()
            self.assertEqual(hashlib.sha256(self.raw[key]).hexdigest(), digest, name)

    def _parse(self, key):
        return FreeeJournalCsvParser().parse_bytes(self.raw[key], Path(E5B2_FILES[key][0]).name)

    def test_registered_observations_equal_the_files(self):
        for observation, keys in ((jc.E5B2A_OBSERVATION, ("2a_new",)), (jc.E5B2B_OBSERVATION, ("2b_new", "2b_old"))):
            seen_values: dict[str, set[str]] = {}
            for key in keys:
                result = self._parse(key)
                variant = result.header.variant
                self.assertIn(result.header.fingerprint, observation.header_fingerprints)
                columns = {name for e in result.entries for name, _ in e.metadata[jc.NONBLANK_COLUMNS_KEY]}
                self.assertEqual(columns, observation.columns_with_values[variant], key)
                rows = list(csv.reader(io.StringIO(self.raw[key].decode("utf-8"), newline="")))
                for record in (dict(zip(rows[0], row)) for row in rows[1:]):
                    for name, value in record.items():
                        base = name[2:] if name[:2] in {"借方", "貸方"} else name
                        if value and base in observation.value_sets:
                            seen_values.setdefault(base, set()).add(value)
                if variant is FreeeJournalVariant.NEW_CSV:
                    layouts = {tuple((r.debit is not None, r.credit is not None) for r in journal_physical_rows(e))
                               for e in result.entries}
                    self.assertEqual(layouts, set(observation.tax_line_layouts), key)
                    self.assertEqual({e.metadata[jc.REGISTRATION_SOURCE_KEY] for e in result.entries},
                                     set(observation.registration_sources))
                    accounts = {(e.lines[c.tax_line].side.value, e.lines[c.tax_line].account,
                                 e.lines[c.tax_line].metadata[jc.LINE_ACCOUNT_CODE_KEY])
                                for e in result.entries for c in [classify_tax_lines(e)]}
                    self.assertEqual(accounts, set(observation.tax_line_accounts))
            self.assertEqual({k: set(v) for k, v in observation.value_sets.items()}, seen_values, observation.evidence_id)

    def test_diagnosis_of_the_real_files(self):
        for key, rows, journals, statuses, separate in (
            ("2a_new", 18, 8, {"IDENTIFIED": 8, "AGGREGATED": 2}, 8),
            ("2b_new", 4, 2, {"IDENTIFIED": 2}, 2),
            ("2b_old", 4, 2, {"UNDETERMINABLE": 2}, 0),
        ):
            with self.subTest(key):
                result = self._parse(key)
                self.assertEqual((result.data_rows, result.accepted_rows, len(result.entries), result.issues),
                                 (rows, rows, journals, ()))
                diagnosis = diagnose_parse_result(result)
                self.assertEqual(dict(diagnosis.tax_lines), statuses)
                self.assertEqual(diagnosis.tax.get("separate_tax_lines", 0), separate)
                self.assertEqual(diagnosis.formal_ready, 0)
                blockers = Counter(code for codes in diagnosis.journal_blockers.values() for code in codes)
                self.assertNotIn(UNOBSERVED, blockers)
                self.assertNotIn(SHAPE, blockers)
                self.assertNotIn(BLOCKER_UNIDENTIFIED, blockers)
                self.assertEqual(blockers["SYSTEM_IMPLEMENTATION:DIRECTION_NOT_PRODUCTION"], journals)
                if key != "2b_old":
                    self.assertEqual(blockers[BLOCKER_JDL_UNVERIFIED], journals)
                    self.assertEqual(blockers[BLOCKER_AGGREGATED], statuses.get("AGGREGATED", 0))
                    self.assertEqual(diagnosis.tax_accounting_methods, {"税抜経理": journals})
                self.assertNotIn("@", json.dumps(diagnosis.to_dict(), ensure_ascii=False))

    def test_other_exports_of_e5b2b(self):
        jdl = diagnose_freee_jdl9(self.raw["2b_jdl9"])
        self.assertTrue(jdl.readable)
        self.assertEqual(jdl.counts["data_rows"], 6)  # 2 journals x (base, relay, tax)
        self.assertEqual(dict(jdl.values["課区/税区"]), {"0/0": 2, "11/10": 2, "31/10": 2})
        self.assertEqual(jdl.information_loss, Counter())
        yayoi = diagnose_freee_yayoi25(self.raw["2b_yayoi25"])
        self.assertTrue(yayoi.readable)
        self.assertEqual(yayoi.counts["data_rows"], 2)  # one 2000 row per journal: no tax row
        self.assertEqual(yayoi.counts["taxed_sides_with_tax_amount"], 2)
        self.assertEqual(yayoi.counts["taxed_sides_with_blank_tax_amount"], 0)


if __name__ == "__main__":
    unittest.main()
