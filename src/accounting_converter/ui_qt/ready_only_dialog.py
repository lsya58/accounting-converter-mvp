"""READYのみ変換: writes only the READY journals, never presented as a full migration.

Opened from the 出力・照合 page (and the 変換診断 dialog when nothing is unsaved). The plan (which journals are written / excluded and why) is the production diagnosis
(controller.plan_yayoi_ready_only). Nothing is written until the user ticks all three acknowledgements, enters a
name, chooses a new file and confirms the counts once more. The result always says how many journals are still
NOT migrated.
"""
from __future__ import annotations

from html import escape
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from accounting_converter.application import yayoi_ready_only as ro
from accounting_converter.infrastructure.local_diagnostic_log import log_local_exception
from accounting_converter.ui.output_conflicts import refusal_message

from . import components as ui
from .file_dialogs import choose_new_file

TITLE = "READYのみ変換（全件移行ではありません）"
COLUMNS = ("元の行", "日付", "伝票No.", "借方金額合計", "除外の理由")


def counts_html(plan) -> str:
    return (f"<span style='font-size:16px; font-weight:700'>入力 {plan.total_journals:,}仕訳 ＝ "
            f"変換対象（READY） {plan.ready_count:,}仕訳 ＋ 除外（未移行のまま残る） {plan.excluded_count:,}仕訳</span><br>"
            "除外する仕訳は、変換診断でBLOCKの仕訳です。BLOCKの仕訳は出力に含まれません。"
            "件数は仕訳の数です（CSVの行数・借貸の明細行数ではありません）。")


def target_text(company_name: str, source_path) -> str:
    """Which company and which source this run is for (shown before anything is acknowledged)."""
    name = Path(source_path).name if source_path else "（未選択）"
    return f"対象の会社: {company_name}　｜　仕訳データ: {name}"


def result_text(result) -> str:
    return (f"READYのみ変換が完了しました（全件移行ではありません）。変換済み {result.output_journals:,}仕訳"
            f"（JDL {result.output_rows:,}行）／ 未移行 {result.excluded_journals:,}仕訳（除外一覧に記録）。")


class ReadyOnlyConversionDialog(QDialog):
    def __init__(self, controller, company_id: str, source_path, parent=None) -> None:
        super().__init__(parent)
        self.controller, self.company_id, self.source_path = controller, company_id, source_path
        self.plan = None
        self.result = None
        self.setWindowTitle(TITLE)
        ui.fit_to_screen(self, 900, 640)
        layout = QVBoxLayout(self)
        from .resolution_center import report_company_name

        self.target = QLabel(target_text(report_company_name(controller, company_id), source_path))
        self.target.setObjectName("sectionTitle")
        self.target.setWordWrap(True)
        self.target.setToolTip(str(source_path))
        self.target.setAccessibleName("出力の対象")
        layout.addWidget(self.target)
        self.banner = QLabel("<b>これは全件移行ではありません。</b>READYの仕訳だけをJDL取込CSVに出力します。"
                             "除外した仕訳はJDLに入らず、未移行のまま残ります。")
        self.banner.setObjectName("warningCard")
        self.banner.setWordWrap(True)
        self.banner.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.banner)
        self.counts = QLabel()
        self.counts.setTextFormat(Qt.TextFormat.RichText)
        self.counts.setWordWrap(True)
        layout.addWidget(self.counts)
        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.setObjectName("warningCard")
        self.problems.setVisible(False)
        layout.addWidget(self.problems)
        layout.addWidget(QLabel("除外される仕訳（未移行）:"))
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(len(COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAccessibleName("除外される仕訳（未移行・BLOCK）")
        layout.addWidget(self.table, 1)
        self.notes = QLabel("<br>".join(escape(n) for n in ro.FOLLOW_UP_NOTES))
        self.notes.setTextFormat(Qt.TextFormat.RichText)
        self.notes.setWordWrap(True)
        self.notes.setObjectName("muted")
        layout.addWidget(self.notes)
        self.ack_partial = QCheckBox()
        self.ack_duplicate = QCheckBox("JDLの取込先に同じ期間の仕訳が既にないか（二重取込）を、取込前に確認します")
        self.ack_follow_up = QCheckBox("除外した仕訳は、承認・修正後の再変換かJDLでの手入力で別に扱います")
        for box in (self.ack_partial, self.ack_duplicate, self.ack_follow_up):
            box.toggled.connect(self._update)
            layout.addWidget(box)
        name_row = QHBoxLayout()
        name_label = QLabel("確認者")
        name_row.addWidget(name_label)
        self.confirmed_by = QLineEdit()
        self.confirmed_by.setAccessibleName("確認者の名前")
        name_label.setBuddy(self.confirmed_by)
        self.confirmed_by.textChanged.connect(self._update)
        name_row.addWidget(self.confirmed_by, 1)
        layout.addLayout(name_row)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setAccessibleName("出力の状態")
        layout.addWidget(self.status)
        footer = QHBoxLayout()
        self.write_button = QPushButton("保存先を選んでREADYのみ出力…")
        self.write_button.setObjectName("primaryButton")
        self.write_button.clicked.connect(self._write)
        footer.addWidget(self.write_button)
        footer.addStretch(1)
        close = QPushButton("閉じる")
        close.setAutoDefault(False)
        self.write_button.setAutoDefault(False)     # Enter never starts the output
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        layout.addLayout(footer)
        self.refresh()

    def refresh(self) -> None:
        try:
            self.plan = self.controller.plan_yayoi_ready_only(self.company_id, self.source_path)
        except Exception as exc:  # never invent a plan that could not be computed
            log_local_exception("plan_yayoi_ready_only", exc)
            self.plan = None
            self.counts.setText("診断できませんでした。入力ファイルと会社設定を確認してください。")
            self._update()
            return
        plan = self.plan
        self.counts.setText(counts_html(plan))
        self.ack_partial.setText(f"全件移行ではなく、除外する{plan.excluded_count:,}仕訳はJDLに取り込まれない（未移行のまま残る）ことを理解しました")
        self.problems.setVisible(bool(plan.problems))
        self.problems.setText("\n".join(ro.PROBLEM_MESSAGES.get(p, p) for p in plan.problems))
        self.table.setRowCount(len(plan.excluded))
        for row, item in enumerate(plan.excluded):
            for column, value in enumerate((str(item.source_row), item.date, item.voucher, f"{item.debit_total:,}",
                                            " / ".join(item.reasons))):
                cell = QTableWidgetItem(value)
                cell.setToolTip(" ".join(item.blockers))
                self.table.setItem(row, column, cell)
        self._update()

    def confirmation(self) -> ro.ReadyOnlyConfirmation | None:
        if self.plan is None:
            return None
        return ro.ReadyOnlyConfirmation(
            plan_fingerprint=self.plan.fingerprint, output_journals=self.plan.ready_count,
            excluded_journals=self.plan.excluded_count, confirmed_by=self.confirmed_by.text(),
            acknowledged_not_full_migration=self.ack_partial.isChecked(),
            acknowledged_duplicate_check=self.ack_duplicate.isChecked(),
            acknowledged_excluded_follow_up=self.ack_follow_up.isChecked())

    def ready_to_write(self) -> bool:
        confirmation = self.confirmation()
        return (self.result is None and self.plan is not None and self.plan.available and confirmation is not None
                and not confirmation.problems(self.plan))

    def _update(self) -> None:
        ready = self.ready_to_write()
        self.write_button.setEnabled(ready)
        if self.result is not None:
            return                                   # the result (and its files) stays on screen
        if self.plan is None:
            self.status.setText("出力できません: 診断できませんでした。")
        elif not self.plan.available:
            self.status.setText("出力できません: " + ("／".join(ro.PROBLEM_MESSAGES.get(p, p) for p in self.plan.problems)
                                                 or "READYのみ変換の対象ではありません。"))
        elif ready:
            self.status.setText("出力できます。保存先を選ぶと、件数をもう一度確認してから出力します。")
        else:
            confirmation = self.confirmation()
            missing = confirmation.problems(self.plan) if confirmation is not None else ()
            self.status.setText("出力するには: " + " ".join(missing))

    def _write(self) -> None:
        if not self.ready_to_write():
            return
        plan = self.plan
        # No OS "replace?" question (it could never be honoured): the CSV and every companion file of the run
        # are checked here, before the final question; the write step refuses existing files as well.
        path, existing = choose_new_file(self, "READYのみのJDL取込CSVを保存", "CSV (*.csv)", related_paths=ro.run_paths)
        if path is None:
            self.status.setText("保存先を選ばなかったため、出力しませんでした。")
            return
        if existing:
            self.status.setText("出力していません: " + refusal_message(existing))
            return
        answer = QMessageBox.question(
            self, TITLE,
            f"全件移行ではありません。\n\n出力する仕訳: {plan.ready_count:,}\n除外する仕訳（未移行）: {plan.excluded_count:,}\n\n"
            "この内容でREADYの仕訳だけを出力しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            self.status.setText("出力しませんでした。")
            return
        self.write(Path(path))

    def write(self, output: Path) -> None:
        """The write step itself (after the file and the final question); separated for tests."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result, reasons = self.controller.execute_yayoi_ready_only(
                self.company_id, self.source_path, self.plan, self.confirmation(), output)
        except Exception as exc:
            log_local_exception("execute_yayoi_ready_only", exc)
            result, reasons = None, (f"出力できませんでした（{type(exc).__name__}）。ファイルは残していません。",)
        finally:
            QApplication.restoreOverrideCursor()
        if result is None or result.status != "SUCCESS":
            self.status.setText("出力していません: " + " / ".join(reasons or getattr(result, "errors", ()) or ("不明",)))
            return
        self.result = result
        files = [p.name for p in (result.output_path, result.audit_path, result.excluded_list_path,
                                  result.manifest_path) if p is not None]
        self.status.setText(result_text(result) + "\n出力ファイル: " + "、".join(files))
        self._update()
