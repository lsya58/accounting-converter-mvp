"""変換の準備状況: what is missing, what the user can do, and the buttons that reach the EXISTING screens.

The READY / BLOCK decision is the production assessment (controller.company_resolution_report); this screen only
displays it. A button exists only where an existing screen can resolve the item; Evidence gaps and tax-accountant
decisions have none. After any action the report is recomputed from the saved settings ("再診断").
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QDateEdit, QDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from accounting_converter.application import readiness_breakdown as breakdown
from accounting_converter.application import resolution_report as rr


def where_text(item) -> str:
    parts = list(item.where)
    return "・".join(parts)


def need_tags(item) -> list[str]:
    tags = []
    if item.app_resolvable:
        tags.append("アプリ内で対応できます")
    if item.jdl_work:
        tags.append("JDL側の作業が必要")
    if item.tax_accountant:
        tags.append("税理士の判断・承認が必要")
    if item.technical_evidence:
        tags.append("追加の実機確認（技術Evidence）が必要")
    return tags


def code_lines(codes) -> list[str]:
    return [f"{breakdown.describe(code)[0]}: {code}" for code in codes]


class VoucherSplitApprovalDialog(QDialog):
    """Shows the split the existing rule would write and records the tax accountant's agreement (explicit action)."""

    def __init__(self, controller, company_id: str, source_path, journal_ids, parent=None) -> None:
        super().__init__(parent)
        self.controller, self.company_id = controller, company_id
        self.saved = False
        self.setWindowTitle("伝票分割の承認")
        self.setMinimumSize(720, 480)
        self.resize(900, 640)
        if self.screen():
            size = self.screen().availableGeometry().size()
            self.resize(min(900, size.width()), min(640, size.height()))
        layout = QVBoxLayout(self)
        self.briefs = ()
        self.limit = None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.limit, self.briefs = controller.voucher_split_briefs(company_id, source_path, journal_ids)
        finally:
            QApplication.restoreOverrideCursor()
        intro = QLabel(
            f"振替伝票入力行数 {self.limit}行以内 の設定で、次の{len(self.briefs)}仕訳はJDLの1伝票に入りきりません。"
            "JDLへは複数の伝票に分けて取り込みます（元の1伝票としての一体性だけが変わります）。<br>"
            "<b>変わらないもの</b>: 借方・貸方の各明細（科目・補助・税区分・税額・金額・摘要・元の行番号）、日付、貸借の一致。"
            "相手科目の金額だけが各伝票の合計額に分かれ、合計は元の金額と一致します（再構成検査で確認済み）。<br>"
            "分割後の各伝票の形は、JDL実機で確認済みです。")
        intro.setTextFormat(Qt.TextFormat.RichText)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        table = QTableWidget(len(self.briefs), 7)
        table.setHorizontalHeaderLabels(["仕訳", "元の行数", "分割後の伝票", "各伝票の行数", "相手科目の金額", "税額（元→分割後合計）", "再構成検査"])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setWordWrap(True)
        for row, brief in enumerate(self.briefs):
            if not brief.get("split"):
                values = [rr.short_id(brief["journal"]), "", "分割できません", brief.get("why_not", ""), "", "", ""]
            else:
                parts = brief["parts"]
                values = [rr.short_id(brief["journal"]), str(brief["original"]["physical_rows"]), f"{len(parts)}伝票",
                          " / ".join(str(p["jdl_rows"]) for p in parts), " / ".join(f"{int(p['counterpart_amount']):,}" for p in parts),
                          f"{int(float(brief['original']['explicit_tax'])):,} → {sum(int(float(p['explicit_tax'])) for p in parts):,}",
                          "一致" if brief["rebuilds_original"] else "不一致"]
            for col, value in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(value))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.resizeRowsToContents()
        layout.addWidget(table, 1)
        scope = QLabel(
            "<b>この承認の適用範囲</b>: この会社設定・振替伝票入力行数 " + f"{self.limit}行以内・分割規則 {rr_rule()} に限ります。"
            "行数を変更すると承認は無効になり、記録し直しが必要です（16行と64行の承認は共用しません）。<br>"
            "承認しても、分割後の伝票に別のBLOCK理由があれば変換されません。承認は正式診断の結果を直接READYにしません。")
        scope.setTextFormat(Qt.TextFormat.RichText)
        scope.setWordWrap(True)
        scope.setObjectName("warningCard")
        layout.addWidget(scope)
        form = QFormLayout()
        self.approver = QLineEdit()
        self.accountant = QLineEdit()
        self.reference = QLineEdit()
        self.reference.setPlaceholderText("例: メール・LINEの日付と件名、書面番号など")
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.date.setDate(date.today())
        form.addRow("記録する人（あなた）", self.approver)
        form.addRow("了承した税理士", self.accountant)
        form.addRow("了承の記録（参照）", self.reference)
        form.addRow("了承日", self.date)
        layout.addLayout(form)
        self.confirm = QCheckBox("上記の内容について、税理士が分割を了承したことを確認しました")
        layout.addWidget(self.confirm)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        self.save_button = QPushButton("承認を記録")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)
        for widget in (self.approver, self.accountant, self.reference):
            widget.textChanged.connect(self._update)
        self.confirm.toggled.connect(self._update)
        self._update()

    def _complete(self) -> bool:
        return bool(self.approver.text().strip() and self.accountant.text().strip() and self.reference.text().strip()
                    and self.confirm.isChecked() and all(b.get("split") for b in self.briefs) and self.briefs
                    and all(b.get("rebuilds_original") for b in self.briefs))

    def _update(self) -> None:
        self.save_button.setEnabled(self._complete())

    def _save(self) -> None:
        if not self._complete():
            return
        qdate = self.date.date()
        state = self.controller.approve_voucher_split(
            self.company_id, human_approver=self.approver.text(), tax_accountant=self.accountant.text(),
            signoff_reference=self.reference.text(), signoff_date=date(qdate.year(), qdate.month(), qdate.day()),
            explicitly_confirmed=self.confirm.isChecked())
        if state.developer_error is not None:
            QMessageBox.warning(self, "承認を記録できませんでした", state.user_message)
            return
        self.saved = True
        QMessageBox.information(self, "承認を記録しました", "会社設定に保存しました。続けて正式な診断で結果を確認します。")
        self.accept()


def rr_rule() -> str:
    from accounting_converter.application.voucher_split import RULE

    return RULE


class ResolutionCenterDialog(QDialog):
    """変換の準備状況 (read-only report + buttons into the existing screens)."""

    def __init__(self, controller, company_id: str, source_path, callbacks: dict | None = None, parent=None,
                 *, unsaved_changes: bool = False) -> None:
        super().__init__(parent)
        self.controller, self.company_id, self.source_path = controller, company_id, source_path
        self.callbacks = callbacks or {}
        self.goto: str | None = None  # a tab key the opener should show after this dialog closes
        self.report = None
        self.comparison = None
        self.setWindowTitle("変換の準備状況")
        self.setMinimumSize(760, 480)
        self.resize(1040, 700)
        if self.screen():
            size = self.screen().availableGeometry().size()
            self.resize(min(1040, size.width()), min(700, size.height()))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.summary)
        self.notice = QLabel("保存済みの設定による正式な判定です。" + (
            "<b>この画面の未保存の変更は含まれていません。</b>" if unsaved_changes else ""))
        self.notice.setTextFormat(Qt.TextFormat.RichText)
        self.notice.setObjectName("warningCard" if unsaved_changes else "muted")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.completed = QLabel()
        self.completed.setObjectName("muted")
        self.completed.setWordWrap(True)
        layout.addWidget(self.completed)
        self.alternative = QLabel()
        self.alternative.setWordWrap(True)
        self.alternative.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.alternative)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.item_list = QListWidget()
        self.item_list.setMinimumWidth(260)
        self.item_list.currentRowChanged.connect(self._show_item)
        split.addWidget(self.item_list)
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.detail_page = QWidget()
        self.detail_layout = QVBoxLayout(self.detail_page)
        self.detail_layout.setContentsMargins(8, 4, 8, 4)
        self.detail_text = QLabel()
        self.detail_text.setWordWrap(True)
        self.detail_text.setTextFormat(Qt.TextFormat.RichText)
        self.detail_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detail_layout.addWidget(self.detail_text)
        self.action_button = QPushButton()
        self.action_button.setObjectName("primaryButton")
        self.action_button.clicked.connect(self._do_action)
        self.detail_layout.addWidget(self.action_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.why_no_button = QLabel()
        self.why_no_button.setObjectName("muted")
        self.why_no_button.setWordWrap(True)
        self.detail_layout.addWidget(self.why_no_button)
        self.show_details = QCheckBox("詳細（BLOCKコード・仕訳別）を表示")
        self.show_details.toggled.connect(self._toggle_details)
        self.detail_layout.addWidget(self.show_details)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setVisible(False)
        self.details.setMinimumHeight(160)
        self.detail_layout.addWidget(self.details)
        self.detail_layout.addStretch(1)
        self.detail_scroll.setWidget(self.detail_page)
        split.addWidget(self.detail_scroll)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)
        footer = QHBoxLayout()
        self.status = QLabel()
        self.status.setObjectName("muted")
        footer.addWidget(self.status, 1)
        self.rediagnose_button = QPushButton("再診断")
        self.rediagnose_button.clicked.connect(self.refresh)
        close = QPushButton("閉じる")
        close.clicked.connect(self.accept)
        footer.addWidget(self.rediagnose_button)
        footer.addWidget(close)
        layout.addLayout(footer)
        self.refresh()

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        keep = self._current_key()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.report, self.comparison = self.controller.company_resolution_report(self.company_id, self.source_path)
        except Exception as exc:  # the screen must not invent a state it could not compute
            self.report = None
            QApplication.restoreOverrideCursor()
            self.summary.setText("診断できませんでした。入力ファイルと会社設定を確認してください。")
            self.status.setText(type(exc).__name__)
            self.item_list.clear()
            self.detail_text.setText("")
            self.action_button.setVisible(False)
            return
        QApplication.restoreOverrideCursor()
        report = self.report
        self.summary.setText(
            f"<b>変換できる仕訳 {report.ready:,} / {report.total:,}件</b>　確認が必要な仕訳 {report.blocked:,}件　"
            f"対応項目 {len(report.items)}種類<br>次の操作: {report.next_step}")
        self.completed.setText("完了している項目: " + ("、".join(report.completed) if report.completed else "なし"))
        alt = report.alternative
        if alt is None:
            self.alternative.setText("")
            self.alternative.setVisible(False)
        else:
            self.alternative.setVisible(True)
            self.alternative.setObjectName("warningCard")
            delta = alt.ready - report.ready
            self.alternative.setText(
                f"<b>設定によって変わる結果（試算）</b>: 振替伝票入力行数を{alt.limit}行にすると、変換できる仕訳は {alt.ready:,}件"
                f"（{delta:+,}）。新たに変換できる仕訳 {len(alt.released)}件、変換できなくなる仕訳 {len(alt.lost)}件、残るBLOCK {alt.still_blocked}件。"
                "これは試算です。JDLの実際の設定と一致させる必要があり、設定を変えると承認の記録し直しが必要です。")
            self.alternative.style().unpolish(self.alternative)
            self.alternative.style().polish(self.alternative)
        self.item_list.blockSignals(True)
        self.item_list.clear()
        for item in report.items:
            row = QListWidgetItem(f"{item.title}（{len(item.journals)}仕訳）")
            row.setData(Qt.ItemDataRole.UserRole, item.key)
            self.item_list.addItem(row)
        self.item_list.blockSignals(False)
        if report.items:
            index = next((i for i, it in enumerate(report.items) if it.key == keep), 0)
            self.item_list.setCurrentRow(index)
            self._show_item(index)
        else:
            self.detail_text.setText("確認が必要な項目はありません。すべての仕訳が変換できます。")
            self.action_button.setVisible(False)
            self.why_no_button.setText("")
            self.details.setPlainText("")
        approved = not report.split_policy_problems
        self.status.setText("再診断しました（保存済み設定）。" + ("伝票分割: 承認記録あり。" if approved else ""))

    def _current_key(self) -> str | None:
        row = self.item_list.currentRow() if self.report is not None else -1
        if row < 0 or self.report is None or row >= len(self.report.items):
            return None
        return self.report.items[row].key

    def _current_item(self):
        key = self._current_key()
        return self.report.item(key) if key and self.report else None

    # ------------------------------------------------------------------ display
    def _show_item(self, row: int) -> None:
        item = self._current_item()
        if item is None:
            return
        report = self.report
        tags = need_tags(item)
        parts = [
            f"<h3>{item.title}</h3>",
            f"<p><b>何が問題か</b><br>{item.problem or '—'}</p>",
            f"<p><b>影響する仕訳</b>: {len(item.journals)}仕訳（これだけで止まっている仕訳 {item.only_this}）<br>"
            + "、".join(item.journals[:30]) + (" ほか" if len(item.journals) > 30 else "") + "</p>",
            f"<p><b>確認済みのこと</b><br>{item.confirmed or '（このBLOCKに関して確認済みの事項はありません）'}</p>",
            f"<p><b>やること</b><br>{item.todo}</p>",
            f"<p><b>作業の場所</b>: {where_text(item)}<br><b>必要なこと</b>: {'、'.join(tags) if tags else 'なし'}</p>",
            "<p><b>対応後</b><br>保存後に「再診断」で正式な判定をやり直します。この画面の操作だけでは変換可能になりません。</p>",
        ]
        notes = [n for j in report.journals if j.short_id in item.journals[:6] for n in j.notes]
        if notes:
            parts.append("<p><b>仕訳ごとの注意</b><br>" + "<br>".join(dict.fromkeys(notes)) + "</p>")
        self.detail_text.setText("".join(parts))
        # a button exists only where an existing screen can resolve the item
        label = item.action_label
        enabled = item.action != rr.ACT_NONE and bool(label)
        self.action_button.setVisible(enabled)
        self.action_button.setText(label)
        self.action_button.setEnabled(enabled and self._can_do(item))
        if not enabled:
            self.why_no_button.setText(
                "この項目は、画面の操作だけでは解決できません（承認ボタンはありません）。" if item.technical_evidence or item.tax_accountant else "")
        else:
            self.why_no_button.setText("" if self._can_do(item) else "この操作は現在の画面からは開けません。")
        lines = []
        for journal in report.journals:
            if journal.short_id in item.journals:
                lines.append(f"仕訳 {journal.short_id}: " + " / ".join(journal.codes))
        self.details.setPlainText(
            "BLOCKコード（この項目）:\n" + "\n".join(code_lines(item.codes)) + "\n\n仕訳別（その仕訳のすべてのBLOCKコード）:\n" + "\n".join(lines))

    def _can_do(self, item) -> bool:
        return item.action == rr.ACT_SPLIT or item.action in self.callbacks

    def _toggle_details(self, on: bool) -> None:
        self.details.setVisible(on)

    # ------------------------------------------------------------------ actions
    def _do_action(self) -> None:
        item = self._current_item()
        if item is None:
            return
        if item.action == rr.ACT_SPLIT:
            self._split_approval(item)
            return
        callback = self.callbacks.get(item.action)
        if callback is None:
            return
        if isinstance(callback, str):
            self.goto = callback  # a tab key / flow name: the opener continues there once this dialog is closed
            self.accept()
            return
        callback()
        self.refresh()

    def _split_approval(self, item) -> None:
        dialog = VoucherSplitApprovalDialog(self.controller, self.company_id, self.source_path, item.journals, self)
        dialog.exec()
        if dialog.saved:
            self.refresh()
