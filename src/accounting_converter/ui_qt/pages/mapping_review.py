"""対応の確認 (要確認ページ): accounts, subaccounts, tax categories, descriptions and retention, view only (Phase 3C-2).

Shows a ui.mapping_review_view.MappingReviewView. Unconfirmed rows come first, confirmed rows are folded away, and
"人の確認が必要" / "JDL側で登録が必要" / "JDLでの確認待ち" are separate states with their own words and symbols.
Nothing is confirmed or saved here: the buttons only ask the window to open the EXISTING confirmation screens
(`open_group`), which save only on their own explicit confirmation."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from accounting_converter.ui import mapping_review_view as mv

from .. import components as ui

BADGE_KEY = {mv.UNCONFIRMED: "UNCONFIRMED", mv.CONFIRMED: "CONFIRMED", mv.NEEDS_JDL: "NEEDS_JDL",
             mv.NEEDS_EVIDENCE: "EVIDENCE", mv.WAITING_PARENT: "UNCONFIRMED"}
GROUP_BUTTONS = {
    mv.G_ACCOUNT: "科目を確認…", mv.G_SUBACCOUNT: "補助科目を確認…", mv.G_TAX: "税区分を確認…",
    mv.G_DESCRIPTION: "摘要を確認…", mv.G_RETENTION: "保持方法を確認…",
}
NEEDS_PERSON = (mv.UNCONFIRMED, mv.WAITING_PARENT)
MAX_VISIBLE_ROWS = 10


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())


def _table(rows, group_key: str, name: str) -> ui.JournalTable:
    with_parent = group_key == mv.G_SUBACCOUNT
    columns = ["状態", "元の名前"] + (["親科目"] if with_parent else []) + ["対応先の候補", "根拠・理由", "件数"]
    last = len(columns) - 1
    stretch = {columns.index("根拠・理由"), columns.index("対応先の候補")}
    table = ui.JournalTable(columns, name=name, numeric=(last,), stretch=tuple(sorted(stretch)))
    data = []
    for row in rows:
        reason = "／".join(x for x in (row.reason, row.basis) if x)
        cells = [(ui.badge_text(BADGE_KEY[row.state], _STATE_TEXT.get(row.state)), mv._ORDER[row.state]), row.source]
        if with_parent:
            cells.append(row.parent)
        cells += [row.candidate or "—", reason or "—",
                  (f"{row.journals:,}{row.unit}", row.journals or 0) if row.journals else "—"]
        data.append(cells)
    table.set_rows(data)
    table.sortItems(0, Qt.SortOrder.AscendingOrder)           # 未確認 first (the state column sorts by its order)
    table.horizontalHeader().setSortIndicator(0, Qt.SortOrder.AscendingOrder)
    table.horizontalHeader().setStretchLastSection(False)
    height = table.horizontalHeader().height() + 4
    shown = min(max(len(rows), 1), MAX_VISIBLE_ROWS)
    height += shown * table.verticalHeader().defaultSectionSize()
    table.setFixedHeight(height + 6)
    return table


_STATE_TEXT = {mv.UNCONFIRMED: "未確認", mv.NEEDS_JDL: "JDL側で登録が必要", mv.NEEDS_EVIDENCE: "JDLでの確認待ち",
               mv.WAITING_PARENT: "親科目の確認待ち"}


class MappingReviewPanel(QWidget):
    open_group = Signal(str)
    open_all = Signal()
    reload_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.mode_banner = ui.ModeBanner(
            "view", "表示だけで、対応は確認・保存されません。確認は各ボタンの確認画面で行い、保存はその確認後です。")
        layout.addWidget(self.mode_banner)
        self.message = ui.MessageBar()
        layout.addWidget(self.message)
        self.metrics = QWidget()
        self.metric_row = QHBoxLayout(self.metrics)
        self.metric_row.setContentsMargins(0, 0, 0, 0)
        self.metric_row.setSpacing(12)
        layout.addWidget(self.metrics)
        self.notes = ui.WrappingLabel()
        self.notes.setObjectName("muted")
        layout.addWidget(self.notes)
        self.groups_box = QVBoxLayout()
        self.groups_box.setSpacing(12)
        layout.addLayout(self.groups_box)
        self.technical_section, self.technical_body = ui.collapsible_text("技術情報（コード・担当）を表示")
        layout.addWidget(self.technical_section)
        footer = QHBoxLayout()
        self.reload_button = ui.make_button(
            "対応の確認を再読込", description="現在の設定と元データで、一覧を読み込み直します（保存しません）")
        self.reload_button.clicked.connect(lambda _checked=False: self.reload_requested.emit())
        footer.addStretch(1)
        footer.addWidget(self.reload_button)
        layout.addLayout(footer)
        self.technical_section.hide()
        self.metrics.hide()
        self.notes.hide()
        self.view: mv.MappingReviewView | None = None
        self.group_buttons: dict[str, object] = {}
        self.tables: dict[str, ui.JournalTable] = {}
        self.confirmed_tables: dict[str, ui.JournalTable] = {}

    # ------------------------------------------------------------------ states
    def _reset(self) -> None:
        self.view = None
        self.group_buttons, self.tables, self.confirmed_tables = {}, {}, {}
        _clear(self.groups_box)
        _clear(self.metric_row)
        self.metrics.hide()
        self.notes.hide()
        self.technical_section.hide()

    def show_idle(self, text: str) -> None:
        self._reset()
        self.message.show_message("info", text)

    def show_loading(self, text: str = "対応の確認を読み込んでいます…（表示だけで、保存はしません）") -> None:
        self._reset()
        self.message.show_message("info", text)

    def show_error(self, text: str) -> None:
        self._reset()
        self.message.show_message("error", text)

    # ------------------------------------------------------------------ the view
    def show_view(self, view: mv.MappingReviewView) -> None:
        self._reset()
        self.view = view
        if view.message:
            self.message.show_message(*view.message)
        counts = {state: sum(g.count(state) for g in view.groups) for state in mv.STATE_WORDS}
        person = counts[mv.UNCONFIRMED] + counts[mv.WAITING_PARENT]
        for label, value, hint, tone in (
            ("人の確認が必要", person, "税理士・事務所が選ぶ・確認する項目", "pending" if person else "ready"),
            ("JDL側で登録が必要", counts[mv.NEEDS_JDL], "JDLに同じ科目・補助がない項目", "block" if counts[mv.NEEDS_JDL] else "neutral"),
            ("JDLでの確認待ち", counts[mv.NEEDS_EVIDENCE], "実機の確認がなく、画面では確認できない項目",
             "block" if counts[mv.NEEDS_EVIDENCE] else "neutral"),
            ("確認済み", counts[mv.CONFIRMED], "この会社で確認済みの項目", "ready"),
        ):
            self.metric_row.addWidget(ui.MetricCard(label, f"{value:,}件", hint, tone), 1)
        self.metrics.show()
        notes = list(view.notes)
        if view.journals:
            notes.append(f"元データの仕訳 {view.journals:,}仕訳が対象です。件数は項目の数で、仕訳の数とは別です。")
        self.notes.setText("\n".join(notes))
        self.notes.setVisible(bool(notes))
        technical = []
        for group in view.groups:
            self.groups_box.addWidget(self._group(group))
            technical += [f"{group.title} / {r.source}: {r.technical}" for r in group.rows if r.technical]
        if technical:
            from html import escape

            self.technical_body.setText("<br>".join(escape(line) for line in technical))
            self.technical_section.show()
        self.layout().activate()
        self.updateGeometry()

    def _group(self, group: mv.ReviewGroup) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        card.setAccessibleName(group.title)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)
        head = QHBoxLayout()
        title = QLabel(group.title)
        title.setObjectName("sectionTitle")
        head.addWidget(title)
        head.addStretch(1)
        person = sum(group.count(s) for s in NEEDS_PERSON)
        if not group.rows:
            head.addWidget(ui.StatusBadge("NOT_REQUIRED", "該当なし"))
        elif person:
            head.addWidget(ui.StatusBadge("UNCONFIRMED", f"未確認 {person:,}件"))
        elif group.pending:
            head.addWidget(ui.StatusBadge("EVIDENCE", f"確認待ち {len(group.pending):,}件"))
        else:
            head.addWidget(ui.StatusBadge("CONFIRMED", f"確認済み {len(group.confirmed):,}件"))
        if person:
            button = ui.make_button(
                GROUP_BUTTONS[group.key], "secondary",
                description=f"{group.title}の確認画面を開きます（保存は確認画面で確認した後だけ）")
            button.clicked.connect(lambda _checked=False, k=group.key: self.open_group.emit(k))
            head.addWidget(button)
            self.group_buttons[group.key] = button
        layout.addLayout(head)
        if group.pending:
            table = _table(group.pending, group.key, f"{group.title}（未確認・対応待ち）")
            self.tables[group.key] = table
            layout.addWidget(table)
            hints = []
            if any(r.state == mv.NEEDS_JDL for r in group.pending):
                hints.append("「JDL側で登録が必要」は、人が確認しても解決しません。JDLで科目・補助を登録するか、別の対応先を選びます。")
            if any(r.state == mv.NEEDS_EVIDENCE for r in group.pending):
                hints.append("「JDLでの確認待ち」は、実機の確認がなく画面では確認できません。確認が済むのを待ちます。")
            if hints:
                text = ui.WrappingLabel("\n".join(hints))
                text.setObjectName("muted")
                layout.addWidget(text)
        elif group.rows:
            note = QLabel("未確認の項目はありません。")
            note.setObjectName("muted")
            layout.addWidget(note)
        if group.confirmed:
            table = _table(group.confirmed, group.key, f"{group.title}（確認済み）")
            self.confirmed_tables[group.key] = table
            section = ui.CollapsibleSection(f"確認済み {len(group.confirmed):,}件を表示", table)
            section.setAccessibleName(f"{group.title}の確認済み {len(group.confirmed):,}件")
            layout.addWidget(section)
        return card

    def first_group_needing_person(self) -> str | None:
        if self.view is None:
            return None
        return next((g.key for g in self.view.groups if any(r.state in NEEDS_PERSON for r in g.rows)), None)
