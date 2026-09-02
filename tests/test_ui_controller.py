from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from accounting_converter.application.profile_preflight import (
    ObservedMappingRequirements,
    ProfilePreflightStatus,
)
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from accounting_converter.infrastructure.conversion_profile_store import (
    ConversionProfileStore,
    default_profile_store_dir,
)
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_35_5_observed_schema_definition,
    yayoi_desktop_import_25_documented_schema,
)
from accounting_converter.ui.controllers import AccountingConverterController
from accounting_converter.ui.view_models import DiagnosticKind, DiagnosticStatus


class ExplodingAnalyzer:
    def analyze_path(self, path: Path):
        _ = path
        raise RuntimeError("raw accounting text must not leak")


class UiControllerTests(unittest.TestCase):
    def test_profile_zero_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            controller = AccountingConverterController(
                profile_store=ConversionProfileStore(Path(tmpdir))
            )

            state = controller.load_profiles()

        self.assertEqual(state.profiles, ())
        self.assertIn("保存済み変換設定はありません", state.user_message)

    def test_profile_list_is_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ConversionProfileStore(Path(tmpdir))
            store.create(self.profile())
            controller = AccountingConverterController(profile_store=store)

            state = controller.load_profiles()

        self.assertEqual(len(state.profiles), 1)
        self.assertEqual(state.profiles[0].profile_id, "profile-001")

    def test_input_missing_blocks_preflight(self) -> None:
        controller = AccountingConverterController()

        state = controller.run_preflight()

        self.assertEqual(state.preflight_status, ProfilePreflightStatus.UNKNOWN.value)
        self.assertFalse(state.conversion_available)
        self.assertIn("入力ファイルを選択", state.user_message)

    def test_yayoi_diagnostics_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            controller = AccountingConverterController(
                profile_store=ConversionProfileStore(Path(tmpdir))
            )
            path = Path("tests/fixtures/yayoi/official_import_demo.csv")

            controller.select_file(path)
            state = controller.diagnose_selected(DiagnosticKind.YAYOI)

        self.assertEqual(state.diagnostic_status, DiagnosticStatus.SUCCESS)
        self.assertEqual(state.diagnostic_summary.kind, DiagnosticKind.YAYOI)
        self.assertGreater(state.diagnostic_summary.data_record_count, 0)
        self.assertNotIn("架空", state.user_message)

    def test_jdl_diagnostics_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            controller = AccountingConverterController(
                profile_store=ConversionProfileStore(Path(tmpdir))
            )
            path = Path("tests/fixtures/jdl/valid_simple.csv")

            controller.select_file(path)
            state = controller.diagnose_selected(DiagnosticKind.JDL)

        self.assertEqual(state.diagnostic_status, DiagnosticStatus.SUCCESS)
        self.assertEqual(state.diagnostic_summary.kind, DiagnosticKind.JDL)
        self.assertGreaterEqual(state.diagnostic_summary.data_record_count, 1)

    def test_diagnostics_failure_is_reported_without_raw_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.csv"
            input_path.write_text("secret journal body", encoding="utf-8")
            original = input_path.read_text(encoding="utf-8")
            controller = AccountingConverterController(
                profile_store=ConversionProfileStore(Path(tmpdir) / "profiles"),
                yayoi_analyzer=ExplodingAnalyzer(),
            )

            controller.select_file(input_path)
            state = controller.diagnose_selected(DiagnosticKind.YAYOI)

            self.assertEqual(state.diagnostic_status, DiagnosticStatus.FAILED)
            self.assertEqual(state.developer_error, "RuntimeError")
            self.assertNotIn("secret journal body", state.user_message)
            self.assertNotIn("raw accounting text", state.user_message)
            self.assertEqual(input_path.read_text(encoding="utf-8"), original)

    def test_ready_preflight_still_disables_conversion_without_formal_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ConversionProfileStore(Path(tmpdir) / "profiles")
            profile = self.profile()
            store.create(profile)
            controller = AccountingConverterController(profile_store=store)
            input_path = Path(tmpdir) / "input.csv"
            input_path.write_text("", encoding="utf-8")

            controller.load_profiles()
            controller.select_profile(profile.profile_id)
            controller.select_file(input_path)
            state = controller.run_preflight(
                ObservedMappingRequirements(accounts=frozenset({"現金"}))
            )

            self.assertEqual(state.preflight_status, ProfilePreflightStatus.READY.value)
            self.assertFalse(state.conversion_available)
            self.assertIn("正式変換Adapterは未登録", state.user_message)

    def test_requires_mapping_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ConversionProfileStore(Path(tmpdir) / "profiles")
            profile = self.profile()
            store.create(profile)
            controller = AccountingConverterController(profile_store=store)
            input_path = Path(tmpdir) / "input.csv"
            input_path.write_text("", encoding="utf-8")

            controller.load_profiles()
            controller.select_profile(profile.profile_id)
            controller.select_file(input_path)
            state = controller.run_preflight(
                ObservedMappingRequirements(accounts=frozenset({"未登録科目"}))
            )

            self.assertEqual(
                state.preflight_status,
                ProfilePreflightStatus.REQUIRES_MAPPING.value,
            )
            self.assertFalse(state.conversion_available)

    def test_format_mismatch_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ConversionProfileStore(Path(tmpdir) / "profiles")
            profile = self.profile()
            store.create(profile)
            controller = AccountingConverterController(profile_store=store)
            input_path = Path(tmpdir) / "input.csv"
            input_path.write_text("", encoding="utf-8")

            controller.load_profiles()
            controller.select_profile(profile.profile_id)
            controller.select_file(input_path)
            controller.diagnose_selected(DiagnosticKind.JDL)
            state = controller.run_preflight()

            self.assertEqual(
                state.preflight_status,
                ProfilePreflightStatus.FORMAT_MISMATCH.value,
            )
            self.assertFalse(state.conversion_available)

    def test_default_profile_store_prefers_local_appdata(self) -> None:
        with patch.dict(
            "os.environ",
            {"LOCALAPPDATA": r"C:\Users\demo\AppData\Local", "APPDATA": r"C:\Users\demo\AppData\Roaming"},
        ):
            path = default_profile_store_dir()

        self.assertEqual(
            str(path),
            r"C:\Users\demo\AppData\Local/AccountingConverter/profiles",
        )

    def test_gui_entry_module_is_importable_without_starting_tk(self) -> None:
        import accounting_converter.ui.app as app

        self.assertTrue(hasattr(app, "main"))

    def profile(self) -> ConversionProfile:
        source = yayoi_desktop_import_25_documented_schema()
        target = jdl_ibex_cashbook_35_5_observed_schema_definition()
        return ConversionProfile(
            profile_id="profile-001",
            profile_name="GUI test profile",
            source_format_identity=source.identity,
            target_format_identity=target.identity,
            account_mappings={
                "現金": MappingValue("現金", "JDL現金", MappingStatus.USER_CONFIRMED),
            },
            created_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
            updated_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        )


if __name__ == "__main__":
    unittest.main()
