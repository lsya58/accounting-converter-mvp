from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path

from accounting_converter.ui.view_models import UserFacingStatus
from accounting_converter.ui_qt.drop_policy import evaluate_csv_drop
from accounting_converter.ui_qt.theme import APP_STYLE_SHEET, COLORS, status_visual


class QtGuiContractTests(unittest.TestCase):
    def test_runtime_dependency_and_dual_build_entries_are_declared(self) -> None:
        project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn("PySide6>=6.8,<7", project["project"]["dependencies"])
        script = Path("scripts/build_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("ui_qt\\app.py", script)
        self.assertIn("ui\\app.py", script)
        self.assertIn("--collect-all", script)
        self.assertIn("TkFallback", script)

    def test_single_csv_drop_is_accepted_without_modification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.csv"
            path.write_bytes(b"synthetic")
            before = path.read_bytes()
            decision = evaluate_csv_drop((path,))

            self.assertTrue(decision.accepted)
            self.assertEqual(decision.accepted_path, path)
            self.assertEqual(path.read_bytes(), before)

    def test_multiple_files_are_rejected(self) -> None:
        decision = evaluate_csv_drop((Path("a.csv"), Path("b.csv")))
        self.assertFalse(decision.accepted)
        self.assertIn("1件", decision.message)

    def test_non_csv_and_directory_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            text = root / "input.txt"
            text.write_text("synthetic", encoding="ascii")
            self.assertFalse(evaluate_csv_drop((text,)).accepted)
            self.assertFalse(evaluate_csv_drop((root,)).accepted)

    def test_empty_or_nonexistent_drop_is_rejected(self) -> None:
        self.assertFalse(evaluate_csv_drop(()).accepted)
        self.assertFalse(evaluate_csv_drop((Path("missing.csv"),)).accepted)

    def test_visual_tokens_cover_all_presentation_states(self) -> None:
        self.assertEqual(COLORS["surface"], "#FFFFFF")
        for status in UserFacingStatus:
            label, foreground, background = status_visual(status)
            self.assertTrue(label)
            self.assertNotEqual(foreground, background)

    def test_company_setting_ui_is_visible_without_internal_terminology(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(encoding="utf-8")
        for label in ("会社設定を選択", "会社を追加", "名前を変更", "入力元", "対応設定"):
            self.assertIn(label, source)
        visible_literals = (
            "Conversion Profile", "JdlTargetContext", "Evidence ID", "fingerprint"
        )
        for literal in visible_literals:
            self.assertNotIn(f'"{literal}"', source)

    def test_company_add_flow_has_explanations_and_japanese_actions(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(encoding="utf-8")
        expected = (
            "会社名を設定",
            "この名前はアプリ内で会社を識別するために使います。",
            "入力元を選択",
            "この会社で使用している会計ソフトを選択してください。",
            "変換設定を選択",
            "この会社で使用する対応設定とJDL設定を選択してください。",
            "会社設定を確認",
            "内容を確認して保存してください。",
            'QPushButton("戻る")',
            'QPushButton("キャンセル")',
            'QPushButton("次へ")',
        )
        for text in expected:
            self.assertIn(text, source)
        self.assertNotIn("QInputDialog", source)
        self.assertNotIn('"OK"', source)
        self.assertNotIn('"Cancel"', source)

    def test_dialog_controls_have_explicit_light_theme_states(self) -> None:
        for selector in (
            "QDialog", "QLineEdit", "QComboBox", "QAbstractItemView",
            "QPushButton:disabled", "QComboBox:disabled", "QLineEdit:focus",
        ):
            self.assertIn(selector, APP_STYLE_SHEET)
        self.assertIn(COLORS["disabled_text"], APP_STYLE_SHEET)

    def test_moneyforward_profile_creation_route_is_user_facing(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(encoding="utf-8")
        expected = (
            "この入力元の対応設定がまだありません。",
            "対応設定を作成",
            "Money Forwardの仕訳CSVから対応設定を作成",
            "Money Forwardの仕訳CSV",
            "JDLの科目を確認",
            "確認しました",
            "完全一致する候補は初期表示されていますが、まだ確定していません。",
            "このCSVには現在設定できない項目があります",
            "対応設定を保存",
        )
        for text in expected:
            self.assertIn(text, source)
        for internal in (
            "MappingRequirementExtractor", "USER_CONFIRMED", "JdlTargetContext",
            "fingerprint", "Evidence ID",
        ):
            self.assertNotIn(f'"{internal}"', source)


if __name__ == "__main__":
    unittest.main()
