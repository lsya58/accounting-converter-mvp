from __future__ import annotations

import hashlib
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from accounting_converter.application.moneyforward_description_replacement import (
    MF_DESCRIPTION_REPLACEMENT_POLICY,
    MoneyForwardDescriptionReplacementPolicy,
    moneyforward_description_replacement_key,
    observed_jdl_description,
    recommended_description_replacement,
)
from accounting_converter.application.moneyforward_jdl_loss import MoneyForwardToJdlLossRule
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.journal import JournalEntry, JournalLine, Side, SourceReference
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
    moneyforward_cloud_journal_export_observed_schema,
)


class MoneyForwardDescriptionReplacementTests(unittest.TestCase):
    def test_observed_character_has_explanatory_preview_and_human_candidate(self):
        self.assertEqual(observed_jdl_description("髙橋"), "・橋")
        self.assertEqual(recommended_description_replacement("髙橋"), "高橋")
        self.assertIsNone(recommended_description_replacement("通常摘要"))

    def test_unconfirmed_non_roundtrip_character_blocks(self):
        entry = self._entry("髙橋")
        result = MoneyForwardDescriptionReplacementPolicy(
            self._profile()
        ).apply((entry,))

        self.assertEqual(
            [item.rule_id for item in result.validation_results],
            ["MF-JDL-DESCRIPTION-NONROUNDTRIP-CHARACTER"],
        )
        self.assertEqual(result.entries[0].description, "髙橋")
        self.assertEqual(
            [item.field for item in MoneyForwardToJdlLossRule().validate(entry)],
            ["description_character"],
        )

    def test_confirmed_exact_replacement_is_applied_and_reused(self):
        original = "髙橋"
        key = moneyforward_description_replacement_key(original)
        profile = self._profile({
            key: MappingValue(
                key,
                "高橋",
                MappingStatus.USER_CONFIRMED,
                metadata={
                    "policy": MF_DESCRIPTION_REPLACEMENT_POLICY,
                    "original_description_sha256": hashlib.sha256(
                        original.encode()
                    ).hexdigest(),
                },
            )
        })

        result = MoneyForwardDescriptionReplacementPolicy(profile).apply(
            (self._entry(original, "one"), self._entry(original, "two"))
        )

        self.assertEqual(result.validation_results, ())
        self.assertEqual([item.description for item in result.entries], ["高橋", "高橋"])
        self.assertEqual(
            MoneyForwardToJdlLossRule().validate(result.entries[0]), []
        )

    def test_changed_source_does_not_reuse_replacement(self):
        original = "髙橋"
        key = moneyforward_description_replacement_key(original)
        profile = self._profile({
            key: MappingValue(
                key,
                "高橋",
                MappingStatus.USER_CONFIRMED,
                metadata={
                    "policy": MF_DESCRIPTION_REPLACEMENT_POLICY,
                    "original_description_sha256": hashlib.sha256(
                        original.encode()
                    ).hexdigest(),
                },
            )
        })

        result = MoneyForwardDescriptionReplacementPolicy(profile).apply(
            (self._entry("髙橋X"),)
        )

        self.assertEqual(len(result.validation_results), 1)
        self.assertEqual(result.entries[0].description, "髙橋X")

    @staticmethod
    def _entry(description: str, suffix: str = "one") -> JournalEntry:
        reference = SourceReference("synthetic.csv", 2, suffix)
        return JournalEntry(
            f"mf:{suffix}",
            reference,
            date(2026, 1, 8),
            [
                JournalLine(Side.DEBIT, "A", Decimal("100"), reference),
                JournalLine(Side.CREDIT, "B", Decimal("100"), reference),
            ],
            description,
            metadata={
                "moneyforward_descriptions": (
                    {"row_number": 2, "value": description},
                )
            },
        )

    @staticmethod
    def _profile(loss_policies=None) -> ConversionProfile:
        now = datetime.now(timezone.utc)
        return ConversionProfile(
            "profile",
            "profile",
            moneyforward_cloud_journal_export_observed_schema().identity,
            jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
            loss_policy_mappings=loss_policies or {},
            created_at=now,
            updated_at=now,
        )


if __name__ == "__main__":
    unittest.main()
