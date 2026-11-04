"""Bulk confirmation dialogs for the review screen.

Both dialogs only return what the Human ticked / approved. They never save:
the review dialog fills its own per-row controls and the existing save runs
all checks again.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from accounting_converter.application.review_bulk import (
    BulkRow,
    description_preview,
    preview_signature,
    rule_problems,
)

_CHECKED = Qt.CheckState.Checked
_UNCHECKED = Qt.CheckState.Unchecked


def _table(headers) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(40)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    return table


def _cell(text: str) -> QTableWidgetItem:
    cell = QTableWidgetItem(text)
    cell.setToolTip(text)
    return cell


class BulkCandidateDialog(QDialog):
    """Preview of suggested targets; returns the rows the Human kept ticked."""

    def __init__(self, title: str, rows: list[BulkRow], parent=None) -> None:
        super().__init__(parent)
        self.rows = rows
        self.setWindowTitle(title)
        self.resize(980, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        note = QLabel(
            "名前が同じ候補だけ、最初からチェックしています。言い換え・部分一致・類似の候補は"
            "チェックしていません。違うものはチェックを外してください。"
            "ここで選んだ行は確認画面の「確認しました」にチェックが入るだけで、保存は確認画面の保存ボタンで行います。"
        )
        note.setObjectName("infoCard")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = _table(("対象", "入力元の親科目", "入力元の科目・補助", "JDLの対応先（候補）", "候補の種類", "影響仕訳", "注意"))
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            tick = QTableWidgetItem()
            tick.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            tick.setCheckState(_CHECKED if row.pre_ticked else _UNCHECKED)
            self.table.setItem(index, 0, tick)
            for column, value in enumerate(
                (row.parent or "-", row.source, row.target_label, row.kind_label, f"{row.journals}件", row.warning), 1
            ):
                self.table.setItem(index, column, _cell(value))
        self.table.itemChanged.connect(self._update)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        select_none = QPushButton("すべて外す")
        select_none.clicked.connect(lambda: self._set_all(False))
        select_same = QPushButton("名前が同じものだけ選ぶ")
        select_same.clicked.connect(lambda: self._set_all(None))
        self.count_label = QLabel()
        self.count_label.setObjectName("muted")
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        self.apply_button = QPushButton()
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.clicked.connect(self.accept)
        actions.addWidget(select_none)
        actions.addWidget(select_same)
        actions.addWidget(self.count_label, 1)
        actions.addWidget(cancel)
        actions.addWidget(self.apply_button)
        layout.addLayout(actions)
        self._update()

    def _set_all(self, value: bool | None) -> None:
        for index, row in enumerate(self.rows):
            ticked = row.pre_ticked if value is None else value
            self.table.item(index, 0).setCheckState(_CHECKED if ticked else _UNCHECKED)

    def selected(self) -> list[BulkRow]:
        return [row for index, row in enumerate(self.rows)
                if self.table.item(index, 0).checkState() == _CHECKED]

    def _update(self, *_args) -> None:
        chosen = self.selected()
        self.count_label.setText(f"選択 {len(chosen)}件 / 影響 {sum(row.journals for row in chosen):,}仕訳（延べ）")
        self.apply_button.setText(f"選んだ{len(chosen)}件を確認済みにする")
        self.apply_button.setEnabled(bool(chosen))


class DescriptionRulesDialog(QDialog):
    """Edit / approve shortening rules, preview every description, apply the fitting ones."""

    def __init__(self, descriptions: list[tuple[str, str]], rules: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.descriptions = descriptions
        self.rules = rules
        self._previewed: str | None = None
        self.result: dict[str, str] = {}
        self.setWindowTitle("摘要の共通ルール")
        self.resize(1100, 760)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        note = QLabel(
            "ルールを承認すると、そのルールに当てはまる摘要すべてに同じ置き換えをします。"
            "数字（番号・日付・金額）が1文字でも変わる結果は使いません。先頭32文字で切ることもしません。"
            "プレビューで全件を確認してから反映してください。ルールで収まらない摘要は個別に入力します。"
        )
        note.setObjectName("infoCard")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.rule_table = _table(("承認", "ルール", "種類", "対象の語句", "短縮後の語句（入力）", "当てはまる摘要", "説明"))
        self.rule_table.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        self.rule_table.setRowCount(len(rules))
        for index, rule in enumerate(rules):
            tick = QTableWidgetItem()
            tick.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            tick.setCheckState(_UNCHECKED)
            self.rule_table.setItem(index, 0, tick)
            for column, value in enumerate((rule["ルールID"], rule["種類"], rule["対象の語句"]), 1):
                cell = _cell(value)
                cell.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.rule_table.setItem(index, column, cell)
            abbreviation = QTableWidgetItem("")
            if rule["種類"] == "語句の短縮":
                abbreviation.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsSelectable)
                abbreviation.setToolTip("この語をすべての摘要で置き換える短い言い方")
            else:
                abbreviation.setFlags(Qt.ItemFlag.ItemIsEnabled)
                abbreviation.setText("（入力不要）")
            self.rule_table.setItem(index, 4, abbreviation)
            for column, value in ((5, f"{rule['影響する摘要数']}件"), (6, rule["説明"])):
                cell = _cell(str(value))
                cell.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.rule_table.setItem(index, column, cell)
        self.rule_table.itemChanged.connect(self._rules_changed)
        layout.addWidget(self.rule_table, 2)
        preview_row = QHBoxLayout()
        self.preview_button = QPushButton("全件をプレビュー")
        self.preview_button.clicked.connect(self._preview)
        self.preview_label = QLabel("承認したルールでプレビューしてください。")
        self.preview_label.setObjectName("muted")
        preview_row.addWidget(self.preview_button)
        preview_row.addWidget(self.preview_label, 1)
        layout.addLayout(preview_row)
        self.preview_table = _table(("状態", "元の摘要", "置き換え後", "文字数"))
        layout.addWidget(self.preview_table, 3)
        actions = QHBoxLayout()
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        self.apply_button = QPushButton("プレビューした内容を入力欄に反映")
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self._apply)
        actions.addStretch(1)
        actions.addWidget(cancel)
        actions.addWidget(self.apply_button)
        layout.addLayout(actions)

    def current_rules(self) -> list[dict]:
        rules = []
        for index, rule in enumerate(self.rules):
            approved = self.rule_table.item(index, 0).checkState() == _CHECKED
            abbreviation = self.rule_table.item(index, 4).text() if rule["種類"] == "語句の短縮" else ""
            rules.append({**rule, "【記入】承認": "OK" if approved else "", "【記入】短縮後の語句": abbreviation})
        return rules

    def _rules_changed(self, *_args) -> None:
        # Any edit after a preview invalidates it.
        self._previewed = None
        self.apply_button.setEnabled(False)

    def _preview(self) -> None:
        rules = self.current_rules()
        problems = rule_problems(rules)
        if problems:
            self.preview_label.setText(" / ".join(problems))
            return
        lines = description_preview(self.descriptions, rules)
        state_label = {"FIT": "反映できる", "DIGITS_CHANGED": "数字が変わるため使わない", "INDIVIDUAL": "個別に入力"}
        self.preview_table.setRowCount(len(lines))
        for index, line in enumerate(lines):
            for column, value in enumerate(
                (state_label[line.state], line.original, line.result, str(len(line.result)) if line.result else "")
            ):
                self.preview_table.setItem(index, column, _cell(value))
        fit = sum(line.fits for line in lines)
        self.preview_label.setText(
            f"反映できる {fit}件 / 個別に入力 {len(lines) - fit}件（全{len(lines)}件）")
        self._previewed = preview_signature(lines)
        self.apply_button.setEnabled(fit > 0)

    def _apply(self) -> None:
        lines = description_preview(self.descriptions, self.current_rules())
        if self._previewed is None or preview_signature(lines) != self._previewed:
            self.preview_label.setText("プレビュー後にルールが変わりました。もう一度プレビューしてください。")
            self.apply_button.setEnabled(False)
            return
        self.result = {line.key: line.result for line in lines if line.fits}
        self.accept()
