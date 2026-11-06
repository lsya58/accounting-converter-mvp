"""Bulk confirmation dialogs for the review screen.

Both dialogs only return what the Human ticked / approved. They never save:
the review dialog fills its own per-row controls and the existing save runs
all checks again.
"""
from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from accounting_converter.application.review_bulk import (
    BulkRow,
    description_preview,
    mechanical_description_candidates,
    preview_signature,
    provisional_description_preview,
    rule_problems,
    selected_description_results,
)

from .review_layout import CollapsibleSection, count_item, dense_table, text_item

_CHECKED = Qt.CheckState.Checked
_UNCHECKED = Qt.CheckState.Unchecked
_ROW_INDEX = Qt.ItemDataRole.UserRole


def _size_to_screen(dialog: QDialog, width: int, height: int) -> None:
    """Open large, but never larger than the available screen."""
    dialog.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
    screen = dialog.screen() or QApplication.primaryScreen()
    if screen is None:
        dialog.resize(width, height)
        return
    available = screen.availableGeometry()
    dialog.resize(min(width, int(available.width() * 0.92)), min(height, int(available.height() * 0.9)))


def _sortable_count(value: int) -> QTableWidgetItem:
    """An int display value: Qt sorts it numerically without a Python subclass."""
    cell = QTableWidgetItem()
    cell.setData(Qt.ItemDataRole.DisplayRole, int(value))
    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    cell.setToolTip(f"{value:,}仕訳")
    return cell


class BulkCandidateDialog(QDialog):
    """Choose suggested targets, then review the chosen list before applying.

    Only same-name rows start ticked. Nothing is saved here: accepted rows
    only fill the review screen's own selections.
    """

    def __init__(self, title: str, rows: list[BulkRow], parent=None) -> None:
        super().__init__(parent)
        self.rows = rows
        self.setWindowTitle(title)
        _size_to_screen(self, 1280, 820)
        self._has_parent = any(row.parent for row in rows)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        self.pages.addWidget(self._choose_page(title))
        self.pages.addWidget(self._review_page())
        self._update()

    # ------------------------------------------------------------ page 1
    def _choose_page(self, title: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        heading = QLabel(f"{title}（1/2 対象を選ぶ）")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        note = QLabel(
            "名前が同じ候補だけ、最初からチェックしています。言い換え・部分一致・類似の候補は"
            "チェックしていません。違うものはチェックを外してください。"
            "ここで選んだ行は確認画面の「確認」列にチェックが入るだけで、保存は確認画面の保存ボタンで行います。"
        )
        note.setObjectName("detailText")
        note.setWordWrap(True)
        layout.addWidget(CollapsibleSection("この画面の説明", note))
        toolbar = QHBoxLayout()
        self.kind_filter = QComboBox()
        self.kind_filter.addItem("すべての候補", "")
        for kind_label, count in Counter(row.kind_label for row in self.rows).most_common():
            self.kind_filter.addItem(f"{kind_label}（{count}件）", kind_label)
        self.search = QLineEdit()
        self.search.setPlaceholderText("名前で絞り込み")
        self.search.setClearButtonEnabled(True)
        select_none = QPushButton("すべて外す")
        select_none.clicked.connect(lambda: self._set_all(False))
        select_same = QPushButton("名前が同じものだけ選ぶ")
        select_same.clicked.connect(lambda: self._set_all(None))
        toolbar.addWidget(self.kind_filter)
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(select_none)
        toolbar.addWidget(select_same)
        layout.addLayout(toolbar)
        headers = ["対象", "入力元の親科目", "入力元の科目・補助", "JDLの対応先（候補）", "候補の種類", "影響仕訳（件）", "注意"]
        self.table = dense_table(QTableWidget(len(self.rows), len(headers)))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeaderItem(5).setToolTip("この科目・補助を使う仕訳の数です（行をまたいで重複して数えることがあります）。")
        for index, row in enumerate(self.rows):
            tick = QTableWidgetItem()
            tick.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            tick.setCheckState(_CHECKED if row.pre_ticked else _UNCHECKED)
            tick.setData(_ROW_INDEX, index)
            self.table.setItem(index, 0, tick)
            self.table.setItem(index, 1, text_item(row.parent or "-"))
            self.table.setItem(index, 2, text_item(row.source))
            self.table.setItem(index, 3, text_item(row.target_label))
            self.table.setItem(index, 4, text_item(row.kind_label))
            self.table.setItem(index, 5, _sortable_count(row.journals))
            warning = text_item(row.warning)
            if row.warning:
                warning.setForeground(Qt.GlobalColor.darkRed)
            self.table.setItem(index, 6, warning)
        # Names keep a readable width (scroll sideways on narrow screens);
        # the warning column takes what is left.
        header = self.table.horizontalHeader()
        for column, mode in (
            (0, QHeaderView.ResizeMode.ResizeToContents),
            (1, QHeaderView.ResizeMode.Interactive),
            (2, QHeaderView.ResizeMode.Interactive),
            (3, QHeaderView.ResizeMode.Interactive),
            (4, QHeaderView.ResizeMode.ResizeToContents),
            (5, QHeaderView.ResizeMode.ResizeToContents),
            (6, QHeaderView.ResizeMode.Stretch),
        ):
            header.setSectionResizeMode(column, mode)
        header.setMinimumSectionSize(60)
        self.table.setColumnWidth(1, 170)
        self.table.setColumnWidth(2, 240)
        self.table.setColumnWidth(3, 280)
        self.table.setColumnHidden(1, not self._has_parent)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(5, Qt.SortOrder.DescendingOrder)
        self.table.itemChanged.connect(self._update)
        self.kind_filter.currentIndexChanged.connect(self._filter)
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.count_label = QLabel()
        self.count_label.setObjectName("muted")
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        self.next_button = QPushButton()
        self.next_button.setObjectName("primaryButton")
        self.next_button.clicked.connect(self._show_review)
        actions.addWidget(self.count_label, 1)
        actions.addWidget(cancel)
        actions.addWidget(self.next_button)
        layout.addLayout(actions)
        return page

    # ------------------------------------------------------------ page 2
    def _review_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        heading = QLabel("選んだ内容の確認（2/2）")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        self.review_summary = QLabel()
        self.review_summary.setObjectName("detailText")
        self.review_summary.setWordWrap(True)
        layout.addWidget(self.review_summary)
        headers = ("入力元の親科目", "入力元の科目・補助", "JDLの対応先", "候補の種類", "影響仕訳", "注意")
        self.review_table = dense_table(QTableWidget(0, len(headers)))
        self.review_table.setHorizontalHeaderLabels(headers)
        self.review_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.review_table.horizontalHeader()
        for column, mode in (
            (0, QHeaderView.ResizeMode.Interactive),
            (1, QHeaderView.ResizeMode.Interactive),
            (2, QHeaderView.ResizeMode.Interactive),
            (3, QHeaderView.ResizeMode.ResizeToContents),
            (4, QHeaderView.ResizeMode.ResizeToContents),
            (5, QHeaderView.ResizeMode.Stretch),
        ):
            header.setSectionResizeMode(column, mode)
        header.setMinimumSectionSize(60)
        self.review_table.setColumnWidth(0, 170)
        self.review_table.setColumnWidth(1, 240)
        self.review_table.setColumnWidth(2, 280)
        self.review_table.setColumnHidden(0, not self._has_parent)
        layout.addWidget(self.review_table, 1)
        actions = QHBoxLayout()
        back = QPushButton("戻って選び直す")
        back.clicked.connect(lambda: self.pages.setCurrentIndex(0))
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        self.apply_button = QPushButton()
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.clicked.connect(self.accept)
        actions.addWidget(back)
        actions.addStretch(1)
        actions.addWidget(cancel)
        actions.addWidget(self.apply_button)
        layout.addLayout(actions)
        return page

    # ------------------------------------------------------------ logic
    def _ticks(self):
        for table_row in range(self.table.rowCount()):
            tick = self.table.item(table_row, 0)
            yield table_row, tick, self.rows[tick.data(_ROW_INDEX)]

    def _set_all(self, value: bool | None) -> None:
        self.table.blockSignals(True)
        for _table_row, tick, row in self._ticks():
            ticked = row.pre_ticked if value is None else value
            tick.setCheckState(_CHECKED if ticked else _UNCHECKED)
        self.table.blockSignals(False)
        self._update()

    def _filter(self, *_args) -> None:
        wanted = self.kind_filter.currentData()
        text = self.search.text().strip()
        for table_row, _tick, row in self._ticks():
            matches = (not wanted or row.kind_label == wanted) and (
                not text or any(text in value for value in (row.source, row.parent, row.target_label))
            )
            self.table.setRowHidden(table_row, not matches)

    def selected(self) -> list[BulkRow]:
        chosen = {tick.data(_ROW_INDEX) for _r, tick, _row in self._ticks() if tick.checkState() == _CHECKED}
        return [row for index, row in enumerate(self.rows) if index in chosen]

    def _update(self, *_args) -> None:
        chosen = self.selected()
        journals = sum(row.journals for row in chosen)
        self.count_label.setText(f"選択 {len(chosen)}件 / 全{len(self.rows)}件 ・ 影響 {journals:,}仕訳（延べ）")
        self.next_button.setText(f"選んだ{len(chosen)}件の内容を確認へ")
        self.next_button.setEnabled(bool(chosen))

    def _show_review(self) -> None:
        chosen = self.selected()
        if not chosen:
            return
        kinds = Counter(row.kind_label for row in chosen)
        self.review_summary.setText(
            f"次の{len(chosen)}件を、確認画面で「確認」にチェックします"
            f"（{'・'.join(f'{label} {count}件' for label, count in kinds.items())}）。"
            f"影響 {sum(row.journals for row in chosen):,}仕訳（延べ）。\n"
            "まだ保存はされません。確認画面の保存ボタンを押したときに、元ファイルと現在のJDL科目一覧をもう一度照合して保存します。"
        )
        self.review_table.setRowCount(len(chosen))
        for index, row in enumerate(chosen):
            for column, value in enumerate((row.parent or "-", row.source, row.target_label, row.kind_label)):
                self.review_table.setItem(index, column, text_item(value))
            self.review_table.setItem(index, 4, count_item(row.journals))
            self.review_table.setItem(index, 5, text_item(row.warning))
        self.apply_button.setText(f"この{len(chosen)}件を確認済みにする")
        self.pages.setCurrentIndex(1)


_STATE_LABEL = {"FIT": "反映できる", "DIGITS_CHANGED": "数字・表記が変わるため使わない", "INDIVIDUAL": "個別に入力"}


class DescriptionRulesDialog(QDialog):
    """Suggest, preview, and explicitly select fitting descriptions for the review form."""

    def __init__(self, descriptions: list[tuple[str, str]], rules: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.descriptions = descriptions
        self.rules = rules
        self._previewed: str | None = None
        self._lines = []
        self._selected_keys: set[str] = set()
        self.result: dict[str, str] = {}
        self.setWindowTitle("摘要の共通ルール")
        _size_to_screen(self, 1400, 900)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        note = QLabel(
            "ルールを承認すると、そのルールに当てはまる摘要すべてに同じ置き換えをします。"
            "数字（番号・日付・金額）が1文字でも変わる結果は使いません。先頭32文字で切ることもしません。"
            "機械的候補は提案のみです。プレビュー後、反映する行を選択してください。"
            "ルールで収まらない摘要は確認画面で個別に入力します。保存は確認画面で行います。"
        )
        note.setObjectName("detailText")
        note.setWordWrap(True)
        layout.addWidget(CollapsibleSection("手順と安全のための決まり（①ルールを承認 → ②全件をプレビュー → ③反映）", note))
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

        rules_box = QWidget()
        rules_layout = QVBoxLayout(rules_box)
        rules_layout.setContentsMargins(0, 0, 0, 0)
        rules_layout.setSpacing(4)
        rules_title = QLabel(f"① ルール（{len(rules)}件）: 使うルールの「承認」にチェック。語句の短縮は短縮後の語句を入力")
        rules_title.setObjectName("sectionTitle")
        rules_layout.addWidget(rules_title)
        self.rule_table = dense_table(
            QTableWidget(0, 7)
        )
        self.rule_table.setHorizontalHeaderLabels(("承認", "ルール", "種類", "対象の語句", "短縮後の語句（入力）", "当てはまる摘要", "説明"))
        self.rule_table.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        self.rule_table.setRowCount(len(rules))
        for index, rule in enumerate(rules):
            tick = QTableWidgetItem()
            tick.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            tick.setCheckState(_UNCHECKED)
            self.rule_table.setItem(index, 0, tick)
            for column, value in enumerate((rule["ルールID"], rule["種類"], rule["対象の語句"]), 1):
                self.rule_table.setItem(index, column, text_item(value))
            abbreviation = QTableWidgetItem("")
            if rule["種類"] == "語句の短縮":
                abbreviation.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsSelectable)
                abbreviation.setToolTip("この語をすべての摘要で置き換える短い言い方（ダブルクリックで入力）")
            else:
                abbreviation.setFlags(Qt.ItemFlag.ItemIsEnabled)
                abbreviation.setText("（入力不要）")
            self.rule_table.setItem(index, 4, abbreviation)
            self.rule_table.setItem(index, 5, count_item(int(rule["影響する摘要数"])))
            self.rule_table.setItem(index, 6, text_item(str(rule["説明"])))
        header = self.rule_table.horizontalHeader()
        for column, mode in (
            (0, QHeaderView.ResizeMode.ResizeToContents),
            (1, QHeaderView.ResizeMode.ResizeToContents),
            (2, QHeaderView.ResizeMode.ResizeToContents),
            (3, QHeaderView.ResizeMode.Interactive),
            (4, QHeaderView.ResizeMode.Interactive),
            (5, QHeaderView.ResizeMode.ResizeToContents),
            (6, QHeaderView.ResizeMode.Stretch),
        ):
            header.setSectionResizeMode(column, mode)
        self.rule_table.setColumnWidth(3, 220)
        self.rule_table.setColumnWidth(4, 200)
        self.rule_table.itemChanged.connect(self._rules_changed)
        rules_layout.addWidget(self.rule_table, 1)
        splitter.addWidget(rules_box)

        preview_box = QWidget()
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(4)
        preview_row = QHBoxLayout()
        self.suggest_button = QPushButton("機械的候補を探す")
        self.suggest_button.clicked.connect(self._suggest)
        self.preview_button = QPushButton("② 全件をプレビュー")
        self.preview_button.setObjectName("primaryButton")
        self.preview_button.clicked.connect(self._preview)
        self.preview_label = QLabel("承認したルールでプレビューしてください。")
        self.preview_label.setObjectName("muted")
        self.preview_label.setWordWrap(True)
        self.state_filter = QComboBox()
        self.state_filter.addItem("すべて表示", "")
        for state, label in _STATE_LABEL.items():
            self.state_filter.addItem(label, state)
        self.preview_search = QLineEdit()
        self.preview_search.setMinimumWidth(180)
        self.preview_search.setPlaceholderText("摘要で絞り込み")
        self.preview_search.setClearButtonEnabled(True)
        self.wrap_toggle = QCheckBox("長い摘要を折り返して全文表示")
        preview_row.addWidget(self.suggest_button)
        preview_row.addWidget(self.preview_button)
        preview_row.addWidget(self.state_filter)
        preview_row.addWidget(self.preview_search)
        preview_row.addWidget(self.wrap_toggle)
        preview_layout.addLayout(preview_row)
        preview_layout.addWidget(self.preview_label)
        self.pattern_filter = QComboBox()
        self.pattern_filter.addItem("すべての変更パターン", "")
        self.select_pattern = QPushButton("このパターンを選択")
        self.select_pattern.clicked.connect(self._select_pattern)
        self.clear_selection = QPushButton("選択解除")
        self.clear_selection.clicked.connect(self._clear_selection)
        pattern_row = QHBoxLayout()
        pattern_row.addWidget(self.pattern_filter, 1)
        pattern_row.addWidget(self.select_pattern)
        pattern_row.addWidget(self.clear_selection)
        preview_layout.addLayout(pattern_row)
        self.preview_table = dense_table(QTableWidget(0, 7))
        self.preview_table.setHorizontalHeaderLabels(("選択", "状態", "元の摘要", "置き換え後", "変更ルール", "文字数 / CP932バイト", "理由"))
        self.preview_table.horizontalHeaderItem(5).setToolTip(
            "JDLの上限は32文字です。バイト数はCP932で表現できるかの確認用で、32バイト制限ではありません。"
        )
        self.preview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        preview_header = self.preview_table.horizontalHeader()
        for column, mode in (
            (0, QHeaderView.ResizeMode.ResizeToContents),
            (1, QHeaderView.ResizeMode.ResizeToContents),
            (2, QHeaderView.ResizeMode.Stretch),
            (3, QHeaderView.ResizeMode.Stretch),
            (4, QHeaderView.ResizeMode.ResizeToContents),
            (5, QHeaderView.ResizeMode.ResizeToContents),
            (6, QHeaderView.ResizeMode.Interactive),
        ):
            preview_header.setSectionResizeMode(column, mode)
        self.preview_table.setColumnWidth(6, 220)
        self.preview_table.itemChanged.connect(self._selection_changed)
        preview_layout.addWidget(self.preview_table, 1)
        self.preview_detail = QLabel("行を選ぶと、元の摘要と置き換え後の全文をここに表示します。")
        self.preview_detail.setMaximumHeight(160)
        self.preview_detail.setObjectName("detailText")
        self.preview_detail.setWordWrap(True)
        self.preview_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        preview_layout.addWidget(self.preview_detail)
        splitter.addWidget(preview_box)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes((260, 520))
        self.state_filter.currentIndexChanged.connect(self._filter_preview)
        self.pattern_filter.currentIndexChanged.connect(self._filter_preview)
        self.preview_search.textChanged.connect(self._filter_preview)
        self.wrap_toggle.toggled.connect(self._set_wrap)
        self.preview_table.currentCellChanged.connect(lambda row, _c, _pr, _pc: self._show_line(row))

        actions = QHBoxLayout()
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        self.apply_button = QPushButton("③ 選択した候補を入力欄に反映")
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
        self.preview_label.setText("ルールが変わりました。もう一度プレビューしてください。")
        self._previewed = None
        self._lines = []
        self._selected_keys.clear()
        self.preview_table.setRowCount(0)
        self.preview_detail.setText("ルール変更後の結果は、再プレビューで確認してください。")
        self.apply_button.setEnabled(False)

    def _suggest(self) -> None:
        self._previewed = None
        self._selected_keys.clear()
        lines = mechanical_description_candidates(self.descriptions, self.current_rules())
        self._show_preview(lines)
        count = sum(line.fits and line.result != line.original for line in lines)
        self.preview_label.setText(
            f"機械的な整形候補 {count}件。まだ承認・反映していません。"
            "使うルールを承認して②全件をプレビューし、反映する行を選択してください。"
        )
        self.apply_button.setEnabled(False)

    def _preview(self) -> None:
        rules = self.current_rules()
        lines, problems = provisional_description_preview(self.descriptions, rules)
        self._selected_keys.clear()
        self._show_preview(lines)
        fit = sum(line.fits for line in lines)
        prefix = "仮プレビューの候補" if problems else "反映できる"
        summary = f"{prefix} {fit}件 / 個別に入力 {len(lines) - fit}件（全{len(lines)}件）"
        if problems:
            missing_ids = ", ".join(rule["ルールID"] for rule in rules if (
                rule["【記入】承認"] == "OK" and rule["種類"] == "語句の短縮"
                and not rule["【記入】短縮後の語句"].strip()
            ))
            summary += (f"\n承認済みの語句短縮 {len(problems)}件に短縮後の語句が未入力です"
                        f"（{missing_ids}）。入力するか承認を外してください。"
                        "上の件数は入力済みルールだけの仮結果で、まだ反映できません。")
        elif not fit:
            summary += "\n反映できる摘要はありません。右端の理由を確認し、必要な行は個別に入力してください。"
        else:
            summary += "\n反映する行を選ぶか、変更パターンで絞って選択してください。保存は確認画面で行います。"
        self.preview_label.setText(summary)
        self._previewed = preview_signature(lines) if not problems else None
        self._update_apply()

    def _show_preview(self, lines) -> None:
        self._lines = lines
        self.preview_table.blockSignals(True)
        self.preview_table.setRowCount(len(lines))
        for index, line in enumerate(lines):
            try:
                byte_count = str(len(line.result.encode("cp932", errors="strict"))) if line.result else ""
            except UnicodeEncodeError:
                byte_count = "不可"
            size = f"{len(line.result)} / {byte_count}" if line.result else ""
            tick = QTableWidgetItem()
            tick.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            tick.setCheckState(_UNCHECKED)
            if not line.fits or line.result == line.original:
                tick.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.preview_table.setItem(index, 0, tick)
            values = (_STATE_LABEL[line.state], line.original, line.result,
                      "+".join(line.applied_rule_ids) or "変更なし", size, line.reason)
            for column, value in enumerate(values, 1):
                self.preview_table.setItem(index, column, text_item(value.replace("\n", "⏎")))
        self.preview_table.blockSignals(False)
        patterns = sorted({"+".join(line.applied_rule_ids) for line in lines if line.fits and line.applied_rule_ids})
        self.pattern_filter.blockSignals(True)
        self.pattern_filter.clear()
        self.pattern_filter.addItem("すべての変更パターン", "")
        for pattern in patterns:
            self.pattern_filter.addItem(pattern, pattern)
        self.pattern_filter.blockSignals(False)
        self._filter_preview()
        self._set_wrap(self.wrap_toggle.isChecked())

    def _selection_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        if self._previewed is None:
            self.preview_table.blockSignals(True)
            item.setCheckState(_UNCHECKED)
            self.preview_table.blockSignals(False)
            return
        line = self._lines[item.row()]
        if item.checkState() == _CHECKED and line.fits and line.result != line.original:
            self._selected_keys.add(line.key)
        else:
            self._selected_keys.discard(line.key)
        self._update_apply()

    def _update_apply(self) -> None:
        self.apply_button.setText(f"③ 選択した{len(self._selected_keys)}件を入力欄に反映")
        self.apply_button.setEnabled(self._previewed is not None and bool(self._selected_keys))

    def _clear_selection(self) -> None:
        self.preview_table.blockSignals(True)
        for row in range(self.preview_table.rowCount()):
            self.preview_table.item(row, 0).setCheckState(_UNCHECKED)
        self.preview_table.blockSignals(False)
        self._selected_keys.clear()
        self._update_apply()

    def _select_pattern(self) -> None:
        if self._previewed is None:
            return
        wanted = self.pattern_filter.currentData()
        if not wanted:
            return
        self.preview_table.blockSignals(True)
        for index, line in enumerate(self._lines):
            if line.fits and line.result != line.original and "+".join(line.applied_rule_ids) == wanted:
                self.preview_table.item(index, 0).setCheckState(_CHECKED)
                self._selected_keys.add(line.key)
        self.preview_table.blockSignals(False)
        self._update_apply()

    def _filter_preview(self, *_args) -> None:
        wanted = self.state_filter.currentData()
        pattern = self.pattern_filter.currentData()
        text = self.preview_search.text().strip()
        for index, line in enumerate(self._lines):
            matches = (not wanted or line.state == wanted) and (not pattern or "+".join(line.applied_rule_ids) == pattern) and (
                not text or text in line.original or text in line.result
            )
            self.preview_table.setRowHidden(index, not matches)

    def _set_wrap(self, wrap: bool) -> None:
        self.preview_table.setWordWrap(wrap)
        if wrap:
            self.preview_table.resizeRowsToContents()
        else:
            for row in range(self.preview_table.rowCount()):
                self.preview_table.setRowHeight(row, self.preview_table.verticalHeader().defaultSectionSize())

    def _show_line(self, row: int) -> None:
        if not 0 <= row < len(self._lines):
            return
        line = self._lines[row]
        changes = [
            f"{line.original[start:end] or '（なし）'} → {line.result[new_start:new_end] or '（なし）'}"
            for kind, start, end, new_start, new_end in SequenceMatcher(
                None, line.original, line.result, autojunk=False
            ).get_opcodes() if kind != "equal"
        ]
        self.preview_detail.setText(
            f"元の摘要: {line.original}\n置き換え後: {line.result or '（ルールが当てはまりません）'}"
            f"{f'（{len(line.result)}文字）' if line.result else ''}\n"
            f"変更: {' / '.join(changes) if changes else 'なし'}\n状態: {_STATE_LABEL[line.state]}"
            f" / 理由: {line.reason}"
        )

    def _apply(self) -> None:
        rules = self.current_rules()
        lines = description_preview(self.descriptions, rules)
        if rule_problems(rules) or self._previewed is None or preview_signature(lines) != self._previewed:
            self.preview_label.setText("プレビュー後にルールが変わりました。もう一度プレビューしてください。")
            self.apply_button.setEnabled(False)
            return
        try:
            self.result = selected_description_results(lines, self._selected_keys)
        except ValueError:
            self.preview_label.setText("確認対象が重複しているか、適合しない候補が選ばれています。反映せず開き直してください。")
            self.apply_button.setEnabled(False)
            return
        self.accept()
