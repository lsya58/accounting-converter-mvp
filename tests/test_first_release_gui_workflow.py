from __future__ import annotations

import csv
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from accounting_converter.adapters.output.jdl import (
    JdlAccountIdentity,
    JdlContextConfirmationState,
    JdlContextProvenance,
    JdlTargetContextBuilder,
)
from accounting_converter.application.first_release_workflow import (
    FirstReleaseConversionWorkflow,
    FirstReleaseReadiness,
)
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from accounting_converter.profiles.jdl_official import (
    JdlTaxProcessingMode,
)
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
    yayoi_ae19_direct_export_observed_schema,
)
from accounting_converter.profiles.yayoi_official import (
    yayoi_accounting_05_official_import_spec,
)
from accounting_converter.infrastructure.conversion_profile_store import (
    ConversionProfileStore,
)
from accounting_converter.infrastructure.jdl_target_context_loader import (
    JdlTargetContextLoadError,
)
from accounting_converter.ui.controllers import AccountingConverterController


class FirstReleaseGuiWorkflowTests(unittest.TestCase):
    def test_valid_profile_import_adds_selects_and_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_store = ConversionProfileStore(root / "source")
            target_store = ConversionProfileStore(root / "target")
            profile = self.profile()
            source_store.create(profile)
            source = root / "source" / f"{profile.profile_id}.json"
            before = source.read_bytes()
            controller = AccountingConverterController(profile_store=target_store)

            state = controller.import_profile(source)

            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(state.selected_profile_id, profile.profile_id)
            self.assertEqual(len(state.profiles), 1)
            self.assertEqual(target_store.get(profile.profile_id).profile_name, profile.profile_name)
            self.assertIn("追加しました", state.user_message)

    def test_malformed_profile_json_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "malformed.json"
            source.write_text("{malformed", encoding="utf-8")
            controller = AccountingConverterController(
                profile_store=ConversionProfileStore(root / "profiles")
            )

            state = controller.import_profile(source)

            self.assertEqual(state.profiles, ())
            self.assertFalse(state.conversion_available)
            self.assertIn("追加できませんでした", state.user_message)

    def test_profile_with_missing_required_schema_field_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = ConversionProfileStore(root / "profiles")
            payload = json.loads(store.to_json_text(self.profile()))
            del payload["profile_name"]
            source = root / "missing-field.json"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            controller = AccountingConverterController(profile_store=store)

            state = controller.import_profile(source)

            self.assertEqual(state.profiles, ())
            self.assertFalse(state.conversion_available)

    def test_unsupported_profile_schema_version_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = ConversionProfileStore(root / "profiles")
            payload = json.loads(store.to_json_text(self.profile()))
            payload["schema_version"] = "999"
            source = root / "unsupported-version.json"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            controller = AccountingConverterController(profile_store=store)

            state = controller.import_profile(source)

            self.assertEqual(state.profiles, ())
            self.assertFalse(state.conversion_available)

    def test_profile_outside_first_release_identity_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = ConversionProfileStore(root / "profiles")
            payload = json.loads(store.to_json_text(self.profile()))
            payload["source_format_identity"]["product"] = "Unsupported Product"
            source = root / "wrong-identity.json"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            controller = AccountingConverterController(profile_store=store)

            state = controller.import_profile(source)

            self.assertEqual(state.profiles, ())
            self.assertFalse(state.conversion_available)
            self.assertIn("追加できませんでした", state.user_message)

    def test_unresolved_mapping_profile_import_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = ConversionProfileStore(root / "profiles")
            payload = json.loads(store.to_json_text(self.profile()))
            for mapping in payload["account_mappings"]:
                mapping["status"] = MappingStatus.UNRESOLVED.value
                mapping["target_value"] = None
            source = root / "unresolved.json"
            source.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            controller = AccountingConverterController(profile_store=store)

            state = controller.import_profile(source)

            self.assertEqual(state.profiles, ())
            self.assertFalse(state.conversion_available)

    def test_duplicate_profile_id_does_not_overwrite_existing_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = ConversionProfileStore(root / "profiles")
            profile = self.profile()
            store.create(profile)
            existing_path = root / "profiles" / f"{profile.profile_id}.json"
            before = existing_path.read_bytes()
            source = root / "duplicate.json"
            source.write_text(store.to_json_text(profile), encoding="utf-8")
            controller = AccountingConverterController(profile_store=store)
            controller.load_profiles()

            state = controller.import_profile(source)

            self.assertEqual(existing_path.read_bytes(), before)
            self.assertEqual(len(state.profiles), 1)
            self.assertIn("上書きしません", state.user_message)

    def test_duplicate_profile_name_with_new_id_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = ConversionProfileStore(root / "profiles")
            profile = self.profile()
            store.create(profile)
            duplicate_name = replace(profile, profile_id="another-profile-id")
            source = root / "duplicate-name.json"
            source.write_text(store.to_json_text(duplicate_name), encoding="utf-8")
            controller = AccountingConverterController(profile_store=store)
            controller.load_profiles()

            state = controller.import_profile(source)

            self.assertEqual(len(state.profiles), 1)
            self.assertFalse((root / "profiles" / "another-profile-id.json").exists())
            self.assertIn("上書きしません", state.user_message)

    def test_invalid_context_selection_updates_display_and_disables_execution(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            class RejectingContextLoader:
                def load(self, path):
                    _ = path
                    raise JdlTargetContextLoadError("unsupported version")

            class MustNotExecuteWorkflow:
                def execute(self, prepared):
                    _ = prepared
                    raise AssertionError("blocked context must not execute conversion")

            controller = AccountingConverterController(
                profile_store=ConversionProfileStore(root / "profiles"),
                context_loader=RejectingContextLoader(),
                conversion_workflow=MustNotExecuteWorkflow(),
            )
            invalid = root / "jdl_context_bad_version.json"

            state = controller.select_context_file(invalid)

            self.assertEqual(state.selected_context_file, invalid)
            self.assertFalse(state.conversion_available)
            self.assertIsNone(state.conversion_summary)
            self.assertIn("確認できませんでした", state.user_message)

            stopped = controller.execute_conversion(confirmed=True)

            self.assertFalse(stopped.conversion_available)
            self.assertIn("実行前チェック", stopped.user_message)

    def test_controller_success_exposes_privacy_safe_result_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = ConversionProfileStore(root / "profiles")
            profile = self.profile()
            store.create(profile)
            context = self.context()

            class ContextLoader:
                def load(self, path):
                    _ = path
                    return context

            controller = AccountingConverterController(
                profile_store=store,
                context_loader=ContextLoader(),
            )
            controller.load_profiles()
            controller.select_profile(profile.profile_id)
            controller.select_file(self.write_source(root / "input.txt"))
            controller.select_context_file(root / "confirmed-context.json")
            controller.select_output_file(root / "output.csv")

            ready = controller.prepare_conversion()
            completed = controller.execute_conversion(confirmed=True)

            self.assertTrue(ready.conversion_available)
            self.assertIn("結果: SUCCESS", completed.result_summary)
            self.assertIn("出力検証: 成功", completed.result_summary)
            self.assertIn("Output Validation結果: success", completed.verification_report)
            self.assertNotIn("完全架空GUI試験", completed.verification_report)

    def test_valid_selection_enables_formal_conversion_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = self.write_source(root / "input.txt")
            output = root / "output.csv"
            prepared = self.workflow().prepare(
                input_path=source,
                output_path=output,
                profile=self.profile(),
                context=self.context(),
            )

            result = self.workflow().execute(prepared)

            self.assertEqual(prepared.summary.readiness, FirstReleaseReadiness.READY)
            self.assertEqual(prepared.summary.required_mapping_count, 2)
            self.assertEqual(prepared.summary.confirmed_mapping_count, 2)
            self.assertEqual(result.status, "SUCCESS")
            self.assertTrue(output.exists())
            self.assertEqual(result.input_journal_count, 1)
            self.assertEqual(result.output_record_count, 1)
            self.assertIn("Output Validation結果: success", result.verification_report)

    def test_missing_profile_blocks(self) -> None:
        prepared = self.prepare(profile=None)
        self.assert_blocked(prepared, "変換設定")

    def test_missing_context_blocks(self) -> None:
        prepared = self.prepare(context=None)
        self.assert_blocked(prepared, "JDL設定")

    def test_unresolved_mapping_blocks_without_output(self) -> None:
        prepared = self.prepare(profile=self.profile(confirmed=False))
        self.assert_blocked(prepared, "未確認の科目対応")
        self.assertFalse(prepared.summary.output_path.exists())

    def test_wrong_jdl_version_blocks(self) -> None:
        prepared = self.prepare(context=replace(self.context(), version="36.0"))
        self.assert_blocked(prepared, "35.5")

    def test_taxable_context_blocks(self) -> None:
        prepared = self.prepare(
            context=self.context(JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED)
        )
        self.assert_blocked(prepared, "免税")

    def test_existing_output_blocks_and_preserves_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = self.write_source(root / "input.txt")
            output = root / "output.csv"
            output.write_bytes(b"existing")
            prepared = self.workflow().prepare(
                input_path=source,
                output_path=output,
                profile=self.profile(),
                context=self.context(),
            )

            self.assert_blocked(prepared, "既に存在")
            self.assertEqual(output.read_bytes(), b"existing")

    def test_source_output_collision_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = self.write_source(Path(tmpdir) / "input.txt")
            prepared = self.workflow().prepare(
                input_path=source,
                output_path=source,
                profile=self.profile(),
                context=self.context(),
            )
            self.assert_blocked(prepared, "同じパス")

    def prepare(self, *, profile="default", context="default"):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        return self.workflow().prepare(
            input_path=self.write_source(root / "input.txt"),
            output_path=root / "output.csv",
            profile=self.profile() if profile == "default" else profile,
            context=self.context() if context == "default" else context,
        )

    def assert_blocked(self, prepared, text: str) -> None:
        self.assertEqual(prepared.summary.readiness, FirstReleaseReadiness.BLOCKED)
        self.assertIsNone(prepared.request)
        self.assertTrue(any(text in reason for reason in prepared.summary.blocking_reasons))

    @staticmethod
    def workflow() -> FirstReleaseConversionWorkflow:
        return FirstReleaseConversionWorkflow()

    def profile(self, confirmed: bool = True) -> ConversionProfile:
        now = datetime(2026, 10, 5, tzinfo=timezone.utc)
        mappings = {
            name: MappingValue(
                source_value=name,
                target_value=name,
                status=(
                    MappingStatus.USER_CONFIRMED
                    if confirmed
                    else MappingStatus.UNRESOLVED
                ),
                metadata={"target_code": code, "target_formal_name": name},
            )
            for name, code in (("現金", "1001"), ("普通預金", "1002"))
        }
        return ConversionProfile(
            profile_id="first-release-test",
            profile_name="架空 First Release 設定",
            source_format_identity=yayoi_ae19_direct_export_observed_schema().identity,
            target_format_identity=(
                jdl_ibex_cashbook_official_journal_import_schema_definition().identity
            ),
            account_mappings=mappings,
            created_at=now,
            updated_at=now,
        )

    def context(
        self,
        tax_mode: JdlTaxProcessingMode = JdlTaxProcessingMode.EXEMPT,
    ):
        result = JdlTargetContextBuilder().build(
            target_format_identity=(
                jdl_ibex_cashbook_official_journal_import_schema_definition().identity
            ),
            product="JDL IBEX 出納帳",
            version="35.5",
            account_master=(
                JdlAccountIdentity("現金", "1001", "現金", "現金"),
                JdlAccountIdentity("普通預金", "1002", "普通預金", "普通預金"),
            ),
            subaccounts=(),
            departments=(),
            tax_processing_mode=tax_mode,
            department_processing_enabled=False,
            standard_taxation_confirmed=(tax_mode is not JdlTaxProcessingMode.EXEMPT),
            individual_credit_method_confirmed=(tax_mode is not JdlTaxProcessingMode.EXEMPT),
            confirmation_state=JdlContextConfirmationState.CONFIRMED,
            provenance=JdlContextProvenance.USER_CONFIRMED_RUNTIME_SNAPSHOT,
            no_fuzzy_matching=True,
            no_automatic_replacement=True,
        )
        self.assertTrue(result.success)
        return result.context

    @staticmethod
    def write_source(path: Path) -> Path:
        spec = yayoi_accounting_05_official_import_spec()
        values = {column.name: "" for column in spec.columns}
        values.update(
            {
                "識別フラグ": "2111",
                "伝票No.": "101",
                "取引日付": "R.08/10/05",
                "借方勘定科目": "現金",
                "借方金額": "1000",
                "貸方勘定科目": "普通預金",
                "貸方金額": "1000",
                "摘要": "完全架空GUI試験",
            }
        )
        with path.open("w", encoding="cp932", newline="") as handle:
            csv.writer(handle, lineterminator="\r\n").writerow(
                tuple(values[column.name] for column in spec.columns)
            )
        return path


if __name__ == "__main__":
    unittest.main()
