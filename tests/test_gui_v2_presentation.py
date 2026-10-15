from __future__ import annotations

import csv
import io
import tempfile
import unittest
from pathlib import Path

from accounting_converter.profiles.yayoi_official import yayoi_accounting_05_official_import_spec
from accounting_converter.ui.controllers import AccountingConverterController
from accounting_converter.ui.view_models import (
    AppState,
    ConversionResultPresentation,
    FileRecognition,
    RecognizedFormat,
    UserFacingStatus,
    present_main_screen,
    support_diagnostic_text,
)
from accounting_converter.adapters.input.moneyforward import MONEYFORWARD_OBSERVED_HEADER
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.ui.app import GUI_PALETTE, status_visual


class GuiV2PresentationTests(unittest.TestCase):
    def test_visual_tokens_cover_every_user_facing_status(self) -> None:
        self.assertEqual(GUI_PALETTE["surface"], "#FFFFFF")
        for status in UserFacingStatus:
            label, foreground, background = status_visual(status)
            self.assertTrue(label)
            self.assertRegex(foreground, r"^#[0-9A-F]{6}$")
            self.assertRegex(background, r"^#[0-9A-F]{6}$")
            self.assertNotEqual(foreground, background)

    def test_initial_state_is_plain_and_conversion_disabled(self) -> None:
        view = present_main_screen(AppState())

        self.assertEqual(view.status, UserFacingStatus.NEEDS_INPUT)
        self.assertFalse(view.conversion_enabled)
        self.assertIn("CSV", view.status_text)
        self._assert_no_internal_terms(view.status_text + view.guidance)

    def test_yayoi_file_is_recognized_with_count_and_period(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_yayoi(Path(directory) / "input.txt")
            controller = AccountingConverterController(
                profile_store=ConversionProfileStore(Path(directory) / "profiles")
            )
            state = controller.select_file(path)

        self.assertEqual(state.file_recognition.format, RecognizedFormat.YAYOI)
        self.assertEqual(state.file_recognition.journal_count, 1)
        self.assertEqual(state.file_recognition.period_start, "2026-10-19")
        self.assertIn("弥生会計", present_main_screen(state).recognition_text)

    def test_moneyforward_file_is_recognized_but_not_made_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_moneyforward(Path(directory) / "input.csv")
            controller = AccountingConverterController(
                profile_store=ConversionProfileStore(Path(directory) / "profiles")
            )
            state = controller.select_file(path)

        view = present_main_screen(state)
        self.assertEqual(state.file_recognition.format, RecognizedFormat.MONEYFORWARD)
        self.assertEqual(state.file_recognition.journal_count, 1)
        self.assertIn("Money Forward", view.recognition_text)
        self.assertFalse(view.conversion_enabled)

    def test_moneyforward_prepare_uses_exact_company_route_and_requires_company(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._write_moneyforward(root / "input.csv")
            controller = AccountingConverterController(
                profile_store=ConversionProfileStore(root / "profiles")
            )
            controller.select_file(path)
            controller.select_output_file(root / "output.csv")

            state = controller.prepare_conversion()

        self.assertFalse(state.conversion_available)
        self.assertIn("会社設定", state.user_message)
        self._assert_no_internal_terms(state.user_message)

    def test_unknown_csv_has_actionable_block_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unknown.csv"
            path.write_text("not,an,accounting,file\n", encoding="utf-8")
            controller = AccountingConverterController(
                profile_store=ConversionProfileStore(Path(directory) / "profiles")
            )
            state = controller.select_file(path)

        view = present_main_screen(state)
        self.assertEqual(view.status, UserFacingStatus.BLOCKED)
        self.assertIn("対応している仕訳形式ではありません", view.guidance)
        self.assertFalse(view.conversion_enabled)

    def test_ready_confirm_block_and_success_present_without_internal_codes(self) -> None:
        selected = Path("synthetic.csv")
        recognition = FileRecognition(RecognizedFormat.YAYOI, "弥生会計の仕訳データ", 2)
        states = (
            (
                AppState(selected_file=selected, file_recognition=recognition, conversion_available=True),
                UserFacingStatus.READY,
                True,
            ),
            (
                AppState(selected_file=selected, file_recognition=recognition, preflight_status="REQUIRES_MAPPING"),
                UserFacingStatus.CONFIRM,
                False,
            ),
            (
                AppState(selected_file=selected, file_recognition=recognition, preflight_status="VALIDATION_FAILED"),
                UserFacingStatus.BLOCKED,
                False,
            ),
            (
                AppState(
                    selected_file=selected,
                    file_recognition=recognition,
                    result_presentation=ConversionResultPresentation(
                        True, 2, 2, "1600", "1600", 0, True, Path("output.csv")
                    ),
                ),
                UserFacingStatus.SUCCESS,
                False,
            ),
            (
                AppState(
                    selected_file=selected,
                    file_recognition=recognition,
                    user_message="安全のため変換を停止しました。設定を確認してください。",
                    result_presentation=ConversionResultPresentation(
                        False, 2, 0, "1600", "1600", 1, False, None
                    ),
                ),
                UserFacingStatus.BLOCKED,
                False,
            ),
        )
        for state, expected, enabled in states:
            with self.subTest(expected=expected):
                view = present_main_screen(state)
                self.assertEqual(view.status, expected)
                self.assertEqual(view.conversion_enabled, enabled)
                self._assert_no_internal_terms(
                    view.status_text + view.guidance + view.recognition_text
                )

    def test_pending_mapping_counts_are_presented_as_confirmation(self) -> None:
        state = AppState(
            selected_file=Path("synthetic.csv"),
            selected_profile_id="profile",
            selected_context_file=Path("context.json"),
            file_recognition=FileRecognition(
                RecognizedFormat.MONEYFORWARD, "Money Forwardの仕訳帳CSV", 2
            ),
            preflight_status="REQUIRES_CONFIRMATION",
            pending_account_confirmations=3,
            pending_subaccount_confirmations=2,
            pending_tax_confirmations=1,
        )

        view = present_main_screen(state)

        self.assertEqual(view.status, UserFacingStatus.CONFIRM)
        self.assertTrue(view.settings_action_visible)
        self.assertIn("科目: 3件", view.guidance)
        self.assertIn("補助科目: 2件", view.guidance)
        self.assertIn("税区分: 1件", view.guidance)

    def test_unsupported_block_does_not_offer_confirmation_wizard(self) -> None:
        state = AppState(
            selected_file=Path("synthetic.csv"),
            selected_profile_id="profile",
            selected_context_file=Path("context.json"),
            preflight_status="BLOCKED",
            messages=("現在この仕訳の一部は安全に変換できません。",),
        )

        view = present_main_screen(state)

        self.assertEqual(view.status, UserFacingStatus.BLOCKED)
        self.assertFalse(view.settings_action_visible)

    def test_actionable_confirmation_guidance_is_presented(self) -> None:
        state = AppState(
            selected_file=Path("private/customer.csv"),
            selected_profile_id="profile",
            selected_context_file=Path("context.json"),
            file_recognition=FileRecognition(
                RecognizedFormat.MONEYFORWARD, "Money Forwardの仕訳帳CSV", 4
            ),
            preflight_status="REQUIRES_CONFIRMATION",
            pending_account_confirmations=1,
            pending_subaccount_confirmations=1,
            messages=(
                "JDL側に対応する科目が見つかりません。JDLで科目設定を確認し、必要なら科目を追加した後、「JDL科目一覧を更新」してください。",
                "この親科目に対応する補助科目がJDL側にありません。JDLの補助科目設定を確認してください。",
            ),
        )

        guidance = present_main_screen(state).guidance

        self.assertIn("JDL科目一覧を更新", guidance)
        self.assertIn("補助科目設定", guidance)

    def test_support_diagnostics_contains_counts_but_no_private_values(self) -> None:
        state = AppState(
            selected_file=Path("/private/顧客名/秘密.csv"),
            file_recognition=FileRecognition(
                RecognizedFormat.MONEYFORWARD, "Money Forwardの仕訳帳CSV", 482
            ),
            preflight_status="REQUIRES_CONFIRMATION",
            pending_account_confirmations=3,
            pending_subaccount_confirmations=2,
            pending_tax_confirmations=1,
            unsupported_shape_count=4,
            optional_field_blocker_count=5,
            jdl_environment_label="JDL IBEX 出納帳 35.5",
            jdl_master_configured=True,
            jdl_master_state="設定済み",
            jdl_master_updated_at="2026/10/15",
            messages=("架空の内部メッセージ",),
        )

        text = support_diagnostic_text(state, "0.1.0")

        for expected in (
            "アプリ: 0.1.0",
            "仕訳数: 482",
            "科目確認: 3",
            "補助科目確認: 2",
            "税区分確認: 1",
            "未対応仕訳構成: 4",
            "保持方法未確認: 5",
            "JDL科目一覧: 設定済み",
            "最終状態: 確認が必要です",
        ):
            self.assertIn(expected, text)
        for private_value in (
            "顧客名", "秘密.csv", "/private", "架空の内部メッセージ"
        ):
            self.assertNotIn(private_value, text)

    @staticmethod
    def _assert_no_internal_terms(text: str) -> None:
        for term in ("ConversionProfile", "Profile ID", "Registry", "Evidence", "BLOCKED_BY"):
            if term in text:
                raise AssertionError(f"technical term leaked: {term}")

    @staticmethod
    def _write_moneyforward(path: Path) -> Path:
        row = (
            "1", "2026/10/19", "現金", "", "", "", "", "", "700",
            "普通預金", "", "", "", "", "", "700", "架空GUI確認", "", "",
        )
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n", quoting=csv.QUOTE_ALL)
        writer.writerow(MONEYFORWARD_OBSERVED_HEADER)
        writer.writerow(row)
        path.write_bytes(output.getvalue().encode("cp932"))
        return path

    @staticmethod
    def _write_yayoi(path: Path) -> Path:
        spec = yayoi_accounting_05_official_import_spec()
        values = {column.name: "" for column in spec.columns}
        values.update(
            {
                "識別フラグ": "2111",
                "伝票No.": "1",
                "取引日付": "R.08/10/19",
                "借方勘定科目": "現金",
                "借方金額": "700",
                "貸方勘定科目": "普通預金",
                "貸方金額": "700",
                "摘要": "架空GUI確認",
            }
        )
        with path.open("w", encoding="cp932", newline="") as handle:
            csv.writer(handle, lineterminator="\r\n").writerow(
                tuple(values[column.name] for column in spec.columns)
            )
        return path


if __name__ == "__main__":
    unittest.main()
