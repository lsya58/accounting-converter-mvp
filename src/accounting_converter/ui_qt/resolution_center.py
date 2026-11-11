"""変換の準備状況: what is missing, what the user can do, and the buttons that reach the EXISTING screens.

The READY / BLOCK decision is the production assessment (controller.company_resolution_report); this screen only
displays it. A button exists only where an existing screen can resolve the item; Evidence gaps and tax-accountant
decisions have none. After any action the report is recomputed from the saved settings ("再診断").
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from html import escape
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QDateEdit, QDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from accounting_converter.application import readiness_breakdown as breakdown
from accounting_converter.application import resolution_report as rr
from accounting_converter.infrastructure.local_diagnostic_log import log_local_exception


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


SHORT_TITLES = {
    rr.NONCREDIT_KEY: "税区分の確認が必要", rr.NEGATIVE_KEY: "負の金額への対応",
    rr.OVER_OTHER_KEY: "行数・分割規則の問題", rr.EVIDENCE_KEY: "未検証の仕訳形状",
    "HUMAN:VOUCHER_SPLIT_APPROVAL": "伝票分割の承認",
    "SYSTEM_EVIDENCE:CLOSING_ENTRY_REPRESENTATION": "決算区分の確認",
    "HUMAN:ACCOUNT_MAPPING": "科目の確認", "HUMAN:SUBACCOUNT_MAPPING": "補助科目の確認",
    "HUMAN:TAX_MAPPING": "税区分の確認",
}


def short_title(item) -> str:
    return SHORT_TITLES.get(item.key, item.title)


def _kv_table(rows) -> str:
    """Two-column key/value table: wraps at any width (no wide table that would need horizontal scroll)."""
    cell = "style='padding:2px 8px; vertical-align:top'"
    return ("<table style='border-collapse:collapse' width='100%'>"
            + "".join(f"<tr><td {cell} width='28%'><b>{escape(k)}</b></td><td {cell}>{escape(v)}</td></tr>" for k, v in rows)
            + "</table>")


def _code_names(codes) -> str:
    """User names of blocker codes. The raw codes (long words that cannot wrap) stay in the 詳細 panel."""
    return " / ".join(dict.fromkeys(rr.rule_for_code(code).title for code in codes))


def _technical_text(outlook) -> str:
    if outlook is None:
        return "—"
    if not outlook.computed:
        return "未評価（この設定は控除不可の実機確認の範囲外）。現在の理由: " + _code_names(outlook.remaining)
    parts = []
    if outlook.derived:
        parts.append(f"税区分が未確定のため評価できない税・形の確認 {len(outlook.derived)}件"
                     "（承認記録があると仮定した試算では解消）")
    remaining = outlook.technical_remaining
    parts.append(f"残る実機Evidence不足: {len(remaining)}件（{_code_names(remaining)}）" if remaining
                 else "残る実機Evidence不足: なし（試算）")
    return "。".join(parts)


def _approval_text(journal) -> str:
    """Only a saved sign-off that names THIS journal counts. Another journal's sign-off is never shown here."""
    if not journal.approvals:
        return "なし（承認は仕訳ごとです。同じ税区分の別の仕訳の承認はこの仕訳に適用されません）"
    return " / ".join(f"{record.get('signoff_date', '')} {record.get('tax_accountant', '')}（{record.get('signoff_reference', '')}）"
                      for _identity, record in journal.approvals)


def tax_review_summary_html(report, item) -> str:
    """Per journal: the five facts the tax accountant needs first. Values are escaped; nothing here is a verdict."""
    from accounting_converter.adapters.output.jdl import scoped_evidence

    blocks = []
    for journal in report.journals:
        if journal.short_id not in item.journals or not journal.tax_review:
            continue
        lines = journal.tax_review
        identities = " / ".join(dict.fromkeys(ln.tax_identity for ln in lines))
        rates = " / ".join(dict.fromkeys(ln.rate for ln in lines))
        o = journal.outlook
        rows = [
            ("元の税区分", f"控除不可（{identities}）・{len(lines)}明細"),
            ("税率", rates),
            ("確認が必要な理由", "仕入税額控除が「控除不可」で税額0です。JDLには同じ区分がありません。"
                              "入力内容の確認が必要です（誤りと確定したわけではありません）。"),
            ("税理士が判断すること", "取引の実態を確認し、(a) 控除不可のままJDLでは非仕入（税区空欄）として扱うか、"
                                 "(b) 元の税区分を修正するか（弥生で修正して出力し直し、再診断。アプリ内の修正機能はありません）。"),
            ("技術的に残っている問題", _technical_text(o)),
            ("税理士の承認記録（この仕訳）", _approval_text(journal)),
            ("判断後の見通し", o.headline if o is not None else "—"),
        ]
        blocks.append(f"<p style='margin-top:8px'><b>仕訳 {escape(journal.short_id)}</b>（{escape(lines[0].date)}）</p>"
                      + _kv_table(rows))
    if not blocks:
        return ""
    limit = scoped_evidence.SCOPE_VOUCHER_ROW_LIMIT
    return ("<p><b>仕訳ごとの要点</b>（元データは変更しません。承認ボタンはありません）</p>" + "".join(blocks)
            + "<p>BLOCKコードの一覧は「詳細（BLOCKコード・仕訳別）を表示」にあります。<br>"
            f"控除不可の実機確認は振替伝票入力行数 {limit}行の設定だけです。別の行数ではこの見通しは成り立ちません。</p>")


def tax_review_detail_html(report, item) -> str:
    """Opened on demand: every flagged source line as Yayoi recorded it, the journal's other tax categories,
    what JDL keeps, the points to check and every blocker code."""
    from accounting_converter.application import tax_review_facts as facts

    blocks = []
    for journal in report.journals:
        if journal.short_id not in item.journals or not journal.tax_review:
            continue
        blocks.append(f"<p style='margin-top:8px'><b>仕訳 {escape(journal.short_id)} の元の明細</b></p>")
        for ln in journal.tax_review:
            blocks.append(_kv_table((
                ("元の行 / 弥生の仕訳番号", f"行{ln.source_row} / {ln.yayoi_journal_number or '—'}"),
                ("日付", ln.date), ("借貸", {"DEBIT": "借方", "CREDIT": "貸方"}.get(ln.side, ln.side)),
                ("科目 / 補助", ln.account + (f" / {ln.sub_account}" if ln.sub_account else "")),
                ("摘要", ln.description or "（摘要なし）"),
                ("金額（税込）", ln.amount_tax_included),
                ("弥生の税区分（元の値）", ln.tax_identity),
                ("税率 / 税計算", f"{ln.rate} / {ln.tax_calculation or '—'}"),
                ("請求書区分 / 控除割合", f"{ln.invoice_class or '—'} / {ln.purchase_credit or '—'}"),
                ("税額", ln.tax_amount or "—"),
            )))
        if journal.other_tax:
            blocks.append("<p>同じ仕訳のその他の税区分: " + escape(
                " / ".join(f"{name} {count}明細" for name, count in journal.other_tax)) + "</p>")
        o = journal.outlook
        if o is not None:
            blocks.append(_kv_table((
                ("控除不可に直接起因", _code_names(o.direct) or "なし"),
                ("税区分の確定で再評価されるもの", f"{len(o.derived)}件（{_code_names(o.derived)}）" if o.derived else "なし"),
                ("税区分と無関係", _code_names(o.independent) or "なし"),
                ("判断後も残る（試算）" if o.computed else "残る（未評価）", _code_names(o.remaining) or "なし"),
                ("試算の前提", o.basis),
            )))
    if not blocks:
        return ""
    points = "".join(f"<li>{escape(p)}</li>" for p in facts.CHECK_POINTS)
    return ("".join(blocks)
            + f"<p><b>JDLでの扱い</b>: {escape(facts.JDL_COUNTERPART_NONCREDIT)}<br>"
            f"<b>JDLに残らない情報</b>: {escape(facts.NOT_KEPT_IN_JDL_NONCREDIT)}<br>"
            "監査記録（外部ファイル）に残ることは、JDL内に残ることとは別です。</p>"
            f"<p><b>税理士に確認いただきたい点</b></p><ul>{points}</ul>")


def next_priority(report) -> str:
    alt = report.alternative
    if alt is not None and alt.ready > report.ready:
        return f"まず{report.saved_limit}行と{alt.limit}行の結果を比較"
    if report.items:
        item = next((i for i in report.items if i.app_resolvable), report.items[0])
        return f"次にすること: {short_title(item)}"
    return "追加の対応はありません"


class VoucherSplitApprovalDialog(QDialog):
    """Shows the split the existing rule would write and records the tax accountant's agreement (explicit action)."""

    def __init__(self, controller, company_id: str, source_path, journal_ids, parent=None) -> None:
        super().__init__(parent)
        self.controller, self.company_id = controller, company_id
        self.saved = False
        self.setWindowTitle("伝票分割の承認")
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
        requested = tuple(journal_ids)
        returned = tuple(rr.short_id(b["journal"]) for b in self.briefs)
        self._all_requested_present = (len(requested) == len(set(requested)) == len(returned)
                                       and set(requested) == set(returned))
        ready_briefs = [b for b in self.briefs if b.get("split")]
        total_parts = sum(len(b["parts"]) for b in ready_briefs)
        self.intro = QLabel(f"{len(self.briefs)}仕訳の伝票分割を確認　|　{len(ready_briefs)}伝票 → {total_parts}伝票"
                            f"　|　JDL設定 {self.limit}行")
        self.intro.setObjectName("sectionTitle")
        self.intro.setWordWrap(True)
        layout.addWidget(self.intro)
        self.missing_notice = QLabel("対象仕訳をすべて確認できません。最新の診断から開き直してください。")
        self.missing_notice.setObjectName("warningCard")
        self.missing_notice.setVisible(not self._all_requested_present)
        layout.addWidget(self.missing_notice)
        self.scope = QLabel(
            f"<b>一括承認:</b> この会社・{self.limit}行・分割規則に適用。今後の該当仕訳にも適用されます。")
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)
        self.scope_more = QLabel(
            f"分割規則: {rr_rule()}。行数を変更すると承認は無効になり、記録し直しが必要です。"
            "16行と64行では承認を共有しません。ほかのBLOCKが残る仕訳は承認後も変換できず、正式診断で再確認します。")
        self.scope_more.setWordWrap(True)
        self.scope_more.setVisible(False)
        layout.addWidget(self.scope_more)
        center = QSplitter(Qt.Orientation.Horizontal)
        self.journal_list = QListWidget()
        self.journal_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.journal_list.setMinimumWidth(145)
        for brief in self.briefs:
            label = rr.short_id(brief["journal"])
            self.journal_list.addItem(label if brief.get("split") else label + "（分割不可）")
        center.addWidget(self.journal_list)
        self.split_page = QWidget()
        split_layout = QVBoxLayout(self.split_page)
        self.selected_summary = QLabel()
        self.selected_summary.setWordWrap(True)
        split_layout.addWidget(self.selected_summary)
        self.parts_table = QTableWidget(0, 5)
        self.parts_table.setHorizontalHeaderLabels(["伝票", "元の行", "出力行", "相手科目の金額", "税額"])
        self.parts_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.parts_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        split_layout.addWidget(self.parts_table, 1)
        self.split_details_toggle = QCheckBox("変更点・保持情報・承認範囲を表示")
        split_layout.addWidget(self.split_details_toggle)
        self.split_details = QLabel()
        self.split_details.setWordWrap(True)
        self.split_details.setVisible(False)
        self.split_details_toggle.toggled.connect(self.split_details.setVisible)
        self.split_details_toggle.toggled.connect(self.scope_more.setVisible)
        split_layout.addWidget(self.split_details)
        center.addWidget(self.split_page)
        center.setStretchFactor(1, 3)
        center.setSizes([170, 700])
        layout.addWidget(center, 1)
        self._viewed: set[int] = set()
        self.journal_list.currentRowChanged.connect(self._show_split)
        self.approval_toggle = QCheckBox("承認の記録を入力")
        layout.addWidget(self.approval_toggle)
        self.approval_panel = QWidget()
        approval_layout = QVBoxLayout(self.approval_panel)
        approval_layout.setContentsMargins(0, 0, 0, 0)
        form = QGridLayout()
        self.approver = QLineEdit()
        self.accountant = QLineEdit()
        self.reference = QLineEdit()
        self.reference.setPlaceholderText("例: メール・LINEの日付と件名、書面番号など")
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.date.setDate(date.today())
        for row, column, label, widget in (
            (0, 0, "記録する人", self.approver), (0, 2, "税理士", self.accountant),
            (1, 0, "承認参照", self.reference), (1, 2, "承認日", self.date),
        ):
            form.addWidget(QLabel(label), row, column)
            form.addWidget(widget, row, column + 1)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)
        approval_layout.addLayout(form)
        self.review_progress = QLabel()
        self.confirm = QCheckBox("対象を確認し、税理士の一括承認を記録する")
        review_row = QHBoxLayout()
        review_row.addWidget(self.confirm)
        review_row.addStretch(1)
        review_row.addWidget(self.review_progress)
        approval_layout.addLayout(review_row)
        self.approval_panel.setVisible(False)
        self.approval_toggle.toggled.connect(self.approval_panel.setVisible)
        self.approval_toggle.toggled.connect(self._update)
        layout.addWidget(self.approval_panel)
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
        if self.briefs:
            self.journal_list.setCurrentRow(0)
        self._update()

    def _show_split(self, index: int) -> None:
        if index < 0 or index >= len(self.briefs):
            return
        self._viewed.add(index)
        brief = self.briefs[index]
        if not brief.get("split"):
            self.selected_summary.setText("この仕訳は現在の規則で分割できません。" + str(brief.get("why_not") or ""))
            self.parts_table.setRowCount(0)
            self.split_details.setText("")
        else:
            original, parts = brief["original"], brief["parts"]
            tax_after = sum((Decimal(p["explicit_tax"]) for p in parts), Decimal(0))
            amount_after = sum((Decimal(p["counterpart_amount"]) for p in parts), Decimal(0))
            self.selected_summary.setText(
                f"元1伝票・{original['physical_rows']}行 → {len(parts)}伝票　"
                f"元の借方/貸方 {original.get('debit', '—')} / {original.get('credit', '—')}　"
                f"分割後の相手科目合計 {amount_after}　税額 {original['explicit_tax']} → {tax_after}　"
                f"再構成: {'一致' if brief['rebuilds_original'] else '不一致'}")
            self.parts_table.setRowCount(len(parts))
            for row, part in enumerate(parts):
                source_rows = part.get("source_rows") or ()
                source_text = "-" if not source_rows else f"{source_rows[0]}–{source_rows[1]}"
                values = [str(part.get("part", row + 1)), source_text, str(part["jdl_rows"]),
                          str(part["counterpart_amount"]), str(part["explicit_tax"])]
                for col, value in enumerate(values):
                    self.parts_table.setItem(row, col, QTableWidgetItem(value))
            self.split_details.setText(
                "変更: " + " / ".join(brief.get("changes", ())) + "\n"
                "保持: " + " / ".join(brief.get("unchanged", ())) + "\n"
                "失われるもの: " + brief.get("lost", ""))
        self._update()

    def _complete(self) -> bool:
        return bool(self._all_requested_present and self.approval_toggle.isChecked()
                    and self.approver.text().strip() and self.accountant.text().strip() and self.reference.text().strip()
                    and self.confirm.isChecked() and all(b.get("split") for b in self.briefs) and self.briefs
                    and all(b.get("rebuilds_original") for b in self.briefs)
                    and len(self._viewed) == len(self.briefs))

    def _update(self) -> None:
        self.review_progress.setText(f"分割内容の確認: {len(self._viewed)} / {len(self.briefs)}仕訳")
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
        self.next_action = QLabel()
        self.next_action.setObjectName("sectionTitle")
        self.next_action.setWordWrap(True)
        layout.addWidget(self.next_action)
        self.notice = QLabel("保存済みの設定による正式な判定です。" + (
            "<b>この画面の未保存の変更は含まれていません。</b>" if unsaved_changes else ""))
        self.notice.setTextFormat(Qt.TextFormat.RichText)
        self.notice.setObjectName("warningCard" if unsaved_changes else "muted")
        self.notice.setWordWrap(True)
        self.notice.setVisible(unsaved_changes)
        layout.addWidget(self.notice)
        self.completed = QLabel()
        self.completed.setObjectName("muted")
        self.completed.setWordWrap(True)
        self.completed.setVisible(False)
        self.completed_toggle = QCheckBox("完了項目を表示")
        self.completed_toggle.toggled.connect(self.completed.setVisible)
        layout.addWidget(self.completed_toggle)
        layout.addWidget(self.completed)
        comparison_row = QHBoxLayout()
        self.alternative = QLabel()
        self.alternative.setWordWrap(True)
        self.alternative.setTextFormat(Qt.TextFormat.RichText)
        comparison_row.addWidget(self.alternative, 1)
        self.compare_button = QPushButton("16行・64行を比較…")
        self.compare_button.clicked.connect(self._open_comparison)
        comparison_row.addWidget(self.compare_button)
        layout.addLayout(comparison_row)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.item_list = QListWidget()
        self.item_list.setMinimumWidth(220)
        self.item_list.setWordWrap(True)
        self.item_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        self.context_toggle = QCheckBox("問題の背景・確認済み事項を表示")
        self.context_text = QLabel()
        self.context_text.setWordWrap(True)
        self.context_text.setVisible(False)
        self.context_toggle.toggled.connect(self.context_text.setVisible)
        self.detail_layout.addWidget(self.context_toggle)
        self.detail_layout.addWidget(self.context_text)
        self.tax_detail_toggle = QCheckBox("元の明細・内訳を表示")
        self.tax_detail = QLabel()
        self.tax_detail.setWordWrap(True)
        self.tax_detail.setTextFormat(Qt.TextFormat.RichText)
        self.tax_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.tax_detail.setVisible(False)
        self.tax_detail_toggle.setVisible(False)
        self.tax_detail_toggle.toggled.connect(self.tax_detail.setVisible)
        self.detail_layout.addWidget(self.tax_detail_toggle)
        self.detail_layout.addWidget(self.tax_detail)
        self.action_button = QPushButton()
        self.action_button.setObjectName("primaryButton")
        self.action_button.clicked.connect(self._do_action)
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
        split.setSizes([250, 790])
        layout.addWidget(split, 1)
        footer = QHBoxLayout()
        footer.addWidget(self.action_button)
        self.status = QLabel()
        self.status.setObjectName("muted")
        footer.addWidget(self.status, 1)
        # Separate mode, only when part of the input is READY and part is not; never the default conversion.
        self.ready_only_button = QPushButton("READYのみ変換…（全件移行ではありません）")
        self.ready_only_button.setVisible(False)
        self.ready_only_button.clicked.connect(self._open_ready_only)
        footer.addWidget(self.ready_only_button)
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
            log_local_exception("company_resolution_report", exc)
            self.report = None
            self.comparison = None
            QApplication.restoreOverrideCursor()
            self.summary.setText("診断できませんでした。入力ファイルと会社設定を確認してください。")
            self.next_action.setText("入力ファイルと会社設定を確認してください")
            self.alternative.setVisible(False)
            self.compare_button.setVisible(False)
            self.completed.setText("")
            self.status.setText("正式診断を更新できませんでした。")
            self.item_list.clear()
            self.detail_text.setText("")
            self.context_text.setText("")
            self.tax_detail.setText("")
            self.tax_detail_toggle.setVisible(False)
            self.details.setPlainText("")
            self.action_button.setVisible(False)
            self.why_no_button.setText("")
            self.ready_only_button.setVisible(False)
            return
        QApplication.restoreOverrideCursor()
        report = self.report
        from accounting_converter.application.yayoi_sources import detect_format

        source_label = detect_format(self.source_path).label if Path(self.source_path).is_file() else "弥生の仕訳データ"
        company_name = self.controller.company_store.get(self.company_id).display_name if hasattr(
            self.controller, "company_store") else self.company_id
        self.summary.setText(
            f"{escape(source_label)} → JDL IBEX 出納帳35.5　|　会社設定: {escape(company_name)} "
            f"（{report.saved_limit or '未確認'}行）<br>"
            f"<span style='font-size:18px; font-weight:700'>正式診断: READY {report.ready:,} / {report.total:,}件</span>　"
            f"BLOCK {report.blocked:,}件　|　この入力全体: {'変換できます' if report.blocked == 0 else '変換できません'}")
        self.next_action.setText(next_priority(report))
        self.completed.setText(" / ".join(report.completed) if report.completed else "完了項目なし")
        alt = report.alternative
        if alt is None:
            self.alternative.setText("")
            self.alternative.setVisible(False)
        else:
            self.alternative.setVisible(True)
            self.alternative.setText(
                f"<b>{alt.limit}行の条件付き試算: READY {alt.ready:,} / {report.total:,}件</b>　"
                f"新たにREADY {len(alt.released)}件 / 逆にBLOCK {len(alt.lost)}件 / 残るBLOCK {alt.still_blocked}件。"
                "JDL側の設定確認とアプリ設定の保存が必要です。")
        self.compare_button.setVisible(alt is not None)
        self.item_list.blockSignals(True)
        self.item_list.clear()
        for item in report.items:
            if self._can_do(item):
                action = "税理士承認・分割案を開く" if item.action == rr.ACT_SPLIT else item.action_label
            elif item.tax_accountant and item.technical_evidence:
                action = "税理士判断・技術検証"
            elif item.technical_evidence and report.awaiting_tax_decision(item):
                waiting = len(report.awaiting_tax_decision(item))
                action = ("税区分の確定待ち（試算）" if waiting == len(item.journals)
                          else f"開発側で実機確認（{waiting}件は税区分の確定待ち）")
            elif item.technical_evidence:
                action = "開発側で実機確認"
            elif item.tax_accountant:
                action = "税理士の判断で確認"
            else:
                action = where_text(item) + "で確認"
            row = QListWidgetItem(f"{short_title(item)}　{len(item.journals)}件\n{action}")
            row.setToolTip(item.title + "\n" + item.todo)
            row.setSizeHint(QSize(220, 60))
            row.setData(Qt.ItemDataRole.UserRole, item.key)
            self.item_list.addItem(row)
        self.item_list.blockSignals(False)
        if report.items:
            index = next((i for i, it in enumerate(report.items) if it.key == keep), 0)
            self.item_list.setCurrentRow(index)
            self._show_item(index)
        else:
            self.detail_text.setText("確認が必要な項目はありません。すべての仕訳が変換できます。")
            self.tax_detail.setText("")
            self.tax_detail_toggle.setVisible(False)
            self.action_button.setVisible(False)
            self.why_no_button.setText("")
            self.details.setPlainText("")
        self.ready_only_button.setVisible(report.blocked > 0 and report.ready > 0
                                          and hasattr(self.controller, "plan_yayoi_ready_only"))
        approved = not report.split_policy_problems
        self.status.setText("再診断しました（保存済み設定）。" + ("伝票分割: 承認記録あり。" if approved else ""))

    def _open_ready_only(self) -> None:
        from .ready_only_dialog import ReadyOnlyConversionDialog

        ReadyOnlyConversionDialog(self.controller, self.company_id, self.source_path, self).exec()

    def _open_comparison(self) -> None:
        if self.comparison is None:
            return
        from .voucher_limit_comparison import VoucherLimitComparisonDialog

        VoucherLimitComparisonDialog(self.comparison, self).exec()

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
        other_keys = {key for journal in report.journals if item.key in journal.item_keys
                      for key in journal.item_keys if key != item.key}
        remaining = [short_title(other) for other in report.items if other.key in other_keys]
        parts = [
            f"<h3>{escape(short_title(item))}　{len(item.journals)}件</h3>",
            f"<p><b>次にすること</b><br>{escape(item.todo)}</p>",
            f"<p><b>担当・場所</b>: {escape(where_text(item))}<br>"
            f"{escape(' / '.join(tags))}</p>",
            f"<p><b>この対応だけでは残る条件</b>: "
            f"{escape(' / '.join(dict.fromkeys(remaining)) if remaining else 'ほかのBLOCKは現在の診断で検出されていません')}"
            f"<br>この項目だけで止まっている仕訳: {item.only_this}件 / "
            f"ほかの条件もある仕訳: {len(item.journals) - item.only_this}件。"
            "保存後に正式診断をやり直します。</p>",
        ]
        waiting = report.awaiting_tax_decision(item)
        if waiting and len(waiting) == len(item.journals):
            parts[1] = ("<p><b>次にすること</b><br>先に「税区分の確認が必要」の税理士判断が必要です。"
                        "承認記録後に再診断し、それでも残る場合だけ追加の実機確認を検討します。</p>")
        if waiting:
            parts.insert(1, "<p><b>税区分の確定待ち</b>: 仕訳 " + escape("・".join(waiting))
                         + " は、税区分（控除不可）が未確定のため形・税額を評価できていません。"
                         "税理士の承認記録があると仮定した試算では解消しますが、実機確認済みとして扱うわけではありません。"
                         "正式には承認記録後の再診断で確認します。</p>")
        tax_detail = ""
        if item.key == rr.NONCREDIT_KEY:
            parts.insert(1, tax_review_summary_html(report, item))
            tax_detail = tax_review_detail_html(report, item)
        self.tax_detail.setText(tax_detail)
        self.tax_detail_toggle.setVisible(bool(tax_detail))
        if not tax_detail:
            self.tax_detail_toggle.setChecked(False)
        notes = [n for j in report.journals if item.key in j.item_keys for n in j.notes]
        self.context_text.setText(
            f"問題: {item.problem or '—'}\n確認済み: {item.confirmed or 'なし'}\n"
            + ("仕訳ごとの注意: " + " / ".join(dict.fromkeys(notes)) if notes else ""))
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
