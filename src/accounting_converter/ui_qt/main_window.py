from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from accounting_converter.application.company_mapping_update import (
    PARENT_ONLY_SELECTION,
)
from accounting_converter.domain.mapping import SubaccountPolicy
from accounting_converter.ui.controllers import AccountingConverterController
from accounting_converter.ui.view_models import (
    AppState,
    present_main_screen,
    support_diagnostic_text,
)
from accounting_converter.infrastructure.local_diagnostic_log import (
    log_local_exception,
)

from .theme import status_visual
from .widgets import CsvDropZone, WheelSafeComboBox


class AccountingConverterMainWindow(QMainWindow):
    def __init__(self, controller: AccountingConverterController | None = None) -> None:
        super().__init__()
        self.controller = controller or AccountingConverterController()
        self.profile_ids: list[str] = []
        self.setWindowTitle("会計データ変換")
        self.resize(900, 780)
        self.setMinimumSize(720, 620)
        self._build()
        self.controller.load_profiles()
        self._render(self.controller.load_company_settings())

    def _build(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        page = QWidget()
        page.setObjectName("page")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(28, 28, 28, 36)
        outer.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        content = QWidget()
        content.setMaximumWidth(820)
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        outer.addWidget(content)
        scroll.setWidget(page)
        self.setCentralWidget(scroll)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("会計データ変換")
        title.setObjectName("title")
        subtitle = QLabel("Money Forward / 弥生の仕訳データをJDL用CSVへ安全に変換します")
        subtitle.setObjectName("subtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        self.settings_button = QPushButton("設定")
        self.settings_button.clicked.connect(self._open_settings)
        header.addLayout(titles, 1)
        header.addWidget(self.settings_button, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        company_row = QHBoxLayout()
        company_row.addWidget(QLabel("会社"))
        self.company_combo = QComboBox()
        self.company_combo.setPlaceholderText("会社設定を選択")
        self.company_combo.currentIndexChanged.connect(self._select_company)
        company_row.addWidget(self.company_combo, 1)
        company_settings_button = QPushButton("会社設定")
        company_settings_button.clicked.connect(self._open_settings)
        company_row.addWidget(company_settings_button)
        layout.addLayout(company_row)

        self.drop_zone = CsvDropZone()
        self.drop_zone.choose_button.clicked.connect(self._choose_input)
        self.drop_zone.file_selected.connect(self._select_input)
        self.drop_zone.rejected.connect(self._show_drop_error)
        layout.addWidget(self.drop_zone)

        self.recognition_card, recognition_layout = self._card("認識結果")
        self.file_name_label = QLabel("ファイルはまだ選択されていません")
        self.file_name_label.setObjectName("sectionTitle")
        self.recognition_label = QLabel("")
        self.recognition_label.setObjectName("muted")
        self.recognition_label.setWordWrap(True)
        recognition_layout.addWidget(self.file_name_label)
        recognition_layout.addWidget(self.recognition_label)
        self.recognition_card.hide()
        layout.addWidget(self.recognition_card)

        output_card, output_layout = self._card("保存先")
        output_row = QHBoxLayout()
        self.output_label = QLabel("保存先はまだ選択されていません")
        self.output_label.setWordWrap(True)
        output_button = QPushButton("変更")
        output_button.clicked.connect(self._choose_output)
        output_row.addWidget(self.output_label, 1)
        output_row.addWidget(output_button)
        output_layout.addLayout(output_row)
        layout.addWidget(output_card)

        status_card, status_layout = self._card("状態")
        status_row = QHBoxLayout()
        self.status_title = QLabel("CSVを選択してください")
        self.status_title.setObjectName("statusTitle")
        self.status_badge = QLabel("未準備")
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_badge.setContentsMargins(10, 5, 10, 5)
        status_row.addWidget(self.status_title, 1)
        status_row.addWidget(self.status_badge)
        self.status_detail = QLabel("変換する仕訳CSVを選択してください。")
        self.status_detail.setObjectName("muted")
        self.status_detail.setWordWrap(True)
        action_row = QHBoxLayout()
        self.settings_action = QPushButton("確認する")
        self.settings_action.clicked.connect(self._confirm_current_csv)
        self.copy_guidance_button = QPushButton("確認項目をコピー")
        self.copy_guidance_button.clicked.connect(self._copy_guidance)
        self.copy_diagnostics_button = QPushButton("診断情報をコピー")
        self.copy_diagnostics_button.clicked.connect(self._copy_diagnostics)
        self.convert_button = QPushButton("JDL用に変換する")
        self.convert_button.setObjectName("primaryButton")
        self.convert_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.convert_button.clicked.connect(self._convert)
        action_row.addWidget(self.settings_action)
        action_row.addWidget(self.copy_guidance_button)
        action_row.addWidget(self.copy_diagnostics_button)
        action_row.addStretch(1)
        action_row.addWidget(self.convert_button)
        status_layout.addLayout(status_row)
        status_layout.addWidget(self.status_detail)
        status_layout.addLayout(action_row)
        layout.addWidget(status_card)

        self.result_card, result_layout = self._card("変換結果")
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        result_layout.addWidget(self.result_label)
        result_actions = QHBoxLayout()
        open_button = QPushButton("保存先を開く")
        open_button.clicked.connect(self._open_output_folder)
        help_button = QPushButton("JDL取込手順")
        help_button.clicked.connect(self._show_jdl_help)
        report_button = QPushButton("検証レポート")
        report_button.clicked.connect(self._show_report)
        result_actions.addWidget(open_button)
        result_actions.addStretch(1)
        result_actions.addWidget(help_button)
        result_actions.addWidget(report_button)
        result_layout.addLayout(result_actions)
        self.result_card.hide()
        layout.addWidget(self.result_card)

    @staticmethod
    def _card(title_text: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        title = QLabel(title_text)
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        return card, layout

    def _choose_input(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "変換する仕訳CSVを選択",
            "",
            "CSV files (*.csv);;All files (*)",
        )
        if filename:
            self._select_input(Path(filename))

    def _select_input(self, path: Path) -> None:
        self._render(self.controller.select_file(path))
        self._refresh_current_csv_readiness()

    def _confirm_current_csv(self) -> None:
        state = self.controller.state
        company_id = state.selected_company_setting_id
        path = state.selected_file
        if not company_id:
            self._open_settings()
            return
        if path is None:
            return
        try:
            review = self.controller.review_company_mapping_updates(company_id, path)
        except Exception:
            QMessageBox.warning(
                self,
                "確認できませんでした",
                "会社設定とCSVを確認してください。",
            )
            return
        if review.items:
            dialog = CompanyMappingUpdateDialog(self.controller, review, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                self._refresh_current_csv_readiness()
                return
            review = self.controller.review_company_mapping_updates(company_id, path)
        if review.tax_categories:
            saved = self.controller.ensure_selected_tax_requirements(review)
            if saved.developer_error is not None:
                self._render(saved)
                return
            tax_review = self.controller.company_tax_mapping_review(company_id)
            if tax_review.items:
                dialog = TaxMappingConfirmationDialog(self.controller, company_id, self)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    self._refresh_current_csv_readiness()
                    return
            elif tax_review.user_message:
                if self.controller.company_tax_context_pending(company_id):
                    context_dialog = JdlTaxContextConfirmationDialog(
                        self.controller, company_id, self
                    )
                    if context_dialog.exec() != QDialog.DialogCode.Accepted:
                        self._refresh_current_csv_readiness()
                        return
                    tax_review = self.controller.company_tax_mapping_review(company_id)
                    if tax_review.items:
                        dialog = TaxMappingConfirmationDialog(
                            self.controller, company_id, self
                        )
                        if dialog.exec() != QDialog.DialogCode.Accepted:
                            self._refresh_current_csv_readiness()
                            return
                else:
                    QMessageBox.information(
                        self,
                        "税区分の確認",
                        "税区分を確認するには、この会社のJDL税設定の登録が必要です。\n"
                        "現在の科目一覧は読み込み済みですが、課税方式と税込・税抜の"
                        "設定がまだ確認されていません。",
                    )
        self._refresh_current_csv_readiness()

    def _refresh_current_csv_readiness(self) -> None:
        state = self.controller.inspect_selected_moneyforward_confirmations()
        self._render(state)
        if not (
            state.pending_account_confirmations
            or state.pending_subaccount_confirmations
            or state.pending_tax_confirmations
        ):
            self._prepare_if_complete()

    def _choose_output(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "JDL用CSVの保存先",
            "",
            "CSV files (*.csv)",
        )
        if filename:
            output = Path(filename)
            if output.suffix.lower() != ".csv":
                output = output.with_suffix(".csv")
            self._render(self.controller.select_output_file(output))
            if self.controller.state.selected_file:
                self._refresh_current_csv_readiness()
            else:
                self._prepare_if_complete()

    def _prepare_if_complete(self) -> None:
        state = self.controller.state
        if (
            state.selected_file
            and state.selected_output_file
            and state.selected_profile_id
            and state.selected_context_file
            and not state.pending_account_confirmations
            and not state.pending_subaccount_confirmations
            and not state.pending_tax_confirmations
        ):
            self._render(self.controller.prepare_conversion())

    def _convert(self) -> None:
        summary = self.controller.state.conversion_summary
        if summary is None:
            return
        answer = QMessageBox.question(
            self,
            "変換の確認",
            "JDL用CSVを作成します。\n\n"
            f"入力仕訳: {summary.simple_journal_count + summary.compound_journal_count}件\n"
            f"保存先: {summary.output_path}\n\n"
            "入力ファイルは変更せず、既存ファイルは上書きしません。",
        )
        self._render(self.controller.execute_conversion(answer == QMessageBox.StandardButton.Yes))

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.controller, self)
        dialog.exec()
        self._render(self.controller.state)
        self._prepare_if_complete()

    def _select_company(self, index: int) -> None:
        company_id = self.company_combo.itemData(index) if index >= 0 else None
        self._render(self.controller.select_company_setting(company_id))
        if self.controller.state.selected_file:
            self._refresh_current_csv_readiness()
        else:
            self._prepare_if_complete()

    def _show_drop_error(self, message: str) -> None:
        QMessageBox.warning(self, "ファイルを確認してください", message)

    def _copy_guidance(self) -> None:
        presentation = present_main_screen(self.controller.state)
        QApplication.clipboard().setText(presentation.guidance)

    def _copy_diagnostics(self) -> None:
        QApplication.clipboard().setText(
            support_diagnostic_text(self.controller.state, "0.1.0")
        )

    def _show_report(self) -> None:
        QMessageBox.information(
            self,
            "検証レポート",
            self.controller.state.verification_report or "検証レポートはまだありません。",
        )

    def _show_jdl_help(self) -> None:
        QMessageBox.information(
            self,
            "JDLへの取り込み",
            "1. JDLでCSV入力を開き、仕訳データを選択します。\n"
            "2. 必要に応じて出納帳ファイルを退避します。\n"
            "3. 対象期間と集計条件を確認してから実行します。\n\n"
            "画面や設定が異なる場合は、実行せず担当者へ確認してください。",
        )

    def _open_output_folder(self) -> None:
        result = self.controller.state.result_presentation
        if result and result.output_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(result.output_path.parent)))

    def _render(self, state: AppState) -> None:
        presentation = present_main_screen(state)
        self.company_combo.blockSignals(True)
        self.company_combo.clear()
        for item in state.companies:
            self.company_combo.addItem(item.display_name, item.company_setting_id)
        selected_index = next(
            (
                index
                for index in range(self.company_combo.count())
                if self.company_combo.itemData(index) == state.selected_company_setting_id
            ),
            -1,
        )
        self.company_combo.setCurrentIndex(selected_index)
        self.company_combo.blockSignals(False)
        self.file_name_label.setText(state.selected_file.name if state.selected_file else "")
        self.recognition_label.setText(presentation.recognition_text)
        self.recognition_card.setVisible(state.selected_file is not None)
        self.output_label.setText(str(state.selected_output_file) if state.selected_output_file else "保存先はまだ選択されていません")
        self.status_title.setText(presentation.status_text)
        self.status_detail.setText(presentation.guidance)
        self.status_detail.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        badge, foreground, background = status_visual(presentation.status)
        self.status_badge.setText(badge)
        self.status_badge.setStyleSheet(
            f"color: {foreground}; background: {background}; border-radius: 10px; font-weight: 700;"
        )
        self.convert_button.setEnabled(presentation.conversion_enabled)
        self.settings_action.setVisible(presentation.settings_action_visible)
        self.copy_guidance_button.setVisible(
            state.selected_file is not None
            and presentation.status.value in {"CONFIRM", "BLOCKED"}
        )
        self.copy_diagnostics_button.setVisible(state.selected_file is not None)
        result = state.result_presentation
        self.result_card.setVisible(result is not None)
        if result is not None:
            balance = "一致" if result.debit_total == result.credit_total else "不一致"
            self.result_label.setText(
                "\n".join(
                    (
                        f"入力仕訳    {result.input_journal_count}件",
                        f"出力仕訳    {result.output_journal_count}件",
                        f"貸借合計    {balance}",
                        f"エラー      {result.error_count}件",
                        f"出力検証    {'成功' if result.output_validation_success else '未完了'}",
                        f"保存先      {result.output_path or '生成されていません'}",
                    )
                )
            )


class SettingsDialog(QDialog):
    def __init__(self, controller: AccountingConverterController, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.profile_ids = [item.profile_id for item in controller.state.profiles]
        self.setWindowTitle("設定")
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(16)
        title = QLabel("会社設定")
        title.setObjectName("title")
        layout.addWidget(title)

        company_row = QHBoxLayout()
        company_row.addWidget(QLabel("会社設定"))
        self.company_combo = QComboBox()
        for item in controller.state.companies:
            self.company_combo.addItem(
                f"{item.display_name}  /  {item.source_label} → JDL  /  {item.status_label}",
                item.company_setting_id,
            )
        company_row.addWidget(self.company_combo, 1)
        layout.addLayout(company_row)
        company_actions = QGridLayout()
        add_company = QPushButton("会社を追加")
        add_company.clicked.connect(self._add_company)
        rename_company = QPushButton("名前を変更")
        rename_company.clicked.connect(self._rename_company)
        delete_company = QPushButton("削除")
        delete_company.clicked.connect(self._delete_company)
        confirm_tax = QPushButton("対応内容を確認・変更")
        confirm_tax.clicked.connect(self._review_settings)
        refresh_master = QPushButton("JDL科目一覧を更新")
        refresh_master.clicked.connect(self._refresh_master)
        self.tax_context_button = QPushButton("JDL税設定を確認")
        self.tax_context_button.clicked.connect(self._confirm_tax_context)
        trade_partner_button = QPushButton("取引先情報の扱い")
        trade_partner_button.clicked.connect(self._confirm_trade_partner_policy)
        migration_review_button = QPushButton("JDL移行内容を確認")
        migration_review_button.clicked.connect(self._review_jdl_migration)
        refresh_master.setMinimumWidth(refresh_master.sizeHint().width() + 12)
        self.tax_context_button.setMinimumWidth(
            self.tax_context_button.sizeHint().width() + 12
        )
        company_actions.addWidget(add_company, 0, 0)
        company_actions.addWidget(rename_company, 0, 1)
        company_actions.addWidget(delete_company, 0, 2)
        company_actions.addWidget(confirm_tax, 1, 0)
        company_actions.addWidget(refresh_master, 1, 1)
        company_actions.addWidget(self.tax_context_button, 1, 2)
        company_actions.addWidget(trade_partner_button, 2, 0)
        company_actions.addWidget(migration_review_button, 2, 1)
        for column in range(3):
            company_actions.setColumnStretch(column, 1)
        layout.addLayout(company_actions)

        profile_row = QHBoxLayout()
        profile_label = QLabel("対応設定")
        profile_label.hide()
        profile_row.addWidget(profile_label)
        self.profile_combo = QComboBox()
        self.profile_combo.hide()
        self.profile_combo.addItems([item.profile_name for item in controller.state.profiles])
        if controller.state.selected_profile_id in self.profile_ids:
            self.profile_combo.setCurrentIndex(
                self.profile_ids.index(controller.state.selected_profile_id)
            )
        else:
            self.profile_combo.setCurrentIndex(-1)
        self.profile_combo.currentIndexChanged.connect(self._select_profile)
        profile_row.addWidget(self.profile_combo, 1)
        import_button = QPushButton("追加")
        import_button.hide()
        import_button.clicked.connect(self._import_profile)
        profile_row.addWidget(import_button)
        layout.addLayout(profile_row)

        context_row = QHBoxLayout()
        context_row.addWidget(QLabel("JDL科目一覧"))
        self.context_label = QLabel(
            "科目一覧設定済み"
            if controller.state.selected_context_file
            else "未設定"
        )
        context_row.addWidget(self.context_label, 1)
        context_button = QPushButton("選択")
        context_button.hide()
        context_button.clicked.connect(self._select_context)
        context_row.addWidget(context_button)
        layout.addLayout(context_row)
        self.environment_label = QLabel()
        self.environment_label.setWordWrap(True)
        layout.addWidget(self.environment_label)
        note = QLabel("科目構成が変わった場合は「JDL科目一覧を更新」を使用してください。")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.message_label = QLabel(controller.state.user_message)
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)
        close_button = QPushButton("閉じる")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)
        self.company_combo.currentIndexChanged.connect(self._company_changed)
        selected_index = self.company_combo.findData(
            controller.state.selected_company_setting_id
        )
        if selected_index >= 0:
            self.company_combo.setCurrentIndex(selected_index)
        self._refresh_selected_setting(controller.state)

    def _select_profile(self, index: int) -> None:
        profile_id = self.profile_ids[index] if 0 <= index < len(self.profile_ids) else None
        self.controller.select_profile(profile_id)
        self.message_label.setText(self.controller.state.user_message)

    def _import_profile(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "初期設定ファイルを追加", "", "JSON files (*.json)")
        if filename:
            state = self.controller.import_profile(Path(filename))
            self.profile_ids = [item.profile_id for item in state.profiles]
            self.profile_combo.blockSignals(True)
            self.profile_combo.clear()
            self.profile_combo.addItems([item.profile_name for item in state.profiles])
            if state.selected_profile_id in self.profile_ids:
                self.profile_combo.setCurrentIndex(self.profile_ids.index(state.selected_profile_id))
            self.profile_combo.blockSignals(False)
            self.message_label.setText(state.user_message)

    def _select_context(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "会社専用のJDL設定を選択", "", "JSON files (*.json)")
        if filename:
            state = self.controller.select_context_file(Path(filename))
            self.context_label.setText(
                "科目一覧設定済み" if state.selected_context_file else "未設定"
            )
            self.message_label.setText(state.user_message)

    def _add_company(self) -> None:
        dialog = CompanyAddDialog(self.controller, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._reload_companies(self.controller.state)

    def _company_changed(self, _index: int) -> None:
        company_id = self.company_combo.currentData()
        if not company_id:
            return
        state = self.controller.select_company_setting(company_id)
        self._refresh_selected_setting(state)

    def _rename_company(self) -> None:
        company_id = self.company_combo.currentData()
        if not company_id:
            return
        current = self.company_combo.currentText().split("  /  ", 1)[0]
        dialog = CompanyRenameDialog(current, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._reload_companies(
                self.controller.rename_company_setting(company_id, dialog.display_name)
            )

    def _delete_company(self) -> None:
        company_id = self.company_combo.currentData()
        if not company_id:
            return
        answer = QMessageBox.question(self, "会社設定を削除", "この会社設定を削除しますか。対応設定と元のJDL設定は削除されません。")
        if answer == QMessageBox.StandardButton.Yes:
            self._reload_companies(self.controller.delete_company_setting(company_id))

    def _confirm_tax(self) -> None:
        company_id = self.company_combo.currentData()
        if not company_id:
            self.message_label.setText("会社設定を選択してください。")
            return
        dialog = TaxMappingConfirmationDialog(self.controller, company_id, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._reload_companies(self.controller.state)

    def _confirm_tax_context(self) -> None:
        company_id = self.company_combo.currentData()
        if not company_id:
            self.message_label.setText("会社設定を選択してください。")
            return
        dialog = JdlTaxContextConfirmationDialog(self.controller, company_id, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._reload_companies(self.controller.state)

    def _confirm_trade_partner_policy(self) -> None:
        company_id = self.company_combo.currentData()
        if not company_id:
            self.message_label.setText("会社設定を選択してください。")
            return
        dialog = TradePartnerPolicyDialog(self.controller, company_id, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._reload_companies(self.controller.state)

    def _review_jdl_migration(self) -> None:
        company_id = self.company_combo.currentData()
        if not company_id:
            self.message_label.setText("会社設定を選択してください。")
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "JDL移行の確認ファイルを選択", "", "JSON files (*.json)"
        )
        if not filename:
            return
        try:
            review = self.controller.load_jdl_migration_review(
                company_id, Path(filename)
            )
        except Exception as exc:
            log_local_exception("jdl_migration_review_load", exc)
            QMessageBox.warning(
                self, "移行内容を確認できませんでした",
                "確認ファイルと会社設定を確認してください。",
            )
            return
        dialog = JdlMigrationHumanReviewDialog(self.controller, review, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._reload_companies(self.controller.state)

    def _review_settings(self) -> None:
        company_id = self.company_combo.currentData()
        if not company_id:
            self.message_label.setText("会社設定を選択してください。")
            return
        try:
            review = self.controller.review_saved_company_mappings(company_id)
            tax_review = self.controller.company_tax_mapping_review(company_id)
        except Exception as exc:
            log_local_exception("company_mapping_update_review", exc)
            self.message_label.setText("現在の対応内容を確認できませんでした。")
            return
        dialog = CompanyMappingUpdateDialog(
            self.controller, review, self, tax_message=(
                "税設定の確認が必要です。CSV読込時に確認できます。"
                if not tax_review.context_compatible
                else tax_review.user_message
                if not tax_review.items
                else f"未確認の税区分が{len(tax_review.items)}件あります。"
            )
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._reload_companies(self.controller.state)
        if tax_review.items:
            self._confirm_tax()

    def _refresh_master(self) -> None:
        company_id = self.company_combo.currentData()
        if not company_id:
            self.message_label.setText("会社設定を選択してください。")
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "新しいJDL科目一覧PDFを選択", "", "PDF files (*.pdf)"
        )
        if not filename:
            return
        try:
            plan = self.controller.plan_company_master_refresh(
                company_id, Path(filename)
            )
        except Exception as exc:
            log_local_exception("jdl_account_master_refresh_plan", exc)
            self.message_label.setText("JDL科目一覧を確認できませんでした。")
            return
        dialog = CompanyMasterRefreshDialog(self.controller, plan, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._reload_companies(self.controller.state)

    def _review_new_accounts(self) -> None:
        company_id = self.company_combo.currentData()
        if not company_id:
            self.message_label.setText("会社設定を選択してください。")
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "Money Forwardの仕訳CSVを選択", "", "CSV files (*.csv)"
        )
        if not filename:
            return
        try:
            review = self.controller.review_company_mapping_updates(
                company_id, Path(filename)
            )
        except Exception as exc:
            log_local_exception("company_mapping_update_review", exc)
            self.message_label.setText("CSVと現在の会社設定を確認できませんでした。")
            return
        if not review.items:
            self.message_label.setText("追加確認が必要な科目はありません。")
            return
        dialog = CompanyMappingUpdateDialog(self.controller, review, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._reload_companies(self.controller.state)

    def _reload_companies(self, state: AppState) -> None:
        self.profile_ids = [item.profile_id for item in state.profiles]
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItems([item.profile_name for item in state.profiles])
        self.profile_combo.blockSignals(False)
        self.company_combo.blockSignals(True)
        self.company_combo.clear()
        for item in state.companies:
            self.company_combo.addItem(
                f"{item.display_name}  /  {item.source_label} → JDL  /  {item.status_label}",
                item.company_setting_id,
            )
        selected_index = self.company_combo.findData(state.selected_company_setting_id)
        self.company_combo.setCurrentIndex(selected_index)
        self.company_combo.blockSignals(False)
        self._refresh_selected_setting(state)

    def _refresh_selected_setting(self, state: AppState) -> None:
        company_id = state.selected_company_setting_id
        self.context_label.setText(
            "JDL IBEX 出納帳 35.5 / 科目一覧設定済み"
            if state.selected_context_file
            else "未設定"
        )
        self.environment_label.setText(
            "\n".join(
                (
                    f"JDL環境: {state.jdl_environment_label}",
                    f"科目一覧: {state.jdl_master_state}",
                    f"最終更新日: {state.jdl_master_updated_at or '未確認'}",
                )
            )
        )
        pending_tax_context = bool(
            company_id
            and self.controller.company_tax_context_pending(company_id)
        )
        self.tax_context_button.setVisible(pending_tax_context)
        if state.selected_profile_id in self.profile_ids:
            self.profile_combo.blockSignals(True)
            self.profile_combo.setCurrentIndex(
                self.profile_ids.index(state.selected_profile_id)
            )
            self.profile_combo.blockSignals(False)
        self.message_label.setText(
            self.controller.company_setting_status_reason(company_id)
            if company_id
            else state.user_message
        )


class JdlMigrationHumanReviewDialog(QDialog):
    def __init__(self, controller, review, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.review = review
        self.account_controls = {}
        self.subaccount_controls = {}
        self.setWindowTitle("JDL移行内容を確認")
        self.resize(920, 680)
        self.setMinimumSize(700, 480)
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("JDL移行内容を確認"))
        guidance = QLabel(
            "候補は自動確定されません。選択した項目だけを確認済みとして保存します。"
        )
        guidance.setWordWrap(True)
        outer.addWidget(guidance)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)

        layout.addWidget(QLabel(f"科目の確認（{len(review.accounts)}件）"))
        account_table = QTableWidget(len(review.accounts), 6)
        account_table.setHorizontalHeaderLabels(
            ("入力元コード", "入力元科目", "差異", "影響", "JDLの科目", "確認")
        )
        account_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        for row, item in enumerate(review.accounts):
            account_table.setItem(row, 0, QTableWidgetItem(item.source_code))
            account_table.setItem(row, 1, QTableWidgetItem(item.source_name))
            account_table.setItem(row, 2, QTableWidgetItem(item.classification))
            account_table.setItem(row, 3, QTableWidgetItem(
                f"{item.affected_journal_count}仕訳"
            ))
            combo = WheelSafeComboBox()
            combo.addItem("未選択", None)
            for code, name in item.targets:
                combo.addItem(f"{code} {name}", (code, name))
            if not item.targets and item.disabled_name_match:
                combo.setToolTip(
                    "同名科目はJDL側で使用不可です。使用可能にして科目一覧PDFを再出力してください。"
                )
            confirmed = QCheckBox("確認しました")
            confirmed.setEnabled(False)
            combo.currentIndexChanged.connect(
                lambda _index, box=combo, check=confirmed: (
                    check.setChecked(False),
                    check.setEnabled(box.currentData() is not None),
                )
            )
            account_table.setCellWidget(row, 4, combo)
            account_table.setCellWidget(row, 5, confirmed)
            self.account_controls[item.key] = (combo, confirmed)
        account_table.resizeRowsToContents()
        account_table.setMinimumHeight(min(260, 62 + len(review.accounts) * 38))
        layout.addWidget(account_table)

        layout.addWidget(QLabel(f"補助科目の確認（{len(review.subaccounts)}件）"))
        sub_table = QTableWidget(len(review.subaccounts), 4)
        sub_table.setHorizontalHeaderLabels(("親科目", "入力元補助", "処理方法", "確認"))
        sub_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for row, item in enumerate(review.subaccounts):
            sub_table.setItem(row, 0, QTableWidgetItem(
                f"{item.parent_code} {item.parent_name}"
            ))
            sub_table.setItem(row, 1, QTableWidgetItem(
                f"{item.source_code} {item.source_name}（{item.affected_journal_count}仕訳）"
            ))
            combo = WheelSafeComboBox()
            combo.addItem("未選択", None)
            for code, name in item.targets:
                combo.addItem(f"JDL補助科目へ対応: {code} {name}", (code, name))
            combo.addItem(
                "親科目のみで変換する",
                SubaccountPolicy.PARENT_ONLY_CONFIRMED.value,
            )
            if not item.targets:
                combo.setToolTip(
                    "補助を保持するにはJDL側で補助科目を作成し、科目一覧を更新してください。"
                )
            confirmed = QCheckBox("確認しました")
            confirmed.setEnabled(False)
            combo.currentIndexChanged.connect(
                lambda _index, box=combo, check=confirmed: (
                    check.setChecked(False),
                    check.setEnabled(box.currentData() is not None),
                )
            )
            sub_table.setCellWidget(row, 2, combo)
            sub_table.setCellWidget(row, 3, confirmed)
            self.subaccount_controls[item.key] = (combo, confirmed)
        sub_table.resizeRowsToContents()
        sub_table.setMinimumHeight(min(230, 62 + len(review.subaccounts) * 38))
        layout.addWidget(sub_table)

        layout.addWidget(QLabel("税設定"))
        tax_context = QLabel(
            "JDL Version / 課税事業者・免税 / 税込・税抜 / 課税方式 / 対応方式を"
            "既存の「JDL税設定を確認」から確認してください。"
        )
        tax_context.setWordWrap(True)
        layout.addWidget(tax_context)
        for item in review.taxes:
            label = QLabel(
                f"{item.label or '税identity'}: {item.row_count}行 / "
                f"{item.evidence_status} / 実機確認が不足しているためBLOCK中"
            )
            label.setWordWrap(True)
            layout.addWidget(label)

        layout.addWidget(QLabel("摘要の確認"))
        for item in review.descriptions:
            length_text = (
                f"{item.current_length}文字"
                if item.current_length
                else "文字数詳細なし"
            )
            layout.addWidget(QLabel(
                f"{item.journal_identifier}: {length_text} / "
                "32文字を超えるためBLOCKのままです。"
            ))
        description_note = QLabel(
            "切り捨ては行いません。将来、Human確認済みの置換policyが必要です。"
        )
        description_note.setWordWrap(True)
        layout.addWidget(description_note)
        layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        self.status_label = QLabel(
            "未確認または実機Evidence不足の項目がある間は変換できません。"
        )
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)
        actions = QHBoxLayout()
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        save = QPushButton("確認結果を保存")
        save.setObjectName("primaryButton")
        save.clicked.connect(self._save)
        actions.addStretch(1)
        actions.addWidget(cancel)
        actions.addWidget(save)
        outer.addLayout(actions)

    def _save(self) -> None:
        account_selections = {
            key: combo.currentData()
            for key, (combo, _check) in self.account_controls.items()
            if combo.currentData() is not None
        }
        account_confirmed = {
            key for key, (_combo, check) in self.account_controls.items()
            if check.isChecked()
        }
        subaccount_selections = {
            key: combo.currentData()
            for key, (combo, _check) in self.subaccount_controls.items()
            if combo.currentData() is not None
        }
        subaccount_confirmed = {
            key for key, (_combo, check) in self.subaccount_controls.items()
            if check.isChecked()
        }
        try:
            self.controller.save_jdl_migration_review(
                self.review, account_selections, account_confirmed,
                subaccount_selections, subaccount_confirmed,
            )
        except Exception as exc:
            log_local_exception("jdl_migration_review_save", exc)
            self.status_label.setText("確認結果を保存できませんでした。設定を確認してください。")
            QMessageBox.warning(
                self, "確認結果を保存できませんでした",
                "選択内容と会社設定を確認してください。",
            )
            return
        self.accept()


class TradePartnerPolicyDialog(QDialog):
    def __init__(self, controller, company_id: str, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.company_id = company_id
        self.setWindowTitle("取引先情報の扱い")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        title = QLabel("Money Forwardの取引先情報")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        explanation = QLabel(
            "JDLには取引先専用のCSV項目がないため、この会社では取引先名を"
            "摘要へ追加して記録します。摘要が32文字を超える場合やJDLで表現"
            "できない文字がある場合は、情報を省略せず変換を停止します。"
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        state = controller.company_trade_partner_policy_state(company_id)
        self.confirmed = QCheckBox(
            "この会社では取引先を摘要へ追加して変換する"
        )
        self.confirmed.setChecked(state.confirmed)
        self.confirmed.setEnabled(state.context_compatible and not state.confirmed)
        layout.addWidget(self.confirmed)
        self.message = QLabel(
            "設定済みです。"
            if state.confirmed
            else "JDL設定の確認後に明示的な確認が必要です。"
            if not state.context_compatible
            else "自動では有効になりません。内容を確認してください。"
        )
        self.message.setObjectName("muted")
        layout.addWidget(self.message)
        actions = QHBoxLayout()
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        self.save_button = QPushButton("保存")
        self.save_button.setObjectName("primaryButton")
        self.save_button.setEnabled(
            state.context_compatible and not state.confirmed and self.confirmed.isChecked()
        )
        self.confirmed.toggled.connect(
            lambda checked: self.save_button.setEnabled(
                state.context_compatible and not state.confirmed and checked
            )
        )
        self.save_button.clicked.connect(self._save)
        actions.addStretch(1)
        actions.addWidget(cancel)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)

    def _save(self) -> None:
        state = self.controller.confirm_company_trade_partner_policy(
            self.company_id, explicitly_confirmed=self.confirmed.isChecked()
        )
        if state.developer_error is not None:
            self.message.setText("保存できませんでした。JDL設定を確認してください。")
            return
        self.accept()


class CompanyMasterRefreshDialog(QDialog):
    def __init__(self, controller, plan, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.plan = plan
        self.controls: list[tuple[str, QComboBox, QCheckBox]] = []
        self.setWindowTitle("JDL科目一覧を更新")
        self.resize(860, 620)
        self.setMinimumSize(720, 500)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("JDL科目一覧の変更を確認"))
        note = QLabel(
            "同じコードと名称の科目対応は保持します。"
            "変更または削除された対応だけ再確認してください。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(("入力元の科目", "JDLの科目", "確認"))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        stale = tuple(item for item in plan.items if not item.preserved)
        self.table.setRowCount(len(stale))
        for row, item in enumerate(stale):
            self.table.setItem(row, 0, QTableWidgetItem(item.source_value))
            target = WheelSafeComboBox()
            target.addItem("未選択", None)
            for value in item.available_targets:
                target.addItem(value, value)
            confirmed = QCheckBox("確認しました")
            confirmed.setEnabled(False)
            target.currentIndexChanged.connect(
                lambda _index, combo=target, checkbox=confirmed: (
                    checkbox.setChecked(False),
                    checkbox.setEnabled(combo.currentData() is not None),
                    self._update_action(),
                )
            )
            confirmed.stateChanged.connect(self._update_action)
            self.table.setCellWidget(row, 1, target)
            self.table.setCellWidget(row, 2, confirmed)
            self.controls.append((item.source_value, target, confirmed))
        layout.addWidget(self.table, 1)
        self.status_label = QLabel(
            f"保持: {len(plan.items) - len(stale)}件 / 再確認: {len(stale)}件"
        )
        layout.addWidget(self.status_label)
        actions = QHBoxLayout()
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        self.apply_button = QPushButton("更新を保存")
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.clicked.connect(self._apply)
        actions.addStretch(1)
        actions.addWidget(cancel)
        actions.addWidget(self.apply_button)
        layout.addLayout(actions)
        self._update_action()

    def _update_action(self, *_args) -> None:
        self.apply_button.setEnabled(
            all(
                combo.currentData() is not None and checkbox.isChecked()
                for _, combo, checkbox in self.controls
            )
        )

    def _apply(self) -> None:
        selections = {
            source: str(combo.currentData())
            for source, combo, _ in self.controls
            if combo.currentData() is not None
        }
        confirmed = {
            source for source, _, checkbox in self.controls if checkbox.isChecked()
        }
        try:
            self.controller.apply_company_master_refresh(
                self.plan, selections, confirmed
            )
        except Exception as exc:
            log_local_exception("jdl_account_master_refresh_apply", exc)
            message = (
                "既存の科目対応が新しい科目一覧と一致しません。"
                "科目対応を確認してください。"
                if isinstance(exc, ValueError)
                else "科目一覧を保存できませんでした。保存先を確認してください。"
            )
            self.status_label.setText(message)
            QMessageBox.warning(self, "更新を保存できませんでした", message)
            return
        self.accept()


class CompanyMappingUpdateDialog(QDialog):
    def __init__(
        self, controller, review, parent=None, *, tax_message: str = ""
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.review = review
        self.controls: list[tuple[str, QComboBox, QCheckBox]] = []
        self.account_controls: dict[str, tuple[QComboBox, QCheckBox]] = {}
        self.subaccount_controls: list[tuple[object, QComboBox, QCheckBox]] = []
        self.setWindowTitle("新しい科目を確認")
        self.resize(980, 680)
        self.setMinimumSize(760, 520)
        layout = QVBoxLayout(self)
        note = QLabel(
            "保存済みの対応は再利用し、新規または再確認が必要な項目だけ表示しています。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        if any(item.parent_only_available for item in review.items):
            policy_note = QLabel(
                "「親科目のみで変換する」を選ぶと、MF側の補助科目情報は"
                "JDLへ引き継がれません。この会社では親科目のみで変換します。"
            )
            policy_note.setObjectName("warningCard")
            policy_note.setWordWrap(True)
            layout.addWidget(policy_note)
        table = QTableWidget(len(review.items), 5)
        table.setHorizontalHeaderLabels(("種類", "親科目", "入力元", "JDLの科目", "確認"))
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        for row, item in enumerate(review.items):
            kind_label = {
                "SUBACCOUNT": "補助科目",
                "DEFAULT_SUBACCOUNT": "補助なし時",
            }.get(item.mapping_type, "科目")
            table.setItem(row, 0, QTableWidgetItem(kind_label))
            table.setItem(row, 1, QTableWidgetItem(item.parent_account or ""))
            table.setItem(row, 2, QTableWidgetItem(item.source_value))
            target = WheelSafeComboBox()
            target.addItem("未選択", None)
            for value in item.available_targets:
                target.addItem(
                    f"JDL補助科目へ対応: {value}"
                    if item.mapping_type in {"SUBACCOUNT", "DEFAULT_SUBACCOUNT"}
                    else value,
                    value,
                )
            if item.mapping_type == "SUBACCOUNT" and item.parent_only_available:
                target.addItem("親科目のみで変換する", PARENT_ONLY_SELECTION)
            if item.exact_candidate in item.available_targets:
                target.setCurrentIndex(item.available_targets.index(item.exact_candidate) + 1)
            elif item.exact_candidate == PARENT_ONLY_SELECTION:
                target.setCurrentIndex(target.findData(PARENT_ONLY_SELECTION))
            confirmed = QCheckBox("確認しました")
            confirmed.setEnabled(target.currentData() is not None)
            target.currentIndexChanged.connect(
                lambda _index, combo=target, checkbox=confirmed: (
                    checkbox.setChecked(False), checkbox.setEnabled(combo.currentData() is not None), self._update_action()
                )
            )
            confirmed.stateChanged.connect(self._update_action)
            table.setCellWidget(row, 3, target)
            table.setCellWidget(row, 4, confirmed)
            self.controls.append((item.key, target, confirmed))
            if item.mapping_type == "ACCOUNT":
                self.account_controls[item.source_value] = (target, confirmed)
                target.currentIndexChanged.connect(
                    lambda _index, source=item.source_value: self._refresh_subaccounts(
                        source
                    )
                )
                confirmed.stateChanged.connect(
                    lambda _state, source=item.source_value: self._refresh_subaccounts(
                        source
                    )
                )
            else:
                self.subaccount_controls.append((item, target, confirmed))
        layout.addWidget(table, 1)
        tax_status = QLabel(
            tax_message or "税区分はCSV読込時に必要なものだけ確認します。"
        )
        tax_status.setObjectName("warningCard" if tax_message else "muted")
        tax_status.setWordWrap(True)
        layout.addWidget(tax_status)
        actions = QHBoxLayout()
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        self.save_button = QPushButton("追加対応を保存")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save)
        actions.addStretch(1)
        actions.addWidget(cancel)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)
        for source_value in self.account_controls:
            self._refresh_subaccounts(source_value)
        self._update_action()

    def _refresh_subaccounts(self, source_account: str) -> None:
        account_control = self.account_controls.get(source_account)
        if account_control is None:
            return
        account_combo, account_confirmed = account_control
        parent_target = account_combo.currentData()
        parent_is_confirmed = bool(
            parent_target is not None and account_confirmed.isChecked()
        )
        for item, combo, checkbox in self.subaccount_controls:
            if item.parent_account != source_account:
                continue
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("未選択", None)
            if parent_is_confirmed:
                targets = item.subaccount_targets_for(str(parent_target))
                for value in targets:
                    combo.addItem(f"JDL補助科目へ対応: {value}", value)
                if (
                    item.mapping_type == "SUBACCOUNT"
                    and item.has_parent_target(str(parent_target))
                    and not targets
                ):
                    combo.addItem(
                        "親科目のみで変換する", PARENT_ONLY_SELECTION
                    )
            restore_saved_selection = (
                parent_is_confirmed
                and str(parent_target) == item.confirmed_parent_target
            )
            if restore_saved_selection and item.exact_candidate in targets:
                combo.setCurrentIndex(combo.findData(item.exact_candidate))
            elif (
                restore_saved_selection
                and item.exact_candidate == PARENT_ONLY_SELECTION
            ):
                combo.setCurrentIndex(combo.findData(PARENT_ONLY_SELECTION))
            else:
                combo.setCurrentIndex(0)
            combo.blockSignals(False)
            checkbox.setChecked(False)
            checkbox.setEnabled(combo.currentData() is not None)
        self._update_action()

    def _update_action(self, *_args) -> None:
        self.save_button.setEnabled(
            bool(self.controls)
            and all(
                combo.currentData() is not None and check.isChecked()
                for _, combo, check in self.controls
            )
        )

    def _save(self) -> None:
        selections = {key: str(combo.currentData()) for key, combo, _ in self.controls if combo.currentData() is not None}
        confirmed = {key for key, _, check in self.controls if check.isChecked()}
        try:
            self.controller.apply_company_mapping_updates(self.review, selections, confirmed)
        except Exception as exc:
            log_local_exception("company_mapping_update_apply", exc)
            return
        self.accept()


class CompanyAddDialog(QDialog):
    """Small, explicit four-step flow using the shared Qt light theme."""

    def __init__(self, controller: AccountingConverterController, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.context_path: Path | None = None
        self.profile_ids: list[str] = []
        self.initial_company_ids = {
            item.company_setting_id for item in controller.state.companies
        }
        self.setWindowTitle("会社を追加")
        self.setMinimumSize(640, 430)

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 26)
        root.setSpacing(18)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._name_page())
        self.pages.addWidget(self._source_page())
        self.pages.addWidget(self._settings_page())
        self.pages.addWidget(self._confirmation_page())
        root.addWidget(self.pages, 1)

        self.error_label = QLabel("")
        self.error_label.setObjectName("muted")
        self.error_label.setWordWrap(True)
        root.addWidget(self.error_label)

        actions = QHBoxLayout()
        self.back_button = QPushButton("戻る")
        self.back_button.clicked.connect(self._back)
        cancel_button = QPushButton("キャンセル")
        cancel_button.clicked.connect(self.reject)
        self.next_button = QPushButton("次へ")
        self.next_button.setObjectName("primaryButton")
        self.next_button.clicked.connect(self._next)
        actions.addWidget(self.back_button)
        actions.addStretch(1)
        actions.addWidget(cancel_button)
        actions.addWidget(self.next_button)
        root.addLayout(actions)
        self._update_actions()

    def _page(self, title_text: str, description: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        title = QLabel(title_text)
        title.setObjectName("sectionTitle")
        explanation = QLabel(description)
        explanation.setObjectName("muted")
        explanation.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(explanation)
        return page, layout

    def _name_page(self) -> QWidget:
        page, layout = self._page(
            "会社名を設定",
            "会社設定名を入力してください。\nこの名前はアプリ内で会社を識別するために使います。",
        )
        layout.addWidget(QLabel("会社設定名"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例: サンプル株式会社")
        layout.addWidget(self.name_edit)
        layout.addStretch(1)
        return page

    def _source_page(self) -> QWidget:
        page, layout = self._page(
            "入力元を選択",
            "この会社で使用している会計ソフトを選択してください。",
        )
        layout.addWidget(QLabel("入力元"))
        self.source_combo = QComboBox()
        self.source_combo.addItems(("Money Forward", "弥生"))
        layout.addWidget(self.source_combo)
        layout.addStretch(1)
        return page

    def _settings_page(self) -> QWidget:
        page, layout = self._page(
            "JDL科目一覧を設定",
            "この会社のJDLから印刷した科目一覧PDFを読み込んでください。",
        )
        self.profile_label = QLabel("対応設定")
        layout.addWidget(self.profile_label)
        self.profile_combo = QComboBox()
        layout.addWidget(self.profile_combo)
        self.no_profile_message = QLabel(
            "この入力元の対応設定がまだありません。\n"
            "Money Forwardの仕訳CSVから対応設定を作成します。\n"
            "JDL設定を読み込み、必要な科目対応を確認して新しい対応設定を作成できます。"
        )
        self.no_profile_message.setObjectName("muted")
        self.no_profile_message.setWordWrap(True)
        self.no_profile_message.hide()
        layout.addWidget(self.no_profile_message)
        self.create_profile_button = QPushButton("対応設定を作成")
        self.create_profile_button.clicked.connect(self._create_moneyforward_profile)
        self.create_profile_button.hide()
        layout.addWidget(self.create_profile_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(QLabel("JDLの科目設定"))
        context_row = QHBoxLayout()
        self.context_label = QLabel("ファイルはまだ選択されていません")
        self.context_label.setObjectName("muted")
        self.context_button = QPushButton("JDLから読み込む")
        self.context_button.clicked.connect(self._choose_context)
        context_row.addWidget(self.context_label, 1)
        context_row.addWidget(self.context_button)
        layout.addLayout(context_row)
        layout.addStretch(1)
        return page

    def _confirmation_page(self) -> QWidget:
        page, layout = self._page(
            "会社設定を確認",
            "内容を確認して保存してください。",
        )
        self.confirmation_label = QLabel()
        self.confirmation_label.setWordWrap(True)
        layout.addWidget(self.confirmation_label)
        layout.addStretch(1)
        return page

    def _choose_context(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "JDLの科目一覧PDFを選択", "", "PDF files (*.pdf)"
        )
        if filename:
            try:
                self.context_path = self.controller.import_jdl_account_pdf(
                    Path(filename)
                )
            except Exception as exc:
                log_local_exception("jdl_account_pdf_import", exc)
                self.context_path = None
                self.context_label.setText("読み込めませんでした")
                self.error_label.setText(
                    "JDLの科目一覧PDFを確認してください。"
                )
                return
            self.context_label.setText("科目一覧を読み込みました")
            self.error_label.setText(
                "科目対応を保存できます。JDL設定の確認が完了するまで変換はできません。"
            )

    def _back(self) -> None:
        if self.pages.currentIndex() > 0:
            self.pages.setCurrentIndex(self.pages.currentIndex() - 1)
            self.error_label.clear()
            self._update_actions()

    def _next(self) -> None:
        index = self.pages.currentIndex()
        self.error_label.clear()
        if index == 0 and not self.name_edit.text().strip():
            self.error_label.setText("会社設定名を入力してください。")
            return
        if index == 1:
            if self.source_combo.currentText() == "Money Forward":
                self.profile_ids = []
                self.profile_combo.clear()
                self.profile_combo.hide()
                self.profile_label.hide()
                self.no_profile_message.hide()
                self.create_profile_button.hide()
                self.pages.setCurrentIndex(index + 1)
                self._update_actions()
                return
            candidates = list(self.controller.profiles_for_source(self.source_combo.currentText()))
            if not candidates:
                if self.source_combo.currentText() != "Money Forward":
                    self.error_label.setText("選択した入力元で利用できる対応設定がありません。")
                    return
                self.profile_ids = []
                self.profile_combo.clear()
                self.profile_combo.hide()
                self.profile_label.hide()
                self.no_profile_message.show()
                self.create_profile_button.show()
            else:
                self.profile_combo.show()
                self.profile_label.show()
                self.no_profile_message.hide()
                self.profile_ids = [item.profile_id for item in candidates]
                self.profile_combo.clear()
                self.profile_combo.addItems([item.profile_name for item in candidates])
                self.create_profile_button.setVisible(
                    self.source_combo.currentText() == "Money Forward"
                )
                self.create_profile_button.setText("新しい対応設定を作成")
        if index == 2:
            if (
                self.source_combo.currentText() != "Money Forward"
                and self.profile_combo.currentIndex() < 0
            ):
                self.error_label.setText("対応設定を選択してください。")
                return
            if self.context_path is None:
                self.error_label.setText("JDLの科目一覧を読み込んでください。")
                return
            self._render_confirmation()
        if index == 3:
            self._save()
            return
        self.pages.setCurrentIndex(index + 1)
        self._update_actions()

    def _create_moneyforward_profile(self) -> None:
        dialog = MoneyForwardProfileSetupDialog(
            self.controller, self.name_edit.text().strip(), self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.profile_ids = [dialog.profile_id]
        self.profile_combo.clear()
        self.profile_combo.addItem(dialog.profile_name)
        self.profile_combo.show()
        self.profile_label.show()
        self.no_profile_message.hide()
        self.create_profile_button.hide()
        self.context_path = dialog.context_path
        self.context_label.setText(dialog.context_display)
        self.context_button.setEnabled(False)
        self.context_button.setToolTip(
            "対応設定の確認に使用したJDL設定が引き継がれています。"
        )
        self.error_label.setText("対応設定を保存しました。次へ進んでください。")

    def _render_confirmation(self) -> None:
        setup_summary = (
            "CSV読込後に必要な対応だけ確認します"
            if self.source_combo.currentText() == "Money Forward"
            else self.profile_combo.currentText()
        )
        self.confirmation_label.setText(
            "\n".join(
                (
                    f"会社設定名    {self.name_edit.text().strip()}",
                    f"入力元        {self.source_combo.currentText()}",
                    f"対応内容      {setup_summary}",
                    "JDL設定       JDL IBEX 出納帳 35.5 / 設定済み"
                    if self.context_path
                    else "JDL設定       未選択",
                    "状態           保存時に安全確認します",
                )
            )
        )

    def _save(self) -> None:
        assert self.context_path is not None
        if self.source_combo.currentText() == "Money Forward" and not self.profile_ids:
            try:
                profile = self.controller.create_moneyforward_company_draft_profile(
                    self.name_edit.text().strip(), self.context_path
                )
            except Exception:
                self.error_label.setText("会社設定を作成できませんでした。科目一覧を確認してください。")
                return
            self.profile_ids = [profile.profile_id]
            profile_id = profile.profile_id
        else:
            profile_id = self.profile_ids[self.profile_combo.currentIndex()]
        state = self.controller.add_company_setting(
            display_name=self.name_edit.text().strip(),
            source_label=self.source_combo.currentText(),
            conversion_profile_id=profile_id,
            context_source=self.context_path,
        )
        if (
            state.selected_company_setting_id is None
            or state.selected_company_setting_id in self.initial_company_ids
        ):
            self.error_label.setText(state.user_message)
            return
        self.accept()

    def _update_actions(self) -> None:
        index = self.pages.currentIndex()
        self.back_button.setVisible(index > 0)
        self.next_button.setText("保存" if index == self.pages.count() - 1 else "次へ")


class MoneyForwardProfileSetupDialog(QDialog):
    def __init__(
        self,
        controller: AccountingConverterController,
        company_display_name: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.company_display_name = company_display_name
        self.source_path: Path | None = None
        self.context_path: Path | None = None
        self.analysis = None
        self.profile_id = ""
        self.profile_name = ""
        self.context_display = "未選択"
        self.row_controls: list[tuple[str, QComboBox, QCheckBox]] = []
        self.setWindowTitle("Money Forwardの対応設定を作成")
        self.resize(1080, 700)
        self.setMinimumSize(820, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(10)
        title = QLabel("Money Forwardの対応設定を作成")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "Money Forwardの仕訳CSVとJDL設定を読み込み、必要な科目対応を確認します。\n"
            "完全一致する科目も、自動確定せず確認が必要です。"
        )
        description.setObjectName("muted")
        description.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(description)

        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Money Forwardの仕訳CSV"))
        self.source_label = QLabel("未選択")
        self.source_label.setObjectName("muted")
        source_button = QPushButton("CSVを選択")
        source_button.clicked.connect(self._choose_source)
        source_row.addWidget(self.source_label, 1)
        source_row.addWidget(source_button)
        layout.addLayout(source_row)

        context_row = QHBoxLayout()
        context_row.addWidget(QLabel("JDLの科目設定"))
        self.context_label = QLabel("未選択")
        self.context_label.setObjectName("muted")
        context_button = QPushButton("JDLから読み込む")
        context_button.clicked.connect(self._choose_context)
        context_row.addWidget(self.context_label, 1)
        context_row.addWidget(context_button)
        layout.addLayout(context_row)

        analyze_button = QPushButton("科目を確認")
        analyze_button.clicked.connect(self._analyze)
        layout.addWidget(analyze_button, alignment=Qt.AlignmentFlag.AlignLeft)

        guidance = QLabel(
            "Money Forwardの各科目に対応するJDL科目を確認してください。\n"
            "同じ名称の科目は候補として表示しています。内容を確認して「確認しました」を選択してください。"
        )
        guidance.setObjectName("muted")
        guidance.setWordWrap(True)
        layout.addWidget(guidance)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            ("Money Forwardの科目", "JDLの科目", "確認")
        )
        self.table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.table.setMinimumHeight(260)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setMinimumSectionSize(150)
        self.table.setColumnWidth(2, 168)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.verticalHeader().setMinimumSectionSize(40)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.verticalHeader().hide()
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setAlternatingRowColors(True)

        self.tax_card = QFrame()
        self.tax_card.setObjectName("card")
        tax_layout = QVBoxLayout(self.tax_card)
        tax_layout.setContentsMargins(18, 16, 18, 16)
        tax_title = QLabel("税区分を確認")
        tax_title.setObjectName("sectionTitle")
        tax_layout.addWidget(tax_title)
        self.tax_source_label = QLabel("Money Forward: 課税仕入 10%")
        self.tax_target_label = QLabel("JDL: 仕入 / 10%")
        self.tax_status_label = QLabel("状態: 確認してください")
        self.tax_confirmed = QCheckBox("確認しました")
        self.tax_confirmed.stateChanged.connect(
            lambda: self.tax_status_label.setText(
                "状態: 確認済み"
                if self.tax_confirmed.isChecked()
                else "状態: 確認してください"
            )
        )
        tax_layout.addWidget(self.tax_source_label)
        tax_layout.addWidget(self.tax_target_label)
        tax_layout.addWidget(self.tax_status_label)
        tax_layout.addWidget(self.tax_confirmed)
        self.tax_card.hide()

        self.progress_label = QLabel("0 / 0 件確認済み")
        self.progress_label.setObjectName("muted")

        self.message_label = QLabel("")
        self.message_label.setObjectName("muted")
        self.message_label.setWordWrap(True)

        mapping_area = QHBoxLayout()
        mapping_area.setSpacing(16)
        mapping_area.addWidget(self.table, 1)
        mapping_sidebar = QWidget()
        mapping_sidebar.setMinimumWidth(260)
        mapping_sidebar.setMaximumWidth(320)
        mapping_sidebar.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        sidebar_layout = QVBoxLayout(mapping_sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(12)
        sidebar_layout.addWidget(self.tax_card)
        sidebar_layout.addWidget(self.progress_label)
        sidebar_layout.addWidget(self.message_label)
        sidebar_layout.addStretch(1)
        mapping_area.addWidget(mapping_sidebar)
        layout.addLayout(mapping_area, 1)
        layout.setStretchFactor(mapping_area, 1)

        actions = QHBoxLayout()
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        self.save_button = QPushButton("対応設定を保存")
        self.save_button.setObjectName("primaryButton")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save)
        actions.addStretch(1)
        actions.addWidget(cancel)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)

    def _choose_source(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Money Forwardの仕訳CSVを選択", "", "CSV files (*.csv)"
        )
        if filename:
            self.source_path = Path(filename)
            self.source_label.setText(self.source_path.name)
            self._clear_analysis()

    def _choose_context(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "JDLの科目一覧PDFを選択", "", "PDF files (*.pdf)"
        )
        if filename:
            try:
                self.context_path = self.controller.import_jdl_account_pdf(
                    Path(filename)
                )
            except Exception as exc:
                log_local_exception("jdl_account_pdf_import", exc)
                self.context_path = None
                self.context_label.setText("読み込めませんでした")
                self.message_label.setText(
                    "JDLの科目一覧PDFを確認してください。"
                )
                return
            self.context_label.setText("科目一覧を読み込みました")
            self._clear_analysis()

    def _clear_analysis(self) -> None:
        self.analysis = None
        self.row_controls.clear()
        self.table.setRowCount(0)
        self.save_button.setEnabled(False)
        self.progress_label.setText("0 / 0 件確認済み")
        self.message_label.clear()
        self.tax_confirmed.setChecked(False)
        self.tax_card.hide()

    def _analyze(self) -> None:
        if self.source_path is None:
            self.message_label.setText("Money Forwardの仕訳CSVを選択してください。")
            return
        if self.context_path is None:
            self.message_label.setText("JDLの科目一覧を読み込んでください。")
            return
        try:
            analysis = self.controller.analyze_moneyforward_profile_setup(
                self.source_path, self.context_path
            )
        except Exception:
            self._clear_analysis()
            self.message_label.setText(
                "CSVまたはJDL設定を確認できませんでした。対応するファイルを選択してください。"
            )
            return
        self.analysis = analysis
        self.table.setRowCount(0)
        self.row_controls.clear()
        for row_index, item in enumerate(analysis.account_items):
            self.table.insertRow(row_index)
            self.table.setRowHeight(row_index, 40)
            source_item = QTableWidgetItem(item.source_value)
            source_item.setToolTip(item.source_value)
            self.table.setItem(row_index, 0, source_item)
            target = WheelSafeComboBox()
            target.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            target.setMinimumHeight(34)
            target.addItem("未選択", None)
            for available_target in item.available_targets:
                target.addItem(available_target, available_target)
            if item.exact_candidate in item.available_targets:
                target.setCurrentIndex(
                    item.available_targets.index(item.exact_candidate) + 1
                )
            else:
                target.setCurrentIndex(0)
            confirmed = QCheckBox("確認しました")
            confirmed.setMinimumHeight(34)
            confirmed.stateChanged.connect(self._update_confirmation_progress)
            confirmed.setEnabled(target.currentData() is not None)
            target.currentIndexChanged.connect(
                lambda _index, combo=target, checkbox=confirmed: (
                    self._mapping_target_changed(combo, checkbox)
                )
            )
            self.table.setCellWidget(row_index, 1, target)
            confirmation_cell = QWidget()
            confirmation_layout = QHBoxLayout(confirmation_cell)
            confirmation_layout.setContentsMargins(8, 0, 8, 0)
            confirmation_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            confirmation_layout.addWidget(confirmed)
            self.table.setCellWidget(row_index, 2, confirmation_cell)
            self.row_controls.append((item.source_value, target, confirmed))
        self.tax_confirmed.setChecked(False)
        self.tax_card.setVisible(bool(analysis.tax_items))
        messages = []
        if analysis.unsupported_field_types:
            messages.append(
                "まだ設定が必要な項目があります: "
                + "、".join(analysis.unsupported_field_types)
            )
            messages.append(
                "科目対応は先に設定できます。未設定項目が残っている間は変換できません。"
            )
        if analysis.tax_context_message:
            messages.append(analysis.tax_context_message)
        messages.append(
            "完全一致する候補は初期表示されていますが、まだ確定していません。"
        )
        self.message_label.setText("\n".join(messages))
        self.message_label.setObjectName(
            "warningCard" if analysis.unsupported_field_types else "muted"
        )
        self._update_confirmation_progress()

    def _mapping_target_changed(
        self, target: QComboBox, checkbox: QCheckBox
    ) -> None:
        selected = target.currentData() is not None
        if not selected:
            checkbox.setChecked(False)
        checkbox.setEnabled(selected)
        self._update_confirmation_progress()

    def _update_confirmation_progress(self, *_args) -> None:
        total = len(self.row_controls)
        confirmed = sum(
            checkbox.isChecked() and target.currentData() is not None
            for _, target, checkbox in self.row_controls
        )
        self.progress_label.setText(f"{confirmed} / {total} 件確認済み")
        self.save_button.setEnabled(total > 0 and confirmed == total)

    def _save(self) -> None:
        if self.analysis is None:
            return
        selections: dict[str, str] = {}
        confirmed: set[str] = set()
        for source_value, target, checkbox in self.row_controls:
            selected_target = target.currentData()
            if selected_target is not None:
                selections[source_value] = str(selected_target)
            if checkbox.isChecked() and selected_target is not None:
                confirmed.add(source_value)
        try:
            profile = self.controller.create_moneyforward_profile(
                company_display_name=self.company_display_name,
                analysis=self.analysis,
                selections=selections,
                explicitly_confirmed=confirmed,
                explicitly_confirmed_tax=(
                    {self.analysis.tax_items[0].source_value}
                    if self.analysis.tax_items and self.tax_confirmed.isChecked()
                    else set()
                ),
            )
        except Exception:
            self.message_label.setText("すべての科目対応を選択し、明示的に確認してください。")
            return
        self.profile_id = profile.profile_id
        self.profile_name = profile.profile_name
        self.context_display = (
            f"{self.analysis.context.product} {self.analysis.context.version} / 設定済み"
        )
        self.accept()


class JdlTaxContextConfirmationDialog(QDialog):
    def __init__(self, controller, company_setting_id: str, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.company_setting_id = company_setting_id
        self.setWindowTitle("JDL税設定を確認")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)
        title = QLabel("JDL税設定を確認")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        guidance = QLabel(
            "この変換機能は、以下のJDL設定で実機検証済みです。\n"
            "この会社のJDL設定がすべて一致していることを確認してください。"
            "この画面からJDL本体の設定を変更することはありません。"
        )
        guidance.setWordWrap(True)
        layout.addWidget(guidance)
        details = QLabel(
            "製品: JDL IBEX 出納帳\n"
            "Version: 35.5\n"
            "税処理: 課税事業者\n"
            "計算方式: 税込処理\n"
            "課税方式: 本則課税\n"
            "仕入税額控除: 個別対応方式"
        )
        details.setObjectName("card")
        layout.addWidget(details)
        self.confirmed = QCheckBox("JDL側が上記の設定であることを確認しました")
        layout.addWidget(self.confirmed)
        actions = QHBoxLayout()
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        self.save_button = QPushButton("確認して保存")
        self.save_button.setObjectName("primaryButton")
        self.save_button.setEnabled(False)
        self.confirmed.toggled.connect(self.save_button.setEnabled)
        self.save_button.clicked.connect(self._save)
        actions.addStretch(1)
        actions.addWidget(cancel)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)

    def _save(self) -> None:
        if not self.confirmed.isChecked():
            return
        state = self.controller.confirm_company_tax_context(
            self.company_setting_id, explicitly_confirmed=True
        )
        if state.user_message.startswith("JDL税設定を保存しました"):
            self.accept()
            return
        QMessageBox.warning(
            self,
            "JDL税設定を保存できませんでした",
            state.user_message,
        )


class TaxMappingConfirmationDialog(QDialog):
    def __init__(
        self,
        controller: AccountingConverterController,
        company_setting_id: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.company_setting_id = company_setting_id
        self.review = controller.company_tax_mapping_review(company_setting_id)
        self.setWindowTitle("税区分を確認")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        title = QLabel("税区分を確認")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.confirmations: dict[str, QCheckBox] = {}
        if self.review.items:
            guidance = QLabel("内容を確認し、各税区分の「確認しました」を選択してください。")
            guidance.setObjectName("muted")
            guidance.setWordWrap(True)
            layout.addWidget(guidance)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            cards = QWidget()
            cards_layout = QVBoxLayout(cards)
            cards_layout.setContentsMargins(0, 0, 0, 0)
            cards_layout.setSpacing(10)
            for item in self.review.items:
                card = QFrame()
                card.setObjectName("card")
                card_layout = QVBoxLayout(card)
                card_layout.addWidget(QLabel(f"Money Forward: {item.source_value}"))
                card_layout.addWidget(QLabel(f"JDL: {item.target_display}"))
                confirmed = QCheckBox("確認しました")
                confirmed.stateChanged.connect(self._update_save_enabled)
                card_layout.addWidget(confirmed)
                self.confirmations[item.source_value] = confirmed
                cards_layout.addWidget(card)
            if self.review.user_message:
                warning = QLabel(self.review.user_message)
                warning.setObjectName("warningCard")
                warning.setWordWrap(True)
                cards_layout.addWidget(warning)
            cards_layout.addStretch(1)
            scroll.setWidget(cards)
            layout.addWidget(scroll, 1)
        else:
            message = QLabel(
                self.review.user_message
                or "確認できる未設定の税区分はありません。"
            )
            message.setObjectName("warningCard")
            message.setWordWrap(True)
            layout.addWidget(message)
        actions = QHBoxLayout()
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        self.save_button = QPushButton("確認を保存")
        self.save_button.setObjectName("primaryButton")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save)
        actions.addStretch(1)
        actions.addWidget(cancel)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)

    def _update_save_enabled(self) -> None:
        self.save_button.setEnabled(
            bool(self.confirmations)
            and all(item.isChecked() for item in self.confirmations.values())
        )

    def _save(self) -> None:
        if not self.confirmations or not all(
            item.isChecked() for item in self.confirmations.values()
        ):
            return
        state = self.controller.confirm_company_tax_mappings(
            self.company_setting_id, tuple(self.confirmations)
        )
        if state.user_message == "税区分の確認を保存しました。":
            self.accept()


class CompanyRenameDialog(QDialog):
    def __init__(self, current_name: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("会社設定名を変更")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.setSpacing(14)
        title = QLabel("会社設定名を変更")
        title.setObjectName("sectionTitle")
        description = QLabel("アプリ内で表示する会社設定名を入力してください。")
        description.setObjectName("muted")
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(QLabel("会社設定名"))
        self.name_edit = QLineEdit(current_name)
        layout.addWidget(self.name_edit)
        actions = QHBoxLayout()
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存")
        save.setObjectName("primaryButton")
        save.clicked.connect(self._accept_valid)
        actions.addStretch(1)
        actions.addWidget(cancel)
        actions.addWidget(save)
        layout.addLayout(actions)

    @property
    def display_name(self) -> str:
        return self.name_edit.text().strip()

    def _accept_valid(self) -> None:
        if self.display_name:
            self.accept()
