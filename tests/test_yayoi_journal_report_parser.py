"""Yayoi 仕訳日記帳 (汎用形式) parser, with synthetic data only.

All names, amounts and descriptions are invented. The report format has no
2000/2111/2110 identifier flags; multi-row journals are consecutive rows with
the same date and 伝票No., which these tests cover instead.
"""
from __future__ import annotations

import csv
import io
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from accounting_converter.adapters.input.yayoi.journal_report_parser import (
    HEADER,
    YayoiJournalReportParseError,
    YayoiJournalReportParser,
    yayoi_source_tax_identity,
)
from accounting_converter.adapters.output.jdl import (
    JDL_OUTPUT_METADATA_KEY,
    jdl_ibex_35_5_output_profile,
)
from accounting_converter.adapters.output.jdl.preflight import JdlOutputPreflight
from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
from accounting_converter.domain.journal_identity import stable_journal_identity
from accounting_converter.domain.journal_rows import journal_physical_rows
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from tests.test_mf_tax_capability_composition import ACCOUNTS, context

NAME = {code: name for code, name in ACCOUNTS.items()}


def detail(date, voucher, *, debit=None, credit=None, description="", number=1, invoice="", credit_ratio="", sticky="", closing=""):
    """debit/credit: (account, sub, tax, amount, tax_amount)."""
    row = {name: "" for name in HEADER}
    row.update({"[表題行]": "[明細行]", "日付": date, "伝票No.": str(voucher), "決算": closing, "調整": "NO",
                "付箋1": sticky, "タイプ": "[振伝]", "摘要": description, "作業日付": date, "仕訳番号": str(number),
                "借方税区分": "対象外", "貸方税区分": "対象外", "請求書区分": invoice, "仕入税額控除": credit_ratio})
    for prefix, side in (("借方", debit), ("貸方", credit)):
        if side is None:
            continue
        account, sub, tax, amount, tax_amount = side
        row.update({f"{prefix}勘定科目": account, f"{prefix}補助科目": sub, f"{prefix}税区分": tax,
                    f"{prefix}金額": str(amount), f"{prefix}税額": "" if tax_amount is None else str(tax_amount),
                    f"{prefix}税計算区分": "内税" if tax_amount is not None else ""})
    return [row[name] for name in HEADER]


def build(details, *, period=("令和08年05月01日", "令和08年05月31日"), report="仕訳日記帳", fmt="汎用形式", totals=True):
    rows = [["帳票名", report], ["書式名", fmt], ["事業所名", "テスト事業所"], ["処理日時", "令和08年06月01日", "10:00:00"],
            ["検索条件", ""], ["集計期間", *period, "決算仕訳を含む"], ["当日仕訳", "NO"], list(HEADER)]
    by_day: dict[str, list[list[str]]] = {}
    for row in details:
        by_day.setdefault(row[1], []).append(row)
    month = [0, 0, 0, 0]
    for day, day_rows in by_day.items():
        rows.extend(day_rows)
        if totals:
            sums = [sum(int(r[HEADER.index(c)] or 0) for r in day_rows) for c in ("借方金額", "借方税額", "貸方金額", "貸方税額")]
            month = [a + b for a, b in zip(month, sums)]
            total = ["[日次合計行]"] + [""] * 30
            for c, v in zip(("借方金額", "借方税額", "貸方金額", "貸方税額"), sums):
                total[HEADER.index(c)] = str(v)
            rows.append(total)
    if totals:
        total = ["[月度合計行]"] + [""] * 30
        for c, v in zip(("借方金額", "借方税額", "貸方金額", "貸方税額"), month):
            total[HEADER.index(c)] = str(v)
        rows.append(total)
    return rows


def write(directory, rows, name="yayoi.txt", raw=None):
    path = Path(directory) / name
    if raw is None:
        buffer = io.StringIO(newline="")
        csv.writer(buffer, lineterminator="\r\n").writerows(rows)
        raw = buffer.getvalue().encode("cp932")
    path.write_bytes(raw)
    return path


BANK, FEE, SALES = NAME["1311"], NAME["8681"], NAME["6121"]
OUTSIDE = "対象外"


def standard_details():
    return [
        # 1D1C purchase with explicit tax equal to the verified floor pattern.
        detail("令和08年05月10日", 1, debit=(FEE, "", "課対仕入内10%", 1100, 100), credit=(BANK, "銀行A", OUTSIDE, 1100, None),
               description="振込, 手数料", number=11, invoice="適格", credit_ratio="100%"),
        # 2D1C: two rows, the second debit-only, row-specific descriptions.
        detail("令和08年05月10日", 2, debit=(NAME["3561"], "", OUTSIDE, 500, None), credit=(BANK, "銀行A", OUTSIDE, 1100, None),
               description="ROW-1", number=12),
        detail("令和08年05月10日", 2, debit=(FEE, "", "課対仕入内10%", 600, 55), description="ROW-2", number=13,
               invoice="適格", credit_ratio="100%"),
        # Same 伝票No. reused on another date: a different journal.
        detail("令和08年05月11日", 2, debit=(NAME["1111"], "", OUTSIDE, 1100, None), credit=(SALES, "", "課税売上内10%", 1100, 100),
               description="売上", number=14, sticky="1", closing=""),
    ]


class ParserTest(unittest.TestCase):
    def test_groups_rows_semantics_and_explicit_tax(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            entries = YayoiJournalReportParser().parse_path(write(directory, build(standard_details())))
        self.assertEqual(len(entries), 3)
        compound = entries[1]
        rows = journal_physical_rows(compound)
        self.assertEqual([row.description for row in rows], ["ROW-1", "ROW-2"])
        self.assertIsNone(rows[1].credit)
        self.assertEqual(compound.lines[2].tax_info.tax_amount, Decimal("55"))
        self.assertEqual(entries[0].description, "振込, 手数料")
        self.assertEqual(entries[0].lines[0].tax_info.category, "課対仕入内10%｜適格｜100%")
        self.assertEqual(entries[2].metadata["yayoi_optional_fields"], {"付箋1": 1})
        self.assertTrue(all(entry.is_balanced() for entry in entries))

    def test_identity_ignores_row_numbers_work_date_and_file_name(self) -> None:
        details = standard_details()
        renumbered = [list(row) for row in details]
        for row in renumbered:
            row[HEADER.index("仕訳番号")] = "9" + row[HEADER.index("仕訳番号")]
            row[HEADER.index("作業日付")] = "令和08年06月30日"
        with tempfile.TemporaryDirectory() as directory:
            first = YayoiJournalReportParser().parse_path(write(directory, build(details), "a.txt"))
            second = YayoiJournalReportParser().parse_path(write(directory, build(renumbered), "b.txt"))
        self.assertEqual([stable_journal_identity(e) for e in first], [stable_journal_identity(e) for e in second])

    def test_purchase_credit_ratio_is_a_separate_tax_identity(self) -> None:
        self.assertNotEqual(
            yayoi_source_tax_identity("課対仕入内10%", "区分記載", "80%経過措置"),
            yayoi_source_tax_identity("課対仕入内10%", "適格", "100%"),
        )
        self.assertEqual(yayoi_source_tax_identity("対象外", "", ""), "対象外")

    def test_fail_closed_cases(self) -> None:
        good = standard_details()
        bad_column = [list(row) for row in good]
        bad_column[0] = bad_column[0][:-1]
        bad_date = [list(row) for row in good]
        bad_date[0][1] = "2026/05/10"
        incomplete = [list(row) for row in good]
        incomplete[3][HEADER.index("借方税額")] = "5"
        incomplete[3][HEADER.index("借方勘定科目")] = ""
        no_category = [list(row) for row in good]
        no_category[0][HEADER.index("借方税区分")] = ""
        nonconsecutive = good + [detail("令和08年05月10日", 1, debit=(FEE, "", OUTSIDE, 10, None),
                                         credit=(BANK, "銀行A", OUTSIDE, 10, None), number=99)]
        unbalanced = [list(row) for row in good]
        unbalanced[0][HEADER.index("貸方金額")] = "1000"
        cases = {
            "COLUMN_COUNT": build(bad_column),
            "DATE_FORMAT": build(bad_date),
            "DATE_OUT_OF_PERIOD": build(good, period=("令和08年05月11日", "令和08年05月31日")),
            "SIDE_INCOMPLETE": build(incomplete),
            "TAX_AMOUNT_WITHOUT_TAX_CATEGORY": build(no_category),
            # 伝票1 on 05/10 appears again after 伝票2 on the same date.
            "NONCONSECUTIVE_VOUCHER": build(good[:3] + nonconsecutive[-1:] + good[3:]),
            "UNBALANCED_JOURNAL": build(unbalanced),
            "REPORT_TYPE": build(good, report="総勘定元帳"),
            "REPORT_FORMAT": build(good, fmt="弥生インポート形式"),
            "ADJUSTMENT_UNOBSERVED": build([good[0][:4] + ["YES"] + good[0][5:]] + good[1:]),
            "TYPE_UNOBSERVED": build([good[0][:7] + ["[出伝]"] + good[0][8:]] + good[1:]),
            "FILTERED_REPORT": [["検索条件", "条件あり"] if row[0] == "検索条件" else row for row in build(good)],
        }
        for code, rows in cases.items():
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                path = write(directory, rows)
                result = YayoiJournalReportParser().diagnose(path)
                self.assertIn(code, {issue.code for issue in result.issues})
                with self.assertRaises(YayoiJournalReportParseError):
                    YayoiJournalReportParser().parse_path(path)

    def test_totals_unknown_rows_and_encoding(self) -> None:
        good = build(standard_details())
        mismatch = [list(row) for row in good]
        daily = next(i for i, row in enumerate(mismatch) if row[0] == "[日次合計行]")
        mismatch[daily][HEADER.index("借方金額")] = "1"
        unknown = good[:9] + [["[謎の行]"] + [""] * 30] + good[9:]
        with tempfile.TemporaryDirectory() as directory:
            codes = lambda rows: {i.code for i in YayoiJournalReportParser().diagnose(write(directory, rows)).issues}
            self.assertIn("DAILY_TOTAL_MISMATCH", codes(mismatch))
            self.assertIn("ROW_TYPE_UNKNOWN", codes(unknown))
            broken = write(directory, None, "bad.txt", raw=b"\x82")
            self.assertEqual({i.code for i in YayoiJournalReportParser().diagnose(broken).issues}, {"ENCODING"})


def profile(confirmed=True):
    ctx = context()
    mappings = {}
    for identity, target, scope in (
        ("課対仕入内10%｜適格｜100%", "10%", "仕　入"),
        ("課税売上内10%", "10%", "売　上"),
        ("対象外", "", ""),
    ):
        mappings[identity] = MappingValue(
            identity, target, MappingStatus.USER_CONFIRMED if confirmed else MappingStatus.UNRESOLVED,
            metadata={"jdl_tax_scope": scope, "jdl_tax_context_identity_sha256": ev.tax_context_identity_sha256(ctx)},
        )
    from types import SimpleNamespace
    return SimpleNamespace(account_mappings={}, subaccount_context_mappings={}, tax_mappings=mappings)


class YayoiToJdlTargetTest(unittest.TestCase):
    def entries(self, details=None):
        with tempfile.TemporaryDirectory() as directory:
            return YayoiJournalReportParser().parse_path(write(directory, build(details or standard_details())))

    def test_confirmed_mapping_reaches_jdl_preflight_with_source_tax(self) -> None:
        purchase = self.entries()[0]
        purchase.lines[1].sub_account = "銀行A"
        result = ev.match_evidence_for_occurrence(purchase, purchase, context(), profile())
        self.assertIsNotNone(result.evidence, result.mismatch_fields)
        literal = ev.apply_verified_tax_semantics(purchase, purchase, context(), profile())
        literal.metadata[JDL_OUTPUT_METADATA_KEY] = result.evidence.profile.value
        preflight = JdlOutputPreflight(context()).evaluate((literal,), jdl_ibex_35_5_output_profile())
        self.assertEqual(preflight.validation_results, ())
        self.assertEqual(preflight.plan.rows[0].debit_tax_amount, "100")

    def test_unconfirmed_mapping_blocks(self) -> None:
        purchase = self.entries()[0]
        result = ev.match_evidence_for_occurrence(purchase, purchase, context(), profile(confirmed=False))
        self.assertIsNone(result.evidence)
        self.assertIn("TAX_MAPPING_UNCONFIRMED", result.mismatch_fields)

    def test_half_up_explicit_tax_is_blocked_as_unverified(self) -> None:
        # 1105 * 10 / 110 = 100.45 -> floor 100; 1106 -> 100.54: half-up 101.
        details = [detail("令和08年05月10日", 1, debit=(FEE, "", "課対仕入内10%", 1106, 101),
                          credit=(BANK, "銀行A", OUTSIDE, 1106, None), invoice="適格", credit_ratio="100%")]
        purchase = self.entries(details)[0]
        from dataclasses import replace

        from accounting_converter.adapters.output.jdl import JdlTaxRounding

        expected = {
            # JDL 端数処理 unknown: Human must record it first.
            JdlTaxRounding.UNCONFIRMED: "JDL_TAX_ROUNDING_UNCONFIRMED",
            # Matches the target setting, but only floor values are proven.
            JdlTaxRounding.HALF_UP: "EXPLICIT_TAX_COMPANY_ROUNDING_UNVERIFIED",
            # Matches neither the target setting nor floor.
            JdlTaxRounding.FLOOR: "EXPLICIT_TAX_AMOUNT_UNVERIFIED",
        }
        for rounding, gap in expected.items():
            with self.subTest(rounding=rounding):
                target = replace(context(), purchase_tax_rounding=rounding)
                result = ev.match_evidence_for_occurrence(purchase, purchase, target, profile())
                self.assertIsNone(result.evidence)
                self.assertIn(gap, result.mismatch_fields)


if __name__ == "__main__":
    unittest.main()
