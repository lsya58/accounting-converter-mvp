from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from accounting_converter.application.company_settings import CompanySettingStatus
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from accounting_converter.infrastructure.application_preferences import (
    ApplicationPreferences,
    ApplicationPreferencesStore,
)
from accounting_converter.ui.controllers import AccountingConverterController
from accounting_converter.infrastructure.company_setting_store import (
    CompanySettingStore,
    CorruptCompanySettingError,
    DuplicateCompanySettingError,
)
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
    moneyforward_cloud_journal_export_observed_schema,
    yayoi_ae19_direct_export_observed_schema,
)


class CompanySettingStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.profile_store = ConversionProfileStore(self.root / "profiles")
        self.company_store = CompanySettingStore(self.root / "companies", self.profile_store)
        self.context_source = self.root / "source-context.json"
        self._write_context(self.context_source)
        self.profile_store.create(self._profile())

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_create_load_list_and_atomic_layout(self) -> None:
        setting = self._create()
        loaded = self.company_store.get(setting.company_setting_id)
        self.assertEqual(loaded, setting)
        self.assertEqual(self.company_store.list(), (setting,))
        directory = self.root / "companies" / setting.company_setting_id
        self.assertTrue((directory / "company.json").exists())
        self.assertTrue((directory / "jdl-context.json").exists())
        self.assertFalse(any(path.name.endswith(".tmp") for path in directory.iterdir()))

    def test_duplicate_id_is_blocked_without_replacing_files(self) -> None:
        setting = self._create()
        path = self.root / "companies" / setting.company_setting_id / "company.json"
        before = path.read_bytes()
        with self.assertRaises(DuplicateCompanySettingError):
            self._create()
        self.assertEqual(path.read_bytes(), before)

    def test_rename_changes_only_display_metadata(self) -> None:
        original = self._create()
        renamed = self.company_store.rename(original.company_setting_id, "新しい表示名")
        self.assertEqual(renamed.display_name, "新しい表示名")
        self.assertEqual(renamed.profile_fingerprint, original.profile_fingerprint)
        self.assertEqual(renamed.context_fingerprint, original.context_fingerprint)
        self.assertEqual(renamed.created_at, original.created_at)

    def test_delete_removes_only_company_copy(self) -> None:
        setting = self._create()
        original_context = self.context_source.read_bytes()
        self.company_store.delete(setting.company_setting_id)
        self.assertFalse((self.root / "companies" / setting.company_setting_id).exists())
        self.assertEqual(self.context_source.read_bytes(), original_context)
        self.assertIsNotNone(self.profile_store.get("profile-1"))

    def test_corrupt_json_is_explicit(self) -> None:
        setting = self._create()
        path = self.root / "companies" / setting.company_setting_id / "company.json"
        path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(CorruptCompanySettingError):
            self.company_store.get(setting.company_setting_id)

    def test_valid_profile_and_context_resolve(self) -> None:
        setting = self._create()
        resolved = self.company_store.resolve(setting.company_setting_id)
        self.assertTrue(resolved.available)
        self.assertIsNotNone(resolved.profile)
        self.assertIsNotNone(resolved.context)

    def test_missing_profile_or_context_is_stale(self) -> None:
        setting = self._create()
        self.profile_store.delete(setting.conversion_profile_id)
        self.assertEqual(self.company_store.resolve(setting.company_setting_id).status, CompanySettingStatus.STALE)

        self.profile_store.create(self._profile())
        self.company_store.context_path(setting).unlink()
        self.assertEqual(self.company_store.resolve(setting.company_setting_id).status, CompanySettingStatus.STALE)

    def test_changed_profile_or_context_fingerprint_is_stale(self) -> None:
        setting = self._create()
        profile = self.profile_store.get(setting.conversion_profile_id)
        self.profile_store.update(replace(profile, notes="changed", updated_at=datetime.now(timezone.utc)))
        resolved = self.company_store.resolve(setting.company_setting_id)
        self.assertEqual(resolved.status, CompanySettingStatus.STALE)
        self.assertIn("PROFILE_CHANGED", resolved.reason_codes)

        self.profile_store.update(profile)
        context_path = self.company_store.context_path(setting)
        context_path.write_bytes(context_path.read_bytes() + b"\n")
        resolved = self.company_store.resolve(setting.company_setting_id)
        self.assertEqual(resolved.status, CompanySettingStatus.STALE)
        self.assertIn("CONTEXT_CHANGED", resolved.reason_codes)

    def test_expected_format_identity_mismatch_is_incompatible(self) -> None:
        setting = self._create()
        path = self.root / "companies" / setting.company_setting_id / "company.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["expected_source_format_key"] = "different"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(self.company_store.resolve(setting.company_setting_id).status, CompanySettingStatus.INCOMPATIBLE)

    def test_context_master_mismatch_blocks_creation(self) -> None:
        profile = self.profile_store.get("profile-1")
        changed_mapping = MappingValue(
            "現金", "現金", MappingStatus.USER_CONFIRMED,
            metadata={"target_code": "9999", "target_formal_name": "現金"},
        )
        self.profile_store.update(replace(profile, account_mappings={"現金": changed_mapping}))
        with self.assertRaisesRegex(ValueError, "incompatible"):
            self._create()

    def test_application_service_rejects_wrong_exact_source(self) -> None:
        from accounting_converter.application.company_settings import CompanySettingService

        setting = self._create()
        result = CompanySettingService(self.company_store).resolve_for_source(
            setting.company_setting_id,
            moneyforward_cloud_journal_export_observed_schema().identity.stable_key,
        )
        self.assertEqual(result.status, CompanySettingStatus.INCOMPATIBLE)
        self.assertIn("SOURCE_FORMAT_MISMATCH", result.reason_codes)

    def test_controller_auto_selects_single_exact_setting(self) -> None:
        setting = self._create()
        preferences = ApplicationPreferencesStore(self.root / "preferences.json")
        controller = AccountingConverterController(
            profile_store=self.profile_store,
            company_store=self.company_store,
            preferences_store=preferences,
        )
        controller.load_profiles()
        controller.load_company_settings()
        state = controller.select_file(Path("tests/fixtures/yayoi/ae19_observed_single_synthetic.txt"))
        self.assertEqual(state.selected_company_setting_id, setting.company_setting_id)
        self.assertEqual(state.selected_profile_id, setting.conversion_profile_id)
        self.assertIsNotNone(state.selected_context_file)

    def test_multiple_settings_do_not_auto_select_without_preference(self) -> None:
        self._create()
        self.company_store.create(
            company_setting_id="company-2", display_name="別の架空設定",
            conversion_profile_id="profile-1", context_source=self.context_source,
        )
        controller = AccountingConverterController(
            profile_store=self.profile_store,
            company_store=self.company_store,
            preferences_store=ApplicationPreferencesStore(self.root / "preferences.json"),
        )
        controller.load_profiles()
        controller.load_company_settings()
        state = controller.select_file(Path("tests/fixtures/yayoi/ae19_observed_single_synthetic.txt"))
        self.assertIsNone(state.selected_company_setting_id)

    def test_controller_blocks_stale_setting(self) -> None:
        setting = self._create()
        profile = self.profile_store.get(setting.conversion_profile_id)
        self.profile_store.update(replace(profile, notes="changed", updated_at=datetime.now(timezone.utc)))
        controller = AccountingConverterController(
            profile_store=self.profile_store,
            company_store=self.company_store,
            preferences_store=ApplicationPreferencesStore(self.root / "preferences.json"),
        )
        controller.load_profiles()
        controller.load_company_settings()
        state = controller.select_company_setting(setting.company_setting_id)
        self.assertFalse(state.conversion_available)
        self.assertIsNone(state.selected_profile_id)
        self.assertIn("会社設定を確認", state.user_message)

    def _create(self):
        return self.company_store.create(
            company_setting_id="company-1",
            display_name="架空会社設定",
            conversion_profile_id="profile-1",
            context_source=self.context_source,
        )

    @staticmethod
    def _profile() -> ConversionProfile:
        now = datetime(2026, 10, 8, tzinfo=timezone.utc)
        return ConversionProfile(
            profile_id="profile-1",
            profile_name="架空対応設定",
            source_format_identity=yayoi_ae19_direct_export_observed_schema().identity,
            target_format_identity=jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
            account_mappings={
                "現金": MappingValue(
                    "現金", "現金", MappingStatus.USER_CONFIRMED,
                    metadata={"target_code": "1001", "target_formal_name": "現金"},
                )
            },
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _write_context(path: Path) -> None:
        payload = {
            "schema_version": "1", "product": "JDL IBEX 出納帳", "version": "35.5",
            "account_master": [{"mapping_value": "現金", "target_master_code": "1001", "target_name": "現金", "target_formal_name": "現金"}],
            "subaccounts": [], "departments": [], "tax_processing_mode": "EXEMPT",
            "department_processing_enabled": False, "standard_taxation_confirmed": False,
            "individual_credit_method_confirmed": False, "confirmation_state": "CONFIRMED",
            "provenance": "USER_CONFIRMED_RUNTIME_SNAPSHOT", "no_fuzzy_matching": True,
            "no_automatic_replacement": True,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class ApplicationPreferencesStoreTests(unittest.TestCase):
    def test_save_load_deleted_id_and_corrupt_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            store = ApplicationPreferencesStore(path)
            store.save(ApplicationPreferences("company-1"))
            self.assertEqual(store.load({"company-1"}).last_company_setting_id, "company-1")
            self.assertIsNone(store.load(set()).last_company_setting_id)
            path.write_text("broken", encoding="utf-8")
            self.assertEqual(store.load(), ApplicationPreferences())


if __name__ == "__main__":
    unittest.main()
