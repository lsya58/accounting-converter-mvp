"""freee 試験診断（試験対応・診断のみ）: shows ui.freee_trial_view for one freee 仕訳帳CSV.

Opened from the データ取込 page's own freee card, never from the main input flow: it does not select the file in the
controller, does not select or touch a company setting, saves nothing and writes no file (the source is only read).
The READY-only output button is shown disabled with its reason: freee has no formal READY (E5A).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from accounting_converter.ui import freee_trial_view as fv

from . import components as ui

TITLE = f"freee 試験診断（{fv.TRIAL_BADGE}）"


class FreeeTrialDiagnosisDialog(QDialog):
    def __init__(self, view: fv.FreeeTrialView, parent=None) -> None:
        super().__init__(parent)
        self.view = view
        self.setWindowTitle(TITLE)
        self.setObjectName("freeeTrialDialog")
        self.setAccessibleName(TITLE)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setSpacing(12)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self.mode_banner = ui.ModeBanner("view", f"freee: {fv.TRIAL_BADGE}。会社設定・承認・元のファイルは変更しません。")
        layout.addWidget(self.mode_banner)
        self.file_label = QLabel(f"ファイル: {view.file_name}")
        self.file_label.setObjectName("sectionTitle")
        layout.addWidget(self.file_label)
        self.headline = ui.MessageBar()
        self.headline.show_message("info" if view.readable else "error", view.headline)
        layout.addWidget(self.headline)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self.metric_cards: dict[str, ui.MetricCard] = {}
        for index, metric in enumerate(view.metrics):
            card = ui.MetricCard(metric.label, metric.value, metric.hint, metric.tone)
            self.metric_cards[metric.label] = card
            grid.addWidget(card, index // 3, index % 3)
        layout.addLayout(grid)

        self.note = ui.WrappingLabel("\n".join(view.notes))
        self.note.setObjectName("muted")
        layout.addWidget(self.note)

        self.format_card = ui.DetailCard("CSVの形式")
        self.format_card.set_lines(list(view.format_lines) + list(view.file_problems))
        layout.addWidget(self.format_card)

        self.tables: dict[str, ui.JournalTable] = {}
        if view.readable:
            self._table(layout, "rejected", f"未対応の仕訳（解析できなかった仕訳）: {len(view.rejected_rows)}件",
                        ("表示No", "問題のある行", "理由"), view.rejected_rows, stretch=(2,),
                        empty="解析できなかった仕訳はありません。")
            self._table(layout, "reasons", "正式な変換に必要なこと（理由別・解析できた仕訳）",
                        ("担当", "理由", "仕訳数"), view.reason_rows, numeric=(2,), stretch=(1,))
            tax = ui.DetailCard("税区分など意味の確認が必要な項目")
            tax.set_lines(view.tax_lines)
            layout.addWidget(tax)
            self.tax_card = tax
            self._table(layout, "tax", "税区分（明細数）", ("税区分", "明細数", "名前から見える種類（参考）"),
                        view.tax_rows, numeric=(1,), stretch=(2,))
            summary = fv.RETENTION_NOTE + "\n" + "　".join(f"{label} {count}列" for label, count in view.retention_counts)
            self._table(layout, "retention", "情報の保持状況（値のある列）", ("区分", "列名", "値のある仕訳", "扱い"),
                        view.retention_rows, numeric=(2,), stretch=(3,), caption=summary)
            self._table(layout, "journals", "仕訳ごとの結果", ("表示No", "行", "結果", "形・種類", "主な確認事項"),
                        view.journal_rows, stretch=(4,))
        layout.addStretch(1)

        buttons = QHBoxLayout()
        self.output_button = ui.make_button(
            "READYのみ出力（freeeは対象外）", description=view.output_reason)
        self.output_button.setEnabled(False)                # never enabled for freee (E5A)
        self.output_button.setToolTip(view.output_reason)
        self.output_reason = QLabel(view.output_reason)
        self.output_reason.setObjectName("muted")
        self.output_reason.setWordWrap(True)
        self.copy_button = ui.make_button("診断情報をコピー", description="この画面の内容を文字でコピーします（顧客の値は含みません）")
        self.copy_button.clicked.connect(self._copy)
        self.close_button = ui.make_button("閉じる", "primary")
        self.close_button.clicked.connect(self.accept)
        buttons.addWidget(self.output_button)
        buttons.addWidget(self.output_reason, 1)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.close_button)
        outer.addLayout(buttons)
        ui.fit_to_screen(self, 1000, 760)

    def _table(self, layout, key, title, columns, rows, *, numeric=(), stretch=(), empty="", caption=""):
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        if caption:
            note = ui.WrappingLabel(caption)
            note.setObjectName("muted")
            layout.addWidget(note)
        if not rows and empty:
            label = QLabel(empty)
            label.setObjectName("muted")
            layout.addWidget(label)
            return
        table = ui.JournalTable(columns, name=title, numeric=numeric, stretch=stretch)
        # The first column sorts by the view's order (file order, status order): that is the order shown first.
        table.set_rows([((row[0], index),) + tuple(row[1:]) for index, row in enumerate(rows)])
        table.sortItems(0, Qt.SortOrder.AscendingOrder)
        table.setMinimumHeight(min(80 + 30 * len(rows), 320))
        layout.addWidget(table)
        self.tables[key] = table

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.view.plain_text())
