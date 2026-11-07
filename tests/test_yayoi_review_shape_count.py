"""The review screen's "形が未検証" count for a Yayoi company uses the formal structural rules. Synthetic data."""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from accounting_converter.adapters.output.jdl import JdlTaxRounding
from accounting_converter.application.company_mapping_update import CompanyMappingUpdateService
from accounting_converter.application.yayoi_sources import IMPORT
from tests.test_mf_tax_capability_composition import context
from tests.test_yayoi_import_format import OUTSIDE, SALES, YAYOI, Company, journals, row, write_import


def scoped_context(limit=16):
    # The settings of the company the scoped real-JDL Evidence was taken on.
    return replace(context(), sales_tax_rounding=JdlTaxRounding.CEILING, purchase_tax_rounding=JdlTaxRounding.HALF_UP,
                   voucher_row_limit=limit)


def voucher(number, rows, date="R.08/05/20"):
    """A multi-row voucher: (debit, credit) per row."""
    flags = ("2110", *("2100",) * (len(rows) - 2), "2101")
    return [row(flag, number, date, debit, credit, f"V{number}-{i}", kind="3")
            for i, (flag, (debit, credit)) in enumerate(zip(flags, rows, strict=True), start=1)]


SALES_ROW = ((YAYOI["cash"], "", OUTSIDE, 1100, 0), (YAYOI["sales"], "", SALES, 1100, 100))


class ReviewShapeCountTest(unittest.TestCase):
    def count(self, extra, target):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            company = Company(root, "company-s", write_import(root, journals() + extra), IMPORT, target)
            company.confirm_all()
            review = CompanyMappingUpdateService(company.companies, company.profiles).review("company-s", company.source)
            return review.unsupported_shape_count

    def test_three_row_sales_voucher_with_real_jdl_evidence_is_not_counted(self):
        # (3, 3) is not in the MF shape list (the old count said "unverified"), but the layout B3 with
        # 課税売上10% on every credit row round-tripped on the real JDL for this company scope.
        self.assertEqual(self.count(voucher(9, [SALES_ROW] * 3), scoped_context()), 0)

    def test_a_layout_never_round_tripped_is_still_counted(self):
        self.assertEqual(self.count(voucher(9, [SALES_ROW] * 12), scoped_context()), 1)  # B12: no Evidence

    def test_outside_the_evidence_scope_the_original_rules_decide(self):
        floor = replace(context(), sales_tax_rounding=JdlTaxRounding.FLOOR, purchase_tax_rounding=JdlTaxRounding.FLOOR)
        self.assertEqual(self.count(voucher(9, [SALES_ROW] * 3), floor), 1)


if __name__ == "__main__":
    unittest.main()
