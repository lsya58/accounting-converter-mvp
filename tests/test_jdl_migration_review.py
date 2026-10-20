from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from accounting_converter.application.jdl_migration_review import (
    JdlMigrationHumanReviewService,
    JdlMigrationReviewError,
)
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.mapping import MappingStatus, SubaccountPolicy
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_migration_input_schema_definition,
    jdl_ibex_cashbook_official_journal_import_schema_definition,
)


class _Setting:
    def __init__(self, profile_id="profile-initial"):
        self.conversion_profile_id = profile_id


class _ProfileStore:
    def __init__(self, profile):
        self.values = {profile.profile_id: profile}

    def get(self, profile_id):
        return self.values[profile_id]

    def create(self, profile):
        self.values[profile.profile_id] = profile
        return profile

    def delete(self, profile_id):
        self.values.pop(profile_id, None)


class _CompanyStore:
    def __init__(self):
        self.setting = _Setting()

    def get(self, company_id):
        if company_id != "company-a":
            raise ValueError("company not found")
        return self.setting

    def replace_profile(self, company_id, profile_id):
        self.get(company_id)
        self.setting = _Setting(profile_id)


class JdlMigrationHumanReviewTests(unittest.TestCase):
    def setUp(self):
        source = jdl_ibex_cashbook_migration_input_schema_definition().identity
        target = jdl_ibex_cashbook_official_journal_import_schema_definition().identity
        self.profile_store = _ProfileStore(
            ConversionProfile("profile-initial", "Migration", source, target)
        )
        self.company_store = _CompanyStore()
        self.service = JdlMigrationHumanReviewService(
            self.company_store, self.profile_store
        )

    def test_loads_five_accounts_four_subaccounts_and_blockers(self):
        with tempfile.TemporaryDirectory() as directory:
            review = self.service.load(
                "company-a", self._write(Path(directory), self._payload())
            )
        self.assertEqual(len(review.accounts), 5)
        self.assertEqual(len(review.subaccounts), 4)
        self.assertEqual(len(review.taxes), 3)
        self.assertEqual(len(review.descriptions), 2)
        self.assertTrue(all("EVIDENCE" in item.status for item in review.taxes))

    def test_only_explicitly_confirmed_decisions_are_persisted_and_reopenable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(Path(directory), self._payload())
            review = self.service.load("company-a", path)
            account = review.accounts[0]
            subaccount = review.subaccounts[0]
            self.service.save(
                review,
                {account.key: account.targets[0]},
                {account.key},
                {subaccount.key: SubaccountPolicy.PARENT_ONLY_CONFIRMED.value},
                {subaccount.key},
            )
            reopened = self.service.load("company-a", path)
        profile = self.profile_store.get(
            self.company_store.setting.conversion_profile_id
        )
        self.assertEqual(len(profile.account_mappings), 1)
        self.assertEqual(len(profile.subaccount_context_mappings), 1)
        self.assertTrue(all(
            value.status is MappingStatus.USER_CONFIRMED
            for value in profile.account_mappings.values()
        ))
        self.assertEqual(len(reopened.accounts), 5)
        self.assertEqual(len(profile.tax_mappings), 0)

    def test_unconfirmed_parent_blocks_subaccount_and_preserve_needs_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            review = self.service.load(
                "company-a", self._write(Path(directory), self._payload())
            )
        subaccount = review.subaccounts[0]
        with self.assertRaisesRegex(JdlMigrationReviewError, "親科目"):
            self.service.save(
                review, {}, set(),
                {subaccount.key: SubaccountPolicy.PARENT_ONLY_CONFIRMED.value},
                {subaccount.key},
            )

    @staticmethod
    def _payload():
        accounts = []
        for index in range(5):
            code = f"{8000 + index}"
            accounts.append({
                "source": {"code": code, "name": f"入力科目{index}"},
                "classification": "SAME_CODE_NAME_CHANGED",
                "target_candidates": [{"code": code, "name": f"出力科目{index}"}],
                "decision": "HUMAN_REQUIRED",
            })
        subaccounts = [{
            "parent_code": "8000", "parent_name": "入力科目0",
            "source_code": f"000{index + 1}", "source_name": f"入力補助{index}",
            "decision": "HUMAN_REQUIRED", "target_candidates": [],
        } for index in range(4)]
        return {
            "document_type": "JDL_MIGRATION_HUMAN_REVIEW",
            "formal_output_enabled": False,
            "account_mismatches": accounts,
            "subaccounts": subaccounts,
            "tax": {
                "target_context_confirmation": ["product_and_version"],
                "source_identities": [{
                    "scope": "synthetic", "category": f"税{index}",
                    "input_method": "", "row_count": 1,
                    "decision": "EVIDENCE_AND_HUMAN_CONFIRMATION_REQUIRED",
                } for index in range(3)],
            },
            "description": {
                "overflow_row_count": 2,
                "overflow_rows": [
                    {"journal_identifier": "synthetic-1", "current_length": 33},
                    {"journal_identifier": "synthetic-2", "current_length": 40},
                ],
                "policy": "BLOCK_NO_TRUNCATION",
            },
        }

    @staticmethod
    def _write(root: Path, payload) -> Path:
        path = root / "review.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path
