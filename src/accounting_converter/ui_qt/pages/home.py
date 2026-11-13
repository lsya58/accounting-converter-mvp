"""ホーム: the selected company / source, the counts, the migration state and the next work (view only).

The page shows a ui.home_view.HomePresentation; it computes nothing itself and writes nothing. The buttons in
「次に必要な作業」 only switch to another page (navigate signal)."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from accounting_converter.ui.home_view import HomePresentation

from .. import components as ui
from . import scroll_page


class HomePage(QWidget):
    navigate = Signal(str)
    refresh_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll, layout = scroll_page("ホーム", "選択中の会社と仕訳データの状態、次に必要な作業を表示します。", name="homeContent")
        outer.addWidget(scroll)
        self.scroll = scroll
        self.mode_banner = ui.ModeBanner("view", "この画面を開いても、設定・承認・移行状態は変わりません。")
        layout.addWidget(self.mode_banner)
        self.message = ui.MessageBar()
        layout.addWidget(self.message)

        self.company_card = ui.DetailCard("会社・入力データ・JDL設定")
        layout.addWidget(self.company_card)

        self.metric_grid = QGridLayout()
        self.metric_grid.setHorizontalSpacing(12)
        self.metric_grid.setVerticalSpacing(12)
        self.metric_cards: dict[str, ui.MetricCard] = {}
        for index, label in enumerate(("元仕訳", "変換可能", "BLOCK", "税理士の判断", "承認済み", "移行全体")):
            card = ui.MetricCard(label)
            self.metric_cards[label] = card
            self.metric_grid.addWidget(card, index // 3, index % 3)
        layout.addLayout(self.metric_grid)
        self.counts_label = QLabel()
        self.counts_label.setObjectName("muted")
        self.counts_label.setWordWrap(True)
        layout.addWidget(self.counts_label)
        self.notes = QLabel()
        self.notes.setObjectName("muted")
        self.notes.setWordWrap(True)
        layout.addWidget(self.notes)

        actions_title = ui.SectionHeader("次に必要な作業")
        layout.addWidget(actions_title)
        self.actions_box = QVBoxLayout()
        self.actions_box.setSpacing(8)
        layout.addLayout(self.actions_box)
        refresh_row = QHBoxLayout()
        refresh_row.addStretch(1)
        self.refresh_button = ui.make_button(
            "ホームの診断をやり直す", description="弥生の仕訳データを正式診断し直します（保存しません）", shortcut="F5")
        self.refresh_button.clicked.connect(lambda _checked=False: self.refresh_requested.emit())
        refresh_row.addWidget(self.refresh_button)
        layout.addLayout(refresh_row)
        layout.addStretch(1)
        self.action_buttons: list = []
        self.actions_widget: QWidget | None = None
        self.presentation: HomePresentation | None = None

    def render(self, presentation: HomePresentation, *, busy: bool = False) -> None:
        self.presentation = presentation
        self.company_card.set_lines(presentation.company_lines)
        for metric in (*presentation.metrics, presentation.migration):
            self.metric_cards[metric.label].set_value(metric.value, metric.hint, metric.tone)
        by_label = {m.label: m.value for m in presentation.metrics}
        if all(by_label.get(k, "—") not in ("—", "対象外") for k in ("元仕訳", "変換可能", "BLOCK")):
            self.counts_label.setText(
                f"元仕訳 {by_label['元仕訳']} ＝ 変換可能 {by_label['変換可能']} ＋ BLOCK {by_label['BLOCK']}"
                f"　移行全体: {presentation.migration.value}")
        else:
            self.counts_label.setText("")
        self.counts_label.setVisible(bool(self.counts_label.text()))
        self.notes.setText("\n".join(presentation.notes))
        self.notes.setVisible(bool(presentation.notes))
        if presentation.message:
            self.message.show_message(*presentation.message)
        else:
            self.message.clear_message()
        self.refresh_button.setVisible(presentation.yayoi)
        self.refresh_button.setEnabled(not busy)
        self._render_actions(presentation)

    def _render_actions(self, presentation: HomePresentation) -> None:
        """Rebuilt each time: one row per action, the first one primary (one primary per screen)."""
        if self.actions_widget is not None:
            self.actions_box.removeWidget(self.actions_widget)
            self.actions_widget.deleteLater()
        self.actions_widget = QWidget()
        self.actions_widget.setAccessibleName("次に必要な作業")
        rows = QVBoxLayout(self.actions_widget)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(8)
        self.action_buttons = []
        for number, action in enumerate(presentation.next_actions, start=1):
            row = QHBoxLayout()
            text = QLabel(f"{number}. {action.text}")
            text.setWordWrap(True)
            row.addWidget(text, 1)
            if action.target:
                button = ui.make_button(action.button, "primary" if not self.action_buttons else "secondary",
                                        description=action.text)
                button.clicked.connect(lambda _checked=False, t=action.target: self.navigate.emit(t))
                row.addWidget(button)
                self.action_buttons.append(button)
            rows.addLayout(row)
        self.actions_box.addWidget(self.actions_widget)
