from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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
        self._render(self.controller.load_profiles())

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
