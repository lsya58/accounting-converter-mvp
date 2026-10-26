from __future__ import annotations

import unittest
from datetime import date
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from pathlib import Path
import tempfile

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
    EVIDENCE,
    apply_verified_tax_semantics,
    confirmed_mapping_is_in_scope,
    confirmed_mapping_mismatch_fields,
    context_is_verified,
    evidence_for_occurrence,
    tax_context_identity_sha256,
)
from accounting_converter.application.moneyforward_conversion_workflow import (
    MoneyForwardConversionWorkflow,
)
from accounting_converter.application.moneyforward_profile_setup import (
    MoneyForwardProfileSetupService,
)
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.journal import (
    JournalEntry,
    JournalLine,
    Side,
    SourceReference,
    TaxInfo,
)
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from accounting_converter.infrastructure.conversion_profile_store import (
    ConversionProfileStore,
)
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
    moneyforward_cloud_journal_export_observed_schema,
)


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

    def test_all_p01_to_p07_exact_occurrence_signatures_match(self) -> None:
        for index, expected in enumerate(EVIDENCE, start=1):
            with self.subTest(pattern=index):
                codes = {item[1] for item in expected.account_signature}
                accounts = tuple(
                    JdlAccountIdentity(f"A{code}", code, f"A{code}", f"A{code}")
                    for code in sorted(codes)
                )
                sub_keys = {
                    (item[1], item[2])
                    for item in expected.account_signature if item[2]
                }
                subs = tuple(
                    JdlSubaccountIdentity(
                        f"A{parent}", f"S{parent}-{code}", code, code,
                        f"S{parent}-{code}", True, parent, f"S{parent}-{code}",
                    )
                    for parent, code in sorted(sub_keys)
                )
                base = self._context()
                context = JdlTargetContext(
                    **{
                        **base.__dict__,
                        "accounts": frozenset(item.mapping_value for item in accounts),
                        "account_master": accounts,
                        "subaccounts": subs,
                    }
                )
                ref = SourceReference("synthetic.csv", index + 1, str(index))
                source_lines = []
                mapped_lines = []
                for side, account, subaccount, tax in expected.account_signature:
                    metadata = (
                        {"moneyforward_trade_partner": "SYNTHETIC-PARTNER"}
                        if expected.trade_partner and not source_lines else {}
                    )
                    source_lines.append(JournalLine(
                        Side(side), f"SRC-{account}", Decimal("100"), ref,
                        tax_info=TaxInfo(tax), metadata=metadata,
                    ))
                    mapped_lines.append(JournalLine(
                        Side(side), f"A{account}", Decimal("100"), ref,
                        sub_account=(f"S{account}-{subaccount}" if subaccount else None),
                        tax_info=TaxInfo(tax), metadata=metadata,
                    ))
                source = JournalEntry(
                    f"j{index}", ref, date(2026, 4, 19 + index), source_lines,
                    "SYNTHETIC",
                )
                mapped = JournalEntry(
                    f"j{index}", ref, source.date, mapped_lines, "SYNTHETIC",
                )

                actual = evidence_for_occurrence(source, mapped, context)

                self.assertIsNotNone(actual)
                self.assertEqual(actual.evidence_id, expected.evidence_id)

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

    def test_mapping_scope_uses_tax_context_not_unrelated_master_hash(self) -> None:
        context = self._context()
        mapping = MappingValue(
            "課税仕入 10%", "10%", MappingStatus.USER_CONFIRMED,
            metadata={
                "jdl_evidence_id": BATCH_EVIDENCE_ID,
                "jdl_tax_processing_mode": "TAXABLE_TAX_EXCLUDED",
                "jdl_tax_scope": "仕　入",
                "jdl_tax_context_identity_sha256": (
                    tax_context_identity_sha256(context)
                ),
                "jdl_context_sha256": "older-full-context-hash",
            },
        )

        self.assertTrue(
            confirmed_mapping_is_in_scope("課税仕入 10%", mapping, context)
        )
        self.assertFalse(confirmed_mapping_is_in_scope(
            "課税仕入 10%",
            MappingValue(
                "課税仕入 10%", "10%", MappingStatus.USER_CONFIRMED,
                metadata={**mapping.metadata, "jdl_evidence_id": "WRONG"},
            ),
            context,
        ))

    def test_evidence_failure_is_not_reported_as_shape_failure(self) -> None:
        context = self._context()
        source, mapped = self._p05()
        mapping = MappingValue(
            "課税仕入 10%", "10%", MappingStatus.USER_CONFIRMED,
            metadata={
                "jdl_evidence_id": "WRONG",
                "jdl_tax_processing_mode": "TAXABLE_TAX_EXCLUDED",
            },
        )
        profile = SimpleNamespace(
            tax_mappings={"課税仕入 10%": mapping, "対象外": mapping}
        )

        _assignments, _reasons, shapes, tax_evidence = (
            MoneyForwardConversionWorkflow()._route_assignments(
                (source,), (mapped,), profile, context
            )
        )

        self.assertEqual(shapes, set())
        self.assertEqual(tax_evidence, {"j1"})

    def test_old_mapping_is_reviewed_and_human_reconfirmation_updates_metadata(self) -> None:
        context = self._context()
        old = MappingValue(
            "課税仕入 10%", "10%", MappingStatus.USER_CONFIRMED,
            metadata={
                "jdl_evidence_id": "EVID-JDL-MF-TAX-PURCHASE-10-ROUNDTRIP-001",
                "jdl_tax_processing_mode": "TAXABLE_TAX_EXCLUDED",
                "jdl_tax_scope": "仕　入",
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            store = ConversionProfileStore(Path(directory))
            now = datetime.now(timezone.utc)
            profile = ConversionProfile(
                "profile", "profile",
                moneyforward_cloud_journal_export_observed_schema().identity,
                jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
                tax_mappings={"課税仕入 10%": old},
                created_at=now, updated_at=now,
            )
            store.create(profile)
            service = MoneyForwardProfileSetupService(store)

            review = service.tax_mapping_review(profile, context)
            self.assertEqual(review.stale_source_values, ("課税仕入 10%",))
            self.assertIn("再確認", review.user_message)
            service.confirm_evidence_backed_tax_mapping(
                profile_id="profile", context=context,
                source_value="課税仕入 10%",
            )
            saved = store.get("profile").tax_mappings["課税仕入 10%"]

        self.assertEqual(saved.metadata["jdl_evidence_id"], BATCH_EVIDENCE_ID)
        self.assertIn("jdl_tax_context_identity_sha256", saved.metadata)
        self.assertEqual(
            confirmed_mapping_mismatch_fields("課税仕入 10%", saved, context),
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
