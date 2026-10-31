from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from accounting_converter.adapters.output.jdl import (
    JDL_OUTPUT_METADATA_KEY,
    JdlAccountIdentity,
    JdlContextConfirmationState,
    JdlContextProvenance,
    JdlEvidenceProfile,
    JdlInputTaxCreditMethod,
    JdlSubaccountIdentity,
    JdlTargetContext,
    JdlTaxationMethod,
    jdl_ibex_35_5_output_profile,
)
from accounting_converter.adapters.output.jdl.preflight import JdlOutputPreflight
from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
from accounting_converter.adapters.output.jdl.tax_semantics import JdlTaxSemantic
from tests.support.confirmed_tax import with_confirmed_tax
from accounting_converter.application.moneyforward_description_replacement import (
    description_requires_replacement,
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
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode


ACCOUNTS = {
    "1111": "現金", "1311": "普通預金", "1551": "売掛金", "3141": "未払金",
    "3181": "未払費用", "3561": "仮払", "6121": "売上高", "8491": "消耗品費",
    "8571": "保険料", "8681": "手数料", "9111": "受取利息", "9251": "雑収入",
}


def context() -> JdlTargetContext:
    return JdlTargetContext(
        product="JDL IBEX 出納帳", version="35.5",
        accounts=frozenset(ACCOUNTS.values()),
        account_master=tuple(
            JdlAccountIdentity(name, code, name, name) for code, name in ACCOUNTS.items()
        ),
        subaccounts=(
            JdlSubaccountIdentity(
                "普通預金", "銀行A", "0002", "0002", "銀行A", True,
                parent_account_code="1311", target_name="銀行A",
            ),
            JdlSubaccountIdentity(
                "未払費用", "未払A", "0001", "0001", "未払A", True,
                parent_account_code="3181", target_name="未払A",
            ),
            JdlSubaccountIdentity(
                "売掛金", "得意先A", "0003", "0003", "得意先A", True,
                parent_account_code="1551", target_name="得意先A",
            ),
        ),
        tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED,
        taxation_method=JdlTaxationMethod.STANDARD,
        standard_taxation_confirmed=True,
        input_tax_credit_method=JdlInputTaxCreditMethod.PROPORTIONAL,
        confirmation_state=JdlContextConfirmationState.CONFIRMED,
        provenance=JdlContextProvenance.USER_CONFIRMED_RUNTIME_SNAPSHOT,
    )


SUBS = {"1311": "銀行A", "3181": "未払A", "1551": "得意先A"}


def entry(*lines, partner: bool = False, entry_id: str = "mf:synthetic:1") -> JournalEntry:
    reference = SourceReference("synthetic.csv", 2, "1")
    built = []
    for index, (side, code, sub, tax, amount) in enumerate(lines):
        metadata = {
            "journal_row_number": 2 + index // 2,
            "journal_row_description": "TEST",
        }
        if partner and index == 0:
            metadata["moneyforward_trade_partner"] = "PARTNER-A"
            metadata["journal_counterparty"] = "PARTNER-A"
        built.append(JournalLine(
            Side(side), ACCOUNTS[code], Decimal(amount), reference,
            sub_account=SUBS[code] if sub else None,
            tax_info=TaxInfo(category=tax) if tax else None,
            metadata=metadata,
        ))
    rows = tuple(sorted({line.metadata["journal_row_number"] for line in built}))
    return JournalEntry(
        entry_id, reference, date(2026, 5, 28), built, "TEST",
        metadata={
            "source": "moneyforward_cloud_journal_export_observed",
            "physical_row_numbers": rows,
            "moneyforward_descriptions": tuple(
                {"row_number": row, "value": "TEST"} for row in rows
            ),
        },
    )


def taxed_profile():
    return with_confirmed_tax(None, context())


def match(item: JournalEntry):
    return ev.match_evidence_for_occurrence(item, item, context(), taxed_profile())


class CapabilityCompositionTest(unittest.TestCase):
    def test_0876_exact_nonpur_signature_is_registered(self) -> None:
        result = match(entry(
            ("DEBIT", "8571", False, "非課税仕入", "1100"),
            ("CREDIT", "1311", True, "対象外", "1100"),
        ))
        self.assertEqual(result.evidence.evidence_id, ev.NONPUR_1311_EVIDENCE_ID)
        self.assertIs(result.evidence.profile, JdlEvidenceProfile.MF_NONPUR_PROPORTIONAL_1111)

    def test_account_independence_is_derived_from_real_evidence(self) -> None:
        caps = ev.LINE_CAPABILITIES
        purchase, sales = JdlTaxSemantic.PURCHASE_10_INTERNAL.value, JdlTaxSemantic.SALES_10_EXTERNAL.value
        no_tax = JdlTaxSemantic.NO_TAX.value
        self.assertTrue(caps[("DEBIT", purchase)].account_independent)
        self.assertTrue(caps[("DEBIT", no_tax)].account_independent)
        self.assertTrue(caps[("CREDIT", no_tax)].account_independent)
        self.assertEqual(caps[("CREDIT", sales)].verified_accounts, {"6121", "9251"})
        self.assertFalse(caps[("CREDIT", sales)].account_independent)
        self.assertEqual(caps[("DEBIT", JdlTaxSemantic.NON_TAXABLE_PURCHASE.value)].verified_accounts, {"8571"})
        self.assertEqual(caps[("CREDIT", JdlTaxSemantic.NON_TAXABLE_SALES.value)].verified_accounts, {"9111"})
        # 対象外仕入 reaches JDL as the same blank literal as 対象外.
        self.assertIn("8311", caps[("DEBIT", no_tax)].verified_accounts)

    def test_purchase_on_new_expense_account_is_composed(self) -> None:
        result = match(entry(
            ("DEBIT", "8491", False, "課税仕入 10%", "1100"),
            ("CREDIT", "1311", True, "対象外", "1100"),
        ))
        self.assertEqual(result.evidence.evidence_id, ev.COMPOSITION_ROUTE_ID)
        self.assertIs(result.evidence.profile, JdlEvidenceProfile.MF_TAX_EXCLUDED_PROPORTIONAL_1111)
        self.assertIn(
            "EVID-MF-JDL-35-5-1D2C-REAL-ROUNDTRIP-001",
            result.evidence.supporting_evidence_ids,
        )

    def test_sales10_on_verified_account_with_new_receivable_is_composed(self) -> None:
        result = match(entry(
            ("DEBIT", "1551", True, "対象外", "1100"),
            ("CREDIT", "6121", False, "課税売上 10%", "1100"),
        ))
        self.assertIs(
            result.evidence.profile,
            JdlEvidenceProfile.MF_SALES10_EXCLUDED_PROPORTIONAL_1111,
        )

    def test_unverified_or_ambiguous_capabilities_stay_blocked(self) -> None:
        cases = {
            "TAX_ACCOUNT_UNVERIFIED": entry(
                ("DEBIT", "1311", True, "対象外", "1100"),
                ("CREDIT", "9111", False, "課税売上 10%", "1100"),
            ),
            "TAX_AMOUNT_ROUNDING_UNVERIFIED": entry(
                # 1106 * 10 / 110 = 100.54...: floor 100, half-up 101.
                # Rounding is verified on 6121 only (0877), not on 9251.
                ("DEBIT", "1551", True, "対象外", "1106"),
                ("CREDIT", "9251", False, "課税売上 10%", "1106"),
            ),
            "SUBACCOUNT_REQUIRED_BY_MASTER": entry(
                ("DEBIT", "1311", False, "対象外", "1100"),
                ("CREDIT", "6121", False, "課税売上 10%", "1100"),
            ),
            "TAX_SIDE_UNVERIFIED": entry(
                ("DEBIT", "6121", False, "課税売上 10%", "1100"),
                ("CREDIT", "1311", True, "対象外", "1100"),
            ),
            "SHAPE_UNVERIFIED_IN_TAX_CONTEXT": entry(
                ("DEBIT", "3561", False, "対象外", "300"),
                ("CREDIT", "1311", True, "対象外", "1100"),
                ("DEBIT", "8681", False, "課税仕入 10%", "400"),
                ("DEBIT", "8491", False, "課税仕入 10%", "400"),
            ),
        }
        for gap, item in cases.items():
            with self.subTest(gap=gap):
                result = match(item)
                self.assertIsNone(result.evidence)
                self.assertIn(gap, result.mismatch_fields)

    def test_0877_sales10_rounding_and_9251_are_released(self) -> None:
        rounding = match(entry(
            ("DEBIT", "1551", True, "対象外", "1106"),
            ("CREDIT", "6121", False, "課税売上 10%", "1106"),
        ))
        self.assertIn(ev.SALES10_ROUNDING_EVIDENCE_ID, rounding.evidence.supporting_evidence_ids)
        second_account = match(entry(
            ("DEBIT", "1311", True, "対象外", "1100"),
            ("CREDIT", "9251", False, "課税売上 10%", "1100"),
        ))
        self.assertIs(
            second_account.evidence.profile,
            JdlEvidenceProfile.MF_SALES10_EXCLUDED_PROPORTIONAL_1111,
        )

    def test_2d2c_with_one_purchase_row_uses_p01_shape(self) -> None:
        result = match(entry(
            ("DEBIT", "3141", False, "対象外", "500"),
            ("CREDIT", "1311", True, "対象外", "500"),
            ("DEBIT", "8681", False, "課税仕入 10%", "600"),
            ("CREDIT", "1311", True, "対象外", "600"),
        ))
        self.assertIs(
            result.evidence.profile,
            JdlEvidenceProfile.MF_COMPOUND_2D2C_TAX_EXCLUDED_PROPORTIONAL,
        )

    def test_verified_literals_and_mixed_group_file(self) -> None:
        ctx = context()
        sources = (
            entry(("DEBIT", "1551", True, "対象外", "1100"),
                  ("CREDIT", "6121", False, "課税売上 10%", "1100"), entry_id="mf:s:1"),
            entry(("DEBIT", "8571", False, "非課税仕入", "1100"),
                  ("CREDIT", "3181", True, "対象外", "1100"), entry_id="mf:s:2"),
            entry(("DEBIT", "1311", True, "対象外", "1100"),
                  ("CREDIT", "9111", False, "非課税売上", "1100"), entry_id="mf:s:3"),
            entry(("DEBIT", "8491", False, "課税仕入 10%", "1100"),
                  ("CREDIT", "1311", True, "対象外", "1100"), entry_id="mf:s:4"),
        )
        routed = []
        for source in sources:
            result = ev.match_evidence_for_occurrence(source, source, ctx, taxed_profile())
            mapped = ev.apply_verified_tax_semantics(source, source, ctx, taxed_profile())
            mapped.metadata[JDL_OUTPUT_METADATA_KEY] = result.evidence.profile.value
            routed.append(mapped)
        preflight = JdlOutputPreflight(ctx).evaluate(routed, jdl_ibex_35_5_output_profile())
        self.assertEqual(preflight.validation_results, ())
        rows = preflight.plan.rows
        self.assertEqual(
            (rows[0].credit_tax_scope, rows[0].credit_tax_category,
             rows[0].credit_tax_input_method, rows[0].credit_tax_amount),
            ("売　上", "10%", "外税", "100"),
        )
        self.assertEqual(
            (rows[1].debit_tax_scope, rows[1].debit_tax_category,
             rows[1].debit_tax_input_method, rows[1].debit_tax_amount),
            ("非仕入", "", "", ""),
        )
        self.assertEqual(
            (rows[2].credit_tax_scope, rows[2].credit_tax_category,
             rows[2].credit_tax_amount, rows[2].debit_tax_scope),
            ("非売上", "", "", ""),
        )
        self.assertEqual(rows[3].debit_tax_input_method, "内税")

    def test_tax_review_offers_new_identities_with_evidence(self) -> None:
        items = {
            item.source_value: item
            for item in MoneyForwardProfileSetupService._tax_items(
                ("非課税仕入", "非課税売上", "課税売上 10%", "対象外仕入"), context()
            )
        }
        for source in ("非課税仕入", "非課税売上", "課税売上 10%", "対象外仕入"):
            with self.subTest(source=source):
                item = items[source]
                self.assertTrue(item.human_confirmable)
                self.assertEqual(item.action_owner, "HUMAN")
                self.assertEqual(
                    (item.target_value, item.target_scope, item.evidence_id),
                    ev.TAX_MAPPING_SPECS[source],
                )
                mapping = MappingValue(
                    source, item.target_value, MappingStatus.USER_CONFIRMED,
                    metadata=MoneyForwardProfileSetupService._tax_mapping_metadata(
                        item, None, context()
                    ),
                )
                self.assertTrue(ev.confirmed_mapping_is_in_scope(source, mapping, context()))

    def test_description_replacement_triggers(self) -> None:
        self.assertFalse(description_requires_replacement("A" * 32))
        self.assertTrue(description_requires_replacement("A" * 33))
        self.assertTrue(description_requires_replacement("一行目\n二行目"))
        self.assertTrue(description_requires_replacement("髙橋"))


if __name__ == "__main__":
    unittest.main()
