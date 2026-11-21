"""設定: the selected company's settings in six sections (view only; Phase 3C-1).

The page shows a ui.settings_view.SettingsOverview; it computes nothing and writes nothing. Every button emits
`action_requested(action key)` and the window opens the EXISTING screen for it (tax settings, master refresh, row
limit, trade partner, mapping review, company add / rename / delete): each of those saves only on its own
confirmation. After one of them returns, the window calls `render` again and, if the overview changed, `show_saved`
offers the way to the diagnosis (nothing is diagnosed automatically)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from accounting_converter.ui import settings_view as sv

from .. import components as ui
from . import scroll_page

BADGE_KEY = {sv.CONFIRMED: "CONFIRMED", sv.UNCONFIRMED: "UNCONFIRMED", sv.WAITING_EVIDENCE: "EVIDENCE",
             sv.NOT_APPLICABLE: "NOT_REQUIRED", sv.UNREADABLE: "ERROR"}
BADGE_TEXT = {sv.UNREADABLE: "読み込めません", sv.WAITING_EVIDENCE: "JDLでの確認待ち"}
SECTION_NUMBERS = {"company": "1", "software": "2", "accounts": "3", "tax": "4", "conditions": "5", "technical": "6"}
ATTENTION = (sv.UNREADABLE, sv.UNCONFIRMED, sv.WAITING_EVIDENCE)
_ROW_ORDER = {sv.UNREADABLE: 0, sv.UNCONFIRMED: 1, sv.WAITING_EVIDENCE: 2, sv.CONFIRMED: 3, sv.NOT_APPLICABLE: 4}
DANGER_ACTIONS = (sv.ACT_DELETE_COMPANY,)


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())


class SettingsPage(QWidget):
    action_requested = Signal(str)
    diagnosis_requested = Signal()
    legacy_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll, layout = scroll_page(
            "設定", "選択中の会社の設定を、会社・会計ソフト・科目・消費税・変換条件に分けて表示します。",
            name="settingsContent")
        outer.addWidget(scroll)
        self.scroll = scroll
        self.mode_banner = ui.ModeBanner(
            "view", "この画面を見るだけでは設定は保存されません。変更は各ボタンの確認画面で、確認してから保存します。")
        layout.addWidget(self.mode_banner)
        self.message = ui.MessageBar()
        layout.addWidget(self.message)
        self.saved_bar = QFrame()
        self.saved_bar.setObjectName("detailCard")
        saved_row = QHBoxLayout(self.saved_bar)
        saved_row.setContentsMargins(12, 8, 12, 8)
        self.saved_label = ui.WrappingLabel(sv.SAVED_CHANGE_NOTICE)
        saved_row.addWidget(self.saved_label, 1)
        self.to_diagnosis = ui.make_button(
            "変換診断で確認する", "primary", description="変換診断ページを表示します（ページの切り替えのみ。保存しません）")
        self.to_diagnosis.clicked.connect(lambda _checked=False: self.diagnosis_requested.emit())
        saved_row.addWidget(self.to_diagnosis)
        self.saved_bar.hide()
        layout.addWidget(self.saved_bar)
        self.progress_box = QVBoxLayout()
        layout.addLayout(self.progress_box)
        self.next_box = QVBoxLayout()
        layout.addLayout(self.next_box)
        self.sections_box = QVBoxLayout()
        self.sections_box.setSpacing(16)
        layout.addLayout(self.sections_box)
        legacy_row = QHBoxLayout()
        legacy_row.addStretch(1)
        self.legacy_button = ui.make_button(
            "従来の設定ダイアログを開く…", "subtle",
            description="会社の管理・対応内容の見直しなど、従来の設定画面を開きます（保存は各画面の確認後だけ）")
        self.legacy_button.clicked.connect(lambda _checked=False: self.legacy_requested.emit())
        legacy_row.addWidget(self.legacy_button)
        layout.addLayout(legacy_row)
        layout.addStretch(1)
        self.overview: sv.SettingsOverview | None = None
        self.action_buttons: dict[str, list] = {}

    # ------------------------------------------------------------------ rendering
    def render(self, overview: sv.SettingsOverview) -> None:
        """Rebuild the sections (they change with the setting); the reader's scroll position is kept."""
        bar = self.scroll.verticalScrollBar()
        position = bar.value()
        self.overview = overview
        self.action_buttons = {}
        if overview.message:
            self.message.show_message(*overview.message)
        else:
            self.message.clear_message()
        _clear(self.progress_box)
        _clear(self.next_box)
        _clear(self.sections_box)
        if overview.has_company:
            self.progress_box.addWidget(self._progress(overview))
        if overview.next_steps:
            self.next_box.addWidget(self._next_steps(overview))
        for section in overview.sections:
            self.sections_box.addWidget(self._section(section))
        self.scroll.widget().layout().activate()
        bar.setValue(min(position, bar.maximum()))

    def show_saved(self, shown: bool) -> None:
        self.saved_bar.setVisible(shown)

    def _progress(self, overview) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        row.addWidget(ui.MetricCard("会社", overview.company_name, "設定を表示している会社"), 1)
        tone = "ready" if overview.needed and overview.confirmed >= overview.needed else "pending"
        row.addWidget(ui.MetricCard("確認済みの設定", f"{overview.confirmed:,} / {overview.needed:,} 項目",
                                    "確認が必要な設定のうち、確認済みの数", tone), 1)
        column = QWidget()
        stack = QVBoxLayout(column)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(6)
        stack.addWidget(box)
        self.count_note = ui.WrappingLabel(sv.COUNT_SCOPE_NOTE)
        self.count_note.setObjectName("muted")
        self.count_note.setAccessibleName("件数の範囲")
        stack.addWidget(self.count_note)
        return column

    def _next_steps(self, overview) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)
        layout.addWidget(ui.SectionHeader("次に必要な設定", "上から順に確認します。確認が済むまで、関係する仕訳は変換できません。"))
        first = True
        for number, step in enumerate(overview.next_steps, start=1):
            row = QHBoxLayout()
            text = ui.WrappingLabel(f"{number}. {step.text}")
            text.setAccessibleName(f"次の設定 {number}")
            row.addWidget(text, 1)
            button = ui.make_button(step.button, "primary" if first else "secondary", description=step.text)
            button.clicked.connect(lambda _checked=False, a=step.action: self.action_requested.emit(a))
            row.addWidget(button)
            self.action_buttons.setdefault(step.action, []).append(button)
            layout.addLayout(row)
            first = False
        return card

    def _section(self, section: sv.SettingSection) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        card.setAccessibleName(f"{SECTION_NUMBERS[section.key]}. {section.title}")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 18)
        layout.setSpacing(10)
        head = QHBoxLayout()
        title = QLabel(f"{SECTION_NUMBERS[section.key]}. {section.title}")
        title.setObjectName("sectionTitle")
        head.addWidget(title)
        head.addStretch(1)
        if section.key != "technical":
            confirmed, needed = section.counts()
            badge_state = section.state
            head.addWidget(ui.StatusBadge(
                BADGE_KEY[badge_state],
                f"{confirmed:,} / {needed:,} 確認済み" if badge_state in (sv.CONFIRMED, sv.UNCONFIRMED, sv.WAITING_EVIDENCE)
                else BADGE_TEXT.get(badge_state)))
        layout.addLayout(head)
        summary = QLabel(section.summary)
        summary.setObjectName("keyValue")              # the section's main values, readable at a glance
        summary.setWordWrap(True)
        summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        summary.setAccessibleName(f"{section.title}の主な設定値")
        layout.addWidget(summary)
        if section.key == "technical":
            body_section, body = ui.collapsible_text("技術情報を表示（会社ID・改訂履歴・指紋）")
            body.setText("<br>".join(f"<b>{_esc(r.label)}</b>: {_esc(r.value)}" for r in section.rows))
            layout.addWidget(body_section)
            return card
        rows = sorted((r for r in section.rows if r.action not in DANGER_ACTIONS),
                      key=lambda r: _ROW_ORDER[r.state])          # what needs a confirmation first (stable)
        danger = [r for r in section.rows if r.action in DANGER_ACTIONS]
        attention = any(r.state in ATTENTION for r in rows)
        # While something here needs a confirmation, confirmed values without an action are folded away (they stay
        # one click away). Rows with a button are always shown: every existing screen stays reachable.
        folded = [r for r in rows if attention and r.state == sv.CONFIRMED and not self._has_button(r)]
        shown = [r for r in rows if r not in folded]
        layout.addLayout(self._grid(shown))
        if folded:
            box = QWidget()
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(0, 0, 0, 0)
            box_layout.addLayout(self._grid(folded))
            fold = ui.CollapsibleSection(f"確認済みの設定 {len(folded):,}項目を表示", box)
            fold.setAccessibleName(f"{section.title}の確認済みの設定 {len(folded):,}項目")
            layout.addWidget(fold)
        impacts = [f"<b>{_esc(r.label)}</b>: {_esc(r.impact)}" for r in section.rows if r.impact]
        if impacts:
            impact_section, body = ui.collapsible_text("変更した場合の影響（READY / BLOCK）")
            body.setText("<br>".join(impacts))
            layout.addWidget(impact_section)
        if danger:
            layout.addWidget(self._danger_zone(danger))
        return card

    @staticmethod
    def _has_button(row) -> bool:
        return bool(row.action) and (row.state != sv.CONFIRMED or row.key in _ALWAYS_EDITABLE)

    def _danger_zone(self, rows) -> QWidget:
        """Operations that remove something, kept apart from ordinary settings (each asks again before it acts)."""
        zone = QFrame()
        zone.setObjectName("dangerZone")
        zone.setAccessibleName("取り消せない操作")
        layout = QVBoxLayout(zone)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(6)
        title = QLabel("取り消せない操作（確認ダイアログで確定します）")
        title.setObjectName("dangerZoneTitle")
        layout.addWidget(title)
        for row in rows:
            line = QHBoxLayout()
            text = ui.WrappingLabel(f"{row.label}: {row.value}。{row.impact}")
            line.addWidget(text, 1)
            button = ui.make_button(row.action_label, "danger", description=f"{row.label}: {row.impact}")
            button.clicked.connect(lambda _checked=False, a=row.action: self.action_requested.emit(a))
            line.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
            self.action_buttons.setdefault(row.action, []).append(button)
            layout.addLayout(line)
        return zone

    def _grid(self, rows) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        row_number = 0
        for row in rows:
            label = QLabel(row.label)
            label.setWordWrap(True)
            label.setMinimumWidth(150)
            label.setMaximumWidth(210)
            bold = label.font()
            bold.setBold(True)
            label.setFont(bold)
            value = ui.WrappingLabel(row.value)
            value.setAccessibleName(f"{row.label}の値")
            value.setAccessibleDescription(row.note)
            grid.addWidget(label, row_number, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(value, row_number, 1, Qt.AlignmentFlag.AlignTop)
            if row.state != sv.NOT_APPLICABLE or row.state_text:
                grid.addWidget(ui.StatusBadge(BADGE_KEY[row.state], row.state_text or BADGE_TEXT.get(row.state)),
                               row_number, 2, Qt.AlignmentFlag.AlignTop)
            if self._has_button(row):
                button = ui.make_button(row.action_label, "secondary", description=f"{row.label}: {row.note or row.impact}")
                button.clicked.connect(lambda _checked=False, a=row.action: self.action_requested.emit(a))
                grid.addWidget(button, row_number, 3, Qt.AlignmentFlag.AlignTop)
                self.action_buttons.setdefault(row.action, []).append(button)
            row_number += 1
            if row.note:
                note = ui.WrappingLabel(row.note)
                note.setObjectName("muted")
                grid.addWidget(note, row_number, 1, 1, 3)
                row_number += 1
        return grid


# Settings that are confirmed but can still be changed on purpose (the same button as when unconfirmed).
_ALWAYS_EDITABLE = {"name", "add", "delete", "master", "tax_mode", "row_limit",
                    "trade_partner", "jdl_migration", "tax_mapping", "accounts", "subaccounts", "information"}


def _esc(text: str) -> str:
    from html import escape

    return escape(text)
