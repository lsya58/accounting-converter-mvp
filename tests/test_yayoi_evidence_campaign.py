"""Evidence campaign tools: planning keys and synthetic probe serialization. Synthetic data only."""
from __future__ import annotations

import csv
import io
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from accounting_converter.adapters.output.jdl import JdlTaxRounding
from accounting_converter.domain.journal import JournalEntry, JournalLine, Side, SourceReference, TaxInfo
from accounting_converter.domain.journal_rows import LINE_ROW_DESCRIPTION_KEY, LINE_ROW_KEY, ROW_ORDER_KEY
from accounting_converter.profiles.jdl_official import jdl_ibex_cashbook_official_journal_import_spec
from accounting_converter.tools import generate_yayoi_evidence_campaign as gen
from accounting_converter.tools import yayoi_evidence_campaign as campaign
from accounting_converter.tools.yayoi_probe_check import check
from tests.test_mf_tax_capability_composition import context

REF = SourceReference("synthetic", 1)
ACCOUNTS = {"cash": "1111", "purchase": "8681", "no_tax_credit": "3141",
            "credit_purchase": ["8681", "8491", "8571"], "nonpur": ["8571", "8491", "8681"]}


def buddies_like_context():
    return replace(context(), sales_tax_rounding=JdlTaxRounding.CEILING, purchase_tax_rounding=JdlTaxRounding.HALF_UP)


def yayoi_entry(rows, closing=False) -> JournalEntry:
    """rows: [(debit, credit)] with each side (tax identity, amount, explicit tax) or None."""
    lines = []
    for number, row in enumerate(rows, start=1):
        for side, spec in zip((Side.DEBIT, Side.CREDIT), row):
            if spec is None:
                continue
            identity, amount, tax = spec
            lines.append(JournalLine(side, "科目", Decimal(amount), REF,
                                     tax_info=TaxInfo(category=identity, tax_amount=None if tax is None else Decimal(tax)),
                                     metadata={LINE_ROW_KEY: number, LINE_ROW_DESCRIPTION_KEY: "x"}))
    metadata = {ROW_ORDER_KEY: tuple(range(1, len(rows) + 1))}
    if closing:
        metadata["yayoi_closing"] = True
    return JournalEntry("j", REF, date(2026, 1, 1), lines, metadata=metadata)


SALES = "課税売上10%"
OUT = "対象外"


class CampaignKeysTest(unittest.TestCase):
    def keys(self, rows, **kw):
        return campaign.journal_keys(yayoi_entry(rows, **kw), buddies_like_context())[0]

    def test_taxed_2d2c_is_keyed_by_its_exact_layout(self):
        keys = self.keys([((OUT, 1100, None), (SALES, 1100, 100)), ((OUT, 1100, None), (SALES, 1100, 100))])
        self.assertIn("TAXED_2D2C_LAYOUT:C:S10,C:S10", keys)
        self.assertNotIn("MULTI_TAXED:2D2C", keys)

    def test_company_rounding_explicit_tax_and_floor_tax_are_different_questions(self):
        ceil = self.keys([((OUT, 1105, None), (SALES, 1105, 101))])
        floor = self.keys([((OUT, 1105, None), (SALES, 1105, 100))])
        self.assertIn("EXPLICIT_TAX:EXPLICIT_TAX_COMPANY_ROUNDING_UNVERIFIED:CREDIT:JDL_SALES_10_EXTERNAL", ceil)
        self.assertIn("EXPLICIT_TAX:EXPLICIT_TAX_KEEP_UNVERIFIED:CREDIT:JDL_SALES_10_EXTERNAL", floor)
        self.assertIn("SALES10_TARGET_ACCOUNT", ceil)  # sales 10% is account-specific

    def test_unknown_representations_need_self_export_and_known_ones_do_not(self):
        export = self.keys([((OUT, 1100, None), ("輸出売上", 1100, None))])
        reduced = self.keys([(("課対仕入8%（軽）｜適格｜100%", 1080, 80), (OUT, 1080, None))])
        transitional = self.keys([(("課対仕入10%｜区分記載｜80%経過措置", 1100, 100), (OUT, 1100, None))])
        non_deductible = self.keys([(("課対仕入8%（軽）｜区分記載｜控除不可", 1080, 80), (OUT, 1080, None))])
        out_of_scope = self.keys([(("対外仕入", 1100, None), (OUT, 1100, None))])
        self.assertIn("TAX_UNAVAILABLE:EXPORT_EXEMPT:CREDIT", export)
        self.assertIn("TAX_UNAVAILABLE:REDUCED_8:DEBIT", reduced)
        self.assertIn("TAX_UNAVAILABLE:TRANSITIONAL_80:DEBIT", transitional)
        self.assertIn("TAX_UNAVAILABLE:NON_DEDUCTIBLE:DEBIT", non_deductible)
        self.assertIn("TAX_UNAVAILABLE:OUT_OF_SCOPE_KNOWN_REPRESENTATION:DEBIT", out_of_scope)
        self.assertIn("CLOSING_ENTRY", self.keys([((OUT, 1100, None), (OUT, 1100, None))], closing=True))

    def test_row_pattern_and_class(self):
        entry = yayoi_entry([((OUT, 3300, None), (SALES, 1100, 100)), ((OUT, 1100, None), None), ((OUT, 1100, None), None)])
        _keys, profile = campaign.journal_keys(entry, buddies_like_context())
        self.assertEqual(profile["pattern"], "B1D2")
        self.assertEqual(campaign.pattern_class("B1D2"), "FAN_DEBIT_FIRST_PAIRED(B1Dn)")
        self.assertEqual(campaign.pattern_class("C1D12"), "FAN_CREDIT_FIRST(C1Dn)")
        self.assertEqual(campaign.pattern_class("B4"), "PAIRED(Bn)")


class SyntheticProbeTest(unittest.TestCase):
    def rows_of(self, cases):
        ctx = buddies_like_context()
        names = {item.target_master_code: item.mapping_value for item in ctx.account_master}
        profile = gen._synthetic_profile(ctx)
        entries = [gen._entry(case, index, date(2026, 6, 28), names, profile, ctx) for index, case in enumerate(cases)]
        return entries, gen.serialize(entries, ctx)

    def test_structural_case_balances_with_exact_ten_percent_tax(self):
        for signature in ((("NO", "S10"), ("P10", "-"), ("P10", "-")),
                          (("-", "NO"), ("P10", "-"), ("P10", "-"), ("NO", "-")),
                          (("NO", "S10"), ("-", "NO"), ("P10", "-"), ("P10", "-"))):
            case = gen.structural_case("SH-T", "t", [], signature, ACCOUNTS)
            lines = [spec for row in case.rows for spec in row if spec is not None]
            debit = sum(row[0].amount for row in case.rows if row[0])
            credit = sum(row[1].amount for row in case.rows if row[1])
            self.assertEqual(debit, credit)
            for spec in lines:
                self.assertEqual(spec.amount % gen.UNIT, 0)
                if spec.tax in {"S10", "P10"}:
                    self.assertEqual(spec.explicit_tax, spec.amount / 11)

    def test_serialized_rows_use_production_literals_flags_and_markers(self):
        compound = gen.structural_case("SH-T", "t", [], (("NO", "S10"), ("P10", "-"), ("P10", "-")), ACCOUNTS)
        single = gen.one("EXP-S-CEIL", "t", [], gen.LineSpec("NO", "1111", Decimal(1105)),
                         gen.LineSpec("S10", "6121", Decimal(1105), Decimal(101)))
        _entries, rows = self.rows_of([single, compound])
        self.assertEqual([row[0] for row in rows], ["1111", "1110", "1100", "1101"])
        self.assertEqual(rows[0][18:23], ("売　上", "10%", "外税", "1105", "101"))
        self.assertEqual(rows[2][8:13], ("仕　入", "10%", "内税", "1100", "100"))
        self.assertEqual(rows[2][21], "0")  # unused credit side is 0, not blank (rev3 rule)
        self.assertEqual([row[23] for row in rows], ["EXP-S-CEIL", "SH-T-R1", "SH-T-R2", "SH-T-R3"])

    def test_each_case_is_judged_on_its_own(self):
        cases = [gen.structural_case("SH-A", "t", [], (("NO", "S10"), ("NO", "S10")), ACCOUNTS),
                 gen.structural_case("SH-B", "t", [], (("NO", "S10"), ("P10", "-"), ("P10", "-")), ACCOUNTS)]
        _entries, rows = self.rows_of(cases)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "probe_NOT_FOR_PRODUCTION.csv"
            buffer = io.StringIO(newline="")
            csv.writer(buffer, lineterminator="\r\n").writerows(
                (jdl_ibex_cashbook_official_journal_import_spec().column_names, *rows))
            path.write_bytes(buffer.getvalue().encode("cp932"))
            manifest = {"cases": [{"case": case.case_id, "journal_index": index, "physical_rows": len(case.rows),
                                   "pending_evidence_id": "PENDING"} for index, case in enumerate(cases)]}
            result = check(path, path, manifest)
        self.assertEqual({key: value["verdict"] for key, value in result["cases"].items()}, {"SH-A": "PASS", "SH-B": "PASS"})

    def test_production_guards_name_the_capability_being_probed(self):
        case = gen.structural_case("SH-3D1C", "t", [], (("NO", "S10"), ("P10", "-"), ("P10", "-")), ACCOUNTS)
        entries, _rows = self.rows_of([case])
        guards = gen.production_guards(entries, buddies_like_context())
        self.assertIn("JDL-OUT-COMPOUND-SHAPE", guards["SH-3D1C"])

    def test_output_outside_private_storage_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(gen.CampaignError):
                gen.generate(Path("unused"), Path(directory), "company", "20260628", Path(directory) / "out")


if __name__ == "__main__":
    unittest.main()
