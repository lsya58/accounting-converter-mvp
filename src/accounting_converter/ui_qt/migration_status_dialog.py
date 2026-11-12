"""承認・未移行の管理 (D0 / D2): read-only views. Nothing here records an approval or changes a status.

Tab 1 承認待ち: items waiting for the tax accountant (controller.approval_items), their detail and a preview of the
production diagnosis as if the selected items were approved (controller.approval_preview: in-memory trial only).
Recording and applying a decision stays on the CLI (tools/yayoi_approval_ledger), which checks the company, the
source, the setting and the confirmed preview, takes a backup and writes an audit entry.

Tab 2 未移行管理: the tracker of a READY-only run (controller.migration_tracker_status): READY / BLOCK counts, the
tracked journals with filters by reason and state, the detail of one journal, the open integrity problems and the
overall verdict (never "complete" while anything is unproven), and the management sheet as CSV.
"""
from __future__ import annotations

from html import escape
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QListWidget,
    QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from accounting_converter.application import migration_tracker as mt
from accounting_converter.infrastructure.local_diagnostic_log import log_local_exception

TITLE = "承認・未移行の管理（閲覧・試算のみ）"
TRACKER_COLUMNS = ("元の行", "伝票No.", "日付", "BLOCK理由", "状態", "対応方針", "担当者")
PREVIEW_COLUMNS = ("元の行", "仕訳", "承認後", "残るBLOCK理由")
ALL = "（すべて）"


def _label(text: str, rich: bool = False, name: str | None = None) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    if rich:
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if name:
        label.setObjectName(name)
    return label


def item_detail_html(item, state: str) -> str:
    targets = "、".join(f"{t.label}（行{t.source_row}・伝票{t.voucher}）" for t in item.targets) or "—"
    rows = (
        ("会社ID", item.company_id), ("対象期間", "〜".join(item.period or ()) or "—"),
        ("JDLバージョン", item.jdl_version or "—"), ("振替伝票入力行数", str(item.voucher_row_limit or "未確認")),
        ("対象", targets), ("変更の内容", item.change), ("根拠Evidence", "、".join(item.evidence_ids) or "—"),
        ("承認の適用範囲（既定）", item.default_scope.get("text", "")), ("現在の状態", state),
        ("変換への反映", "承認と適用の後、正式診断で判定" if item.applies_to_conversion else "記録のみ（変換は変わりません）"),
    )
    body = "".join(f"<tr><td><b>{escape(k)}</b></td><td>{escape(v)}</td></tr>" for k, v in rows)
    note = f"<p>{escape(item.note)}</p>" if item.note else ""
    return f"<table cellspacing='4'>{body}</table>{note}"


def preview_html(preview) -> str:
    out = (f"<b>現在</b> READY {preview.ready_before:,}／BLOCK {preview.block_before:,}　→　"
           f"<b>承認後の予測</b> READY {preview.ready_after:,}／BLOCK {preview.block_after:,}<br>"
           f"READYになる見込み {len(preview.released)}仕訳・BLOCKのまま {len(preview.still_blocked)}仕訳・"
           f"新たにBLOCK {len(preview.newly_blocked)}仕訳<br><span>試算です。承認は記録していません。</span>")
    for text in preview.setting_sensitivity + preview.record_only:
        out += f"<br>・{escape(text)}"
    for problem in preview.problems:
        out += f"<br><b>問題: {escape(problem)}</b>"
    return out


class MigrationStatusDialog(QDialog):
    def __init__(self, controller, company_id: str, source_path, parent=None) -> None:
        super().__init__(parent)
        self.controller, self.company_id, self.source_path = controller, company_id, source_path
        self.items: tuple = ()
        self.preview = None
        self.tracker = None
        self.integrity = None
        self.verdict = None
        self.setWindowTitle(TITLE)
        self.resize(1000, 680)
        layout = QVBoxLayout(self)
        layout.addWidget(_label("この画面では承認を記録しません。承認の記録・適用は、確認手順のあるコマンド"
                                "（yayoi_approval_ledger）で行います。未移行の状態も変更しません。", name="warningCard"))
        self.tabs = QTabWidget()
        self.tabs.addTab(self._approval_tab(), "承認待ち")
        self.tabs.addTab(self._tracker_tab(), "未移行管理")
        layout.addWidget(self.tabs, 1)
        footer = QHBoxLayout()
        footer.addStretch(1)
        close = QPushButton("閉じる")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        layout.addLayout(footer)
        self.refresh_items()

    # ------------------------------------------------------------ approvals
    def _approval_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.item_list = QListWidget()
        self.item_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.item_list.currentRowChanged.connect(self._show_item)
        split.addWidget(self.item_list)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.item_detail = _label("", rich=True)
        right_layout.addWidget(self.item_detail)
        self.preview_button = QPushButton("選択した項目の承認後を試算")
        self.preview_button.clicked.connect(self.run_preview)
        right_layout.addWidget(self.preview_button)
        self.preview_text = _label("", rich=True)
        right_layout.addWidget(self.preview_text)
        self.preview_table = QTableWidget(0, len(PREVIEW_COLUMNS))
        self.preview_table.setHorizontalHeaderLabels(PREVIEW_COLUMNS)
        self.preview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview_table.horizontalHeader().setSectionResizeMode(len(PREVIEW_COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)
        self.preview_table.verticalHeader().setVisible(False)
        right_layout.addWidget(self.preview_table, 1)
        split.addWidget(right)
        split.setSizes([260, 700])
        layout.addWidget(split, 1)
        return page

    def refresh_items(self) -> None:
        try:
            self.items = self.controller.approval_items(self.company_id, self.source_path)
        except Exception as exc:  # never invent items that could not be computed
            log_local_exception("approval_items", exc)
            self.items = ()
            self.item_detail.setText("承認待ちの項目を読み込めませんでした。入力ファイルと会社設定を確認してください。")
        self.item_list.clear()
        for item, state in self.items:
            self.item_list.addItem(f"{item.item_id}（{len(item.targets)}仕訳）— {state}")
        if self.items:
            self.item_list.setCurrentRow(0)

    def _show_item(self, row: int) -> None:
        if 0 <= row < len(self.items):
            item, state = self.items[row]
            self.item_detail.setText(item_detail_html(item, state))

    def selected_item_ids(self) -> tuple[str, ...]:
        rows = sorted(index.row() for index in self.item_list.selectedIndexes())
        return tuple(self.items[r][0].item_id for r in rows if 0 <= r < len(self.items))

    def run_preview(self, item_ids=None) -> None:
        ids = tuple(item_ids) if item_ids is not None else self.selected_item_ids()
        if not ids:
            self.preview_text.setText("項目を選択してください。")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.preview = self.controller.approval_preview(self.company_id, self.source_path, ids)
        except Exception as exc:
            log_local_exception("approval_preview", exc)
            self.preview = None
            self.preview_text.setText("試算できませんでした。")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.preview_text.setText(preview_html(self.preview))
        self.preview_table.setRowCount(len(self.preview.targets))
        for row, change in enumerate(self.preview.targets):
            for column, value in enumerate((str(change.source_row), change.label, change.state, " ".join(change.after))):
                self.preview_table.setItem(row, column, QTableWidgetItem(value))

    # ------------------------------------------------------------ tracker
    def _tracker_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.open_button = QPushButton("READY-only出力と管理表を開く…")
        self.open_button.clicked.connect(self._choose_tracker)
        row.addWidget(self.open_button)
        self.export_button = QPushButton("管理表をCSVで出力…")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export)
        row.addWidget(self.export_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.tracker_counts = _label("管理表が開かれていません。", rich=True)
        layout.addWidget(self.tracker_counts)
        filters = QHBoxLayout()
        filters.addWidget(QLabel("理由"))
        self.reason_filter = QComboBox()
        self.reason_filter.currentIndexChanged.connect(self._fill_tracker)
        filters.addWidget(self.reason_filter, 1)
        filters.addWidget(QLabel("状態"))
        self.status_filter = QComboBox()
        self.status_filter.currentIndexChanged.connect(self._fill_tracker)
        filters.addWidget(self.status_filter, 1)
        layout.addLayout(filters)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.tracker_table = QTableWidget(0, len(TRACKER_COLUMNS))
        self.tracker_table.setHorizontalHeaderLabels(TRACKER_COLUMNS)
        self.tracker_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tracker_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tracker_table.verticalHeader().setVisible(False)
        self.tracker_table.currentCellChanged.connect(lambda r, *_: self._show_journal(r))
        split.addWidget(self.tracker_table)
        self.journal_detail = _label("", rich=True)
        split.addWidget(self.journal_detail)
        split.setSizes([600, 380])
        layout.addWidget(split, 1)
        self.open_issues = _label("", rich=True)
        layout.addWidget(self.open_issues)
        self._shown: list[dict] = []
        return page

    def _choose_tracker(self) -> None:
        output, _ = QFileDialog.getOpenFileName(self, "READY-only出力CSV", "", "CSV (*.csv)")
        if not output:
            return
        tracker, _ = QFileDialog.getOpenFileName(self, "未移行管理表（JSON）", "", "JSON (*.json)")
        if tracker:
            self.load_tracker(Path(output), Path(tracker))

    def load_tracker(self, output: Path, tracker_path: Path) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.tracker, self.integrity, self.verdict = self.controller.migration_tracker_status(
                self.company_id, self.source_path, output, tracker_path)
        except Exception as exc:
            log_local_exception("migration_tracker_status", exc)
            self.tracker = self.integrity = self.verdict = None
            self.tracker_counts.setText("管理表を確認できませんでした（会社・出力・管理表の組合せを確認してください）。")
            self.export_button.setEnabled(False)
            return
        finally:
            QApplication.restoreOverrideCursor()
        counts = self.integrity["counts"]
        self.tracker_counts.setText(
            f"<b>元の仕訳 {counts['source_journals']:,}</b> ＝ READY-only出力 {counts['ready_only_output']:,} ＋ "
            f"未移行（BLOCK） {counts['tracked']:,}　整合チェック: <b>{self.integrity['verdict']}</b>　"
            f"移行全体: <b>{'完了' if self.verdict['verdict'] == 'MIGRATION_COMPLETE' else '未完了'}</b>")
        reasons = sorted({b for j in self.tracker["journals"] for b in j["blockers"]})
        for combo, values in ((self.reason_filter, reasons), (self.status_filter, [mt.STATES[s] for s in mt.STATES])):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems([ALL, *values])
            combo.blockSignals(False)
        issues = [f"{k}: {v}" for k, v in self.integrity["problems"].items() if v] + self.verdict["reasons"]
        self.open_issues.setText("<b>未解決事項</b><br>" + "<br>".join(escape(str(i)) for i in issues))
        self.export_button.setEnabled(True)
        self._fill_tracker()

    def _fill_tracker(self) -> None:
        if self.tracker is None:
            return
        reason, status = self.reason_filter.currentText(), self.status_filter.currentText()
        self._shown = [j for j in self.tracker["journals"]
                       if (reason in ("", ALL) or reason in j["blockers"])
                       and (status in ("", ALL) or mt.STATES.get(j["status"]) == status)]
        self.tracker_table.setRowCount(len(self._shown))
        for row, j in enumerate(self._shown):
            values = (str(j["source_row"]), j["voucher"], j["date"], " / ".join(j["reasons"]),
                      mt.STATES.get(j["status"], j["status"]), j["plan"], j["owner"])
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(" ".join(j["blockers"]))
                self.tracker_table.setItem(row, column, cell)

    def _show_journal(self, row: int) -> None:
        if not 0 <= row < len(self._shown):
            return
        j = self._shown[row]
        fields = (("元の行", j["source_row"]), ("伝票No.・日付", f"{j['voucher']}・{j['date']}"),
                  ("BLOCKコード", " ".join(j["blockers"])), ("状態", mt.STATES.get(j["status"], j["status"])),
                  ("対応方針", j["plan"] or "—"), ("担当者", j["owner"] or "—"), ("メモ", j["memo"] or "—"),
                  ("関連Evidence", " ".join(j["evidence_ids"]) or "—"),
                  ("手入力", {None: "未定", True: "必要", False: "不要"}.get(j["manual_entry_required"], "—")),
                  ("JDL入力", j["jdl_entry"] or "—"), ("照合", j["reconciliation"] or "—"),
                  ("最終確認", f"{j['final_checker'] or '—'} {j['final_checked_at']}"),
                  ("履歴", f"{len(j['history'])}件"))
        self.journal_detail.setText("<table>" + "".join(
            f"<tr><td><b>{escape(k)}</b></td><td>{escape(str(v))}</td></tr>" for k, v in fields) + "</table>")

    def _export(self) -> None:
        if self.tracker is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "未移行管理表をCSVで保存", "", "CSV (*.csv)")
        if path:
            self.export_csv(Path(path))

    def export_csv(self, path: Path) -> bool:
        if path.exists():
            QMessageBox.warning(self, TITLE, "既存のファイルは上書きしません。別の名前を選択してください。")
            return False
        with path.open("xb") as handle:
            handle.write(mt.to_csv(self.tracker))
        return True
