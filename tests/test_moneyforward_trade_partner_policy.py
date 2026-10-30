from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import date, datetime, timezone
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from accounting_converter.adapters.output.jdl import (
    JdlContextConfirmationState,
    JdlContextProvenance,
    JdlAccountIdentity,
    JdlTargetContextBuilder,
)
from accounting_converter.application.moneyforward_jdl_loss import MoneyForwardToJdlLossRule
from accounting_converter.application.moneyforward_trade_partner import (
    MoneyForwardTradePartnerDescriptionPolicy,
    TRADE_PARTNER_1D1C_EVIDENCE_ID,
    TRADE_PARTNER_CAPABILITY_KEY,
    TRADE_PARTNER_POLICY_SCOPE_KEY,
    trade_partner_target_capability_sha256,
    upgrade_trade_partner_policy,
)
from accounting_converter.application.moneyforward_tax_excluded_evidence import (
    tax_context_identity_sha256,
)
from accounting_converter.application.company_trade_partner_policy import (
    CompanyTradePartnerPolicyService,
)
from accounting_converter.domain.conversion_profile import (
    ConversionProfile,
    LossPolicy,
    TRADE_PARTNER_LOSS_POLICY_KEY,
)
from accounting_converter.domain.journal import JournalEntry, JournalLine, Side, SourceReference
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode
from accounting_converter.profiles.known_formats import jdl_ibex_cashbook_official_journal_import_schema_definition, moneyforward_cloud_journal_export_observed_schema


class MoneyForwardTradePartnerPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        result = JdlTargetContextBuilder().build(
            target_format_identity=jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
            product="JDL IBEX 出納帳", version="35.5",
            account_master=(JdlAccountIdentity("A", "1001", "A", "A"),),
            subaccounts=(), departments=(),
            tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED,
            department_processing_enabled=False, standard_taxation_confirmed=True,
            individual_credit_method_confirmed=True,
            confirmation_state=JdlContextConfirmationState.CONFIRMED,
            provenance=JdlContextProvenance.USER_CONFIRMED_RUNTIME_SNAPSHOT,
            no_fuzzy_matching=True, no_automatic_replacement=True,
        )
        self.assertTrue(result.success)
        self.context = result.context
        self.profile = self._profile(self._context_hash())

    def test_confirmed_policy_appends_with_and_without_source_description(self) -> None:
        policy = MoneyForwardTradePartnerDescriptionPolicy(self.profile, self.context)
        with_description = policy.apply((self._entry(description="TEST"),))
        without_description = policy.apply((self._entry(description=None),))
        self.assertFalse(with_description.validation_results)
        self.assertEqual(with_description.entries[0].description, "TEST / 取引先:PARTNER-A")
        self.assertEqual(without_description.entries[0].description, "取引先:PARTNER-A")
        self.assertEqual(
            with_description.entries[0].lines[0].metadata["moneyforward_trade_partner"],
            "PARTNER-A",
        )
        self.assertFalse(MoneyForwardToJdlLossRule().validate(with_description.entries[0]))

    def test_exact_32_characters_pass_and_33_block(self) -> None:
        policy = MoneyForwardTradePartnerDescriptionPolicy(self.profile, self.context)
        fixed = " / 取引先:PARTNER-A"
        exact = policy.apply((self._entry(description="A" * (32 - len(fixed))),))
        over = policy.apply((self._entry(description="A" * (33 - len(fixed))),))
        self.assertEqual(len(exact.entries[0].description or ""), 32)
        self.assertFalse(exact.validation_results)
        self.assertEqual(over.validation_results[0].rule_id, "MF-JDL-PARTNER-DESCRIPTION-LENGTH")

    def test_cp932_unsafe_value_blocks_without_replacement(self) -> None:
        result = MoneyForwardTradePartnerDescriptionPolicy(
            self.profile, self.context
        ).apply((self._entry(partner="PARTNER-😀"),))
        self.assertEqual(result.validation_results[0].rule_id, "MF-JDL-PARTNER-DESCRIPTION-CP932")
        self.assertEqual(result.entries[0].description, "TEST")

    def test_unconfirmed_stale_compound_both_side_and_multiple_partner_block(self) -> None:
        unresolved = self._profile(self._context_hash(), MappingStatus.UNRESOLVED)
        stale = self._profile("stale")
        cases = (
            (MoneyForwardTradePartnerDescriptionPolicy(unresolved, self.context), self._entry(), "MF-JDL-PARTNER-POLICY"),
            (MoneyForwardTradePartnerDescriptionPolicy(stale, self.context), self._entry(), "MF-JDL-PARTNER-POLICY"),
            (MoneyForwardTradePartnerDescriptionPolicy(self.profile, self.context), self._entry(compound=True), "MF-JDL-PARTNER-SHAPE"),
            (MoneyForwardTradePartnerDescriptionPolicy(self.profile, self.context), self._entry(credit_partner="PARTNER-A"), "MF-JDL-PARTNER-IDENTITY"),
            (MoneyForwardTradePartnerDescriptionPolicy(self.profile, self.context), self._entry(credit_partner="PARTNER-B"), "MF-JDL-PARTNER-IDENTITY"),
        )
        for policy, entry, rule in cases:
            with self.subTest(rule=rule):
                self.assertEqual(policy.apply((entry,)).validation_results[0].rule_id, rule)

    def test_transform_is_idempotent_without_string_search(self) -> None:
        policy = MoneyForwardTradePartnerDescriptionPolicy(self.profile, self.context)
        first = policy.apply((self._entry(),))
        second = policy.apply(first.entries)
        self.assertFalse(second.validation_results)
        self.assertEqual(second.entries[0].description, first.entries[0].description)

    def test_confirmed_policy_updates_only_partner_row_in_2d2c(self) -> None:
        source = SourceReference("synthetic.csv", 2, "1")
        lines = [
            JournalLine(Side.DEBIT, "A", Decimal("600"), source, metadata={"moneyforward_trade_partner": "PARTNER-A", "moneyforward_source_row_number": 2, "moneyforward_description": "TEST"}),
            JournalLine(Side.CREDIT, "B", Decimal("300"), source, metadata={"moneyforward_source_row_number": 2, "moneyforward_description": "TEST"}),
            JournalLine(Side.DEBIT, "C", Decimal("400"), source, metadata={"moneyforward_source_row_number": 3, "moneyforward_description": "ROW2"}),
            JournalLine(Side.CREDIT, "D", Decimal("700"), source, metadata={"moneyforward_source_row_number": 3, "moneyforward_description": "ROW2"}),
        ]
        entry = JournalEntry(
            "synthetic:1", source, date(2026, 11, 27), lines, "TEST",
            metadata={
                "physical_row_numbers": (2, 3),
                "moneyforward_descriptions": (
                    {"row_number": 2, "value": "TEST"},
                    {"row_number": 3, "value": "ROW2"},
                ),
            },
        )
        result = MoneyForwardTradePartnerDescriptionPolicy(self.profile, self.context).apply((entry,))
        self.assertFalse(result.validation_results)
        descriptions = {
            (line.metadata["moneyforward_source_row_number"], line.metadata["moneyforward_description"])
            for line in result.entries[0].lines
        }
        self.assertEqual(descriptions, {(2, "TEST / 取引先:PARTNER-A"), (3, "ROW2")})

    def test_untrusted_marker_does_not_bypass_loss_rule(self) -> None:
        entry = self._entry()
        entry.metadata["moneyforward_trade_partner_transformation"] = {
            "policy": LossPolicy.APPEND_TRADE_PARTNER_TO_DESCRIPTION_CONFIRMED.value,
            "target_description_sha256": "wrong",
        }
        self.assertEqual(
            MoneyForwardToJdlLossRule().validate(entry)[0].field,
            "trade_partner",
        )

    def test_policy_round_trips_through_profile_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConversionProfileStore(Path(directory))
            store.create(self.profile)
            restored = store.get(self.profile.profile_id)
        mapping = restored.loss_policy_mappings[TRADE_PARTNER_LOSS_POLICY_KEY]
        self.assertEqual(mapping.status, MappingStatus.USER_CONFIRMED)
        self.assertEqual(
            mapping.target_value,
            LossPolicy.APPEND_TRADE_PARTNER_TO_DESCRIPTION_CONFIRMED.value,
        )

    def test_scoped_policy_survives_unrelated_master_change_but_not_tax_change(self) -> None:
        policy = self.profile.loss_policy_mappings[TRADE_PARTNER_LOSS_POLICY_KEY]
        scoped = replace(policy, metadata={
            **policy.metadata,
            TRADE_PARTNER_POLICY_SCOPE_KEY: tax_context_identity_sha256(self.context),
        })
        profile = replace(self.profile, loss_policy_mappings={
            TRADE_PARTNER_LOSS_POLICY_KEY: scoped,
        })
        changed_master = replace(
            self.context,
            account_master=(*self.context.account_master,
                            JdlAccountIdentity("UNRELATED", "9999", "UNRELATED", "UNRELATED")),
        )
        self.assertFalse(MoneyForwardTradePartnerDescriptionPolicy(
            profile, changed_master
        ).apply((self._entry(),)).validation_results)
        changed_tax = replace(
            changed_master,
            tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED,
        )
        self.assertTrue(MoneyForwardTradePartnerDescriptionPolicy(
            profile, changed_tax
        ).apply((self._entry(),)).validation_results)

    def test_capability_policy_ignores_tax_and_master_but_blocks_target_change(self) -> None:
        policy = self.profile.loss_policy_mappings[TRADE_PARTNER_LOSS_POLICY_KEY]
        capability = trade_partner_target_capability_sha256(self.context)
        self.assertIsNotNone(capability)
        scoped = replace(policy, metadata={
            TRADE_PARTNER_CAPABILITY_KEY: capability,
            "jdl_evidence_id": TRADE_PARTNER_1D1C_EVIDENCE_ID,
        })
        profile = replace(self.profile, loss_policy_mappings={
            TRADE_PARTNER_LOSS_POLICY_KEY: scoped,
        })
        changed_tax = replace(
            self.context,
            tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED,
        )
        changed_master = replace(
            changed_tax,
            account_master=(*self.context.account_master,
                            JdlAccountIdentity("UNRELATED", "9999", "UNRELATED", "UNRELATED")),
        )
        for context in (changed_tax, changed_master):
            self.assertFalse(MoneyForwardTradePartnerDescriptionPolicy(
                profile, context
            ).apply((self._entry(),)).validation_results)
        for context in (
            replace(self.context, product="Other JDL"),
            replace(self.context, version="35.6"),
            replace(self.context, target_format_identity=
                    moneyforward_cloud_journal_export_observed_schema().identity),
        ):
            self.assertTrue(MoneyForwardTradePartnerDescriptionPolicy(
                profile, context
            ).apply((self._entry(),)).validation_results)

    def test_legacy_scope_is_upgraded_only_from_valid_old_context(self) -> None:
        policy = self.profile.loss_policy_mappings[TRADE_PARTNER_LOSS_POLICY_KEY]
        new_context = replace(
            self.context,
            tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED,
        )
        upgraded = upgrade_trade_partner_policy(policy, self.context, new_context)
        self.assertIn(TRADE_PARTNER_CAPABILITY_KEY, upgraded.metadata)
        self.assertEqual(
            upgrade_trade_partner_policy(policy, new_context, self.context), policy
        )
        self.assertEqual(
            upgrade_trade_partner_policy(
                policy, self.context, replace(self.context, version="35.6")
            ), policy
        )

    def test_company_confirmation_persists_and_is_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profiles = ConversionProfileStore(root / "profiles")
            base = self._profile(self._context_hash(), MappingStatus.UNRESOLVED)
            base = ConversionProfile(
                **{**base.__dict__, "loss_policy_mappings": {}}
            )
            profiles.create(base)
            companies = CompanySettingStore(root / "companies", profiles)
            context_path = root / "context.json"
            context_path.write_text(
                JdlTargetContextLoader().to_json_text(self.context), encoding="utf-8"
            )
            companies.create(
                company_setting_id="company-a", display_name="Synthetic A",
                conversion_profile_id=base.profile_id, context_source=context_path,
            )
            companies.create(
                company_setting_id="company-b", display_name="Synthetic B",
                conversion_profile_id=base.profile_id, context_source=context_path,
            )
            service = CompanyTradePartnerPolicyService(companies, profiles)
            self.assertFalse(service.state("company-a").confirmed)
            service.confirm("company-a")
            self.assertTrue(service.state("company-a").confirmed)
            self.assertFalse(service.state("company-b").confirmed)
            confirmed_profile = profiles.get(
                companies.get("company-a").conversion_profile_id
            )
            metadata = confirmed_profile.loss_policy_mappings[
                TRADE_PARTNER_LOSS_POLICY_KEY
            ].metadata
            self.assertIn(TRADE_PARTNER_CAPABILITY_KEY, metadata)
            self.assertNotIn(TRADE_PARTNER_POLICY_SCOPE_KEY, metadata)
            self.assertNotIn("jdl_context_sha256", metadata)

    def _profile(self, context_hash: str, status=MappingStatus.USER_CONFIRMED):
        now = datetime(2026, 10, 18, tzinfo=timezone.utc)
        return ConversionProfile(
            "partner-policy", "Synthetic partner policy",
            moneyforward_cloud_journal_export_observed_schema().identity,
            jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
            loss_policy_mappings={
                TRADE_PARTNER_LOSS_POLICY_KEY: MappingValue(
                    TRADE_PARTNER_LOSS_POLICY_KEY,
                    LossPolicy.APPEND_TRADE_PARTNER_TO_DESCRIPTION_CONFIRMED.value,
                    status,
                    metadata={
                        "jdl_context_sha256": context_hash,
                        "jdl_evidence_id": TRADE_PARTNER_1D1C_EVIDENCE_ID,
                    },
                )
            },
            created_at=now, updated_at=now,
        )

    def _entry(self, *, description="TEST", partner="PARTNER-A", credit_partner="", compound=False):
        source = SourceReference("synthetic.csv", 2, "1")
        lines = [
            JournalLine(Side.DEBIT, "A", Decimal("100"), source, metadata={"moneyforward_trade_partner": partner}),
            JournalLine(Side.CREDIT, "B", Decimal("100"), source, metadata=({"moneyforward_trade_partner": credit_partner} if credit_partner else {})),
        ]
        if compound:
            lines.insert(1, JournalLine(Side.DEBIT, "C", Decimal("0"), source))
        return JournalEntry("synthetic:1", source, date(2026, 10, 18), lines, description)

    def _context_hash(self):
        loader = JdlTargetContextLoader()
        return hashlib.sha256(loader.to_json_text(self.context).encode("utf-8")).hexdigest()


if __name__ == "__main__":
    unittest.main()
