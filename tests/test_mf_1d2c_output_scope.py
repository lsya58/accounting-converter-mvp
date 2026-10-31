from __future__ import annotations

import unittest
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from accounting_converter.adapters.output.jdl import (
    JDL_OUTPUT_METADATA_KEY, JDLOutputAdapter, JDLOutputValidator,
    JdlAccountIdentity, JdlEvidenceProfile,
    JdlInputTaxCreditMethod, JdlSubaccountIdentity, JdlTargetContext,
    JdlTaxationMethod, jdl_ibex_35_5_output_profile,
)
from accounting_converter.adapters.output.jdl.preflight import JdlOutputPreflight
from accounting_converter.domain.journal import JournalEntry, JournalLine, Side, SourceReference, TaxInfo
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode


class MfExact1D2COutputTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = SourceReference("synthetic.csv", 2, "synthetic")
        self.context = JdlTargetContext(
            product="JDL IBEX 出納帳", version="35.5",
            accounts=frozenset({"仕入費", "未払金", "預り金"}),
            tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED,
            standard_taxation_confirmed=True,
            input_tax_credit_method=JdlInputTaxCreditMethod.PROPORTIONAL,
            taxation_method=JdlTaxationMethod.STANDARD,
            account_master=(
                JdlAccountIdentity("仕入費", "7121", "仕入費", "仕入費"),
                JdlAccountIdentity("未払金", "3141", "未払金", "未払金"),
                JdlAccountIdentity("預り金", "3271", "預り金", "預り金"),
            ),
            subaccounts=(JdlSubaccountIdentity(
                "預り金", "補助A", "0002", "0002", "補助A", True,
                parent_account_code="3271", target_name="補助A",
            ),),
        )

    def entry(self) -> JournalEntry:
        first = {"moneyforward_source_row_number": 2, "moneyforward_description": "ROW1"}
        second = {"moneyforward_source_row_number": 3, "moneyforward_description": "ROW2"}
        return JournalEntry(
            id="synthetic", source_reference=self.source, date=date(2026, 5, 18),
            description="ROW1",
            lines=[
                JournalLine(Side.DEBIT, "仕入費", Decimal("120000"), self.source,
                            tax_info=TaxInfo(category="10%", rate=Decimal("10"),
                                             tax_amount=Decimal("10909"),
                                             metadata={"jdl_tax_scope": "仕　入", "jdl_tax_input_method": "内税"}),
                            metadata=first),
                JournalLine(Side.CREDIT, "未払金", Decimal("107748"), self.source, metadata=first),
                JournalLine(Side.CREDIT, "預り金", Decimal("12252"), self.source,
                            sub_account="補助A", metadata=second),
            ],
            metadata={
                JDL_OUTPUT_METADATA_KEY: JdlEvidenceProfile.MF_COMPOUND_1D2C_TAX_EXCLUDED_PROPORTIONAL.value,
                "physical_row_numbers": (2, 3),
                "moneyforward_descriptions": (
                    {"row_number": 2, "value": "ROW1"},
                    {"row_number": 3, "value": "ROW2"},
                ),
            },
        )

    def evaluate(self, entry: JournalEntry):
        with patch("accounting_converter.adapters.output.jdl.preflight.hashlib.sha256") as digest:
            digest.return_value.hexdigest.return_value = (
                "6099ad2a91a878298c8fac68226f9cc5b6fd263cd5eb95ffd20daeacbe29e949"
            )
            return JdlOutputPreflight(self.context).evaluate((entry,), jdl_ibex_35_5_output_profile())

    def test_exact_verified_two_row_output(self) -> None:
        entry = self.entry()
        result = self.evaluate(entry)
        self.assertTrue(result.supported, [item.rule_id for item in result.validation_results])
        self.assertEqual([row.identifier_flag for row in result.plan.rows], ["1110", "1101"])
        self.assertEqual(len(result.plan.rows), 2)
        with tempfile.TemporaryDirectory() as directory, patch(
            "accounting_converter.adapters.output.jdl.preflight.hashlib.sha256"
        ) as digest:
            digest.return_value.hexdigest.return_value = (
                "6099ad2a91a878298c8fac68226f9cc5b6fd263cd5eb95ffd20daeacbe29e949"
            )
            output = Path(directory) / "candidate.csv"
            profile = jdl_ibex_35_5_output_profile()
            JDLOutputAdapter(self.context).write((entry,), output, profile)
            validated = JDLOutputValidator(self.context).validate(output, (entry,), profile)
            self.assertTrue(validated.success)
            raw = output.read_bytes()
            self.assertFalse(raw.startswith(bytes.fromhex("efbbbf")))
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))

    def test_other_subaccount_cannot_borrow_evidence(self) -> None:
        entry = self.entry()
        entry.lines[2].sub_account = "different"
        result = self.evaluate(entry)
        self.assertFalse(result.supported)
        self.assertIn("JDL-OUT-1D2C-EXACT-SCOPE", {item.rule_id for item in result.validation_results})

    def test_different_journal_identity_cannot_borrow_evidence(self) -> None:
        entry = self.entry()
        with patch("accounting_converter.adapters.output.jdl.preflight.hashlib.sha256") as digest:
            digest.return_value.hexdigest.return_value = "different"
            result = JdlOutputPreflight(self.context).evaluate((entry,), jdl_ibex_35_5_output_profile())
        self.assertFalse(result.supported)
        self.assertIn("JDL-OUT-1D2C-EXACT-SCOPE", {item.rule_id for item in result.validation_results})


if __name__ == "__main__":
    unittest.main()
