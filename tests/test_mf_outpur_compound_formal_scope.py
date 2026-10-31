from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
import tempfile
from pathlib import Path

from accounting_converter.adapters.output.jdl import (
    JDL_OUTPUT_METADATA_KEY, JDLOutputAdapter, JDLOutputValidator,
    JdlAccountIdentity, JdlContextConfirmationState,
    JdlContextProvenance, JdlEvidenceProfile, JdlInputTaxCreditMethod,
    JdlSubaccountIdentity, JdlTargetContext, JdlTaxationMethod,
    jdl_ibex_35_5_output_profile,
)
from accounting_converter.adapters.output.jdl.preflight import JdlOutputPreflight
from accounting_converter.application.moneyforward_profile_setup import MoneyForwardProfileSetupService
from accounting_converter.domain.journal import JournalEntry, JournalLine, Side, SourceReference, TaxInfo
from accounting_converter.domain.mf_outpur_scope import outpur_signature
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode


PROFILES = {
    (4, 6): JdlEvidenceProfile.MF_OUTPUR_COMPOUND_4D6C,
    (5, 7): JdlEvidenceProfile.MF_OUTPUR_COMPOUND_5D7C,
    (5, 8): JdlEvidenceProfile.MF_OUTPUR_COMPOUND_5D8C,
}


class OutpurCompoundFormalScopeTest(unittest.TestCase):
    def setUp(self) -> None:
        names = {"8311": "A", "8441": "B", "3271": "C", "3221": "D"}
        self.context = JdlTargetContext(
            product="JDL IBEX 出納帳", version="35.5",
            accounts=frozenset(names.values()),
            account_master=tuple(JdlAccountIdentity(name, code, name, name) for code, name in names.items()),
            subaccounts=(JdlSubaccountIdentity(
                "C", "SUB-C", "0003", "0003", "SUB-C", True,
                parent_account_code="3271", target_name="SUB-C",
            ),),
            tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED,
            taxation_method=JdlTaxationMethod.STANDARD,
            input_tax_credit_method=JdlInputTaxCreditMethod.PROPORTIONAL,
            confirmation_state=JdlContextConfirmationState.CONFIRMED,
            provenance=JdlContextProvenance.USER_CONFIRMED_RUNTIME_SNAPSHOT,
        )
        self.names = names

    def entry(self, shape: tuple[int, int], index: int = 0) -> JournalEntry:
        reference = SourceReference("synthetic.csv", index * 20 + 2, str(index))
        lines = []
        descriptions = []
        row_numbers = []
        for position, (side, code, sub, _) in enumerate(outpur_signature(shape)):
            row_number = index * 20 + position + 2
            description = f"ROW-{index}-{position}"
            row_numbers.append(row_number)
            descriptions.append({"row_number": row_number, "value": description})
            amount = shape[1] * 100 if side == "DEBIT" else shape[0] * 100
            lines.append(JournalLine(
                Side(side), self.names[code], Decimal(amount), reference,
                sub_account="SUB-C" if sub else None,
                metadata={"journal_row_number": row_number, "journal_row_description": description},
            ))
        return JournalEntry(
            id=f"synthetic-{index}", source_reference=reference, date=date(2026, 5, 27),
            lines=lines, description=None,
            metadata={
                "source": "moneyforward_cloud_journal_export_observed",
                JDL_OUTPUT_METADATA_KEY: PROFILES[shape].value,
                "physical_row_numbers": tuple(row_numbers),
                "moneyforward_descriptions": tuple(descriptions),
            },
        )

    def test_three_exact_shapes_and_eleven_group_batch(self) -> None:
        preflight = JdlOutputPreflight(self.context)
        for shape in PROFILES:
            with self.subTest(shape=shape):
                result = preflight.evaluate((self.entry(shape),), jdl_ibex_35_5_output_profile())
                self.assertTrue(result.supported, [item.rule_id for item in result.validation_results])
                self.assertEqual(len(result.plan.rows), sum(shape))
                self.assertEqual(result.plan.rows[0].identifier_flag, "1110")
                self.assertEqual(result.plan.rows[-1].identifier_flag, "1101")
                self.assertEqual(result.plan.rows[0].debit_tax_amount, "0")
                self.assertEqual(result.plan.rows[0].credit_tax_amount, "")
                with tempfile.TemporaryDirectory() as directory:
                    output = Path(directory) / "synthetic.csv"
                    profile = jdl_ibex_35_5_output_profile()
                    JDLOutputAdapter(self.context).write((self.entry(shape),), output, profile)
                    self.assertTrue(
                        JDLOutputValidator(self.context).validate(output, (self.entry(shape),), profile).success
                    )
                    raw = output.read_bytes()
                    self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
                    self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        shapes = ((4, 6),) * 5 + ((5, 7),) + ((5, 8),) * 5
        batch = tuple(self.entry(shape, index) for index, shape in enumerate(shapes))
        result = preflight.evaluate(batch, jdl_ibex_35_5_output_profile())
        self.assertTrue(result.supported, [item.rule_id for item in result.validation_results])
        self.assertEqual(len(result.plan.rows), 127)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "synthetic-batch.csv"
            profile = jdl_ibex_35_5_output_profile()
            JDLOutputAdapter(self.context).write(batch, output, profile)
            self.assertTrue(JDLOutputValidator(self.context).validate(output, batch, profile).success)

    def test_other_account_tax_or_context_fails_closed(self) -> None:
        entry = self.entry((4, 6))
        entry.lines[0].account = "D"
        result = JdlOutputPreflight(self.context).evaluate((entry,), jdl_ibex_35_5_output_profile())
        self.assertIn("JDL-OUT-OUTPUR-EXACT-SCOPE", {item.rule_id for item in result.validation_results})
        entry = self.entry((4, 6))
        entry.lines[0].tax_info = TaxInfo(category="10%")
        result = JdlOutputPreflight(self.context).evaluate((entry,), jdl_ibex_35_5_output_profile())
        self.assertIn("JDL-OUT-OUTPUR-EXACT-SCOPE", {item.rule_id for item in result.validation_results})
        changed_context = replace(self.context, taxation_method=JdlTaxationMethod.SIMPLIFIED)
        result = JdlOutputPreflight(changed_context).evaluate((self.entry((4, 6)),), jdl_ibex_35_5_output_profile())
        self.assertIn("JDL-OUT-OUTPUR-EXACT-SCOPE", {item.rule_id for item in result.validation_results})

    def test_tax_mapping_is_human_confirmable_not_auto_confirmed(self) -> None:
        item = MoneyForwardProfileSetupService._tax_items(("対象外仕入",), self.context)[0]
        self.assertTrue(item.human_confirmable)
        self.assertEqual(item.target_scope, "")
        self.assertEqual(item.target_value, "")
        self.assertEqual(item.evidence_id, "EVID-MF-JDL-35-5-OUTPUR-8471-1111-ROUNDTRIP-001")


if __name__ == "__main__":
    unittest.main()
