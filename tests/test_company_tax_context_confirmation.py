from __future__ import annotations

import hashlib
from dataclasses import replace
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path

from accounting_converter.application.company_tax_context_confirmation import (
    CompanyTaxContextConfirmationError,
    CompanyTaxContextConfirmationService,
    JdlTaxContextSelection,
    PendingTaxContextConfirmation,
)
from accounting_converter.application.company_master_refresh import (
    CompanyMasterRefreshService,
)
from accounting_converter.application.company_voucher_row_limit import CompanyVoucherRowLimitService
from accounting_converter.adapters.output.jdl import (
    JdlInputTaxCreditMethod,
    JdlTaxRounding,
    JdlSimplifiedBusinessCategory,
    JdlTaxationMethod,
)
from accounting_converter.adapters.output.jdl.context import JdlTargetContextBuildResult
from accounting_converter.domain.validation import Severity, ValidationResult
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
from accounting_converter.ui.view_models import TaxContextSaveStatus


class _PrintedMaster:
    def extract_pages(self, _path):
        return (
            "科 目 一 覧\n1\n"
            "勘定科目 略名称 使用 課区 税区 入力 固変 比率 説明\n"
            "  1001- 架空現金  借A ○\n"
            "  2001- 架空預金  借B ○\n"
            "  -0001 架空補助  借\n",
        )


class _OverlongSubaccountMaster(_PrintedMaster):
    def extract_pages(self, path):
        return tuple(
            page.replace("架空補助", "あ" * 12)
            for page in super().extract_pages(path)
        )


class _AddedMaster(_PrintedMaster):
    def extract_pages(self, path):
        return tuple(
            page + "  3001- 架空追加科目  借C ○\n"
            for page in super().extract_pages(path)
        )


class _DuplicatedNameMaster(_PrintedMaster):
    """Two enabled accounts share a name (as in a real company's master): excluded from targets."""

    def extract_pages(self, path):
        return tuple(
            page + "  5001  重複名  貸D ○\n  5002  重複名  貸E ○\n"
            for page in super().extract_pages(path)
        )


class _DuplicatedNameAddedMaster(_DuplicatedNameMaster):
    def extract_pages(self, path):
        return tuple(
            page + "  3001- 架空追加科目  借C ○\n"
            for page in super().extract_pages(path)
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

    def test_additive_master_refresh_keeps_confirmed_tax_limit_and_mappings(self) -> None:
        self.service.confirm_taxable_included("company-1", confirmed=True)
        CompanyVoucherRowLimitService(self.companies, self.profiles).set(
            "company-1", 16, confirmed=True
        )
        source = self.root / "added.pdf"
        source.write_bytes(b"synthetic added")
        draft = self.root / "added.json"
        JdlAccountPdfDraftStore(_AddedMaster()).import_pdf(source, draft)
        refresh = CompanyMasterRefreshService(self.companies, self.profiles)
        plan = refresh.plan("company-1", draft)
        self.assertTrue(plan.confirmed_context_preservable)
        self.assertEqual(plan.reconfirmation_count, 0)
        refresh.apply(plan, {}, set(), preserve_confirmed_context=True)
        reopened = CompanySettingStore(self.root / "companies", self.profiles)
        setting = reopened.get("company-1")
        context = JdlTargetContextLoader().load(reopened.context_path(setting))
        self.assertEqual(context.voucher_row_limit, 16)
        self.assertEqual(context.confirmation_state.value, "CONFIRMED")
        self.assertEqual(len(context.account_master), 3)
        profile = self.profiles.get(setting.conversion_profile_id)
        self.assertTrue(all(m.status is MappingStatus.USER_CONFIRMED for m in profile.account_mappings.values()))
        self.assertTrue(all(m.status is MappingStatus.USER_CONFIRMED for m in profile.subaccount_context_mappings.values()))

    def test_refresh_keeps_confirmed_settings_when_the_master_has_the_same_duplicated_names(self) -> None:
        source = self.root / "dup.pdf"
        source.write_bytes(b"synthetic duplicated")
        dup_draft = self.root / "dup.json"
        JdlAccountPdfDraftStore(_DuplicatedNameMaster()).import_pdf(source, dup_draft)
        dup_hash = hashlib.sha256(dup_draft.read_bytes()).hexdigest()
        base = self.profiles.get("profile-1")
        restamp = lambda mappings: {  # noqa: E731
            key: replace(value, metadata={**value.metadata, "setup_context_sha256": dup_hash})
            for key, value in mappings.items()
        }
        self.profiles.create(replace(
            base, profile_id="profile-2", account_mappings=restamp(base.account_mappings),
            subaccount_context_mappings=restamp(base.subaccount_context_mappings)))
        self.companies.create(company_setting_id="company-2", display_name="架空会社2",
                              conversion_profile_id="profile-2", context_source=dup_draft)
        self.service.confirm_taxable_included("company-2", confirmed=True)
        CompanyVoucherRowLimitService(self.companies, self.profiles).set("company-2", 16, confirmed=True)
        added_source = self.root / "dup-added.pdf"
        added_source.write_bytes(b"synthetic duplicated added")
        added = self.root / "dup-added.json"
        JdlAccountPdfDraftStore(_DuplicatedNameAddedMaster()).import_pdf(added_source, added)
        refresh = CompanyMasterRefreshService(self.companies, self.profiles)
        plan = refresh.plan("company-2", added)
        # The same name conflict the confirmation accepted must not block keeping that confirmation.
        self.assertTrue(plan.confirmed_context_preservable)
        refresh.apply(plan, {}, set(), preserve_confirmed_context=True)
        reopened = CompanySettingStore(self.root / "companies", self.profiles)
        context = JdlTargetContextLoader().load(reopened.context_path(reopened.get("company-2")))
        self.assertEqual(context.voucher_row_limit, 16)
        self.assertEqual(context.confirmation_state.value, "CONFIRMED")
        codes = {item.target_master_code for item in context.account_master}
        self.assertIn("3001", codes)
        self.assertFalse({"5001", "5002"} & codes)  # duplicated names stay unselectable

    def test_refresh_failure_preserves_previous_confirmed_setting(self) -> None:
        self.service.confirm_taxable_included("company-1", confirmed=True)
        source = self.root / "added.pdf"
        source.write_bytes(b"synthetic added")
        draft = self.root / "added.json"
        JdlAccountPdfDraftStore(_AddedMaster()).import_pdf(source, draft)
        refresh = CompanyMasterRefreshService(self.companies, self.profiles)
        plan = refresh.plan("company-1", draft)
        setting = self.companies.get("company-1")
        before = self.companies.context_path(setting).read_bytes()
        before_profile = setting.conversion_profile_id
        with patch("accounting_converter.infrastructure.company_setting_store.os.replace", side_effect=OSError("synthetic failure")):
            with self.assertRaises(OSError):
                refresh.apply(plan, {}, set(), preserve_confirmed_context=True)
        after = self.companies.get("company-1")
        self.assertEqual(after.conversion_profile_id, before_profile)
        self.assertEqual(self.companies.context_path(after).read_bytes(), before)

    def test_refresh_second_publish_failure_rolls_back_context(self) -> None:
        self.service.confirm_taxable_included("company-1", confirmed=True)
        source = self.root / "added.pdf"
        source.write_bytes(b"synthetic added")
        draft = self.root / "added.json"
        JdlAccountPdfDraftStore(_AddedMaster()).import_pdf(source, draft)
        refresh = CompanyMasterRefreshService(self.companies, self.profiles)
        plan = refresh.plan("company-1", draft)
        setting = self.companies.get("company-1")
        before = self.companies.context_path(setting).read_bytes()
        real_replace = os.replace
        calls = 0

        def fail_second(src, dst):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic second publish failure")
            return real_replace(src, dst)

        with patch("accounting_converter.infrastructure.company_setting_store.os.replace", side_effect=fail_second):
            with self.assertRaises(OSError):
                refresh.apply(plan, {}, set(), preserve_confirmed_context=True)
        after = self.companies.get("company-1")
        self.assertEqual(after.conversion_profile_id, setting.conversion_profile_id)
        self.assertEqual(self.companies.context_path(after).read_bytes(), before)

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

    def test_tax_excluded_standard_proportional_context_persists(self) -> None:
        context = self.service.confirm(
            "company-1",
            selection=JdlTaxContextSelection(
                tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED,
                taxation_method=JdlTaxationMethod.STANDARD,
                input_tax_credit_method=JdlInputTaxCreditMethod.PROPORTIONAL,
            ),
            confirmed=True,
        )
        reopened = JdlTargetContextLoader().load(
            self.companies.context_path(self.companies.get("company-1"))
        )

        self.assertEqual(reopened, context)
        self.assertIs(
            reopened.tax_processing_mode,
            JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED,
        )
        self.assertIs(
            reopened.effective_input_tax_credit_method,
            JdlInputTaxCreditMethod.PROPORTIONAL,
        )
        self.assertTrue(reopened.standard_taxation_confirmed)
        self.assertFalse(reopened.individual_credit_method_confirmed)
        self.assertIsNone(reopened.simplified_business_category)

    def test_legacy_context_without_explicit_enums_loads_as_individual(self) -> None:
        context = self.service.confirm_taxable_included(
            "company-1", confirmed=True
        )
        path = self.companies.context_path(self.companies.get("company-1"))
        payload = json.loads(JdlTargetContextLoader().to_json_text(context))
        payload["schema_version"] = "1"
        payload.pop("taxation_method")
        payload.pop("input_tax_credit_method")
        payload.pop("simplified_business_category")
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        reopened = JdlTargetContextLoader().load(path)
        self.assertIs(
            reopened.effective_taxation_method, JdlTaxationMethod.STANDARD
        )
        self.assertIs(
            reopened.effective_input_tax_credit_method,
            JdlInputTaxCreditMethod.INDIVIDUAL,
        )

    def test_same_canonical_master_refresh_preserves_confirmed_tax_context(self) -> None:
        confirmed = self.service.confirm(
            "company-1",
            selection=JdlTaxContextSelection(
                tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED,
                taxation_method=JdlTaxationMethod.STANDARD,
                input_tax_credit_method=JdlInputTaxCreditMethod.PROPORTIONAL,
            ),
            confirmed=True,
        )
        before = self.companies.get("company-1")
        plan = CompanyMasterRefreshService(
            self.companies, self.profiles
        ).plan("company-1", self.draft)
        self.assertTrue(plan.master_identity_unchanged)

        count = CompanyMasterRefreshService(
            self.companies, self.profiles
        ).apply(plan, {}, set())
        after = self.companies.get("company-1")
        reopened = JdlTargetContextLoader().load(
            self.companies.context_path(after)
        )
        self.assertEqual(count, 0)
        self.assertEqual(after.conversion_profile_id, before.conversion_profile_id)
        self.assertEqual(after.context_fingerprint, before.context_fingerprint)
        self.assertEqual(reopened, confirmed)

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
            "JDL税設定を保存できませんでした。設定内容を確認してください。",
        )
        self.assertEqual(state.tax_context_save_status, TaxContextSaveStatus.NOT_SAVED)
        self.assertEqual(
            state.developer_error, "CompanyTaxContextConfirmationError"
        )

    def test_master_promotion_failure_reports_validation_rule_without_saving(self) -> None:
        result = JdlTargetContextBuildResult(
            context=None,
            validation_results=(ValidationResult(
                severity=Severity.ERROR,
                rule_id="JDL-CONTEXT-SUBACCOUNT-PARENT",
                message="invalid synthetic subaccount",
            ),),
        )
        with patch(
            "accounting_converter.application.company_tax_context_confirmation."
            "JdlTargetContextBuilder.build",
            return_value=result,
        ):
            with self.assertRaisesRegex(
                CompanyTaxContextConfirmationError,
                "JDL-CONTEXT-SUBACCOUNT-PARENT",
            ):
                self.service.confirm_taxable_included("company-1", confirmed=True)
        self.assertEqual(self.companies.get("company-1").conversion_profile_id, "profile-1")

    def test_overlong_subaccount_is_recorded_unusable_without_blocking_the_company(self) -> None:
        source = self.root / "overlong.pdf"
        source.write_bytes(b"synthetic-overlong")
        draft = self.root / "overlong.json"
        JdlAccountPdfDraftStore(_OverlongSubaccountMaster()).import_pdf(source, draft)
        profile = ConversionProfile(
            profile_id="profile-overlong",
            profile_name="overlong master",
            source_format_identity=moneyforward_cloud_journal_export_observed_schema().identity,
            target_format_identity=jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.profiles.create(profile)
        self.companies.create(
            company_setting_id="company-overlong",
            display_name="overlong master",
            conversion_profile_id=profile.profile_id,
            context_source=draft,
        )
        result = self.service.confirm(
            "company-overlong",
            selection=JdlTaxContextSelection(
                tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED,
                taxation_method=JdlTaxationMethod.STANDARD,
                input_tax_credit_method=JdlInputTaxCreditMethod.PROPORTIONAL,
            ),
            confirmed=True,
        )
        # The long name is kept as an unusable subaccount; nothing else is held back.
        self.assertNotIsInstance(result, PendingTaxContextConfirmation)
        context = self.service.current_context("company-overlong")
        self.assertIsNotNone(context)
        self.assertTrue(self.companies.resolve("company-overlong").available)
        self.assertEqual(context.subaccounts, ())
        self.assertEqual(
            [(item.parent_account_code, item.code, item.reason) for item in context.unusable_subaccounts],
            [("2001", "0001", "NAME_EXCEEDS_JDL_IMPORT_FIELD")],
        )
        # JDL still requires a subaccount on that parent.
        self.assertTrue(context.parent_has_subaccounts(code="2001"))
        self.assertFalse(context.parent_has_subaccounts(code="1001"))
        # The same master read again is not a master change.
        from accounting_converter.application.jdl_master_identity import (
            observed_master_identity_sha256,
            target_context_master_identity_sha256,
        )

        self.assertEqual(
            target_context_master_identity_sha256(context),
            observed_master_identity_sha256(JdlAccountPdfDraftStore().load(draft).observation),
        )
        # Saved and loaded unchanged; contexts without unusable subaccounts keep their bytes.
        reloaded = self.service.contexts.load(self.companies.context_path(self.companies.get("company-overlong")))
        self.assertEqual(reloaded.unusable_subaccounts, context.unusable_subaccounts)
        from dataclasses import replace as _replace

        self.assertNotIn("unusable_subaccounts", self.service.contexts.to_json_text(
            _replace(context, unusable_subaccounts=())))

    # ---- 2026-11-07: tax setting could not be saved after a PDF update (Windows, Buddies) -------------

    SIX = dict(
        tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED,
        taxation_method=JdlTaxationMethod.STANDARD,
        input_tax_credit_method=JdlInputTaxCreditMethod.PROPORTIONAL,
    )

    def _overlong_company(self, company_id: str, *, approve_unusable: bool, extra_tax=None):
        """A draft master whose only subaccount name is too long for the import field (becomes unusable),
        and a profile that already approved that subaccount (as the old review allowed on a draft)."""
        source = self.root / f"{company_id}.pdf"
        source.write_bytes(company_id.encode())
        draft = self.root / f"{company_id}.json"
        JdlAccountPdfDraftStore(_OverlongSubaccountMaster()).import_pdf(source, draft)
        draft_hash = hashlib.sha256(draft.read_bytes()).hexdigest()
        base = self.profiles.get("profile-1")
        restamp = lambda mappings: {  # noqa: E731
            key: replace(value, metadata={**value.metadata, "setup_context_sha256": draft_hash})
            for key, value in mappings.items()
        }
        long_name = "あ" * 12
        subs = {}
        if approve_unusable:
            subs[MappingKey(MappingType.SUBACCOUNT, "入力補助", "入力預金")] = MappingValue(
                "入力補助", long_name, MappingStatus.USER_CONFIRMED, parent_account="入力預金",
                metadata={"target_code": "0001", "output_code": "0001", "output_name": long_name,
                          "setup_context_sha256": draft_hash})
        self.profiles.create(replace(
            base, profile_id=f"profile-{company_id}", account_mappings=restamp(base.account_mappings),
            subaccount_context_mappings=subs,
            tax_mappings=extra_tax if extra_tax is not None else base.tax_mappings))
        self.companies.create(company_setting_id=company_id, display_name=company_id,
                              conversion_profile_id=f"profile-{company_id}", context_source=draft)
        return draft

    def test_approval_of_an_unusable_subaccount_does_not_block_the_save_and_is_the_only_one_returned(self) -> None:
        self._overlong_company("company-unusable", approve_unusable=True)
        # The failure seen on Windows: this raised "confirmed JDL setting and mappings are incompatible".
        self.service.confirm("company-unusable", selection=JdlTaxContextSelection(**self.SIX), confirmed=True)
        self.assertEqual(self.service.last_reconfirmation_required, (("2001", "0001"),))
        setting = self.companies.get("company-unusable")
        profile = self.profiles.get(setting.conversion_profile_id)
        self.assertEqual(profile.subaccount_context_mappings, {})  # back to "not confirmed"
        # Parent accounts keep their approval.
        self.assertTrue(all(m.status is MappingStatus.USER_CONFIRMED for m in profile.account_mappings.values()))
        self.assertTrue(self.companies.resolve("company-unusable").available)

    def test_a_usable_subaccount_approval_is_never_returned(self) -> None:
        self.service.confirm_taxable_included("company-1", confirmed=True)
        self.assertEqual(self.service.last_reconfirmation_required, ())
        profile = self.profiles.get(self.companies.get("company-1").conversion_profile_id)
        self.assertEqual(len(profile.subaccount_context_mappings), 1)
        self.assertTrue(all(m.status is MappingStatus.USER_CONFIRMED
                            for m in profile.subaccount_context_mappings.values()))

    def test_review_on_a_draft_does_not_offer_a_subaccount_that_cannot_be_written(self) -> None:
        from accounting_converter.application.company_mapping_update import CompanyMappingUpdateService

        draft = self._overlong_company("company-offer", approve_unusable=False)
        service = CompanyMappingUpdateService.__new__(CompanyMappingUpdateService)
        service.drafts = JdlAccountPdfDraftStore()
        service.contexts = JdlTargetContextLoader()
        offered = service._master_observation(draft).subaccounts
        self.assertEqual(offered, ())
        # A normal-length one is still offered.
        normal = service._master_observation(self.draft).subaccounts
        self.assertEqual([(s.parent_account_code, s.code) for s in normal], [("2001", "0001")])

    def test_parent_only_is_not_valid_for_a_parent_whose_only_subaccount_is_unusable(self) -> None:
        from accounting_converter.adapters.output.jdl import JdlOutputRuntimeFactory, jdl_ibex_35_5_output_profile
        from accounting_converter.domain.mapping import SubaccountPolicy

        self._overlong_company("company-po", approve_unusable=False)
        self.service.confirm("company-po", selection=JdlTaxContextSelection(**self.SIX), confirmed=True)
        context = self.service.current_context("company-po")
        profile = self.profiles.get(self.companies.get("company-po").conversion_profile_id)
        parent_only = MappingValue(
            "入力補助", "", MappingStatus.USER_CONFIRMED, parent_account="入力預金",
            metadata={"subaccount_policy": SubaccountPolicy.PARENT_ONLY_CONFIRMED.value})
        bad = replace(profile, subaccount_context_mappings={
            MappingKey(MappingType.SUBACCOUNT, "入力補助", "入力預金"): parent_only})
        resolution = JdlOutputRuntimeFactory().resolve(jdl_ibex_35_5_output_profile(), bad, context)
        self.assertFalse(resolution.resolved)
        self.assertIn("JDL-CONTEXT-SUBACCOUNT-MAPPING-MISMATCH", {r.rule_id for r in resolution.validation_results})

    def test_failed_save_keeps_the_six_entered_items_and_says_why(self) -> None:
        # An approval whose target does not exist in the master: a real incompatibility.
        draft = self._overlong_company("company-bad", approve_unusable=False)
        profile = self.profiles.get(self.companies.get("company-bad").conversion_profile_id)
        ghost = MappingValue("入力補助", "存在しない補助", MappingStatus.USER_CONFIRMED, parent_account="入力預金",
                             metadata={"target_code": "9999", "output_code": "9999", "output_name": "存在しない補助"})
        new = replace(profile, profile_id="profile-ghost", subaccount_context_mappings={
            MappingKey(MappingType.SUBACCOUNT, "入力補助", "入力預金"): ghost})
        self.profiles.create(new)
        # Rebind the company to the broken profile (same draft, so the fingerprint is recomputed by the store).
        self.companies.replace_profile("company-bad", "profile-ghost")
        controller = AccountingConverterController(
            profile_store=self.profiles, company_store=self.companies,
            preferences_store=ApplicationPreferencesStore(self.root / "prefs.json"))
        controller.load_profiles()
        controller.load_company_settings()
        selection = dict(
            tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED,
            taxation_method=JdlTaxationMethod.STANDARD,
            input_tax_credit_method=JdlInputTaxCreditMethod.PROPORTIONAL,
            sales_tax_rounding=JdlTaxRounding.CEILING, purchase_tax_rounding=JdlTaxRounding.HALF_UP)
        state = controller.confirm_company_tax_context("company-bad", explicitly_confirmed=True, **selection)
        self.assertIs(state.tax_context_save_status, TaxContextSaveStatus.NOT_SAVED)
        self.assertIn("科目・補助科目の対応", state.user_message)       # the real reason, not a generic one
        self.assertIn("入力した税設定は残してあります", state.user_message)
        # Reopening (new service instance = restart) restores what was typed; the company stays unconfirmed.
        reopened = CompanyTaxContextConfirmationService(
            CompanySettingStore(self.root / "companies", self.profiles), self.profiles)
        pending = reopened.pending_selection("company-bad")
        self.assertEqual(
            (pending.tax_processing_mode, pending.taxation_method, pending.input_tax_credit_method,
             pending.sales_tax_rounding, pending.purchase_tax_rounding),
            (JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED, JdlTaxationMethod.STANDARD,
             JdlInputTaxCreditMethod.PROPORTIONAL, JdlTaxRounding.CEILING, JdlTaxRounding.HALF_UP))
        self.assertTrue(reopened.is_pending("company-bad"))
        self.assertIsNone(reopened.current_context("company-bad"))

    def test_error_text_carries_the_rule_ids(self) -> None:
        self._overlong_company("company-rules", approve_unusable=False)
        profile = self.profiles.get(self.companies.get("company-rules").conversion_profile_id)
        ghost = MappingValue("入力補助", "存在しない補助", MappingStatus.USER_CONFIRMED, parent_account="入力預金",
                             metadata={"target_code": "9999", "output_code": "9999", "output_name": "存在しない補助"})
        self.profiles.create(replace(profile, profile_id="profile-rules", subaccount_context_mappings={
            MappingKey(MappingType.SUBACCOUNT, "入力補助", "入力預金"): ghost}))
        self.companies.replace_profile("company-rules", "profile-rules")
        with self.assertRaisesRegex(Exception, "JDL-CONTEXT-SUBACCOUNT-MAPPING-MISMATCH"):
            self.service.confirm("company-rules", selection=JdlTaxContextSelection(**self.SIX), confirmed=True)

    def test_tax_approvals_with_the_same_tax_settings_are_kept_and_others_are_reset(self) -> None:
        from accounting_converter.application.moneyforward_tax_excluded_evidence import tax_context_identity_sha256

        self.service.confirm("company-1", selection=JdlTaxContextSelection(**self.SIX), confirmed=True)
        identity = tax_context_identity_sha256(self.service.current_context("company-1"))
        profile = self.profiles.get(self.companies.get("company-1").conversion_profile_id)
        stamped = {
            "課税仕入 10%": MappingValue("課税仕入 10%", "10%", MappingStatus.USER_CONFIRMED,
                                         metadata={"jdl_tax_context_identity_sha256": identity}),
            "課税売上 10%": MappingValue("課税売上 10%", "10%", MappingStatus.USER_CONFIRMED,
                                         metadata={"jdl_tax_context_identity_sha256": "other-settings"}),
        }
        self.profiles.create(replace(profile, profile_id="profile-stamped", tax_mappings=stamped))
        self.companies.replace_profile("company-1", "profile-stamped")
        # Same settings again: the approval made under them stays; the one made under others is reset.
        self.service.confirm("company-1", selection=JdlTaxContextSelection(**self.SIX), confirmed=True)
        after = self.profiles.get(self.companies.get("company-1").conversion_profile_id).tax_mappings
        self.assertIs(after["課税仕入 10%"].status, MappingStatus.USER_CONFIRMED)
        self.assertIs(after["課税売上 10%"].status, MappingStatus.UNRESOLVED)
        # Different settings: nothing carries over.
        self.service.confirm("company-1", selection=JdlTaxContextSelection(
            tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED,
            taxation_method=JdlTaxationMethod.STANDARD,
            input_tax_credit_method=JdlInputTaxCreditMethod.INDIVIDUAL), confirmed=True)
        after = self.profiles.get(self.companies.get("company-1").conversion_profile_id).tax_mappings
        self.assertTrue(all(m.status is MappingStatus.UNRESOLVED for m in after.values()))

    def test_confirmed_values_survive_restart_and_a_same_master_refresh(self) -> None:
        self.service.confirm("company-1", selection=JdlTaxContextSelection(
            **self.SIX, sales_tax_rounding=JdlTaxRounding.CEILING, purchase_tax_rounding=JdlTaxRounding.HALF_UP),
            confirmed=True)
        reopened_store = CompanySettingStore(self.root / "companies", self.profiles)
        context = JdlTargetContextLoader().load(reopened_store.context_path(reopened_store.get("company-1")))
        self.assertEqual((context.tax_processing_mode, context.sales_tax_rounding, context.purchase_tax_rounding),
                         (JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED, JdlTaxRounding.CEILING, JdlTaxRounding.HALF_UP))
        refresh = CompanyMasterRefreshService(reopened_store, self.profiles)
        plan = refresh.plan("company-1", self.draft)
        self.assertTrue(plan.confirmed_context_preservable)
        refresh.apply(plan, {}, set(), preserve_confirmed_context=True)
        context = JdlTargetContextLoader().load(reopened_store.context_path(reopened_store.get("company-1")))
        self.assertEqual((context.confirmation_state.value, context.sales_tax_rounding),
                         ("CONFIRMED", JdlTaxRounding.CEILING))

    def test_post_save_refresh_failure_is_not_reported_as_persistence_failure(self) -> None:
        controller = AccountingConverterController(
            profile_store=self.profiles,
            company_store=self.companies,
            preferences_store=ApplicationPreferencesStore(
                self.root / "preferences.json"
            ),
        )
        failure = RuntimeError("synthetic refresh failure")
        with (
            patch.object(controller, "load_profiles", side_effect=failure),
            patch("accounting_converter.ui.controllers.log_local_exception") as logger,
        ):
            state = controller.confirm_company_tax_context(
                "company-1", explicitly_confirmed=True
            )
        logger.assert_called_once_with("company_tax_context_post_save_refresh", failure)
        self.assertEqual(
            state.tax_context_save_status, TaxContextSaveStatus.SAVED_REFRESH_WARNING
        )
        self.assertFalse(state.conversion_available)
        setting = self.companies.get("company-1")
        self.assertNotEqual(setting.conversion_profile_id, "profile-1")
        self.assertIsNotNone(
            controller.company_tax_context_confirmation_service.current_context("company-1")
        )


if __name__ == "__main__":
    unittest.main()
