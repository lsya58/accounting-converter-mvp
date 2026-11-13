"""承認・未移行の管理 (D0 / D2): view and trial only. Nothing here records an approval or changes a status.

Tab 1 税理士の判断（承認待ち）: the items waiting for the tax accountant, laid out as the facts the accountant decides
on (overview, how Yayoi has it, what JDL receives, what is lost, the question) and a trial of the production diagnosis
as if the selected items were approved (in-memory only). Recording and applying a decision stays on the CLI
(tools/yayoi_approval_ledger).

Tab 2 未移行の仕訳（進捗管理）: the journals a READY-only run leaves out, from the production diagnosis with no file to
pick. The READY-only run of this exact source is looked for in the source's folder (and in one folder named once), only
as the app's own `<csv>.ready_only.json` pair for this company and this source, then verified with the existing SHA /
audit checks; its tracker is used only when it belongs to exactly that run. Status management starts only on an
explicit confirmation (one tracker next to the CSV, never overwritten or reset).

The slow read-only work (diagnosis, trial, run verification) runs in components.BackgroundTask: one job at a time,
never touching widgets or writing anything, and its result is shown only if its request key (company, source SHA-256,
saved-setting fingerprints, selection) still matches the screen. A changed selection clears the previous trial.
"""
from __future__ import annotations

import hashlib
from decimal import Decimal
from html import escape
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMessageBox, QScrollArea, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from accounting_converter.infrastructure.local_diagnostic_log import log_local_exception

from . import components as ui

TITLE = "承認・未移行の管理（閲覧・試算のみ）"
TRACKER_COLUMNS = ("元の行", "伝票No.", "日付", "BLOCK理由", "税理士の判断", "技術的な問題", "対応状態", "次の作業")
RELEASED_COLUMNS = ("元の行", "伝票No.", "日付")
REMAINING_COLUMNS = ("元の行", "伝票No.", "日付", "残るBLOCK条件", "解消に必要なこと")
ALL = "（すべて）"
STATUS_COLUMN = 6


def _label(text: str = "", rich: bool = False, name: str | None = None) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    if rich:
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if name:
        label.setObjectName(name)
    return label


def _number(text: str):
    return int(text) if str(text).isdigit() else str(text)


class MigrationStatusDialog(QDialog):
    def __init__(self, controller, company_id: str, source_path, parent=None) -> None:
        super().__init__(parent)
        self.controller, self.company_id, self.source_path = controller, company_id, Path(source_path)
        self.trailing_space_record: Path | None = None
        self.catalog_path: Path | None = None
        self.preview = None
        self.preview_view = None
        self.preview_ids: tuple[str, ...] = ()
        self.task = ui.BackgroundTask(self)
        self.task.finished.connect(self._on_task_finished)
        self.task.failed.connect(self._on_task_failed)
        self.task.busy_changed.connect(self._on_busy_changed)
        self._pending_overview = False
        self._running: str | None = None
        self.setWindowTitle(TITLE)
        self.setAccessibleName(TITLE)
        self.setMinimumSize(900, 600)
        ui.fit_to_screen(self, 1200, 760)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        self.mode_banner = ui.ModeBanner("view", "承認の記録は台帳CLI、未移行の状態の変更は進捗管理CLIで行います。")
        layout.addWidget(self.mode_banner)
        self.tabs = QTabWidget()
        self.tabs.setAccessibleName("承認・未移行の管理")
        self.tabs.addTab(self._approval_tab(), "税理士の判断（承認待ち）")
        self.tabs.addTab(self._tracker_tab(), "未移行の仕訳（進捗管理）")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs, 1)
        footer = QHBoxLayout()
        footer.addStretch(1)
        close = ui.make_button("閉じる", description="この画面を閉じます（何も保存しません）")
        close.clicked.connect(lambda _checked=False: self.accept())
        footer.addWidget(close)
        layout.addLayout(footer)
        for keys, index in (("Ctrl+1", 0), ("Ctrl+2", 1)):
            QShortcut(QKeySequence(keys), self, activated=lambda i=index: self.tabs.setCurrentIndex(i))
        self.refresh_items()

    # ------------------------------------------------------------ request keys (no result reaches another company)
    def request_key(self, kind: str, params=()) -> tuple:
        """(kind, company, source SHA-256, saved-setting fingerprints, params): what a background result must match."""
        try:
            source_sha = hashlib.sha256(self.source_path.read_bytes()).hexdigest()
        except OSError:
            source_sha = None
        fingerprint = None
        store = getattr(self.controller, "company_store", None)
        if store is not None:
            try:
                setting = store.get(self.company_id)
                fingerprint = (setting.conversion_profile_id, setting.profile_fingerprint, setting.context_fingerprint)
            except Exception:  # noqa: BLE001 - an unreadable setting makes the key differ (result dropped)
                fingerprint = ("UNREADABLE",)
        return (kind, self.company_id, source_sha, fingerprint, tuple(params))

    def _start(self, kind: str, params, job) -> bool:
        key = self.request_key(kind, params)
        if not self.task.start(key, job):
            return False
        self._update_enabled()
        return True

    def _on_task_finished(self, key, result) -> None:
        if key != self.request_key(key[0], key[4]):   # the source or the saved setting changed during the job
            self._stale(key[0])
            return
        {"preview": self._show_preview, "overview": self._show_overview, "run": self._show_run}[key[0]](key, result)

    def _on_task_failed(self, key, error) -> None:
        log_local_exception(f"migration_status_{key[0]}", error)
        text = f"{type(error).__name__}: {error}"
        if key[0] == "preview":
            self._clear_preview("")
            self.preview_message.show_message("error", "試算できませんでした。" + text
                                              + "\n承認は記録されていません。入力ファイル・会社設定を確認してください。")
        else:
            self.d2_message.show_message("error", "未移行の仕訳を診断できませんでした。" + text
                                         + "\n何も保存していません。入力ファイルと会社設定を確認してください。")
        self._after_task()

    def _stale(self, kind: str) -> None:
        bar = self.preview_message if kind == "preview" else self.d2_message
        bar.show_message("warning", "元データまたは会社設定が処理中に変わったため、結果を破棄しました。もう一度実行してください。")
        self._after_task()

    def _after_task(self) -> None:
        self._update_enabled()

    def _on_busy_changed(self, busy: bool) -> None:
        """Also runs when a job's result was dropped (stale): a waiting overview load is never lost."""
        if not busy:
            self._running = None
        self._update_enabled()
        if not busy and self._pending_overview:
            self._pending_overview = False
            self.load_overview()

    def _update_enabled(self) -> None:
        busy = self.task.busy
        for button in (self.preview_button, self.refresh_button, self.folder_button, self.trailing_button,
                       self.catalog_button):
            button.setEnabled(not busy)
        self.start_button.setEnabled(not busy and bool(self.run_state and self.run_state["state"] == "NO_TRACKER"))
        self.export_button.setEnabled(not busy and bool(self.rows))
        self.run_combo.setEnabled(not busy)

    def done(self, result: int) -> None:
        self.task.shutdown()          # never leave a worker running past the dialog
        super().done(result)

    def closeEvent(self, event) -> None:
        self.task.shutdown()
        super().closeEvent(event)

    # ------------------------------------------------------------ D0: the tax accountant's decisions
    def _approval_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        files = QHBoxLayout()
        files.addWidget(QLabel("確認資料:"))
        self.trailing_button = ui.make_button("摘要末尾空白の記録を選ぶ…", description="往復照合の記録を選ぶと、その判断項目が表示されます")
        self.trailing_button.clicked.connect(lambda _checked=False: self._choose_trailing())
        self.catalog_button = ui.make_button("運用方針の定義を選ぶ…", description="運用方針の定義を選ぶと、その記録項目が表示されます")
        self.catalog_button.clicked.connect(lambda _checked=False: self._choose_catalog())
        self.inputs_label = _label(name="muted")
        files.addWidget(self.trailing_button)
        files.addWidget(self.catalog_button)
        files.addWidget(self.inputs_label, 1)
        layout.addLayout(files)
        self.ledger_message = ui.MessageBar()
        layout.addWidget(self.ledger_message)
        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(ui.SectionHeader("判断対象", "複数選択して、まとめて試算できます"))
        self.item_list = QListWidget()
        self.item_list.setAccessibleName("判断対象の一覧")
        self.item_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.item_list.setWordWrap(True)
        self.item_list.setSpacing(4)                 # each item reads as its own entry
        self.item_list.currentRowChanged.connect(self._show_item)
        self.item_list.itemSelectionChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self.item_list, 1)
        split.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.item_title = _label(name="sectionTitle")
        self.item_badge = ui.StatusBadge("UNDECIDED")
        bar.addWidget(self.item_title, 1)
        bar.addWidget(self.item_badge)
        self.preview_button = ui.make_button("試算する", description="選択した項目を承認した場合のREADY/BLOCKを計算します（保存しません）",
                                             shortcut="Ctrl+T")
        self.preview_button.clicked.connect(self._on_preview_clicked)
        bar.addWidget(self.preview_button)
        right_layout.addLayout(bar)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.d0_scroll = scroll
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 8, 0)
        body_layout.setSpacing(8)
        self.cards = {}
        for key, title in (("what", "選択した仕訳・規則の概要"), ("yayoi", "弥生での処理"), ("jdl", "JDLで提案する処理"),
                           ("lost", "失われる情報・変更点"), ("question", "税理士に判断してほしいこと")):
            self.cards[key] = ui.DetailCard(title)
            body_layout.addWidget(self.cards[key])
        body_layout.addWidget(ui.SectionHeader("承認した場合の試算", "「試算する」の結果です。保存・承認はしません。"))
        self.trial_banner = ui.ModeBanner("trial")
        self.trial_banner.setVisible(False)
        body_layout.addWidget(self.trial_banner)
        self.preview_message = ui.MessageBar()
        body_layout.addWidget(self.preview_message)
        metrics = QHBoxLayout()
        self.metric_now = ui.MetricCard("現在", "—", "READY ／ BLOCK")
        self.metric_after = ui.MetricCard("承認した場合の予測", "—", "READY ／ BLOCK")
        self.metric_released = ui.MetricCard("READYになる仕訳", "—", "", "ready")
        self.metric_remaining = ui.MetricCard("BLOCKが残る仕訳", "—", "", "block")
        for card in (self.metric_now, self.metric_after, self.metric_released, self.metric_remaining):
            metrics.addWidget(card)
        body_layout.addLayout(metrics)
        self.preview_text = _label(rich=True)
        body_layout.addWidget(self.preview_text)
        body_layout.addWidget(_label("<b>READYになる仕訳</b>", rich=True))
        self.released_table = ui.JournalTable(RELEASED_COLUMNS, name="READYになる仕訳", numeric=(0, 1), stretch=(2,))
        self.released_table.setMinimumHeight(120)
        body_layout.addWidget(self.released_table)
        body_layout.addWidget(_label("<b>残るBLOCK条件</b>", rich=True))
        self.remaining_table = ui.JournalTable(REMAINING_COLUMNS, name="承認後もBLOCKが残る仕訳", numeric=(0, 1), stretch=(3, 4))
        self.remaining_table.setMinimumHeight(120)
        body_layout.addWidget(self.remaining_table)
        self.details_section, self.details_body = ui.collapsible_text("詳細・Evidence（承認できない場合の対応・関連項目・技術情報）")
        body_layout.addWidget(self.details_section)
        body_layout.addStretch(1)
        scroll.setWidget(body)
        right_layout.addWidget(scroll, 1)
        split.addWidget(right)
        split.setStretchFactor(1, 3)
        split.setSizes([300, 860])
        layout.addWidget(split, 1)
        self.overview = None
        self.entries: list[tuple] = []
        self._clear_preview("左の一覧から項目を選び、「試算する」を押してください。")
        return page

    def _choose_trailing(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "摘要末尾空白の記録（往復照合の記録）", "", "記録 (*.json)")
        if path:
            self.trailing_space_record = Path(path)
            self.refresh_items()

    def _choose_catalog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "運用方針の定義", "", "定義 (*.json)")
        if path:
            self.catalog_path = Path(path)
            self.refresh_items()

    def refresh_items(self) -> None:
        """The pending items (fast, < 1 s). Clears any trial: it belonged to the old list."""
        self.inputs_label.setText(
            "摘要末尾空白の記録: " + (self.trailing_space_record.name if self.trailing_space_record else "未選択")
            + "　運用方針の定義: " + (self.catalog_path.name if self.catalog_path else "未選択"))
        self.entries = []
        self.ledger_message.clear_message()
        try:
            self.overview = self.controller.approval_overview(
                self.company_id, self.source_path, trailing_space_record=self.trailing_space_record,
                catalog_path=self.catalog_path)
        except Exception as exc:  # shown on the screen, never swallowed
            log_local_exception("approval_overview", exc)
            self.overview = None
            self.item_list.clear()
            self.ledger_message.show_message("error", f"承認待ちの項目を読み込めませんでした: {type(exc).__name__}: {exc}"
                                             "\n何も保存していません。")
            self._show_entry(None)
            return
        explanations = self.overview["explanations"]
        for item, state in self.overview["items"]:
            self.entries.append(("item", item, state, explanations.get(item.item_id)))
        for guide in self.overview["guides"]:
            self.entries.append(("guide", guide))
        if self.overview["ledger_error"]:
            self.ledger_message.show_message("warning", "承認台帳を読めません。" + self.overview["ledger_error"]
                                             + "（記録・適用はできません。試算は引き続き使えます）")
        self.item_list.blockSignals(True)
        self.item_list.clear()
        for entry in self.entries:
            if entry[0] == "item":
                item = entry[1]
                text = f"{(entry[3].title if entry[3] else item.item_id)}\n{ui.badge_text('UNDECIDED', entry[2])}"
            else:
                text = f"{entry[1].title}\n別の承認経路（確認資料が未選択）"
            self.item_list.addItem(text)
            self.item_list.item(self.item_list.count() - 1).setData(Qt.ItemDataRole.AccessibleTextRole, text.replace("\n", "　"))
        self.item_list.blockSignals(False)
        self._clear_preview("左の一覧から項目を選び、「試算する」を押してください。")
        if self.entries:
            self.item_list.setCurrentRow(0)
        else:
            self._show_entry(None)

    def _show_item(self, row: int) -> None:
        self._show_entry(self.entries[row] if 0 <= row < len(self.entries) else None)

    def _show_entry(self, entry) -> None:
        for card in self.cards.values():
            card.setVisible(True)
        if entry is None:
            self.item_title.setText("項目がありません")
            self.item_badge.setVisible(False)
            for card in self.cards.values():
                card.set_lines(())
            self.details_body.setText("")
            return
        if entry[0] == "guide":
            guide = entry[1]
            self.item_title.setText(guide.title)
            self.item_badge.set_status("NOT_STARTED", "別の承認経路")
            self.item_badge.setVisible(True)
            self.cards["what"].set_lines(guide.lines)
            for key in ("yayoi", "jdl", "lost", "question"):
                self.cards[key].setVisible(False)
            self.details_body.setText("")
            return
        _, item, state, explanation = entry
        self.item_title.setText(explanation.title if explanation else item.item_id)
        self.item_badge.set_status("UNDECIDED", state)
        self.item_badge.setVisible(True)
        if explanation is None:
            self.cards["what"].set_lines((item.change,))
            for key in ("yayoi", "jdl", "lost", "question"):
                self.cards[key].set_lines(())
            self.details_body.setText("")
            return
        self.cards["what"].set_lines(explanation.what)
        self.cards["yayoi"].set_lines(explanation.yayoi)
        self.cards["jdl"].set_lines(explanation.jdl)
        self.cards["lost"].set_lines(explanation.lost)
        self.cards["question"].body.setText(
            escape(explanation.question)
            + (("<br><br><b>承認の前に必要な確認</b><br>" + "<br>".join("・" + escape(n) for n in explanation.needs))
               if explanation.needs else "")
            + f"<br><br><b>現在の状態</b>: {escape(state)}")
        self.cards["question"].setAccessibleDescription(explanation.question)
        sections = [("承認できない場合の対応候補", explanation.alternatives), ("関連する項目", explanation.related)]
        html = "".join(f"<p><b>{escape(t)}</b><br>" + "<br>".join("・" + escape(x) for x in lines) + "</p>"
                       for t, lines in sections if lines)
        html += "<p><b>技術情報（Evidence ID・会社ID・内容ID）</b></p><table cellspacing='4'>" + "".join(
            f"<tr><td><b>{escape(k)}</b></td><td>{escape(v)}</td></tr>" for k, v in explanation.technical) + "</table>"
        self.details_body.setText(html)

    def detail_text(self) -> str:
        """Everything the D0 detail shows (cards + the folded details), as plain text (tests, screen readers)."""
        parts = [self.item_title.text(), self.item_badge.text()]
        parts += [card.title.text() + "\n" + card.body.text() for card in self.cards.values() if card.isVisibleTo(self)]
        parts.append(self.details_body.text())
        return "\n".join(parts)

    @property
    def items(self):
        return tuple((e[1], e[2]) for e in self.entries if e[0] == "item")

    def selected_item_ids(self) -> tuple[str, ...]:
        rows = sorted(index.row() for index in self.item_list.selectedIndexes())
        return tuple(self.entries[r][1].item_id for r in rows if 0 <= r < len(self.entries) and self.entries[r][0] == "item")

    def _on_selection_changed(self) -> None:
        """A trial belongs to the items it was made for: any other selection clears it (and drops a running one)."""
        if self.preview_ids and self.selected_item_ids() != self.preview_ids:
            self._clear_preview("選択が変わったため、前の試算を消しました。「試算する」で、選択中の項目を試算してください。")

    def _clear_preview(self, message: str) -> None:
        if self.task.busy and self._running_kind() == "preview":
            self.task.invalidate()
        self.preview = self.preview_view = None
        self.preview_ids = ()
        self.trial_banner.setVisible(False)
        self.preview_text.setText("")
        self.released_table.setRowCount(0)
        self.remaining_table.setRowCount(0)
        for card in (self.metric_now, self.metric_after, self.metric_released, self.metric_remaining):
            card.set_value("—", card.hint.text())
        if message:
            self.preview_message.show_message("info", message)
        else:
            self.preview_message.clear_message()

    def _running_kind(self) -> str | None:
        return self._running if self.task.busy else None

    def _on_preview_clicked(self, _checked: bool = False) -> None:
        """The button's slot. `clicked` passes a bool (checked); it must never reach run_preview as the item list."""
        self.run_preview()

    def run_preview(self, item_ids=None) -> None:
        ids = tuple(item_ids) if isinstance(item_ids, (list, tuple, set, frozenset)) else self.selected_item_ids()
        if not ids:
            rows = sorted(index.row() for index in self.item_list.selectedIndexes()) or [self.item_list.currentRow()]
            if any(0 <= r < len(self.entries) and self.entries[r][0] == "guide" for r in rows):
                self.preview_message.show_message(
                    "info", "この項目は別の承認経路です。確認資料（記録・定義）を選ぶと、判断対象として表示されます。")
            else:
                self.preview_message.show_message("info", "左の一覧から、試算する項目を選んでください（複数選択できます）。")
            return
        if self.task.busy:
            self.preview_message.show_message("info", "別の処理が実行中です。終わってから試算してください。")
            return
        self._clear_preview("")
        self.preview_ids = ids
        self.preview_message.show_message("info", "試算中です…（全仕訳を再診断します。保存はしません）")
        controller, company, source = self.controller, self.company_id, self.source_path
        trailing, catalog = self.trailing_space_record, self.catalog_path
        self._running = "preview"
        self._start("preview", ids, lambda: controller.approval_preview_view(
            company, source, ids, trailing_space_record=trailing, catalog_path=catalog))

    def _show_preview(self, key, result) -> None:
        self._running = None
        if key[4] != self.preview_ids or tuple(self.selected_item_ids()) != self.preview_ids:
            self._clear_preview("選択が変わったため、試算の結果を表示しませんでした。")
            self._after_task()
            return
        self.preview, self.preview_view = result
        view = self.preview_view
        self.trial_banner.set_mode("trial", "対象: " + "、".join(self.preview_ids))
        self.trial_banner.setVisible(True)
        self.metric_now.set_value(f"{view.ready_before:,} ／ {view.block_before:,}", "READY ／ BLOCK", "neutral")
        self.metric_after.set_value(f"{view.ready_after:,} ／ {view.block_after:,}", "READY ／ BLOCK", "pending")
        self.metric_released.set_value(f"{len(view.released):,}件", "承認するとREADYになる", "ready")
        self.metric_remaining.set_value(f"{len(view.remaining):,}件", "承認してもBLOCKのまま", "block")
        lines = ([view.expected_note] if view.expected_note else []) + list(view.prerequisites) + list(view.notes)
        self.preview_text.setText("<br>".join("・" + escape(t) for t in lines))
        if view.problems:
            self.preview_message.show_message("error", "試算に問題があります: " + " / ".join(view.problems))
        else:
            self.preview_message.show_message("success", "試算しました。承認は記録しておらず、会社設定も承認台帳も変更していません。")
        self.released_table.set_rows([[(str(i.source_row), i.source_row), (i.voucher, _number(i.voucher)), i.date]
                                      for i in view.released])
        self.remaining_table.set_rows([[(str(i.source_row), i.source_row), (i.voucher, _number(i.voucher)), i.date,
                                        ("／".join(i.reasons), None, " ".join(i.codes)), "／".join(i.hints)]
                                       for i in view.remaining])
        self.d0_scroll.ensureWidgetVisible(self.trial_banner)   # bring the result into view (focus is not moved)
        self._after_task()

    # ------------------------------------------------------------ D2: unmigrated journals
    def _tracker_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        row = QHBoxLayout()
        self.refresh_button = ui.make_button("表示・更新", description="現在の診断から未移行の仕訳を表示します（保存しません）",
                                             shortcut="F5")
        self.refresh_button.clicked.connect(lambda _checked=False: self.load_overview())
        self.folder_button = ui.make_button("出力フォルダを指定…", description="出力が元データと別のフォルダにある場合に1回だけ指定します")
        self.folder_button.clicked.connect(lambda _checked=False: self._choose_folder())
        self.start_button = ui.make_button("状態管理を開始…", "primary",
                                           description="確認のうえ、出力の隣に管理表を1つ作成します（既存は上書きしません）")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(lambda _checked=False: self._on_start_clicked())
        self.export_button = ui.make_button("CSVで出力…", description="表示中の一覧を保存します（既存のファイルは上書きしません）",
                                            shortcut="Ctrl+E")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(lambda _checked=False: self._export())
        for widget in (self.refresh_button, self.folder_button, self.export_button):
            row.addWidget(widget)
        row.addStretch(1)
        row.addWidget(self.start_button)
        layout.addLayout(row)
        metrics = QHBoxLayout()
        self.metric_total = ui.MetricCard("元の仕訳", "—")
        self.metric_ready = ui.MetricCard("READY", "—", "変換できる", "ready")
        self.metric_blocked = ui.MetricCard("未移行（BLOCK）", "—", "変換できない", "block")
        self.metric_accountant = ui.MetricCard("税理士の判断が必要", "—", "", "pending")
        self.metric_state = ui.MetricCard("移行全体", "—", "", "neutral")
        for card in (self.metric_total, self.metric_ready, self.metric_blocked, self.metric_accountant, self.metric_state):
            metrics.addWidget(card)
        layout.addLayout(metrics)
        self.tracker_counts = _label("「表示・更新」（F5）で、現在の診断結果から未移行の仕訳を表示します"
                                     "（ファイルを選ぶ必要はありません）。", rich=True, name="muted")
        self.tracker_counts.setParent(page)
        self.tracker_counts.setVisible(False)    # the same facts are on the metric cards; kept as the summary text
        self.d2_message = ui.MessageBar()
        layout.addWidget(self.d2_message)
        self.run_banner = self.d2_message      # older name kept for the run messages
        run_row = QHBoxLayout()
        run_row.addWidget(QLabel("出力"))
        self.run_combo = QComboBox()
        self.run_combo.setAccessibleName("READY-only出力の選択")
        self.run_combo.activated.connect(lambda _index=0: self._on_run_chosen())
        run_row.addWidget(self.run_combo, 1)
        run_row.addWidget(QLabel("管理者名"))
        self.creator_edit = QLineEdit()
        self.creator_edit.setAccessibleName("管理者名（状態管理を開始する人）")
        self.creator_edit.setMaximumWidth(220)
        run_row.addWidget(self.creator_edit)
        filters = run_row
        filters.addWidget(QLabel("理由"))
        self.reason_filter = QComboBox()
        self.reason_filter.setAccessibleName("BLOCK理由で絞り込み")
        self.reason_filter.currentIndexChanged.connect(lambda _i=0: self._fill_tracker())
        filters.addWidget(self.reason_filter, 1)
        filters.addWidget(QLabel("状態"))
        self.status_filter = QComboBox()
        self.status_filter.setAccessibleName("対応状態で絞り込み")
        self.status_filter.currentIndexChanged.connect(lambda _i=0: self._fill_tracker())
        filters.addWidget(self.status_filter, 1)
        layout.addLayout(run_row)
        split = QSplitter(Qt.Orientation.Vertical)
        self.tracker_table = ui.JournalTable(TRACKER_COLUMNS, name="未移行の仕訳の一覧", numeric=(0, 1), stretch=(3, 4, 5, 7))
        self.tracker_table.currentCellChanged.connect(lambda r, *_: self._show_journal(r))
        split.addWidget(self.tracker_table)
        detail = QScrollArea()
        detail.setWidgetResizable(True)
        detail.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 8, 0)
        self.journal_card = ui.DetailCard("選択した仕訳")
        self.journal_detail = self.journal_card.body
        holder_layout.addWidget(self.journal_card)
        self.tracker_technical, self.tracker_technical_body = ui.collapsible_text(
            "技術情報（会社ID・READY-only出力・管理表の場所・BLOCKコード）")
        self.tracker_technical.toggle.toggled.connect(lambda _c=False: self._show_journal(self.tracker_table.currentRow()))
        holder_layout.addWidget(self.tracker_technical)
        self.open_issues = _label(rich=True)
        holder_layout.addWidget(self.open_issues)
        holder_layout.addStretch(1)
        detail.setWidget(holder)
        split.addWidget(detail)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 1)
        split.setSizes([340, 170])
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

    def _search_folders(self) -> list[Path]:
        return list(dict.fromkeys([self.source_path.parent, *self.scan_folders]))

    def load_overview(self) -> None:
        """Diagnose and list the unmigrated journals, find the READY-only run and open it (all read-only, background)."""
        self._tracker_loaded_once = True
        if self.task.busy:
            self._pending_overview = True     # e.g. a trial is running: load right after it
            self.d2_message.show_message("info", "別の処理が終わり次第、未移行の仕訳を表示します。")
            return
        self.d2_message.show_message("info", "診断しています…（全仕訳を再診断します。保存はしません）")
        controller, company, source, folders = self.controller, self.company_id, self.source_path, self._search_folders()

        def job():
            overview = controller.unmigrated_overview(company, source)
            runs = tuple(controller.find_ready_only_runs(company, source, folders))
            accepted = [r for r in runs if r.accepted]
            state = controller.open_migration_run(company, source, accepted[0].output) if len(accepted) == 1 else None
            return overview, runs, state

        self._running = "overview"
        self._start("overview", tuple(str(f) for f in folders), job)

    def _show_overview(self, key, result) -> None:
        self._running = None
        self.overview_data, runs, state = result
        self.runs = list(runs)
        accepted = [r for r in self.runs if r.accepted]
        self.run_combo.clear()
        for run in accepted:
            self.run_combo.addItem(run.output.name, str(run.output))
        self._apply_run_state(state, accepted)
        self._after_task()

    def _apply_run_state(self, state, accepted=None) -> None:
        from accounting_converter.application import unmigrated_view as uv

        self.run_state = state
        tracked = state is not None and state["state"] == "TRACKED"
        self.tracker = state["tracker"] if tracked else None
        self.final = state["final"] if tracked else None
        self.rows = uv.build_rows(self.overview_data["plan"], self.overview_data["items"], self.tracker)
        if state is None:
            self._run_message(accepted or [])
        self._render()

    def _run_message(self, accepted) -> None:
        rejected = [r for r in self.runs if not r.accepted]
        if len(accepted) > 1:
            self.d2_message.show_message("info", "READY-onlyの出力が複数あります。上の一覧から1つ選んでください（一覧の表示は読み取り専用です）。")
            return
        text = ("読み込み中の元データに対応するREADY-only出力が見つかっていません。診断結果を表示しています（閲覧のみ・状態管理は未開始）。"
                "出力が別のフォルダにある場合は「READY-only出力のフォルダを指定」を押してください。")
        if rejected:
            text += "\n見つかったが使わなかった出力: " + "、".join(f"{r.output.name}（{r.reason}）" for r in rejected)
        self.d2_message.show_message("warning", text)

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "READY-only出力が入っているフォルダ")
        if folder:
            self.add_folder(Path(folder))

    def add_folder(self, folder: Path) -> None:
        if folder not in self.scan_folders:
            self.scan_folders.append(Path(folder))
        self.load_overview()

    def _on_run_chosen(self) -> None:
        path = self.run_combo.currentData()
        if path:
            self.use_run(Path(path))

    def use_run(self, output: Path) -> None:
        """Verify the chosen run (existing SHA / audit checks) and load its tracker if it belongs to exactly this run."""
        if self.task.busy or self.overview_data is None:
            return
        self.d2_message.show_message("info", "出力を確認しています…（保存はしません）")
        controller, company, source = self.controller, self.company_id, self.source_path
        self._running = "run"
        self._start("run", (str(output),), lambda: controller.open_migration_run(company, source, Path(output)))

    def _show_run(self, key, result) -> None:
        self._running = None
        self._apply_run_state(result)
        self._after_task()

    def _render(self) -> None:
        data = self.overview_data
        if data is None:
            return
        accountant = sum(1 for r in self.rows if r.accountant)
        state = self.run_state["state"] if self.run_state else None
        self.metric_total.set_value(f"{data['total']:,}", "管理表: " + ("管理中（状態は管理表から）" if state == "TRACKED"
                                                                      else "未作成（表示のみ）"))
        self.metric_ready.set_value(f"{data['ready']:,}", "変換できる", "ready")
        self.metric_blocked.set_value(f"{data['blocked']:,}", "変換できない（未移行）", "block")
        self.metric_accountant.set_value(f"{accountant:,}", "仕訳", "pending")
        complete = bool(self.final and self.final["verdict"] == "MIGRATION_COMPLETE")
        self.metric_state.set_value("完了" if complete else "未完了", "" if complete else "未移行が残っています",
                                    "ready" if complete else "block")
        self.tracker_counts.setText(
            f"元の仕訳 {data['total']:,} ＝ READY {data['ready']:,} ＋ 未移行（BLOCK） <b>{data['blocked']:,}</b>"
            + f"　移行全体: <b>{'完了' if complete else '未完了'}</b>")
        self.tracker_table.setAccessibleDescription(self.tracker_counts.text().replace("<b>", "").replace("</b>", ""))
        if state is not None:
            self._show_state_message()
        reasons = sorted({title for r in self.rows for title in r.reasons})
        statuses = list(dict.fromkeys(r.status for r in self.rows))
        for combo, values in ((self.reason_filter, reasons), (self.status_filter, statuses)):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems([ALL, *values])
            if current in values:
                combo.setCurrentText(current)
            combo.blockSignals(False)
        issues = []
        if state == "TRACKED":
            issues = [f"{k}: {v}" for k, v in self.run_state["integrity"]["problems"].items() if v] + self.final["reasons"]
        elif self.run_state is not None:
            issues = list(self.run_state["problems"])
        self.open_issues.setText("<b>未解決事項</b><br>" + "<br>".join(escape(str(i)) for i in issues) if issues else "")
        self._update_enabled()
        self._fill_tracker()

    def _show_state_message(self) -> None:
        state, problems = self.run_state["state"], self.run_state["problems"]
        name = Path(self.run_state["output"]).name
        detail = "".join("\n・" + str(p) for p in problems)
        if state == "TRACKED":
            self.d2_message.show_message("success", f"出力（{name}）と管理表が一致しています。状態は管理表から読み込んでいます。")
        elif state == "NO_TRACKER":
            self.d2_message.show_message("info", f"出力（{name}）を確認しました。状態管理はまだ始まっていません（閲覧のみ・状態はすべて「未対応」）。"
                                         "「状態管理を開始」を押すと、出力の隣に管理表を1つ作成します（既存の管理表は上書きしません）。")
        elif state == "REJECTED":
            self.d2_message.show_message("error", f"この出力は使えません（検証に失敗）。診断結果だけを表示しています。{detail}")
        elif state == "TRACKER_MISMATCH":
            self.d2_message.show_message("error", f"出力（{name}）の隣にある管理表は、この出力と対応しないため使いません。"
                                         f"状態は読み込んでいません（管理表は変更・初期化しません）。{detail}")
        else:
            self.d2_message.show_message("error", f"管理表を読み込めません。診断結果だけを表示しています。{detail}")

    def _fill_tracker(self) -> None:
        reason, status = self.reason_filter.currentText(), self.status_filter.currentText()
        self._shown = [r for r in self.rows if (reason in ("", ALL) or reason in r.reasons)
                       and (status in ("", ALL) or r.status == status)]
        rows = []
        for r in self._shown:
            badge = ui.badge_text(ui.TRACKER_STATUS.get(r.status_code, "NOT_STARTED"), r.status)
            rows.append([(str(r.source_row), r.source_row), (r.voucher, _number(r.voucher)), r.date,
                         (" / ".join(r.reasons), None, " ".join(r.codes)), " / ".join(r.accountant) or "—",
                         " / ".join(r.technical) or "—", (badge, r.status), r.next_steps[0] if r.next_steps else ""])
        self.tracker_table.set_rows(rows)
        if rows:
            self.tracker_table.selectRow(0)       # the first journal's detail is shown without another click
            self._show_journal(0)
        else:
            self.journal_card.set_lines(())

    def _row_at(self, row: int):
        item = self.tracker_table.item(row, 0)
        if item is None:
            return None
        source_row = int(item.text())
        return next((r for r in self._shown if r.source_row == source_row), None)

    def _show_journal(self, row: int) -> None:
        r = self._row_at(row) if row >= 0 else None
        if r is None:
            return
        fields = [("元の仕訳", f"行{r.source_row}・伝票{r.voucher}・{r.date}・借方合計 {Decimal(r.debit_total):,}円"),
                  ("BLOCK理由", "／".join(r.reasons)), ("対応状態", r.status),
                  ("必要な税理士判断", "／".join(r.accountant) or "（税理士の判断で解消する条件はありません）"),
                  ("技術的に残る問題", "／".join(r.technical) or "—"), ("次に必要な作業", "\n".join(r.next_steps))]
        if r.plan or r.owner:
            fields.extend((("対応方針", r.plan or "—"), ("担当者", r.owner or "—")))
        self.journal_card.title.setText(f"選択した仕訳（行{r.source_row}）")
        self.journal_detail.setText("<table cellspacing='4'>" + "".join(
            f"<tr><td valign='top'><b>{escape(k)}</b></td><td>{escape(str(v)).replace(chr(10), '<br>')}</td></tr>"
            for k, v in fields) + "</table>")
        self.journal_card.setAccessibleDescription(" ".join(f"{k}: {v}" for k, v in fields))
        tech = [("BLOCKコード", " ".join(r.codes)), ("会社ID", self.company_id)]
        plan = self.overview_data["plan"] if self.overview_data else None
        if plan is not None:
            tech.append(("元データ（SHA-256）", plan.source_sha256))
        if self.run_state is not None:
            tech += [("READY-only出力", str(self.run_state["output"])), ("管理表の場所", str(self.run_state["tracker_path"])),
                     ("出力の状態", self.run_state["state"])]
        self.tracker_technical_body.setText("<table cellspacing='4'>" + "".join(
            f"<tr><td><b>{escape(k)}</b></td><td>{escape(str(v))}</td></tr>" for k, v in tech) + "</table>")

    def _on_start_clicked(self) -> None:
        if not (self.run_state and self.run_state["state"] == "NO_TRACKER") or self.task.busy:
            return
        target = self.run_state["tracker_path"]
        answer = QMessageBox.question(
            self, "状態管理を開始する",
            f"状態管理を開始します。\n\n管理表を次の場所に1つ作成します（既存の管理表は上書きしません）:\n{target}\n\n"
            f"未移行 {self.overview_data['blocked']}仕訳が、すべて「未対応」で登録されます。READY／BLOCKの判定と承認は変わりません。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            self.start_tracking(self.creator_edit.text())

    def start_tracking(self, created_by: str) -> bool:
        """Create the tracker (after the explicit confirmation; on the UI thread, it writes), then reopen it."""
        try:
            self.controller.start_migration_tracking(self.company_id, self.source_path, self.run_state["output"],
                                                     created_by, explicitly_confirmed=True)
        except Exception as exc:
            log_local_exception("start_migration_tracking", exc)
            self.d2_message.show_message("error", f"管理表を作成できませんでした: {type(exc).__name__}: {exc}\n何も変更していません。")
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
        self.d2_message.show_message("success", f"一覧を保存しました: {path.name}（{len(self.rows)}仕訳）")
        return True
