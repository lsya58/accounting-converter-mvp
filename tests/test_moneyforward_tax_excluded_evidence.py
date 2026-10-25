from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from accounting_converter.adapters.output.jdl import (
    JdlAccountIdentity,
    JdlContextConfirmationState,
    JdlContextProvenance,
    JdlInputTaxCreditMethod,
    JdlSubaccountIdentity,
    JdlTargetContext,
    JdlTaxationMethod,
)
from accounting_converter.application.moneyforward_tax_excluded_evidence import (
    BATCH_EVIDENCE_ID,
    apply_verified_tax_semantics,
    context_is_verified,
    evidence_for_occurrence,
)
from accounting_converter.application.moneyforward_profile_setup import (
    MoneyForwardProfileSetupService,
)
from accounting_converter.domain.journal import (
    JournalEntry,
    JournalLine,
    Side,
    SourceReference,
    TaxInfo,
)
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode


class MoneyForwardTaxExcludedEvidenceTests(unittest.TestCase):
    def test_exact_pattern_activates_and_adds_tax_excluded_fields(self) -> None:
        context = self._context()
        source, mapped = self._p05()
        evidence = evidence_for_occurrence(source, mapped, context)
        transformed = apply_verified_tax_semantics(source, mapped, context)

        self.assertIsNotNone(evidence)
        info = transformed.lines[0].tax_info
        self.assertIsNotNone(info)
        self.assertEqual(info.category, "10%")
        self.assertEqual(info.tax_amount, Decimal("100"))
        self.assertEqual(info.metadata["jdl_tax_input_method"], "内税")
        self.assertEqual(transformed.lines[1].tax_info, None)

    def test_context_or_account_mismatch_remains_unverified(self) -> None:
        source, mapped = self._p05()
        individual = self._context(JdlInputTaxCreditMethod.INDIVIDUAL)
        self.assertFalse(context_is_verified(individual))
        self.assertIsNone(evidence_for_occurrence(source, mapped, individual))

        mapped.lines[0].account = "通信費"
        self.assertIsNone(evidence_for_occurrence(source, mapped, self._context()))

    def test_batch_evidence_id_is_stable(self) -> None:
        self.assertEqual(
            BATCH_EVIDENCE_ID,
            "EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-BATCH-001",
        )

    def test_tax_review_is_available_only_for_exact_verified_context(self) -> None:
        items = MoneyForwardProfileSetupService._tax_items(
            ("課税仕入 10%", "対象外"), self._context()
        )
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item.evidence_id == BATCH_EVIDENCE_ID for item in items))
        self.assertEqual(
            MoneyForwardProfileSetupService._tax_items(
                ("課税仕入 10%",),
                self._context(JdlInputTaxCreditMethod.INDIVIDUAL),
            ),
            (),
        )

    @staticmethod
    def _context(
        method: JdlInputTaxCreditMethod = JdlInputTaxCreditMethod.PROPORTIONAL,
    ) -> JdlTargetContext:
        accounts = (
            JdlAccountIdentity("旅費交通費", "8471", "旅費交通費", "旅費交通費"),
            JdlAccountIdentity("未払金", "3181", "未払金", "未払金"),
        )
        return JdlTargetContext(
            product="JDL IBEX 出納帳",
            version="35.5",
            accounts=frozenset(item.mapping_value for item in accounts),
            account_master=accounts,
            subaccounts=(),
            tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED,
            standard_taxation_confirmed=True,
            taxation_method=JdlTaxationMethod.STANDARD,
            input_tax_credit_method=method,
            confirmation_state=JdlContextConfirmationState.CONFIRMED,
            provenance=JdlContextProvenance.USER_CONFIRMED_RUNTIME_SNAPSHOT,
        )

    @staticmethod
    def _p05() -> tuple[JournalEntry, JournalEntry]:
        ref = SourceReference("synthetic.csv", 2, "1")
        source = JournalEntry(
            "j1", ref, date(2026, 4, 24),
            [
                JournalLine(Side.DEBIT, "旅費交通費", Decimal("1100"), ref, tax_info=TaxInfo("課税仕入 10%")),
                JournalLine(Side.CREDIT, "未払金", Decimal("1100"), ref, tax_info=TaxInfo("対象外")),
            ],
            "SYNTHETIC",
        )
        mapped = JournalEntry(
            "j1", ref, source.date,
            [
                JournalLine(Side.DEBIT, "旅費交通費", Decimal("1100"), ref, tax_info=TaxInfo("10%")),
                JournalLine(Side.CREDIT, "未払金", Decimal("1100"), ref, tax_info=TaxInfo("")),
            ],
            "SYNTHETIC",
        )
        return source, mapped
