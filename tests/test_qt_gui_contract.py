from __future__ import annotations

import ast
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
        self.assertIn("pypdf>=5,<7", project["project"]["dependencies"])
        script = Path("scripts/build_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("ui_qt\\app.py", script)
        self.assertIn("ui\\app.py", script)
        self.assertIn("--collect-all", script)
        self.assertIn('"--collect-all", "pypdf"', script)
        self.assertIn("from pypdf import PdfReader", script)
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
        for label in (
            "会社設定を選択", "会社を追加", "名前を変更", "入力元",
            "JDL科目一覧", "対応内容を確認・変更",
        ):
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
            "JDL科目一覧を設定",
            "この会社のJDLから印刷した科目一覧PDFを読み込んでください。",
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
            "Money Forwardの各科目に対応するJDL科目を確認してください。",
            "確認しました",
            "完全一致する候補は初期表示されていますが、まだ確定していません。",
            "まだ設定が必要な項目があります",
            "科目対応は先に設定できます。未設定項目が残っている間は変換できません。",
            "対応設定を保存",
            "新しい対応設定を作成",
        )
        for text in expected:
            self.assertIn(text, source)
        for internal in (
            "MappingRequirementExtractor", "USER_CONFIRMED", "JdlTargetContext",
            "fingerprint", "Evidence ID",
        ):
            self.assertNotIn(f'"{internal}"', source)

    def test_jdl_account_pdf_is_selected_without_exposing_internal_json(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        for text in (
            "JDLから読み込む",
            "JDLの科目一覧PDFを選択",
            "PDF files (*.pdf)",
            "科目一覧を読み込みました",
        ):
            self.assertIn(text, source)
        company_flow = source.split("class CompanyAddDialog", maxsplit=1)[1]
        self.assertNotIn("JSON files (*.json)", company_flow)
        self.assertNotIn("JDL設定JSON", company_flow)
        self.assertEqual(source.count('log_local_exception("jdl_account_pdf_import", exc)'), 2)

    def test_created_moneyforward_profile_replaces_parent_selection(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        method = source.split(
            "def _create_moneyforward_profile(self)", maxsplit=1
        )[1].split("def _render_confirmation", maxsplit=1)[0]
        self.assertIn("self.profile_ids = [dialog.profile_id]", method)
        self.assertIn("self.profile_combo.clear()", method)
        self.assertIn("self.profile_combo.addItem(dialog.profile_name)", method)
        self.assertIn("self.context_path = dialog.context_path", method)

    def test_moneyforward_mapping_table_is_readable_and_requires_confirmation(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        expected = (
            "self.resize(1080, 700)",
            "self.setMinimumSize(820, 560)",
            "layout.setContentsMargins(24, 18, 24, 18)",
            "layout.setSpacing(10)",
            "self.table.setMinimumHeight(260)",
            "self.table.setSizePolicy(",
            "layout.addLayout(mapping_area, 1)",
            "layout.setStretchFactor(mapping_area, 1)",
            "self.table.setColumnWidth(2, 168)",
            "self.table.verticalHeader().setDefaultSectionSize(40)",
            "self.table.setRowHeight(row_index, 40)",
            "ScrollBarAlwaysOff",
            "confirmation_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)",
            "self.table.setCellWidget(row_index, 1, target)",
            "self.table.setCellWidget(row_index, 2, confirmation_cell)",
            'target.addItem("未選択", None)',
            "confirmed.setEnabled(target.currentData() is not None)",
            "checkbox.setChecked(False)",
            "checkbox.setEnabled(selected)",
            "target.currentData() is not None",
            "Money Forwardの科目",
            "JDLの科目",
            "0 / 0 件確認済み",
            "confirmed == total",
            "JDL IBEX 出納帳 35.5 / 科目一覧設定済み",
        )
        for text in expected:
            self.assertIn(text, source)
        for selector in (
            "QTableWidget", "QHeaderView::section", "QScrollBar:vertical",
            "QCheckBox::indicator",
        ):
            self.assertIn(selector, APP_STYLE_SHEET)

    def test_moneyforward_mapping_actions_remain_below_only_stretching_area(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        dialog = source.split(
            "class MoneyForwardProfileSetupDialog", maxsplit=1
        )[1].split("class TaxMappingConfirmationDialog", maxsplit=1)[0]

        mapping_position = dialog.index("layout.addLayout(mapping_area, 1)")
        actions_position = dialog.index("layout.addLayout(actions)")
        self.assertLess(mapping_position, actions_position)
        self.assertNotIn("layout.addLayout(actions, 1)", dialog)

    def test_existing_company_can_refresh_jdl_account_master_with_diff_review(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        controller = Path("src/accounting_converter/ui/controllers.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('QPushButton("JDL科目一覧を更新")', source)
        self.assertIn("class CompanyMasterRefreshDialog", source)
        self.assertIn("同じコードと名称の科目対応は保持", source)
        self.assertIn('target.addItem("未選択", None)', source)
        self.assertIn("plan_company_master_refresh", controller)
        self.assertIn("apply_company_master_refresh", controller)

    def test_existing_company_can_review_only_new_accounts_and_subaccounts(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(encoding="utf-8")
        self.assertIn('QPushButton("対応内容を確認・変更")', source)
        self.assertIn('QPushButton("確認する")', source)
        self.assertIn("self._confirm_current_csv", source)
        self.assertIn("self._refresh_current_csv_readiness()", source)
        self.assertNotIn("self._review_required_mappings(path)", source)
        self.assertIn("class CompanyMappingUpdateDialog", source)
        self.assertIn("追加確認が必要な科目はありません", source)
        self.assertIn("WheelSafeComboBox()", source)
        self.assertIn('target.addItem("未選択", None)', source)
        self.assertIn("review_saved_company_mappings", source)
        self.assertIn("税設定の確認が必要です。CSV読込時に確認できます。", source)

    def test_normal_moneyforward_flow_does_not_expose_old_settings_route(self) -> None:
        window = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        workflow = Path(
            "src/accounting_converter/application/moneyforward_conversion_workflow.py"
        ).read_text(encoding="utf-8")
        main_window = window.split("class SettingsDialog", maxsplit=1)[0]
        self.assertIn('QPushButton("確認する")', main_window)
        self.assertIn("CompanyMappingUpdateDialog", main_window)
        self.assertIn("TaxMappingConfirmationDialog", main_window)
        self.assertNotIn("新しい科目を確認", workflow)

    def test_pilot_support_and_jdl_environment_controls_are_visible(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        controller = Path("src/accounting_converter/ui/controllers.py").read_text(
            encoding="utf-8"
        )
        for text in (
            'QPushButton("確認項目をコピー")',
            'QPushButton("診断情報をコピー")',
            "JDL環境:",
            "科目一覧:",
            "最終更新日:",
            "QApplication.clipboard()",
        ):
            self.assertIn(text, source)
        self.assertIn("このJDL環境は確認が必要です", controller)
        self.assertIn("JDL科目一覧を更新", controller)
        self.assertIn("補助科目設定を確認", controller)

    def test_tax_confirmation_dialog_supports_multiple_explicit_confirmations(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        dialog = source.split("class TaxMappingConfirmationDialog", maxsplit=1)[1].split(
            "class CompanyRenameDialog", maxsplit=1
        )[0]
        controller = Path("src/accounting_converter/ui/controllers.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("for item in self.review.items", dialog)
        self.assertIn('QCheckBox("確認しました")', dialog)
        self.assertIn("all(item.isChecked()", dialog)
        self.assertIn("confirm_company_tax_mappings", dialog)
        self.assertIn("def confirm_company_tax_mappings", controller)

    def test_mapping_selector_ignores_wheel_so_table_can_scroll(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        widgets = Path("src/accounting_converter/ui_qt/widgets.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("QAbstractItemView.ScrollMode.ScrollPerPixel", source)
        self.assertIn("WheelSafeComboBox()", source)
        self.assertIn("class WheelSafeComboBox(QComboBox)", widgets)
        self.assertIn("def wheelEvent(self, event: QWheelEvent)", widgets)
        self.assertIn("event.ignore()", widgets)

    def test_verified_tax_confirmation_ui_is_explicit_and_scoped(self) -> None:
        source = "\n".join(
            (
                Path("src/accounting_converter/ui_qt/main_window.py").read_text(
                    encoding="utf-8"
                ),
                Path(
                    "src/accounting_converter/application/moneyforward_profile_setup.py"
                ).read_text(encoding="utf-8"),
            )
        )
        for text in (
            "税区分を確認",
            "Money Forward: 課税仕入 10%",
            "JDL: 仕入 / 10%",
            "状態: 確認してください",
            "確認しました",
            "現在のJDL設定ではこの税区分を確認できません",
        ):
            self.assertIn(text, source)
        self.assertIn("self.save_button.setEnabled(False)", source)

    def test_company_selector_connections_use_handlers_owned_by_each_view(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        classes = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
        }
        main_methods = {
            node.name for node in classes["AccountingConverterMainWindow"].body
            if isinstance(node, ast.FunctionDef)
        }
        settings_methods = {
            node.name for node in classes["SettingsDialog"].body
            if isinstance(node, ast.FunctionDef)
        }
        main_window_source, settings_source = source.split(
            "class SettingsDialog", maxsplit=1
        )
        self.assertIn("_select_company", main_methods)
        self.assertNotIn("_company_changed", main_methods)
        self.assertIn("_company_changed", settings_methods)
        self.assertIn(
            "self.company_combo.currentIndexChanged.connect(self._select_company)",
            main_window_source,
        )
        self.assertNotIn("self._company_changed", main_window_source)
        self.assertIn(
            "self.company_combo.currentIndexChanged.connect(self._company_changed)",
            settings_source,
        )
        self.assertIn("def _company_changed(self, _index: int)", settings_source)

    def test_main_window_company_handler_uses_existing_controller_flow(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(encoding="utf-8")
        main_window_source = source.split("class SettingsDialog", maxsplit=1)[0]
        self.assertIn("company_id = self.company_combo.itemData(index)", main_window_source)
        self.assertIn(
            "self.controller.select_company_setting(company_id)",
            main_window_source,
        )
        self.assertIn("self._prepare_if_complete()", main_window_source)

    def test_file_picker_and_drop_share_company_preserving_input_flow(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(encoding="utf-8")
        main_window_source = source.split("class SettingsDialog", maxsplit=1)[0]
        self.assertIn("self.drop_zone.file_selected.connect(self._select_input)", main_window_source)
        self.assertIn("self._select_input(Path(filename))", main_window_source)
        self.assertIn("self.controller.select_file(path)", main_window_source)
        self.assertIn("self._refresh_current_csv_readiness()", main_window_source)

    def test_subaccount_review_offers_explicit_parent_only_policy(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(encoding="utf-8")
        dialog = source.split("class CompanyMappingUpdateDialog", maxsplit=1)[1]
        self.assertIn("親科目のみで変換する", dialog)
        self.assertIn("MF側の補助科目情報は", dialog)
        self.assertIn("PARENT_ONLY_SELECTION", dialog)
        self.assertIn("combo.currentData() is not None and check.isChecked()", dialog)

    def test_subaccount_candidates_follow_confirmed_parent_selection(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(encoding="utf-8")
        dialog = source.split("class CompanyMappingUpdateDialog", maxsplit=1)[1]

        self.assertIn("self._refresh_subaccounts", dialog)
        self.assertIn("account_confirmed.isChecked()", dialog)
        self.assertIn("item.subaccount_targets_for", dialog)
        self.assertIn("item.confirmed_parent_target", dialog)
        self.assertIn("combo.clear()", dialog)
        self.assertIn('combo.addItem("未選択", None)', dialog)
        self.assertIn("checkbox.setChecked(False)", dialog)


if __name__ == "__main__":
    unittest.main()
