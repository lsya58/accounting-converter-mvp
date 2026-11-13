"""承認・未移行の管理 (D0 / D2): read-only views. Nothing here records an approval or changes a status.

Tab 1 税理士の判断（承認待ち）: the items waiting for the tax accountant, each explained in plain language, and a preview
of the production diagnosis as if the selected items were approved (in-memory trial only). Recording and applying a
decision stays on the CLI (tools/yayoi_approval_ledger).

Tab 2 未移行の仕訳（進捗管理）: the journals a READY-only run leaves out, shown from the production diagnosis with no
file to pick (controller.unmigrated_overview). The app looks for the READY-only run of this exact source file in the
source's folder (and in one folder the user names once): only the app's own `<csv>.ready_only.json` files, accepted only
for this company and this source, then verified with the existing SHA / audit checks. If the run has a tracker, it is
opened only when it belongs to exactly that run; if not, the list stays read-only until the user explicitly starts
status management (one tracker is written next to the CSV; an existing one is never overwritten or reset).
Nothing here changes READY / BLOCK, records an approval or moves a journal to "migrated".
"""
from __future__ import annotations

from decimal import Decimal
from html import escape
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QMessageBox, QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
    QWidget,
)

from accounting_converter.application import migration_tracker as mt
from accounting_converter.infrastructure.local_diagnostic_log import log_local_exception

TITLE = "承認・未移行の管理（閲覧・試算のみ）"
TRACKER_COLUMNS = ("元の行", "伝票No.", "日付", "BLOCK理由", "現在の状態", "必要な税理士判断", "技術的な未解決条件", "次に必要な作業")
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


def preview_html(view) -> str:
    """The trial, in words. `view` is application.approval_explanation.PreviewView."""
    out = (f"<b>現在</b> READY {view.ready_before:,}／BLOCK {view.block_before:,}　→　"
           f"<b>承認した場合の予測</b> READY {view.ready_after:,}／BLOCK {view.block_after:,}<br>"
           f"READYになる {len(view.released)}仕訳・承認後もBLOCKが残る {len(view.remaining)}仕訳"
           "<br><span>これは試算です。承認は記録しておらず、会社設定も承認台帳も変更していません。</span>")
    if view.expected_note:
        out += "<br>" + escape(view.expected_note)
    for text in (*view.prerequisites, *view.notes):
        out += "<br>・" + escape(text)
    for problem in view.problems:
        out += "<br><b>問題: " + escape(problem) + "</b>"
    return out


class MigrationStatusDialog(QDialog):
    def __init__(self, controller, company_id: str, source_path, parent=None) -> None:
        super().__init__(parent)
        self.controller, self.company_id, self.source_path = controller, company_id, source_path
        self.trailing_space_record: Path | None = None
        self.catalog_path: Path | None = None
        self.preview = None
        self.preview_view = None
        self.tracker = None
        self.integrity = None
        self.verdict = None
        self.setWindowTitle(TITLE)
        self.resize(1000, 680)
        layout = QVBoxLayout(self)
        layout.addWidget(_label("この画面では承認を記録しません。承認の記録・適用は、確認手順のあるコマンド"
                                "（yayoi_approval_ledger）で行います。未移行の状態も変更しません。", name="warningCard"))
        self.tabs = QTabWidget()
        self.tabs.addTab(self._approval_tab(), "税理士の判断（承認待ち）")
        self.tabs.addTab(self._tracker_tab(), "未移行の仕訳（進捗管理）")
        self.tabs.currentChanged.connect(self._on_tab_changed)
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
        files = QHBoxLayout()
        self.trailing_button = QPushButton("摘要末尾空白の記録を選ぶ…")
        self.trailing_button.clicked.connect(lambda _checked=False: self._choose_trailing())
        self.catalog_button = QPushButton("運用方針の定義を選ぶ…")
        self.catalog_button.clicked.connect(lambda _checked=False: self._choose_catalog())
        self.inputs_label = _label("", name="muted")
        files.addWidget(self.trailing_button)
        files.addWidget(self.catalog_button)
        files.addWidget(self.inputs_label, 1)
        layout.addLayout(files)
        self.ledger_notice = _label("", rich=True, name="warningCard")
        self.ledger_notice.setVisible(False)
        layout.addWidget(self.ledger_notice)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.item_list = QListWidget()
        self.item_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.item_list.setWordWrap(True)
        self.item_list.currentRowChanged.connect(self._show_item)
        split.addWidget(self.item_list)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.item_detail = _label("", rich=True)
        right_layout.addWidget(self.item_detail)
        self.technical_toggle = QCheckBox("技術情報（会社ID・Evidence ID・内容IDなど）を表示")
        self.technical_toggle.toggled.connect(lambda _checked=False: self._show_item(self.item_list.currentRow()))
        right_layout.addWidget(self.technical_toggle)
        self.preview_button = QPushButton("選択した項目の承認後を試算")
        self.preview_button.clicked.connect(self._on_preview_clicked)
        right_layout.addWidget(self.preview_button)
        self.preview_text = _label("", rich=True)
        right_layout.addWidget(self.preview_text)
        right_layout.addWidget(_label("<b>READYになる仕訳</b>", rich=True))
        self.released_table = self._table(("元の行", "伝票No.", "日付"))
        right_layout.addWidget(self.released_table)
        right_layout.addWidget(_label("<b>承認後もBLOCKが残る仕訳</b>", rich=True))
        self.remaining_table = self._table(("元の行", "伝票No.", "日付", "残る条件", "解消に必要なこと"))
        right_layout.addWidget(self.remaining_table)
        scroll.setWidget(right)
        split.addWidget(scroll)
        split.setSizes([280, 720])
        layout.addWidget(split, 1)
        self.overview = None
        self.entries: list[tuple] = []
        return page

    @staticmethod
    def _table(columns) -> QTableWidget:
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(list(columns))
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(len(columns) - 1, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setMinimumHeight(110)
        return table

    def _choose_trailing(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "摘要末尾空白の記録（往復照合の記録 .json）", "", "JSON (*.json)")
        if path:
            self.trailing_space_record = Path(path)
            self.refresh_items()

    def _choose_catalog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "運用方針の定義（.json）", "", "JSON (*.json)")
        if path:
            self.catalog_path = Path(path)
            self.refresh_items()

    def refresh_items(self) -> None:
        self.inputs_label.setText(
            "摘要末尾空白の記録: " + (self.trailing_space_record.name if self.trailing_space_record else "未選択")
            + "　運用方針の定義: " + (self.catalog_path.name if self.catalog_path else "未選択"))
        self.entries = []
        self.ledger_notice.setVisible(False)
        try:
            self.overview = self.controller.approval_overview(
                self.company_id, self.source_path, trailing_space_record=self.trailing_space_record,
                catalog_path=self.catalog_path)
        except Exception as exc:  # shown on the screen, never swallowed
            log_local_exception("approval_overview", exc)
            self.overview = None
            self.item_detail.setText("承認待ちの項目を読み込めませんでした: " + escape(f"{type(exc).__name__}: {exc}"))
            self.item_list.clear()
            return
        explanations = self.overview["explanations"]
        for item, state in self.overview["items"]:
            self.entries.append(("item", item, state, explanations.get(item.item_id)))
        for guide in self.overview["guides"]:
            self.entries.append(("guide", guide))
        if self.overview["ledger_error"]:
            self.ledger_notice.setText("<b>承認台帳を読めません。</b>" + escape(self.overview["ledger_error"])
                                       + "（記録・適用はできません。画面の試算は引き続き使えます）")
            self.ledger_notice.setVisible(True)
        self.item_list.clear()
        for entry in self.entries:
            if entry[0] == "item":
                item = entry[1]
                self.item_list.addItem(f"{(entry[3].title if entry[3] else item.item_id)}\n　状態: {entry[2]}")
            else:
                self.item_list.addItem(f"{entry[1].title}\n　別の承認経路（資料未選択）")
        if self.entries:
            self.item_list.setCurrentRow(0)

    @staticmethod
    def _section(title: str, lines) -> str:
        lines = [line for line in lines if line]
        if not lines:
            return ""
        return f"<p><b>{escape(title)}</b><br>" + "<br>".join("・" + escape(line) for line in lines) + "</p>"

    def detail_html(self, entry) -> str:
        if entry[0] == "guide":
            guide = entry[1]
            return f"<h3>{escape(guide.title)}</h3>" + "".join(f"<p>{escape(line)}</p>" for line in guide.lines)
        _, item, state, explanation = entry
        if explanation is None:
            return item_detail_html(item, state)
        body = f"<h3>{escape(explanation.title)}</h3>"
        body += self._section("1. 何の取引・仕訳か", explanation.what)
        body += self._section("2. 元の弥生での処理", explanation.yayoi)
        body += self._section("3. JDLで提案している処理", explanation.jdl)
        body += self._section("4. 変換によって失われる区別・変更点", explanation.lost)
        body += f"<p><b>5. 税理士に判断してほしいこと</b><br>{escape(explanation.question)}</p>"
        body += ("<p><b>6・7. 承認した場合にREADYになる仕訳／承認しても残るBLOCK条件</b><br>"
                 "下の「選択した項目の承認後を試算」を押すと表示します（読み取り専用。承認は記録されません）。</p>")
        body += self._section("8. 承認できない場合の対応候補", explanation.alternatives)
        body += f"<p><b>9. 現在の承認状態</b>: {escape(state)}</p>"
        body += self._section("　 必要な追加確認", explanation.needs)
        body += self._section("　 関連する項目", explanation.related)
        if self.technical_toggle.isChecked():
            body += "<p><b>技術情報</b></p><table cellspacing='4'>" + "".join(
                f"<tr><td><b>{escape(k)}</b></td><td>{escape(v)}</td></tr>" for k, v in explanation.technical) + "</table>"
        return body

    def _show_item(self, row: int) -> None:
        if 0 <= row < len(self.entries):
            self.item_detail.setText(self.detail_html(self.entries[row]))

    @property
    def items(self):
        return tuple((e[1], e[2]) for e in self.entries if e[0] == "item")

    def selected_item_ids(self) -> tuple[str, ...]:
        rows = sorted(index.row() for index in self.item_list.selectedIndexes())
        return tuple(self.entries[r][1].item_id for r in rows if 0 <= r < len(self.entries) and self.entries[r][0] == "item")

    def _on_preview_clicked(self, _checked: bool = False) -> None:
        """The button's slot. `clicked` passes a bool (checked); it must never reach run_preview as the item list."""
        self.run_preview()

    def run_preview(self, item_ids=None) -> None:
        ids = tuple(item_ids) if isinstance(item_ids, (list, tuple, set, frozenset)) else self.selected_item_ids()
        if not ids:
            rows = sorted(index.row() for index in self.item_list.selectedIndexes()) or [self.item_list.currentRow()]
            if any(0 <= r < len(self.entries) and self.entries[r][0] == "guide" for r in rows):
                self.preview_text.setText("この項目は別の承認経路です。記録ファイル／定義ファイルを選ぶと、承認待ちの項目として表示されます。")
            else:
                self.preview_text.setText("左の一覧から、試算する項目を選んでください（複数選択できます）。")
            return
        self.preview_text.setText("試算中です…（会社Aの全仕訳を再診断するため、数十秒かかることがあります）")
        self._clear_preview_tables()
        QApplication.processEvents()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.preview, self.preview_view = self.controller.approval_preview_view(
                self.company_id, self.source_path, ids, trailing_space_record=self.trailing_space_record,
                catalog_path=self.catalog_path)
        except Exception as exc:  # never silent: say what failed
            log_local_exception("approval_preview", exc)
            self.preview = self.preview_view = None
            self.preview_text.setText("<b>試算できませんでした。</b><br>" + escape(f"{type(exc).__name__}: {exc}")
                                      + "<br>承認は記録されていません。入力ファイル・会社設定を確認してください。")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.preview_text.setText(preview_html(self.preview_view))
        self._fill_preview_tables(self.preview_view)

    def _clear_preview_tables(self) -> None:
        self.released_table.setRowCount(0)
        self.remaining_table.setRowCount(0)

    def _fill_preview_tables(self, view) -> None:
        self.released_table.setRowCount(len(view.released))
        for row, item in enumerate(view.released):
            for column, value in enumerate((str(item.source_row), item.voucher, item.date)):
                self.released_table.setItem(row, column, QTableWidgetItem(value))
        self.remaining_table.setRowCount(len(view.remaining))
        for row, item in enumerate(view.remaining):
            values = (str(item.source_row), item.voucher, item.date, "／".join(item.reasons), "／".join(item.hints))
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(" ".join(item.codes))
                self.remaining_table.setItem(row, column, cell)

    # ------------------------------------------------------------ unmigrated journals (D2)
    def _tracker_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.refresh_button = QPushButton("未移行の仕訳を診断して表示")
        self.refresh_button.clicked.connect(lambda _checked=False: self.load_overview())
        self.folder_button = QPushButton("READY-only出力のフォルダを指定…")
        self.folder_button.clicked.connect(lambda _checked=False: self._choose_folder())
        self.start_button = QPushButton("状態管理を開始（管理表を作成）…")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(lambda _checked=False: self._on_start_clicked())
        self.export_button = QPushButton("一覧をCSVで出力…")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(lambda _checked=False: self._export())
        for widget in (self.refresh_button, self.folder_button, self.start_button, self.export_button):
            row.addWidget(widget)
        row.addStretch(1)
        layout.addLayout(row)
        self.tracker_counts = _label("「未移行の仕訳を診断して表示」を押すと、現在の診断結果から未移行の仕訳を表示します"
                                     "（ファイルを選ぶ必要はありません）。", rich=True)
        layout.addWidget(self.tracker_counts)
        self.run_banner = _label("", rich=True, name="warningCard")
        self.run_banner.setVisible(False)
        layout.addWidget(self.run_banner)
        run_row = QHBoxLayout()
        run_row.addWidget(QLabel("READY-only出力"))
        self.run_combo = QComboBox()
        self.run_combo.activated.connect(lambda _index=0: self._on_run_chosen())
        run_row.addWidget(self.run_combo, 1)
        run_row.addWidget(QLabel("管理者名"))
        self.creator_edit = QLineEdit()
        self.creator_edit.setMaximumWidth(180)
        run_row.addWidget(self.creator_edit)
        layout.addLayout(run_row)
        filters = QHBoxLayout()
        filters.addWidget(QLabel("理由"))
        self.reason_filter = QComboBox()
        self.reason_filter.currentIndexChanged.connect(lambda _i=0: self._fill_tracker())
        filters.addWidget(self.reason_filter, 1)
        filters.addWidget(QLabel("状態"))
        self.status_filter = QComboBox()
        self.status_filter.currentIndexChanged.connect(lambda _i=0: self._fill_tracker())
        filters.addWidget(self.status_filter, 1)
        layout.addLayout(filters)
        split = QSplitter(Qt.Orientation.Vertical)
        self.tracker_table = QTableWidget(0, len(TRACKER_COLUMNS))
        self.tracker_table.setHorizontalHeaderLabels(TRACKER_COLUMNS)
        self.tracker_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tracker_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tracker_table.verticalHeader().setVisible(False)
        self.tracker_table.horizontalHeader().setStretchLastSection(True)
        self.tracker_table.currentCellChanged.connect(lambda r, *_: self._show_journal(r))
        split.addWidget(self.tracker_table)
        detail = QScrollArea()
        detail.setWidgetResizable(True)
        detail.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        self.journal_detail = _label("", rich=True)
        holder_layout.addWidget(self.journal_detail)
        self.tracker_technical_toggle = QCheckBox("技術情報（会社ID・manifest・SHA-256・BLOCKコード）を表示")
        self.tracker_technical_toggle.toggled.connect(lambda _c=False: self._show_journal(self.tracker_table.currentRow()))
        holder_layout.addWidget(self.tracker_technical_toggle)
        self.open_issues = _label("", rich=True)
        holder_layout.addWidget(self.open_issues)
        detail.setWidget(holder)
        split.addWidget(detail)
        split.setSizes([360, 220])
        layout.addWidget(split, 1)
        self._shown: list = []
        self.overview_data = None
        self.run_state = None
        self.rows: tuple = ()
        self.tracker = None
        self.final = None
        self.scan_folders: list[Path] = []
        self.runs: list = []
        self._tracker_loaded_once = False
        return page

    def _on_tab_changed(self, index: int) -> None:
        if index == 1 and not self._tracker_loaded_once:
            self.load_overview()

    def load_overview(self) -> None:
        """Diagnose and list the unmigrated journals (read-only), then look for a matching READY-only run."""
        self._tracker_loaded_once = True
        self.tracker_counts.setText("診断しています…（会社の全仕訳を再診断するため、数十秒かかることがあります）")
        QApplication.processEvents()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.overview_data = self.controller.unmigrated_overview(self.company_id, self.source_path)
        except Exception as exc:  # shown on the screen, never swallowed
            log_local_exception("unmigrated_overview", exc)
            self.overview_data = None
            self.rows = ()
            self.tracker_counts.setText("未移行の仕訳を診断できませんでした: " + escape(f"{type(exc).__name__}: {exc}")
                                        + "<br>入力ファイルと会社設定を確認してください。")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.run_state = None
        self.tracker = None
        self.final = None
        self.rows = self.overview_data["rows"]
        self._refresh_runs()
        self._render()

    def _search_folders(self) -> list[Path]:
        folders = [Path(self.source_path).parent, *self.scan_folders]
        return list(dict.fromkeys(folders))

    def _refresh_runs(self) -> None:
        try:
            self.runs = list(self.controller.find_ready_only_runs(self.company_id, self.source_path, self._search_folders()))
        except Exception as exc:
            log_local_exception("find_ready_only_runs", exc)
            self.runs = []
        accepted = [r for r in self.runs if r.accepted]
        self.run_combo.clear()
        for run in accepted:
            self.run_combo.addItem(run.output.name, str(run.output))
        if len(accepted) == 1:
            self.use_run(accepted[0].output)       # exactly one verified-by-name candidate: open it (full checks follow)
        else:
            self._set_banner(self._no_run_text(accepted))

    def _no_run_text(self, accepted) -> str:
        rejected = [r for r in self.runs if not r.accepted]
        if len(accepted) > 1:
            return "READY-onlyの出力が複数あります。上の一覧から1つ選んでください（診断結果の表示は読み取り専用です）。"
        text = ("読み込み中の元データに対応するREADY-only出力が見つかっていません。診断結果を表示しています"
                "（表示のみ。状態管理は未開始）。出力フォルダを指定すると、状態を管理できます。")
        if rejected:
            text += "<br>見つかったが使わなかった出力: " + "、".join(f"{escape(r.output.name)}（{escape(r.reason)}）" for r in rejected)
        return text

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "READY-only出力が入っているフォルダ")
        if folder:
            self.add_folder(Path(folder))

    def add_folder(self, folder: Path) -> None:
        if folder not in self.scan_folders:
            self.scan_folders.append(folder)
        if self.overview_data is None:
            self.load_overview()
            return
        self._refresh_runs()
        self._render()

    def _on_run_chosen(self) -> None:
        path = self.run_combo.currentData()
        if path:
            self.use_run(Path(path))

    def use_run(self, output: Path) -> None:
        """Verify the run (existing SHA / audit checks) and load its tracker if it belongs to exactly this run."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.run_state = self.controller.open_migration_run(self.company_id, self.source_path, output)
        except Exception as exc:
            log_local_exception("open_migration_run", exc)
            self.run_state = {"state": "REJECTED", "output": output, "tracker": None, "integrity": None, "final": None,
                              "problems": [f"{type(exc).__name__}: {exc}"], "tracker_path": None}
        finally:
            QApplication.restoreOverrideCursor()
        state = self.run_state["state"]
        self.tracker = self.run_state["tracker"] if state == "TRACKED" else None
        self.final = self.run_state["final"] if state == "TRACKED" else None
        from accounting_converter.application import unmigrated_view as uv

        self.rows = uv.build_rows(self.overview_data["plan"], self.overview_data["items"], self.tracker)
        self._render()

    def _set_banner(self, text: str) -> None:
        self.run_banner.setText(text)
        self.run_banner.setVisible(bool(text))

    def _banner_for_state(self) -> str:
        state, problems = self.run_state["state"], self.run_state["problems"]
        name = escape(Path(self.run_state["output"]).name)
        detail = "".join("<br>・" + escape(str(p)) for p in problems)
        if state == "TRACKED":
            return f"出力（{name}）と管理表が一致しています。状態は管理表から読み込んでいます。"
        if state == "NO_TRACKER":
            return (f"出力（{name}）を確認しました。状態管理はまだ始まっていません（表示のみ・状態はすべて「未対応」）。"
                    "「状態管理を開始」を押すと、出力の隣に管理表を1つ作成します（既存の管理表は上書きしません）。")
        if state == "REJECTED":
            return f"この出力は使えません（検証に失敗）。診断結果だけを表示しています。{detail}"
        if state == "TRACKER_MISMATCH":
            return (f"出力（{name}）の隣にある管理表は、この出力と対応しないため使いません。状態は読み込んでいません"
                    f"（管理表は変更・初期化しません）。{detail}")
        return f"管理表を読み込めません。診断結果だけを表示しています。{detail}"

    def _render(self) -> None:
        data = self.overview_data
        if data is None:
            return
        self.tracker_counts.setText(
            f"<b>元の仕訳 {data['total']:,}</b> ＝ READY {data['ready']:,} ＋ 未移行（BLOCK） <b>{data['blocked']:,}</b>"
            + (f"　移行全体: <b>{'完了' if self.final['verdict'] == 'MIGRATION_COMPLETE' else '未完了'}</b>"
               if self.final else "　移行全体: <b>未完了（未移行が残っています）</b>")
            + "<br>この一覧は読み取り専用です。表示するだけでは、READY／BLOCKも移行の状態も変わりません。")
        if self.run_state is not None:
            self._set_banner(self._banner_for_state())
        self.start_button.setEnabled(bool(self.run_state and self.run_state["state"] == "NO_TRACKER"))
        self.export_button.setEnabled(bool(self.rows))
        reasons = sorted({title for r in self.rows for title in r.reasons})
        statuses = []
        for r in self.rows:
            if r.status not in statuses:
                statuses.append(r.status)
        for combo, values in ((self.reason_filter, reasons), (self.status_filter, statuses)):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems([ALL, *values])
            if current in values:
                combo.setCurrentText(current)
            combo.blockSignals(False)
        issues = []
        if self.run_state is not None and self.run_state["state"] == "TRACKED":
            issues = [f"{k}: {v}" for k, v in self.run_state["integrity"]["problems"].items() if v] + self.final["reasons"]
        elif self.run_state is not None:
            issues = list(self.run_state["problems"])
        self.open_issues.setText("<b>未解決事項</b><br>" + "<br>".join(escape(str(i)) for i in issues) if issues else "")
        self._fill_tracker()

    def _fill_tracker(self) -> None:
        reason, status = self.reason_filter.currentText(), self.status_filter.currentText()
        self._shown = [r for r in self.rows if (reason in ("", ALL) or reason in r.reasons)
                       and (status in ("", ALL) or r.status == status)]
        self.tracker_table.setRowCount(len(self._shown))
        for row, r in enumerate(self._shown):
            values = (str(r.source_row), r.voucher, r.date, " / ".join(r.reasons), r.status,
                      " / ".join(r.accountant) or "—", " / ".join(r.technical) or "—", r.next_steps[0] if r.next_steps else "")
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(" ".join(r.codes))
                self.tracker_table.setItem(row, column, cell)
        if self._shown:
            self.tracker_table.selectRow(0)       # the first journal's detail is shown without another click
        else:
            self.journal_detail.setText("")

    def _show_journal(self, row: int) -> None:
        if not 0 <= row < len(self._shown):
            return
        r = self._shown[row]
        fields = [("元の行", r.source_row), ("伝票No.・日付", f"{r.voucher}・{r.date}"), ("借方合計", f"{Decimal(r.debit_total):,}円"),
                  ("BLOCK理由", "／".join(r.reasons)), ("現在の対応状態", r.status),
                  ("必要な税理士判断", "／".join(r.accountant) or "（税理士の判断で解消する条件はありません）"),
                  ("技術的な未解決条件", "／".join(r.technical) or "—"), ("次に必要な作業", "\n".join(r.next_steps))]
        if r.plan or r.owner:
            fields.extend((("対応方針", r.plan or "—"), ("担当者", r.owner or "—")))
        html = "<table cellspacing='4'>" + "".join(
            f"<tr><td valign='top'><b>{escape(k)}</b></td><td>{escape(str(v)).replace(chr(10), '<br>')}</td></tr>"
            for k, v in fields) + "</table>"
        if self.tracker_technical_toggle.isChecked():
            plan = self.overview_data["plan"] if self.overview_data else None
            tech = [("BLOCKコード", " ".join(r.codes)), ("会社ID", self.company_id)]
            if plan is not None:
                tech.append(("元データ（SHA-256）", plan.source_sha256))
            if self.run_state is not None:
                tech.append(("READY-only出力", str(self.run_state["output"])))
                tech.append(("管理表の場所", str(self.run_state["tracker_path"])))
                tech.append(("出力の状態", self.run_state["state"]))
            html += "<p><b>技術情報</b></p><table cellspacing='4'>" + "".join(
                f"<tr><td><b>{escape(k)}</b></td><td>{escape(str(v))}</td></tr>" for k, v in tech) + "</table>"
        self.journal_detail.setText(html)

    def _on_start_clicked(self) -> None:
        if not (self.run_state and self.run_state["state"] == "NO_TRACKER"):
            return
        target = self.run_state["tracker_path"]
        answer = QMessageBox.question(
            self, TITLE,
            f"状態管理を開始します。\n\n管理表を次の場所に1つ作成します（既存の管理表は上書きしません）:\n{target}\n\n"
            f"未移行 {self.overview_data['blocked']}仕訳が、すべて「未対応」で登録されます。READY／BLOCKの判定は変わりません。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.start_tracking(self.creator_edit.text())

    def start_tracking(self, created_by: str) -> bool:
        """Create the tracker (after the explicit confirmation), then open it through the same checks."""
        try:
            self.controller.start_migration_tracking(self.company_id, self.source_path, self.run_state["output"],
                                                     created_by, explicitly_confirmed=True)
        except Exception as exc:
            log_local_exception("start_migration_tracking", exc)
            self.run_banner.setText("管理表を作成できませんでした: " + escape(f"{type(exc).__name__}: {exc}"))
            self.run_banner.setVisible(True)
            return False
        self.use_run(Path(self.run_state["output"]))
        return True

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "未移行の一覧をCSVで保存", "", "CSV (*.csv)")
        if path:
            self.export_csv(Path(path))

    def export_csv(self, path: Path) -> bool:
        from accounting_converter.application import unmigrated_view as uv

        if path.exists():
            QMessageBox.warning(self, TITLE, "既存のファイルは上書きしません。別の名前を選択してください。")
            return False
        with path.open("xb") as handle:
            handle.write(uv.rows_csv(self.rows))
        return True
