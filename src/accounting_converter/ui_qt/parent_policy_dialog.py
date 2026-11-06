"""Per-parent subaccount policy: keep the subaccounts, or convert with the parent account only.

Fills the review form's own selections and confirmation checks; it never saves. Nothing is
pre-selected, "parent only" is offered only where the JDL parent has no subaccount, and the
loss is shown and acknowledged before anything is applied.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from accounting_converter.application.parent_subaccount_policy import ParentPolicyRow

from .review_layout import count_item, dense_table, text_item

KEEP = "KEEP"
PARENT_ONLY = "PARENT_ONLY"
_LOSS = ("入力元の補助科目名はJDLへ引き継がれません（CSVの補助は空欄になります）。"
         "元の補助名・親科目・行番号は、出力CSVと対になる監査ファイル（.audit.json）に残ります。")


class ParentPolicyDialog(QDialog):
    def __init__(self, rows: tuple[ParentPolicyRow, ...], parent=None) -> None:
        super().__init__(parent)
        self.rows = rows
        self.setWindowTitle("親科目ごとに補助科目の扱いを選ぶ")
        self.resize(1100, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        self.pages.addWidget(self._choose_page())
        self.pages.addWidget(self._confirm_page())
        self._changed()

    # ------------------------------------------------------------ page 1
    def _choose_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        intro = QLabel(
            "親科目ごとに、補助科目の扱いを選びます（初期値は「選ばない」。選んだ親科目だけが対象です）。\n"
            "・補助を保持：JDLに同名の補助がある分を対応付けます。残りは個別に対応付けるか、JDLへ登録してください。\n"
            "・親科目のみ：JDLの親科目に補助がない場合だけ選べます。補助別の管理はJDLでは行いません。\n"
            "ここでは保存しません。確認画面の保存ボタンで、元ファイルと現在のJDL科目一覧を照合して保存します。")
        intro.setObjectName("detailText")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        headers = ("入力元の親科目", "JDLの親科目", "補助の数", "仕訳数（延べ）", "選べる扱い", "この親科目の扱い")
        self.table = dense_table(QTableWidget(len(self.rows), len(headers)))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        for column, mode in enumerate((
            QHeaderView.ResizeMode.Interactive, QHeaderView.ResizeMode.Interactive,
            QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.ResizeToContents,
            QHeaderView.ResizeMode.Stretch, QHeaderView.ResizeMode.Interactive,
        )):
            header.setSectionResizeMode(column, mode)
        self.table.setColumnWidth(0, 170)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(5, 220)
        self.combos: list[QComboBox] = []
        for index, row in enumerate(self.rows):
            self.table.setItem(index, 0, text_item(row.group.source_parent))
            self.table.setItem(index, 1, text_item(row.group.parent_target or "（未確定）"))
            self.table.setItem(index, 2, count_item(row.subaccounts))
            self.table.setItem(index, 3, count_item(row.journals))
            self.table.setItem(index, 4, text_item(self._availability(row)))
            self.table.item(index, 4).setToolTip(self._availability_detail(row))
            combo = QComboBox()
            combo.addItem("選ばない（個別に確認）", None)
            combo.addItem("補助を保持（同名の補助を対応付け）", KEEP)
            combo.addItem("親科目のみ（補助を引き継がない）", PARENT_ONLY)
            model = combo.model()
            for position, allowed, reason in ((1, row.preserve_allowed, row.preserve_reason),
                                              (2, row.parent_only_allowed, row.parent_only_reason)):
                if not allowed:
                    model.item(position).setEnabled(False)
                    combo.setItemData(position, reason or "", Qt.ItemDataRole.ToolTipRole)
            combo.currentIndexChanged.connect(self._changed)
            self.table.setCellWidget(index, 5, combo)
            self.combos.append(combo)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.count_label = QLabel()
        self.count_label.setObjectName("muted")
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        self.next_button = QPushButton("選んだ内容を確認へ")
        self.next_button.setObjectName("primaryButton")
        self.next_button.clicked.connect(self._show_confirm)
        actions.addWidget(self.count_label, 1)
        actions.addWidget(cancel)
        actions.addWidget(self.next_button)
        layout.addLayout(actions)
        return page

    @staticmethod
    def _availability(row: ParentPolicyRow) -> str:
        parts = []
        if row.preserve_allowed:
            parts.append(f"補助を保持（同名{row.preserve_matches}件" +
                         (f"・残り{row.individual_after_preserve}件は個別" if row.individual_after_preserve else "") + "）")
        if row.parent_only_allowed:
            parts.append("親科目のみ")
        return "・".join(parts) if parts else "個別に対応付けが必要"

    @staticmethod
    def _availability_detail(row: ParentPolicyRow) -> str:
        notes = []
        if not row.parent_only_allowed:
            notes.append("親科目のみにできない理由: " + (row.parent_only_reason or ""))
        if not row.preserve_allowed:
            notes.append("補助を保持できない理由: " + (row.preserve_reason or ""))
        return "\n".join(notes)

    # ------------------------------------------------------------ page 2
    def _confirm_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        heading = QLabel("選んだ内容の確認")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        self.summary = QLabel()
        self.summary.setObjectName("detailText")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        headers = ("入力元の親科目", "扱い", "補助の数", "仕訳数（延べ）", "影響")
        self.review_table = dense_table(QTableWidget(0, len(headers)))
        self.review_table.setHorizontalHeaderLabels(headers)
        self.review_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.review_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.review_table, 1)
        self.loss_ack = QCheckBox("補助科目を引き継がない親科目があることを理解し、確認しました")
        self.loss_ack.toggled.connect(self._ack_changed)
        layout.addWidget(self.loss_ack)
        actions = QHBoxLayout()
        back = QPushButton("戻って選び直す")
        back.clicked.connect(lambda: self.pages.setCurrentIndex(0))
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        self.apply_button = QPushButton("確認画面に反映する（まだ保存しません）")
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.clicked.connect(self.accept)
        actions.addWidget(back)
        actions.addStretch(1)
        actions.addWidget(cancel)
        actions.addWidget(self.apply_button)
        layout.addLayout(actions)
        return page

    # ------------------------------------------------------------ logic
    def choices(self) -> dict[str, str]:
        """source parent -> KEEP / PARENT_ONLY, for the parents the Human actually chose."""
        return {row.group.source_parent: combo.currentData()
                for row, combo in zip(self.rows, self.combos) if combo.currentData() is not None}

    def _changed(self, *_args) -> None:
        chosen = self.choices()
        self.count_label.setText(f"選んだ親科目 {len(chosen)}件 / 全{len(self.rows)}件")
        self.next_button.setEnabled(bool(chosen))

    def _show_confirm(self) -> None:
        chosen = self.choices()
        picked = [(row, chosen[row.group.source_parent]) for row in self.rows if row.group.source_parent in chosen]
        only = [(row, c) for row, c in picked if c == PARENT_ONLY]
        self.review_table.setRowCount(len(picked))
        for index, (row, choice) in enumerate(picked):
            if choice == PARENT_ONLY:
                label, effect = "親科目のみ", f"補助{row.subaccounts}件を引き継ぎません。{_LOSS}"
            else:
                label = "補助を保持"
                effect = (f"同名の補助{row.preserve_matches}件を対応付けます。"
                          + (f"残り{row.individual_after_preserve}件は個別の確認が必要です。" if row.individual_after_preserve else ""))
            for column, value in enumerate((row.group.source_parent, label)):
                self.review_table.setItem(index, column, text_item(value))
            self.review_table.setItem(index, 2, count_item(row.subaccounts))
            self.review_table.setItem(index, 3, count_item(row.journals))
            self.review_table.setItem(index, 4, text_item(effect))
        lost = sum(row.subaccounts for row, _c in only)
        self.summary.setText(
            f"{len(picked)}件の親科目を選びました（親科目のみ {len(only)}件・補助 {lost}件を引き継ぎません）。\n"
            "選んでいない親科目には何も反映しません。確認画面の保存ボタンを押すまで保存されません。")
        self.loss_ack.setVisible(bool(only))
        self.loss_ack.setChecked(False)
        self._ack_changed()
        self.pages.setCurrentIndex(1)

    def _ack_changed(self, *_args) -> None:
        needs = any(c == PARENT_ONLY for c in self.choices().values())
        self.apply_button.setEnabled(not needs or self.loss_ack.isChecked())
