from __future__ import annotations

import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from accounting_converter.application.jdl_migration_review import (
    JdlMigrationHumanReviewService,
    JdlMigrationReviewError,
)
from accounting_converter.application.jdl_migration_tax_evidence import (
    JDL_TO_JDL_TARGET_MASTER_IDENTITY_SHA256,
)
from accounting_converter.adapters.output.jdl import (
    JdlAccountIdentity,
    JdlSimplifiedBusinessCategory,
    JdlTargetContext,
    JdlTaxationMethod,
)
from accounting_converter.application.company_settings import (
    CompanySettingStatus,
    ResolvedCompanySetting,
)
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.mapping import (
    MappingStatus,
    MappingValue,
    SubaccountPolicy,
)
from accounting_converter.adapters.input.jdl import jdl_source_account_key
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_migration_input_schema_definition,
    jdl_ibex_cashbook_official_journal_import_schema_definition,
)
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode


class _Setting:
    def __init__(self, profile_id="profile-initial"):
        self.conversion_profile_id = profile_id
        self.context_fingerprint = "d" * 64
        self.expected_source_format_key = (
            jdl_ibex_cashbook_migration_input_schema_definition().identity.stable_key
        )
        self.expected_target_format_key = (
            jdl_ibex_cashbook_official_journal_import_schema_definition().identity.stable_key
        )


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
        self.master_hash = "b" * 64
        self.status = CompanySettingStatus.AVAILABLE
        self.context = None
        self.target_count = 5
        self.target_accounts_override = None
        self.target_subaccounts = ()

    def get(self, company_id):
        if company_id not in {"company-a", "company-b"}:
            raise ValueError("company not found")
        return self.setting

    def resolve(self, company_id):
        return ResolvedCompanySetting(
            self.get(company_id), self.status,
            profile=None, context=self.context,
        )

    def target_master_identity_sha256(self, company_id):
        self.get(company_id)
        return self.master_hash

    def target_master_inventory(self, company_id):
        self.get(company_id)
        return (
            self.target_accounts_override or tuple(
                SimpleNamespace(
                    target_master_code=f"{8000 + index}",
                    target_formal_name=f"出力科目{index}",
                )
                for index in range(self.target_count)
            ),
            self.target_subaccounts,
            frozenset(),
        )

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
        self.assertEqual(
            profile.source_format_identity,
            jdl_ibex_cashbook_migration_input_schema_definition().identity,
        )
        self.assertEqual(
            profile.target_format_identity,
            jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
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

    def test_exact_parent_is_persisted_for_confirmed_subaccount_mapping(self):
        self.company_store.target_accounts_override = (
            SimpleNamespace(
                target_master_code="8000",
                target_formal_name="入力科目0",
            ),
        )
        self.company_store.target_subaccounts = (
            SimpleNamespace(
                parent_account_code="8000",
                target_master_code="0001",
                target_name="出力補助",
                output_name="出力補助",
            ),
        )
        payload = self._payload()
        payload["subaccounts"][0]["target_candidates"] = [
            {"code": "0001", "name": "出力補助"}
        ]
        with tempfile.TemporaryDirectory() as directory:
            review = self.service.load(
                "company-a", self._write(Path(directory), payload)
            )
        subaccount = review.subaccounts[0]

        self.service.save(
            review,
            {},
            set(),
            {subaccount.key: ("0001", "出力補助")},
            {subaccount.key},
        )

        profile = self.profile_store.get(
            self.company_store.setting.conversion_profile_id
        )
        parent_key = jdl_source_account_key("8000", "入力科目0")
        self.assertEqual(
            profile.account_mappings[parent_key].status,
            MappingStatus.USER_CONFIRMED,
        )
        self.assertEqual(
            profile.account_mappings[parent_key].metadata["target_code"],
            "8000",
        )
        self.assertEqual(
            profile.account_mappings[parent_key].metadata["setup_context_sha256"],
            "d" * 64,
        )
    def test_same_case_and_master_can_open_for_another_company_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(Path(directory), self._payload())
            self.assertEqual(
                len(self.service.load("company-b", path).accounts), 5
            )

    def test_master_format_schema_and_stale_mismatches_are_blocked(self):
        cases = (
            (
                "target_master_identity_sha256", "c" * 64,
                "JDL-MIGRATION-REVIEW-TARGET-MASTER-MISMATCH",
            ),
            (
                "source_format_key", "wrong-source",
                "JDL-MIGRATION-REVIEW-SOURCE-FORMAT-MISMATCH",
            ),
            (
                "target_format_key", "wrong-target",
                "JDL-MIGRATION-REVIEW-TARGET-FORMAT-MISMATCH",
            ),
            (
                "review_schema_version", "1",
                "JDL-MIGRATION-REVIEW-SCHEMA-UNSUPPORTED",
            ),
        )
        for field, value, code in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                payload = self._payload()
                payload[field] = value
                with self.assertRaises(JdlMigrationReviewError) as caught:
                    self.service.load(
                        "company-a", self._write(Path(directory), payload)
                    )
                self.assertEqual(caught.exception.code, code)

        self.company_store.status = CompanySettingStatus.STALE
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(JdlMigrationReviewError) as caught:
                self.service.load(
                    "company-a", self._write(Path(directory), self._payload())
                )
        self.assertEqual(
            caught.exception.code, "JDL-MIGRATION-REVIEW-COMPANY-STALE"
        )

    def test_error_string_contains_stable_code_for_local_diagnostics(self):
        error = JdlMigrationReviewError("STABLE-CODE", "利用者向けメッセージ")

        self.assertIn("STABLE-CODE", str(error))
        self.assertEqual(error.user_message, "利用者向けメッセージ")

    def test_derives_current_review_without_external_json_and_offers_all_targets(self):
        source = Path("tests/fixtures/jdl/valid_simple.csv")

        review = self.service.derive("company-a", source)

        self.assertTrue(review.derived_state)
        self.assertEqual(len(review.accounts), 3)
        self.assertTrue(all(not item.recommended_targets for item in review.accounts))
        self.assertTrue(all(len(item.targets) == 5 for item in review.accounts))
        self.assertTrue(all(
            item.targets[0] == ("8000", "出力科目0")
            for item in review.accounts
        ))

    def test_derived_review_omits_reusable_confirmed_mapping(self):
        profile = self.profile_store.get("profile-initial")
        source_key = jdl_source_account_key("111", "現金")
        self.profile_store.values[profile.profile_id] = replace(
            profile,
            account_mappings={
                source_key: MappingValue(
                    source_key,
                    "出力科目0",
                    MappingStatus.USER_CONFIRMED,
                    metadata={
                        "target_code": "8000",
                        "target_printed_name": "出力科目0",
                    },
                )
            },
        )

        review = self.service.derive(
            "company-a", Path("tests/fixtures/jdl/valid_simple.csv")
        )

        self.assertEqual(review.reused_account_count, 1)
        self.assertNotIn("111", {item.source_code for item in review.accounts})

    def test_derived_review_blocks_save_after_source_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            source.write_bytes(Path("tests/fixtures/jdl/valid_simple.csv").read_bytes())
            review = self.service.derive("company-a", source)
            source.write_bytes(source.read_bytes() + b"changed")

            with self.assertRaises(JdlMigrationReviewError) as caught:
                self.service.save(review, {}, set(), {}, set())

        self.assertEqual(
            caught.exception.code, "JDL-MIGRATION-REVIEW-SOURCE-CHANGED"
        )

    def test_other_enabled_target_requires_confirmation_then_is_reused(self):
        source = Path("tests/fixtures/jdl/valid_simple.csv")
        review = self.service.derive("company-a", source)
        item = review.accounts[0]
        selected = item.targets[-1]

        self.service.save(
            review, {item.key: selected}, {item.key}, {}, set()
        )
        reopened = self.service.derive("company-a", source)

        self.assertEqual(reopened.reused_account_count, 1)
        self.assertNotIn(item.source_code, {row.source_code for row in reopened.accounts})

    def test_partial_save_reuses_only_confirmed_items_and_keeps_remainder(self):
        source = Path("tests/fixtures/jdl/valid_simple.csv")
        review = self.service.derive("company-a", source)
        selected_items = review.accounts[:2]

        self.service.save(
            review,
            {item.key: item.targets[0] for item in selected_items},
            {item.key for item in selected_items},
            {},
            set(),
        )
        reopened = self.service.derive("company-a", source)

        self.assertEqual(reopened.reused_account_count, 2)
        self.assertEqual(len(reopened.accounts), len(review.accounts) - 2)
        profile = self.profile_store.get(
            self.company_store.setting.conversion_profile_id
        )
        self.assertEqual(len(profile.account_mappings), 2)
        self.assertTrue(all(
            value.metadata.get("target_formal_name")
            for value in profile.account_mappings.values()
        ))
        self.assertTrue(all(
            value.metadata.get("setup_context_sha256") == "d" * 64
            for value in profile.account_mappings.values()
        ))
        self.assertTrue(all(
            value.status is MappingStatus.USER_CONFIRMED
            for value in profile.account_mappings.values()
        ))

    def test_nine_items_can_save_eight_and_reopen_with_one(self):
        self.company_store.target_count = 12
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "nine-accounts.csv"
            fixture_rows = list(csv.reader(
                Path("tests/fixtures/jdl/valid_simple.csv").read_text(
                    encoding="cp932"
                ).splitlines()
            ))
            header = fixture_rows[0]
            rows = []
            for index in range(9):
                row = [""] * 30
                row[0] = "1111"
                row[1] = str(index + 1)
                row[2] = "20260821"
                row[3:6] = [f"{9000 + index}", f"入力科目{index}", f"入力科目{index}"]
                row[11] = "100"
                row[13:16] = ["9000", "入力科目0", "入力科目0"]
                row[21] = "100"
                row[23] = f"SYNTHETIC-{index}"
                rows.append(row)
            with source.open("w", encoding="cp932", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\r\n")
                writer.writerow(header)
                writer.writerows(rows)

            review = self.service.derive("company-a", source)
            confirmed = review.accounts[:8]
            self.service.save(
                review,
                {item.key: item.targets[0] for item in confirmed},
                {item.key for item in confirmed},
                {},
                set(),
            )
            reopened = self.service.derive("company-a", source)

        self.assertEqual(len(review.accounts), 9)
        self.assertEqual(reopened.reused_account_count, 8)
        self.assertEqual(len(reopened.accounts), 1)
        profile = self.profile_store.get(
            self.company_store.setting.conversion_profile_id
        )
        self.assertEqual(len(profile.account_mappings), 8)
        self.assertTrue(all(
            value.status is MappingStatus.USER_CONFIRMED
            for value in profile.account_mappings.values()
        ))

    def test_exact_master_and_simplified_first_context_activate_sales_evidence(self):
        self.company_store.master_hash = JDL_TO_JDL_TARGET_MASTER_IDENTITY_SHA256
        self.company_store.target_accounts_override = (
            SimpleNamespace(target_master_code="111", target_formal_name="現金"),
            SimpleNamespace(target_master_code="612", target_formal_name="売上高"),
        )
        self.company_store.context = JdlTargetContext(
            product="JDL IBEX 出納帳",
            version="35.5",
            accounts=frozenset({"現金", "売上高"}),
            tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED,
            taxation_method=JdlTaxationMethod.SIMPLIFIED,
            simplified_business_category=JdlSimplifiedBusinessCategory.FIRST,
            account_master=self._tax_evidence_accounts(),
        )

        review = self.service.derive(
            "company-a", Path("tests/fixtures/jdl/valid_simple.csv")
        )

        fifth = next(item for item in review.taxes if item.label == "売五種 / 10%")
        self.assertEqual(fifth.evidence_status, "VERIFIED_BY_REAL_IMPORT")
        self.assertEqual(fifth.status, "HUMAN_CONFIRMATION_REQUIRED")

    def test_evidence_backed_tax_requires_confirmation_then_is_reused(self):
        self.company_store.target_accounts_override = (
            SimpleNamespace(target_master_code="111", target_formal_name="現金"),
            SimpleNamespace(target_master_code="612", target_formal_name="売上高"),
        )
        self.company_store.context = JdlTargetContext(
            product="JDL IBEX 出納帳",
            version="35.5",
            accounts=frozenset({"現金", "売上高"}),
            tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED,
            taxation_method=JdlTaxationMethod.SIMPLIFIED,
            simplified_business_category=JdlSimplifiedBusinessCategory.FIRST,
            account_master=self._tax_evidence_accounts(),
        )
        source = Path("tests/fixtures/jdl/valid_simple.csv")
        review = self.service.derive("company-a", source)
        fifth = next(item for item in review.taxes if item.label == "売五種 / 10%")

        self.service.save(
            review, {}, set(), {}, set(), {fifth.source_key}
        )
        reopened = self.service.derive("company-a", source)

        self.assertEqual(reopened.reused_tax_count, 1)
        self.assertNotIn(
            fifth.source_key, {item.source_key for item in reopened.taxes}
        )
        saved = self.profile_store.get(
            self.company_store.setting.conversion_profile_id
        ).tax_mappings[fifth.source_key]
        self.assertIs(saved.status, MappingStatus.USER_CONFIRMED)
        self.assertEqual(saved.metadata["jdl_evidence_id"], fifth.evidence_id)
        self.assertEqual(saved.metadata["setup_context_sha256"], "d" * 64)

        self.company_store.context = replace(
            self.company_store.context,
            taxation_method=JdlTaxationMethod.STANDARD,
            simplified_business_category=None,
        )
        changed = self.service.derive("company-a", source)
        changed_fifth = next(
            item for item in changed.taxes if item.source_key == fifth.source_key
        )
        self.assertEqual(
            changed_fifth.evidence_status, "VERIFIED_CONTEXT_MISMATCH"
        )

    def test_non_taxable_sales_requires_confirmation_then_is_reused(self):
        self.company_store.target_accounts_override = (
            SimpleNamespace(target_master_code="111", target_formal_name="現金"),
            SimpleNamespace(target_master_code="612", target_formal_name="売上高"),
        )
        self.company_store.context = JdlTargetContext(
            product="JDL IBEX 出納帳",
            version="35.5",
            accounts=frozenset({"現金", "売上高"}),
            tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED,
            taxation_method=JdlTaxationMethod.SIMPLIFIED,
            simplified_business_category=JdlSimplifiedBusinessCategory.FIRST,
            account_master=self._tax_evidence_accounts(),
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "non-taxable-sales.csv"
            raw = Path("tests/fixtures/jdl/valid_simple.csv").read_bytes()
            source.write_bytes(
                raw.replace("売五種".encode("cp932"), "非売上".encode("cp932"))
                .replace(b",10%,", b",,", 1)
            )
            review = self.service.derive("company-a", source)
            item = next(row for row in review.taxes if row.label == "非売上")

            self.assertEqual(item.evidence_status, "VERIFIED_BY_REAL_IMPORT")
            self.assertEqual(item.status, "HUMAN_CONFIRMATION_REQUIRED")
            self.service.save(review, {}, set(), {}, set(), {item.source_key})
            reopened = self.service.derive("company-a", source)

        self.assertEqual(reopened.reused_tax_count, 1)
        self.assertNotIn(item.source_key, {row.source_key for row in reopened.taxes})
        saved = self.profile_store.get(
            self.company_store.setting.conversion_profile_id
        ).tax_mappings[item.source_key]
        self.assertIs(saved.status, MappingStatus.USER_CONFIRMED)
        self.assertEqual(
            saved.metadata["jdl_evidence_id"],
            "EVID-JDL-MIGRATION-TAX-NON-TAXABLE-SALES-ROUNDTRIP-001",
        )

    def test_tax_without_evidence_cannot_be_confirmed(self):
        review = self.service.derive(
            "company-a", Path("tests/fixtures/jdl/valid_simple.csv")
        )
        with self.assertRaises(JdlMigrationReviewError) as caught:
            self.service.save(
                review, {}, set(), {}, set(), {"unverified-tax-key"}
            )

        self.assertEqual(
            caught.exception.code,
            "JDL-MIGRATION-REVIEW-TAX-EVIDENCE-REQUIRED",
        )

    def test_description_replacement_partial_save_and_source_staleness(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "long-description.csv"
            raw = Path("tests/fixtures/jdl/valid_simple.csv").read_bytes()
            raw = raw.replace("架空デモ売上".encode("cp932"), b"A" * 33)
            source.write_bytes(raw)
            review = self.service.derive("company-a", source)
            item = review.descriptions[0]

            self.service.save(
                review,
                {},
                set(),
                {},
                set(),
                set(),
                {item.row_key: "Human replacement"},
                {item.row_key},
            )
            reopened = self.service.derive("company-a", source)
            self.assertEqual(reopened.descriptions, ())
            mapping = self.profile_store.get(
                self.company_store.setting.conversion_profile_id
            ).loss_policy_mappings[item.row_key]
            self.assertIs(mapping.status, MappingStatus.USER_CONFIRMED)
            self.assertEqual(
                mapping.metadata["original_description_sha256"],
                item.original_description_sha256,
            )

            source.write_bytes(raw.replace(b"A" * 33, b"B" * 33))
            changed = self.service.derive("company-a", source)
            self.assertEqual(len(changed.descriptions), 1)

    def test_description_replacement_rejects_length_and_cp932(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "long-description.csv"
            source.write_bytes(
                Path("tests/fixtures/jdl/valid_simple.csv").read_bytes().replace(
                    "架空デモ売上".encode("cp932"), b"A" * 33
                )
            )
            review = self.service.derive("company-a", source)
            item = review.descriptions[0]
            for replacement, code in (
                ("", "JDL-MIGRATION-REVIEW-DESCRIPTION-INVALID"),
                ("A" * 33, "JDL-MIGRATION-REVIEW-DESCRIPTION-INVALID"),
                ("𠀋", "JDL-MIGRATION-REVIEW-DESCRIPTION-CP932"),
            ):
                with self.subTest(replacement=replacement), self.assertRaises(
                    JdlMigrationReviewError
                ) as caught:
                    self.service.save(
                        review, {}, set(), {}, set(), set(),
                        {item.row_key: replacement}, {item.row_key},
                    )
                self.assertEqual(caught.exception.code, code)

    def test_known_evidence_with_wrong_context_remains_blocked_with_clear_reason(self):
        self.company_store.master_hash = JDL_TO_JDL_TARGET_MASTER_IDENTITY_SHA256
        self.company_store.target_accounts_override = (
            SimpleNamespace(target_master_code="111", target_formal_name="現金"),
            SimpleNamespace(target_master_code="612", target_formal_name="売上高"),
        )
        self.company_store.context = JdlTargetContext(
            product="JDL IBEX 出納帳",
            version="35.5",
            accounts=frozenset({"現金", "売上高"}),
            tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED,
            taxation_method=JdlTaxationMethod.STANDARD,
            account_master=self._tax_evidence_accounts(),
        )

        review = self.service.derive(
            "company-a", Path("tests/fixtures/jdl/valid_simple.csv")
        )

        fifth = next(item for item in review.taxes if item.label == "売五種 / 10%")
        self.assertEqual(fifth.evidence_status, "VERIFIED_CONTEXT_MISMATCH")
        self.assertEqual(fifth.status, "CONTEXT_CONFIRMATION_REQUIRED")
        self.assertIn("JDL税設定が実機確認時の条件と異なります", fifth.dependency_detail)
        self.assertTrue(fifth.evidence_id)

    def test_relevant_master_with_unconfirmed_context_reports_context_mismatch(self):
        self.company_store.target_accounts_override = (
            SimpleNamespace(target_master_code="111", target_formal_name="現金"),
            SimpleNamespace(target_master_code="612", target_formal_name="売上高"),
        )
        self.company_store.context = None

        review = self.service.derive(
            "company-a", Path("tests/fixtures/jdl/valid_simple.csv")
        )

        fifth = next(item for item in review.taxes if item.label == "売五種 / 10%")
        self.assertEqual(fifth.evidence_status, "VERIFIED_CONTEXT_MISMATCH")
        self.assertEqual(fifth.status, "CONTEXT_CONFIRMATION_REQUIRED")
        self.assertIn("JDL税設定の再確認", fifth.dependency_detail)

    def test_known_evidence_with_wrong_master_remains_blocked_with_clear_reason(self):
        self.company_store.context = JdlTargetContext(
            product="JDL IBEX 出納帳",
            version="35.5",
            accounts=frozenset(),
            tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED,
            taxation_method=JdlTaxationMethod.SIMPLIFIED,
            simplified_business_category=JdlSimplifiedBusinessCategory.FIRST,
        )

        review = self.service.derive(
            "company-a", Path("tests/fixtures/jdl/valid_simple.csv")
        )

        fifth = next(item for item in review.taxes if item.label == "売五種 / 10%")
        self.assertEqual(fifth.evidence_status, "VERIFIED_MASTER_MISMATCH")
        self.assertEqual(fifth.status, "TARGET_MASTER_CONFIRMATION_REQUIRED")
        self.assertTrue(fifth.evidence_id)

    def test_derived_review_blocks_save_after_master_changes(self):
        review = self.service.derive(
            "company-a", Path("tests/fixtures/jdl/valid_simple.csv")
        )
        self.company_store.master_hash = "c" * 64

        with self.assertRaises(JdlMigrationReviewError) as caught:
            self.service.save(review, {}, set(), {}, set())

        self.assertEqual(
            caught.exception.code,
            "JDL-MIGRATION-REVIEW-TARGET-MASTER-CHANGED",
        )

    @staticmethod
    def _tax_evidence_accounts():
        return (
            JdlAccountIdentity("現金", "111", "現金", "現金"),
            JdlAccountIdentity("売上高", "612", "売上高", "売上高"),
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
            "review_schema_version": "2",
            "formal_output_enabled": False,
            "source_sha256": "a" * 64,
            "target_master_identity_sha256": "b" * 64,
            "source_format_key": (
                jdl_ibex_cashbook_migration_input_schema_definition().identity.stable_key
            ),
            "target_format_key": (
                jdl_ibex_cashbook_official_journal_import_schema_definition().identity.stable_key
            ),
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
