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
    def test_jdl_migration_review_is_scrollable_and_failures_are_visible(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        dialog = source.split(
            "class JdlMigrationHumanReviewDialog", maxsplit=1
        )[1].split("class TradePartnerPolicyDialog", maxsplit=1)[0]
        for contract in (
            "QScrollArea()", "確認済み0件を保存", "jdl_migration_review_save",
            "QMessageBox.warning", "実機確認が不足しているため変換できません",
            "実機確認済みですが、現在のJDL税設定と一致しません",
            "実機確認済みですが、確認に使用したJDL科目の条件と一致しません",
            "32文字を超えるため変換できません",
            'content.setObjectName("page")',
            'setObjectName("sectionTitle")',
            "推奨候補がない科目があります。",
            "補助情報は引き継がれません。",
            "この画面で確認済み:",
            "確認済み{confirmed}件を保存",
            "未確認{remaining_count}件が残っています。",
            "self.save_button.setEnabled(confirmed > 0)",
        ):
            self.assertIn(contract, dialog)

    def test_jdl_migration_partial_save_failure_keeps_visible_confirmation(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        dialog = source.split(
            "class JdlMigrationHumanReviewDialog", maxsplit=1
        )[1].split("class TradePartnerPolicyDialog", maxsplit=1)[0]
        failure = dialog.split("except Exception as exc:", maxsplit=1)[1]
        self.assertIn('log_local_exception("jdl_migration_review_save", exc)', failure)
        self.assertNotIn("check.setChecked(False)", failure)
        self.assertIn("exc.user_message", failure)
        self.assertIn("QMessageBox.warning", failure)

    def test_jdl_migration_checkbox_does_not_trigger_persistence(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        dialog = source.split(
            "class JdlMigrationHumanReviewDialog", maxsplit=1
        )[1].split("class TradePartnerPolicyDialog", maxsplit=1)[0]
        self.assertIn("confirmed.toggled.connect(self._refresh_save_state)", dialog)
        self.assertNotIn("confirmed.toggled.connect(self._save)", dialog)
        self.assertIn("self.save_button.setAutoDefault(False)", dialog)
        self.assertIn("self.save_button.setDefault(False)", dialog)
        self.assertIn("self.save_button.clicked.connect(self._save)", dialog)

    def test_scroll_area_corner_uses_light_application_surface(self) -> None:
        self.assertIn("QAbstractScrollArea::corner", APP_STYLE_SHEET)
        self.assertIn(COLORS["page"], APP_STYLE_SHEET)

    def test_jdl_migration_review_uses_current_state_without_json_picker(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        handler = source.split(
            "def _review_jdl_migration", maxsplit=1
        )[1].split("def _review_settings", maxsplit=1)[0]

        self.assertIn("current_jdl_migration_review", handler)
        self.assertNotIn("QFileDialog", handler)
        self.assertIn("その他のJDL科目", source)
        self.assertIn("対応する利用可能なJDL科目がありません", source)
        self.assertIn("補助を保持するにはJDL側で補助科目を作成", source)

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

    def test_trade_partner_policy_requires_explicit_company_confirmation(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        for text in (
            "取引先情報の扱い",
            "JDLには取引先専用のCSV項目がないため",
            "取引先名を摘要に引き継ぐ",
            "自動では有効になりません。内容を確認してください。",
        ):
            self.assertIn(text, source)

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

    def test_company_add_flow_exposes_gated_jdl_to_jdl_identity(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'self.source_combo.addItems(("Money Forward", "弥生", "JDL"))',
            source,
        )
        self.assertIn('self.target_combo.addItem("JDL")', source)
        self.assertIn("create_jdl_migration_company_draft_profile", source)

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
        self.assertIn("review_company_settings_with_current_source", source)
        self.assertIn(
            "if tax_review.items:\n            self._confirm_tax()\n"
            "        else:\n            self.accept()",
            source,
        )
        self.assertIn("税設定の確認が必要です。CSV読込時に確認できます。", source)

    def test_pdf_company_has_explicit_jdl_tax_context_confirmation_flow(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        controller = Path("src/accounting_converter/ui/controllers.py").read_text(
            encoding="utf-8"
        )
        for text in (
            'QPushButton("JDL税設定を確認・変更")',
            "class JdlTaxContextConfirmationDialog",
            'self.taxable_status.addItem("課税"',
            '"税込", JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED.value',
            "原則課税",
            "簡易課税",
            "第一種事業",
            "個別対応方式",
            "一括比例配分方式",
            "JDL側が上記の設定であることを確認しました",
            "この画面からJDL本体の設定を変更することはありません。",
            "JDL税設定: 課税 / {processing} / 簡易課税 / {category} / 確認済み",
            "税区分を確認するには、この会社のJDL税設定の登録が必要です。",
        ):
            self.assertIn(text, source)
        self.assertIn("confirm_company_tax_context", controller)
        self.assertIn(
            'log_local_exception("company_tax_context_confirmation", error)',
            controller,
        )
        self.assertIn(
            'QMessageBox.warning(\n            self,\n            "JDL税設定を保存できませんでした"',
            source,
        )
        self.assertIn(
            "if dialog.exec() == QDialog.DialogCode.Accepted:\n"
            "            self._reload_companies(self.controller.state)",
            source,
        )

    def test_jdl_migration_description_replacement_is_explicit_and_bounded(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        for text in (
            "現在の摘要:",
            "置換後の摘要（1〜32文字）",
            "この摘要への置換を確認しました",
            "_valid_description_replacement",
            'value.encode("cp932", errors="strict")',
            "description_confirmed",
        ):
            self.assertIn(text, source)

    def test_master_refresh_failure_is_logged_and_user_visible(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'log_local_exception("jdl_account_master_refresh_apply", exc)',
            source,
        )
        self.assertIn(
            'QMessageBox.warning(self, "更新を保存できませんでした", message)',
            source,
        )
        self.assertIn(
            "既存の科目対応が新しい科目一覧と一致しません。",
            source,
        )

    def test_company_setting_actions_reserve_width_for_windows_text(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "refresh_master.setMinimumWidth(refresh_master.sizeHint().width() + 12)",
            source,
        )
        self.assertIn(
            "self.tax_context_button.sizeHint().width() + 12", source
        )
        self.assertIn("company_actions = QGridLayout()", source)
        self.assertIn("company_actions.addWidget(refresh_master, 1, 1)", source)

    def test_mapping_dialog_distinguishes_default_subaccount_from_parent_only(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('item.mapping_type == "DEFAULT_SUBACCOUNT"', source)
        self.assertIn('("親科目のみの場合", item.parent_only_loss)', source)
        self.assertIn('target.addItem(value, value)', source)
        self.assertIn('"MFでは補助科目がありません。JDLでこの親科目に補助が必要なため、"', source)
        self.assertIn('item.mapping_type == "SUBACCOUNT"', source)

    def test_mapping_dialog_warns_on_unsaved_close_and_separates_tax_evidence(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        dialog = source.split("class CompanyMappingUpdateDialog", 1)[1].split(
            "class CompanyAddDialog", 1
        )[0]
        self.assertIn('self._review_state() != self._initial_review_state', dialog)
        self.assertIn('QMessageBox.StandardButton.Discard', dialog)
        self.assertIn('実機検証待ち{tax_system_pending}', dialog)
        self.assertIn('self.save_button.setEnabled(confirmed > 0)', dialog)

    def test_mapping_dialog_initializes_actions_before_subaccount_refresh(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        dialog = source.split("class CompanyMappingUpdateDialog", maxsplit=1)[1].split(
            "class CompanyAddDialog", maxsplit=1
        )[0]
        save_button = dialog.index('self.save_button = QPushButton("確認済み0件を保存")')
        initial_refresh = dialog.index(
            "for source_value in self.account_controls:\n"
            "            self._refresh_subaccounts(source_value)"
        )
        self.assertLess(save_button, initial_refresh)

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
        self.assertIn("log_local_event(", workflow)
        self.assertIn("MF-JDL-TAX-EVIDENCE-CONDITION-MISMATCH", workflow)

    def test_packaged_build_collects_runtime_diagnostic_module(self) -> None:
        build = Path("scripts/build_windows.ps1").read_text(encoding="utf-8")
        self.assertIn('--collect-submodules "accounting_converter"', build)

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
        self.assertIn('QCheckBox("この税区分のJDLでの扱いを確認しました")', dialog)
        self.assertIn("if item.human_confirmable", dialog)
        self.assertIn("item.blocker_code", dialog)
        self.assertIn("all(item.isChecked()", dialog)
        self.assertIn("confirm_company_tax_mappings", dialog)
        self.assertIn("def confirm_company_tax_mappings", controller)

    def test_tax_confirmation_cards_scroll_without_moving_actions(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        dialog = source.split("class TaxMappingConfirmationDialog", maxsplit=1)[1].split(
            "class CompanyRenameDialog", maxsplit=1
        )[0]
        cards_section, actions_section = dialog.split(
            "actions = QHBoxLayout(footer)", maxsplit=1
        )
        self.assertIn("scroll = QScrollArea()", cards_section)
        self.assertIn("scroll.setWidgetResizable(True)", cards_section)
        self.assertIn("ScrollBarAlwaysOff", cards_section)
        self.assertIn("scroll.setWidget(cards)", cards_section)
        self.assertIn("layout.addWidget(scroll, 1)", cards_section)
        self.assertIn('QPushButton("確認を保存")', actions_section)
        self.assertNotIn("scroll.setWidget", actions_section)

    def test_tax_review_keeps_blocked_items_visible_and_shares_parent_state(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        mapping = source.split("class CompanyMappingUpdateDialog", maxsplit=1)[1].split(
            "class CompanyAddDialog", maxsplit=1
        )[0]
        tax = source.split("class TaxMappingConfirmationDialog", maxsplit=1)[1].split(
            "class CompanyRenameDialog", maxsplit=1
        )[0]
        self.assertIn("self.tax_review = tax_review", mapping)
        self.assertIn("review=self.tax_review", mapping)
        self.assertIn("システム側のEvidence・対応待ち", tax)
        self.assertIn("if item.human_confirmable", tax)
        self.assertIn("item.reason", tax)
        self.assertIn("item.blocker_code", tax)

    def test_review_footer_is_outside_stretching_content(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        for class_name, next_class in (
            ("CompanyMappingUpdateDialog", "CompanyAddDialog"),
            ("TaxMappingConfirmationDialog", "CompanyRenameDialog"),
        ):
            dialog = source.split(f"class {class_name}", maxsplit=1)[1].split(
                f"class {next_class}", maxsplit=1
            )[0]
            self.assertIn('footer.setObjectName("dialogFooter")', dialog)
            self.assertIn("layout.addWidget(footer, 0)", dialog)

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

    def test_main_window_dispatches_selected_jdl_route_and_updates_header(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        main_window_source = source.split("class SettingsDialog", maxsplit=1)[0]
        self.assertIn("RecognizedFormat.JDL", main_window_source)
        self.assertIn("inspect_selected_jdl_migration", main_window_source)
        self.assertIn("JdlMigrationHumanReviewDialog", main_window_source)
        self.assertIn(
            "JDLの仕訳データを別のJDL会社用CSVへ安全に移行します",
            main_window_source,
        )

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
        self.assertIn("item.allows_parent_only_for", dialog)
        self.assertIn("item.confirmed_parent_target", dialog)
        self.assertIn("combo.clear()", dialog)
        self.assertIn('combo.addItem("未選択", None)', dialog)
        self.assertIn("checkbox.setChecked(False)", dialog)
        self.assertIn("候補を生成できません。科目一覧を再確認してください。", dialog)

    def test_moneyforward_review_exposes_recommendations_and_partial_save(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        dialog = source.split("class CompanyMappingUpdateDialog", maxsplit=1)[1].split(
            "class CompanyAddDialog", maxsplit=1
        )[0]
        for text in (
            'target.addItem("おすすめ", None)',
            'target.addItem("その他のJDL科目", None)',
            "item.recommended_reason",
            "確認済み / 設定数:",
            "確認済み{confirmed}件を保存",
            "if key in confirmed",
            "item.already_confirmed",
        ):
            self.assertIn(text, dialog)
        self.assertIn("self.progress_label = QLabel()", dialog)

    def test_moneyforward_review_requires_explicit_description_replacement(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        dialog = source.split("class CompanyMappingUpdateDialog", maxsplit=1)[1].split(
            "class CompanyAddDialog", maxsplit=1
        )[0]
        for text in (
            "JDLでは正しく保存できない文字があります",
            "この摘要を使う仕訳:",
            "このままJDLへ変換すると:",
            "意味を保つ",
            "この置き換え内容を確認しました",
            "recommended_description_replacement",
            "observed_jdl_description",
            "description_confirmed",
        ):
            self.assertIn(text, dialog)

    def test_moneyforward_review_uses_scrollable_category_navigation(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        dialog = source.split("class CompanyMappingUpdateDialog", maxsplit=1)[1].split(
            "class CompanyAddDialog", maxsplit=1
        )[0]
        for text in (
            "self.tabs = QTabWidget()",
            'self._add_tab("accounts", "科目"',
            '"subaccounts", "補助科目"',
            'self._add_tab("descriptions", "摘要・文字置換"',
            'self._add_tab("tax", "税区分"',
            'self._add_tab("other", "その他"',
            "QScrollArea()",
            "ScrollPerPixel",
            '("影響する仕訳",',
            "_select_first_unresolved_tab",
            "QSplitter(Qt.Orientation.Horizontal)",
            "QStackedWidget()",
        ):
            self.assertIn(text, dialog)

    def test_moneyforward_review_dialogs_are_resizable_and_restore_geometry(self) -> None:
        source = Path("src/accounting_converter/ui_qt/main_window.py").read_text(
            encoding="utf-8"
        )
        mapping = source.split("class CompanyMappingUpdateDialog", maxsplit=1)[1].split(
            "class CompanyAddDialog", maxsplit=1
        )[0]
        tax = source.split("class TaxMappingConfirmationDialog", maxsplit=1)[1].split(
            "class CompanyRenameDialog", maxsplit=1
        )[0]
        for dialog in (mapping, tax):
            self.assertIn("WindowMaximizeButtonHint", dialog)
            self.assertIn("_restore_dialog_geometry", dialog)
            self.assertIn("saveGeometry", dialog)
        helper = source.split("def _restore_dialog_geometry", maxsplit=1)[1].split(
            "class AccountingConverterMainWindow", maxsplit=1
        )[0]
        self.assertIn("availableGeometry()", helper)
        self.assertIn("available.contains(frame)", helper)
        self.assertIn("dialog.setGeometry", helper)
        self.assertIn("setHorizontalScrollBarPolicy", mapping)
        self.assertIn("setVerticalScrollBarPolicy", mapping)


if __name__ == "__main__":
    unittest.main()
