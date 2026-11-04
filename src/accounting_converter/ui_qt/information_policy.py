"""GUI for Yayoi fields that JDL cannot hold (部門・生成元・付箋 など).

Confirming a field does NOT put it into JDL. It means: the field is left out of
the JDL CSV and every original value is preserved in the audit file next to
the formal CSV. The Human must state what the field means; nothing is inferred
or pre-filled.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
)

from accounting_converter.application.yayoi_information_policy import field_help

from .review_layout import checkbox_cell, count_item, dense_table, text_item


class YayoiInformationPolicyDialog(QDialog):
    def __init__(self, controller, company_id: str, fields, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.company_id = company_id
        self.fields = tuple(fields)
        self.saved: dict[str, str] = {}
        self.rows: list[tuple[object, QLineEdit | None, QCheckBox | None]] = []
        self.setWindowTitle("JDLに保持されない弥生の情報")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.resize(980, 560)
        self.setMinimumSize(720, 420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        title = QLabel("JDLに保持されない弥生の情報")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        explanation = QLabel(
            "次の項目は、JDLの取込CSVに入れる欄がありません。確認すると、この情報は"
            "<b>JDLには出力されず</b>、正式CSVと同じ場所に作られる<b>監査記録ファイル"
            "（出力ファイル名.audit.json）にすべての元の値を残します</b>。"
            "JDLの帳簿の上ではこの情報を見られなくなります。"
            "監査記録に残すことと、JDLに保持することは別です。"
        )
        explanation.setTextFormat(Qt.TextFormat.RichText)
        explanation.setObjectName("warningCard")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        hint = QLabel(
            "「この会社での意味」に、その項目が何の情報かを入力してから「確認」にチェックしてください。"
            "候補は入力していません。分からない項目は未確認のままにすると、その項目を含む仕訳は変換されません。"
        )
        hint.setObjectName("hintLine")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        headers = ("確認", "項目", "含む仕訳", "どんな情報か", "この会社での意味（入力）", "状態")
        self.table = dense_table(QTableWidget(len(self.fields), len(headers)))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        header = self.table.horizontalHeader()
        for column, mode in (
            (0, QHeaderView.ResizeMode.ResizeToContents),
            (1, QHeaderView.ResizeMode.ResizeToContents),
            (2, QHeaderView.ResizeMode.ResizeToContents),
            (3, QHeaderView.ResizeMode.Stretch),
            (4, QHeaderView.ResizeMode.Stretch),
            (5, QHeaderView.ResizeMode.ResizeToContents),
        ):
            header.setSectionResizeMode(column, mode)
        for row, item in enumerate(self.fields):
            self.table.setItem(row, 1, text_item(item.field))
            self.table.setItem(row, 2, count_item(item.journals))
            self.table.setItem(row, 3, text_item(field_help(item.field)))
            if item.confirmed:
                self.table.setItem(row, 4, text_item(item.meaning))
                self.table.setItem(row, 5, text_item("確認済み（監査記録に残す）"))
                self.rows.append((item, None, None))
                continue
            meaning = QLineEdit()
            meaning.setPlaceholderText("例: 担当者の確認済みの印")
            check = QCheckBox()
            check.setEnabled(False)
            check.setToolTip("この項目をJDLへは出さず、監査記録に残すことを確認しました")
            meaning.textChanged.connect(
                lambda text, box=check: (box.setChecked(False), box.setEnabled(bool(text.strip())))
            )
            check.toggled.connect(self._update)
            self.table.setCellWidget(row, 0, checkbox_cell(check))
            self.table.setCellWidget(row, 4, meaning)
            self.table.setItem(row, 5, text_item("未確認"))
            self.rows.append((item, meaning, check))
        layout.addWidget(self.table, 1)
        self.acknowledge = QCheckBox(
            "チェックした項目はJDLに保持されず、監査記録ファイルにのみ残ることを理解しました"
        )
        self.acknowledge.toggled.connect(self._update)
        layout.addWidget(self.acknowledge)
        self.message = QLabel()
        self.message.setObjectName("muted")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        actions = QHBoxLayout()
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        self.save_button = QPushButton("確認した項目を保存")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save)
        actions.addStretch(1)
        actions.addWidget(cancel)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)
        self._update()

    def chosen(self) -> dict[str, str]:
        return {
            item.field: meaning.text().strip()
            for item, meaning, check in self.rows
            if check is not None and check.isChecked() and meaning.text().strip()
        }

    def _update(self, *_args) -> None:
        chosen = self.chosen()
        self.save_button.setText(f"確認した{len(chosen)}項目を保存")
        self.save_button.setEnabled(bool(chosen) and self.acknowledge.isChecked())

    def _save(self) -> None:
        chosen = self.chosen()
        if not chosen or not self.acknowledge.isChecked():
            return
        state = self.controller.confirm_yayoi_information_policies(self.company_id, chosen)
        if state.developer_error is not None:
            self.message.setText(state.user_message or "保存できませんでした。")
            return
        self.saved = chosen
        self.accept()
