from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from accounting_converter.application.account_mapping_review import (
    AccountCandidateClassification,
    AccountMappingReviewService,
)
from accounting_converter.application.jdl_master_observation import (
    JdlMasterCompleteness,
    JdlMasterObservation,
    JdlMasterSourceEvidence,
    JdlPrintedAccount,
)
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.journal import JournalEntry, JournalLine, Side, SourceReference
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from accounting_converter.infrastructure.adapter_registry import (
    AdapterAvailabilityStatus,
    production_adapter_registry,
)
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
    moneyforward_cloud_journal_export_observed_schema,
)


class AccountMappingReviewServiceTests(unittest.TestCase):
    def test_28_requirements_classify_20_exact_and_8_missing_without_auto_confirmation(self) -> None:
        result = AccountMappingReviewService().build(self._entries(), self._master())
        summary = result.privacy_safe_summary()

        self.assertEqual(summary["total_requirements"], 28)
        self.assertEqual(summary["exact_candidate_count"], 20)
        self.assertEqual(summary["no_candidate_count"], 8)
        self.assertEqual(summary["ambiguous_count"], 0)
        self.assertEqual(summary["confirmed_count"], 0)
        self.assertEqual(summary["unresolved_count"], 28)
        self.assertEqual(result.journals_affected_by_unresolved_accounts, 28)
        self.assertTrue(all(not item.usable for item in result.items))
        self.assertNotIn("架空科目01", str(summary))

    def test_exact_candidate_becomes_usable_only_after_user_confirmation(self) -> None:
        profile = self._profile({
            "架空科目01": MappingValue(
                "架空科目01", "架空科目01", MappingStatus.USER_CONFIRMED,
                metadata={"target_code": "1001"},
            )
        })
        result = AccountMappingReviewService().build(
            self._entries(), self._master(), profile
        )
        item = next(x for x in result.items if x.requirement.source_value == "架空科目01")

        self.assertEqual(item.classification, AccountCandidateClassification.EXACT_CANDIDATE)
        self.assertTrue(item.confirmed)
        self.assertTrue(item.usable)

    def test_missing_candidate_can_use_only_explicit_context_target(self) -> None:
        profile = self._profile({
            "架空科目28": MappingValue(
                "架空科目28", "架空科目01", MappingStatus.USER_CONFIRMED,
                metadata={"target_code": "1001"},
            )
        })
        result = AccountMappingReviewService().build(
            self._entries(), self._master(), profile
        )
        item = next(x for x in result.items if x.requirement.source_value == "架空科目28")
        self.assertEqual(item.classification, AccountCandidateClassification.NO_CANDIDATE)
        self.assertTrue(item.usable)

        outside = self._profile({
            "架空科目28": MappingValue(
                "架空科目28", "存在しない科目", MappingStatus.USER_CONFIRMED,
            )
        })
        blocked = AccountMappingReviewService().build(
            self._entries(), self._master(), outside
        )
        blocked_item = next(
            x for x in blocked.items if x.requirement.source_value == "架空科目28"
        )
        self.assertFalse(blocked_item.usable)
        self.assertEqual(blocked_item.blocker_reason, "CONFIRMED_TARGET_NOT_IN_CONTEXT")

    def test_ambiguous_exact_identity_is_blocked_without_fuzzy_fallback(self) -> None:
        master = self._master(extra=(
            JdlPrintedAccount("1999", "架空科目01", "別略称", "DEBIT", True),
        ))
        result = AccountMappingReviewService().build(self._entries(), master)
        item = next(x for x in result.items if x.requirement.source_value == "架空科目01")
        self.assertEqual(item.classification, AccountCandidateClassification.AMBIGUOUS)
        self.assertIsNone(item.exact_candidate)
        self.assertFalse(item.usable)

    def test_private_report_is_explicitly_private_and_registry_stays_narrow(self) -> None:
        result = AccountMappingReviewService().build(self._entries(), self._master())
        report = result.private_report()
        self.assertIn("PRIVATE LOCAL REPORT", report["privacy_notice"])
        self.assertEqual(len(report["items"]), 28)
        registry = production_adapter_registry()
        source = moneyforward_cloud_journal_export_observed_schema().identity
        target = jdl_ibex_cashbook_official_journal_import_schema_definition().identity
        self.assertEqual(registry.get_exact_input(source).status, AdapterAvailabilityStatus.UNAVAILABLE)
        self.assertFalse(registry.has_conversion_pair(source, target))

    @staticmethod
    def _entries():
        entries = []
        for index in range(1, 29):
            account = f"架空科目{index:02d}"
            reference = SourceReference("synthetic.csv", index, str(index))
            entries.append(JournalEntry(
                id=str(index), source_reference=reference, date=date(2026, 1, 1),
                lines=[
                    JournalLine(Side.DEBIT, account, Decimal("1"), reference,
                                sub_account="架空補助" if index <= 3 else None),
                    JournalLine(Side.CREDIT, account, Decimal("1"), reference),
                ],
            ))
        return entries

    @staticmethod
    def _master(extra=()):
        accounts = tuple(
            JdlPrintedAccount(
                str(1000 + index), f"架空科目{index:02d}",
                f"略称{index:02d}", "DEBIT", True,
            )
            for index in range(1, 21)
        ) + tuple(extra)
        return JdlMasterObservation(
            accounts=(), subaccounts=(), departments=(),
            sources=(JdlMasterSourceEvidence("0" * 64, "SYNTHETIC", 20),),
            completeness=JdlMasterCompleteness.OBSERVED_PRINTED_MASTER,
            printed_accounts=accounts,
        )

    @staticmethod
    def _profile(mappings):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return ConversionProfile(
            profile_id="synthetic-review", profile_name="Synthetic review",
            source_format_identity=moneyforward_cloud_journal_export_observed_schema().identity,
            target_format_identity=jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
            account_mappings=mappings, created_at=now, updated_at=now,
        )


if __name__ == "__main__":
    unittest.main()
