from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
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

from accounting_converter.ui.controllers import AccountingConverterController
from accounting_converter.ui.view_models import AppState, present_main_screen

from .theme import status_visual
from .widgets import CsvDropZone


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
        self.settings_action = QPushButton("設定を確認する")
        self.settings_action.clicked.connect(self._open_settings)
        self.convert_button = QPushButton("JDL用に変換する")
        self.convert_button.setObjectName("primaryButton")
        self.convert_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.convert_button.clicked.connect(self._convert)
        action_row.addWidget(self.settings_action)
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
            self._prepare_if_complete()

    def _prepare_if_complete(self) -> None:
        state = self.controller.state
        if state.selected_file and state.selected_output_file and state.selected_profile_id and state.selected_context_file:
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
        self._prepare_if_complete()

    def _show_drop_error(self, message: str) -> None:
        QMessageBox.warning(self, "ファイルを確認してください", message)

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
        badge, foreground, background = status_visual(presentation.status)
        self.status_badge.setText(badge)
        self.status_badge.setStyleSheet(
            f"color: {foreground}; background: {background}; border-radius: 10px; font-weight: 700;"
        )
        self.convert_button.setEnabled(presentation.conversion_enabled)
        self.settings_action.setVisible(presentation.settings_action_visible)
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
        self.company_combo.currentIndexChanged.connect(self._company_changed)
        company_row.addWidget(self.company_combo, 1)
        layout.addLayout(company_row)
        company_actions = QHBoxLayout()
        add_company = QPushButton("会社を追加")
        add_company.clicked.connect(self._add_company)
        rename_company = QPushButton("名前を変更")
        rename_company.clicked.connect(self._rename_company)
        delete_company = QPushButton("削除")
        delete_company.clicked.connect(self._delete_company)
        confirm_tax = QPushButton("税区分を確認")
        confirm_tax.clicked.connect(self._confirm_tax)
        company_actions.addWidget(add_company)
        company_actions.addWidget(rename_company)
        company_actions.addWidget(confirm_tax)
        company_actions.addWidget(delete_company)
        company_actions.addStretch(1)
        layout.addLayout(company_actions)

        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("対応設定"))
        self.profile_combo = QComboBox()
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
        import_button.clicked.connect(self._import_profile)
        profile_row.addWidget(import_button)
        layout.addLayout(profile_row)

        context_row = QHBoxLayout()
        context_row.addWidget(QLabel("JDL設定"))
        self.context_label = QLabel(
            "設定済み" if controller.state.selected_context_file else "未設定"
        )
        context_row.addWidget(self.context_label, 1)
        context_button = QPushButton("選択")
        context_button.clicked.connect(self._select_context)
        context_row.addWidget(context_button)
        layout.addLayout(context_row)
        note = QLabel("初回設定で受け取った、会社専用の確認済みファイルを選択してください。")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.message_label = QLabel(controller.state.user_message)
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)
        close_button = QPushButton("閉じる")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)

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
            self.context_label.setText("設定済み" if state.selected_context_file else "未設定")
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
        self.context_label.setText(
            "JDL IBEX 出納帳 35.5 / 設定済み"
            if state.selected_context_file
            else "未設定"
        )
        if state.selected_profile_id in self.profile_ids:
            self.profile_combo.blockSignals(True)
            self.profile_combo.setCurrentIndex(
                self.profile_ids.index(state.selected_profile_id)
            )
            self.profile_combo.blockSignals(False)
        company_id = state.selected_company_setting_id
        self.message_label.setText(
            self.controller.company_setting_status_reason(company_id)
            if company_id
            else state.user_message
        )


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
            "変換設定を選択",
            "この会社で使用する対応設定とJDL設定を選択してください。",
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
        layout.addWidget(QLabel("JDL設定"))
        context_row = QHBoxLayout()
        self.context_label = QLabel("ファイルはまだ選択されていません")
        self.context_label.setObjectName("muted")
        self.context_button = QPushButton("ファイルを選択")
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
            self, "JDL設定を選択", "", "JSON files (*.json)"
        )
        if filename:
            self.context_path = Path(filename)
            self.context_label.setText(self.context_path.name)
            self.error_label.clear()

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
                self.create_profile_button.hide()
                self.profile_ids = [item.profile_id for item in candidates]
                self.profile_combo.clear()
                self.profile_combo.addItems([item.profile_name for item in candidates])
        if index == 2:
            if self.profile_combo.currentIndex() < 0:
                self.error_label.setText("対応設定を選択してください。")
                return
            if self.context_path is None:
                self.error_label.setText("JDL設定ファイルを選択してください。")
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
        self.confirmation_label.setText(
            "\n".join(
                (
                    f"会社設定名    {self.name_edit.text().strip()}",
                    f"入力元        {self.source_combo.currentText()}",
                    f"対応設定      {self.profile_combo.currentText()}",
                    "JDL設定       JDL IBEX 出納帳 35.5 / 設定済み"
                    if self.context_path
                    else "JDL設定       未選択",
                    "状態           保存時に安全確認します",
                )
            )
        )

    def _save(self) -> None:
        assert self.context_path is not None
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
        self.resize(1040, 760)
        self.setMinimumSize(900, 680)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 24)
        layout.setSpacing(14)
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
        context_row.addWidget(QLabel("JDL設定"))
        self.context_label = QLabel("未選択")
        self.context_label.setObjectName("muted")
        context_button = QPushButton("JDL設定を選択")
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
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMinimumHeight(320)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

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
        layout.addWidget(self.tax_card)

        self.progress_label = QLabel("0 / 0 件確認済み")
        self.progress_label.setObjectName("muted")
        layout.addWidget(self.progress_label)

        self.message_label = QLabel("")
        self.message_label.setObjectName("muted")
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)
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
            self, "JDL設定を選択", "", "JSON files (*.json)"
        )
        if filename:
            self.context_path = Path(filename)
            self.context_label.setText(self.context_path.name)
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
            self.message_label.setText("JDL設定を選択してください。")
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
            source_item = QTableWidgetItem(item.source_value)
            source_item.setToolTip(item.source_value)
            self.table.setItem(row_index, 0, source_item)
            target = QComboBox()
            target.addItems(item.available_targets)
            if item.exact_candidate in item.available_targets:
                target.setCurrentIndex(item.available_targets.index(item.exact_candidate))
            else:
                target.setCurrentIndex(-1)
            confirmed = QCheckBox("確認しました")
            confirmed.setMinimumHeight(34)
            confirmed.stateChanged.connect(self._update_confirmation_progress)
            target.currentIndexChanged.connect(self._update_confirmation_progress)
            self.table.setCellWidget(row_index, 1, target)
            self.table.setCellWidget(row_index, 2, confirmed)
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

    def _update_confirmation_progress(self, *_args) -> None:
        total = len(self.row_controls)
        confirmed = sum(
            checkbox.isChecked() and target.currentIndex() >= 0
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
            if target.currentIndex() >= 0:
                selections[source_value] = target.currentText()
            if checkbox.isChecked():
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
        self.confirmed = QCheckBox("確認しました")
        if self.review.items:
            item = self.review.items[0]
            layout.addWidget(QLabel(f"Money Forward: {item.source_value}"))
            layout.addWidget(QLabel(f"JDL: {item.target_display}"))
            layout.addWidget(QLabel("状態: 確認してください"))
            layout.addWidget(self.confirmed)
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
        self.confirmed.stateChanged.connect(
            lambda: self.save_button.setEnabled(self.confirmed.isChecked())
        )
        actions.addStretch(1)
        actions.addWidget(cancel)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)

    def _save(self) -> None:
        if not self.review.items or not self.confirmed.isChecked():
            return
        state = self.controller.confirm_company_tax_mapping(
            self.company_setting_id, self.review.items[0].source_value
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
