from __future__ import annotations

import hashlib
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path

from accounting_converter.application.company_tax_context_confirmation import (
    CompanyTaxContextConfirmationError,
    CompanyTaxContextConfirmationService,
    JdlTaxContextSelection,
)
from accounting_converter.adapters.output.jdl import (
    JdlInputTaxCreditMethod,
    JdlSimplifiedBusinessCategory,
    JdlTaxationMethod,
)
from accounting_converter.application.moneyforward_profile_setup import (
    MoneyForwardProfileSetupService,
)
from accounting_converter.infrastructure.application_preferences import (
    ApplicationPreferencesStore,
)
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.mapping import (
    MappingKey,
    MappingStatus,
    MappingType,
    MappingValue,
)
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.infrastructure.jdl_account_pdf_draft import JdlAccountPdfDraftStore
from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
    moneyforward_cloud_journal_export_observed_schema,
)
from accounting_converter.ui.controllers import AccountingConverterController


class _PrintedMaster:
    def extract_pages(self, _path):
        return (
            "科 目 一 覧\n1\n"
            "勘定科目 略名称 使用 課区 税区 入力 固変 比率 説明\n"
            "  1001- 架空現金  借A ○\n"
            "  2001- 架空預金  借B ○\n"
            "  -0001 架空補助  借\n",
        )


class CompanyTaxContextConfirmationTests(unittest.TestCase):
    TAXES = (
        "課税仕入 10%",
        "課税売上 10%",
        "課税仕入 (軽)8%",
        "課税売上 (軽)8%",
        "非課税仕入",
        "対象外",
    )

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        source = self.root / "master.pdf"
        source.write_bytes(b"synthetic")
        self.draft = self.root / "master.json"
        JdlAccountPdfDraftStore(_PrintedMaster()).import_pdf(source, self.draft)
        draft_hash = hashlib.sha256(self.draft.read_bytes()).hexdigest()
        self.profiles = ConversionProfileStore(self.root / "profiles")
        now = datetime(2026, 10, 17, tzinfo=timezone.utc)
        self.profiles.create(
            ConversionProfile(
                profile_id="profile-1",
                profile_name="架空対応設定",
                source_format_identity=(
                    moneyforward_cloud_journal_export_observed_schema().identity
                ),
                target_format_identity=(
                    jdl_ibex_cashbook_official_journal_import_schema_definition().identity
                ),
                account_mappings={
                    "入力現金": MappingValue(
                        "入力現金",
                        "架空現金",
                        MappingStatus.USER_CONFIRMED,
                        metadata={
                            "target_code": "1001",
                            "target_formal_name": "架空現金",
                            "setup_context_sha256": draft_hash,
                        },
                    ),
                    "入力預金": MappingValue(
                        "入力預金",
                        "架空預金",
                        MappingStatus.USER_CONFIRMED,
                        metadata={
                            "target_code": "2001",
                            "target_formal_name": "架空預金",
                            "setup_context_sha256": draft_hash,
                        },
                    ),
                },
                subaccount_context_mappings={
                    MappingKey(MappingType.SUBACCOUNT, "入力補助", "入力預金"):
                    MappingValue(
                        "入力補助",
                        "架空補助",
                        MappingStatus.USER_CONFIRMED,
                        parent_account="入力預金",
                        metadata={
                            "target_code": "0001",
                            "output_code": "0001",
                            "output_name": "架空補助",
                            "setup_context_sha256": draft_hash,
                        },
                    )
                },
                tax_mappings={
                    value: MappingValue(
                        value,
                        "old",
                        MappingStatus.USER_CONFIRMED,
                        metadata={"jdl_evidence_id": "old"},
                    )
                    for value in self.TAXES
                },
                created_at=now,
                updated_at=now,
            )
        )
        self.companies = CompanySettingStore(self.root / "companies", self.profiles)
        self.setting = self.companies.create(
            company_setting_id="company-1",
            display_name="架空会社",
            conversion_profile_id="profile-1",
            context_source=self.draft,
        )
        self.service = CompanyTaxContextConfirmationService(
            self.companies, self.profiles
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_explicit_confirmation_promotes_draft_and_preserves_master(self) -> None:
        old_fingerprint = self.setting.context_fingerprint
        master_identity = self.companies.target_master_identity_sha256("company-1")
        self.assertTrue(self.service.is_pending("company-1"))
        with self.assertRaises(CompanyTaxContextConfirmationError):
            self.service.confirm_taxable_included("company-1", confirmed=False)

        context = self.service.confirm_taxable_included(
            "company-1", confirmed=True
        )
        updated_setting = self.companies.get("company-1")
        saved_context = JdlTargetContextLoader().load(
            self.companies.context_path(updated_setting)
        )
        self.assertFalse(self.service.is_pending("company-1"))
        self.assertNotEqual(updated_setting.context_fingerprint, old_fingerprint)
        reopened_companies = CompanySettingStore(
            self.root / "companies", self.profiles
        )
        self.assertEqual(
            reopened_companies.target_master_identity_sha256("company-1"),
            master_identity,
        )
        self.assertEqual(saved_context, context)
        self.assertEqual(len(saved_context.account_master), 2)
        self.assertEqual(len(saved_context.subaccounts), 1)
        self.assertTrue(saved_context.subaccounts[0].output_representation_confirmed)
        self.assertIs(
            saved_context.tax_processing_mode,
            JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED,
        )
        self.assertTrue(saved_context.standard_taxation_confirmed)
        self.assertTrue(saved_context.individual_credit_method_confirmed)

        profile = self.profiles.get(updated_setting.conversion_profile_id)
        original_profile = self.profiles.get("profile-1")
        self.assertEqual(
            profile.source_format_identity,
            original_profile.source_format_identity,
        )
        self.assertEqual(
            profile.target_format_identity,
            original_profile.target_format_identity,
        )
        self.assertTrue(
            all(
                value.status is MappingStatus.USER_CONFIRMED
                for value in profile.account_mappings.values()
            )
        )
        self.assertTrue(
            all(
                value.status is MappingStatus.USER_CONFIRMED
                for value in profile.subaccount_context_mappings.values()
            )
        )
        self.assertTrue(
            all(value.status is MappingStatus.UNRESOLVED for value in profile.tax_mappings.values())
        )
        self.assertTrue(
            all(
                value.metadata["setup_context_sha256"]
                == updated_setting.context_fingerprint
                for value in (
                    *profile.account_mappings.values(),
                    *profile.subaccount_context_mappings.values(),
                )
            )
        )
        review = MoneyForwardProfileSetupService(self.profiles).tax_mapping_review(
            profile, saved_context
        )
        self.assertTrue(review.context_compatible)
        self.assertEqual(
            {item.source_value for item in review.items}, set(self.TAXES)
        )

    def test_reconfirmation_changes_only_tax_context_and_resets_tax_mapping(self) -> None:
        self.service.confirm_taxable_included("company-1", confirmed=True)
        before_master = self.companies.target_master_identity_sha256("company-1")
        context = self.service.confirm(
            "company-1",
            selection=JdlTaxContextSelection(
                tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED,
                taxation_method=JdlTaxationMethod.SIMPLIFIED,
                simplified_business_category=JdlSimplifiedBusinessCategory.FIRST,
            ),
            confirmed=True,
        )
        self.assertIs(context.taxation_method, JdlTaxationMethod.SIMPLIFIED)
        self.assertIs(
            context.simplified_business_category,
            JdlSimplifiedBusinessCategory.FIRST,
        )
        reopened = JdlTargetContextLoader().load(
            self.companies.context_path(self.companies.get("company-1"))
        )
        self.assertEqual(reopened, context)
        self.assertEqual(
            self.companies.target_master_identity_sha256("company-1"),
            before_master,
        )
        setting = self.companies.get("company-1")
        profile = self.profiles.get(setting.conversion_profile_id)
        self.assertTrue(all(
            value.status is MappingStatus.USER_CONFIRMED
            for value in profile.account_mappings.values()
        ))
        self.assertTrue(all(
            value.status is MappingStatus.USER_CONFIRMED
            for value in profile.subaccount_context_mappings.values()
        ))
        self.assertTrue(all(
            value.status is MappingStatus.UNRESOLVED
            for value in profile.tax_mappings.values()
        ))

    def test_printed_formal_name_and_short_name_remain_distinct(self) -> None:
        context = self.service.confirm_taxable_included(
            "company-1", confirmed=True
        )
        identity = next(
            item for item in context.account_master if item.mapping_value == "架空預金"
        )
        self.assertEqual(identity.target_formal_name, "架空預金")
        self.assertTrue(identity.target_name)
        self.assertLessEqual(len(identity.target_name), 4)

    def test_contradictory_taxation_specific_fields_are_blocked(self) -> None:
        with self.assertRaises(CompanyTaxContextConfirmationError):
            self.service.confirm(
                "company-1",
                selection=JdlTaxContextSelection(
                    tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED,
                    taxation_method=JdlTaxationMethod.SIMPLIFIED,
                    input_tax_credit_method=JdlInputTaxCreditMethod.INDIVIDUAL,
                    simplified_business_category=JdlSimplifiedBusinessCategory.FIRST,
                ),
                confirmed=True,
            )
        with self.assertRaises(CompanyTaxContextConfirmationError):
            self.service.confirm(
                "company-1",
                selection=JdlTaxContextSelection(
                    tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED,
                    taxation_method=JdlTaxationMethod.STANDARD,
                    input_tax_credit_method=JdlInputTaxCreditMethod.INDIVIDUAL,
                    simplified_business_category=JdlSimplifiedBusinessCategory.FIRST,
                ),
                confirmed=True,
            )

    def test_controller_exposes_six_candidates_then_saves_user_confirmed(self) -> None:
        self.service.confirm_taxable_included("company-1", confirmed=True)
        controller = AccountingConverterController(
            profile_store=self.profiles,
            company_store=self.companies,
            preferences_store=ApplicationPreferencesStore(
                self.root / "preferences.json"
            ),
        )
        controller.load_profiles()
        controller.load_company_settings()
        review = controller.company_tax_mapping_review("company-1")
        self.assertEqual(
            {item.source_value for item in review.items}, set(self.TAXES)
        )
        state = controller.confirm_company_tax_mappings(
            "company-1", self.TAXES
        )
        self.assertEqual(state.user_message, "税区分の確認を保存しました。")
        setting = self.companies.get("company-1")
        profile = self.profiles.get(setting.conversion_profile_id)
        self.assertTrue(
            all(
                item.status is MappingStatus.USER_CONFIRMED
                for item in profile.tax_mappings.values()
            )
        )

    def test_controller_logs_tax_context_persistence_failure(self) -> None:
        controller = AccountingConverterController(
            profile_store=self.profiles,
            company_store=self.companies,
            preferences_store=ApplicationPreferencesStore(
                self.root / "preferences.json"
            ),
        )
        failure = CompanyTaxContextConfirmationError("synthetic failure")
        with (
            patch.object(
                controller.company_tax_context_confirmation_service,
                "confirm",
                side_effect=failure,
            ),
            patch(
                "accounting_converter.ui.controllers.log_local_exception"
            ) as logger,
        ):
            state = controller.confirm_company_tax_context(
                "company-1", explicitly_confirmed=True
            )
        logger.assert_called_once_with(
            "company_tax_context_confirmation", failure
        )
        self.assertEqual(
            state.user_message,
            "JDL税設定を保存できませんでした。科目対応を確認してください。",
        )
        self.assertEqual(
            state.developer_error, "CompanyTaxContextConfirmationError"
        )


if __name__ == "__main__":
    unittest.main()
