"""振替伝票入力行数 (JDL company setting) entered by the Human.

JDL rejects a voucher with more rows than this setting, also when it arrives
by CSV Import (real JDL Evidence, 2026-11-05). The value is read from the JDL
company setting; nothing is pre-filled or inferred. Entering it never makes an
over-limit journal importable, and the app never changes the JDL setting or
splits a journal.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)


def journals_over_limit(counts, limit: int | None) -> int:
    return sum(journals for rows, journals in counts if limit is not None and rows > limit)


class VoucherRowLimitDialog(QDialog):
    def __init__(self, controller, company_id: str, counts, current: int | None, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.company_id = company_id
        self.counts = tuple(counts)
        self.saved: int | None = None
        self.setWindowTitle("振替伝票入力行数")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        title = QLabel("振替伝票入力行数（JDLの会社設定）")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        note = QLabel(
            "JDLの会社設定に表示されている「振替伝票入力行数」の数字を、そのまま入力してください。<br>"
            "JDLは、この行数を超える伝票を<b>CSVの取込でも受け付けません</b>"
            "（実機の確認: 16行以内の設定で、16行は取込でき、17行以上は拒否されました）。<br>"
            "JDL出納帳35.5の選択肢は「16行以内」「64行以内」です。64行以内は2026-11-08の実機確認で、借方・貸方それぞれ64明細まで取り込めました（確認した形だけ変換できます。決算整理仕訳と控除不可は16行以内でのみ確認済みです）。<br>"
            "アプリはJDLの設定を変更せず、仕訳を自動で分割もしません。"
            "入力しても、行数を超える仕訳が取り込めるようにはなりません（分割するか、JDLで手入力が必要です）。"
        )
        note.setTextFormat(Qt.TextFormat.RichText)
        note.setObjectName("warningCard")
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        row.addWidget(QLabel("振替伝票入力行数"))
        self.value = QSpinBox()
        self.value.setRange(0, 999)
        self.value.setSuffix(" 行以内")
        self.value.setSpecialValueText("（未入力）")  # never pre-filled
        self.value.setValue(current or 0)
        row.addWidget(self.value)
        row.addStretch(1)
        layout.addLayout(row)
        self.over_label = QLabel()
        self.over_label.setWordWrap(True)
        layout.addWidget(self.over_label)
        self.acknowledge = QCheckBox("JDLの会社設定画面で確認した値です")
        layout.addWidget(self.acknowledge)
        self.message = QLabel()
        self.message.setObjectName("muted")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        actions = QHBoxLayout()
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        self.save_button = QPushButton("保存")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save)
        actions.addStretch(1)
        actions.addWidget(cancel)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)
        self.value.valueChanged.connect(self._update)
        self.acknowledge.toggled.connect(self._update)
        self._update()

    def _update(self, *_args) -> None:
        limit = self.value.value() or None
        longest = max((rows for rows, _journals in self.counts), default=0)
        if limit is None:
            self.over_label.setText(f"この会社の仕訳は、最長 {longest} 行です。")
        else:
            from accounting_converter.adapters.output.jdl.scoped_evidence import verified_row_limits

            over = journals_over_limit(self.counts, limit)
            self.over_label.setText(
                f"この会社の仕訳は最長 {longest} 行です。{limit}行を超える仕訳: <b>{over}仕訳</b>"
                + ("（JDLに1伝票として取り込めません。分割または手入力が必要です）" if over else "")
                + ("" if limit in verified_row_limits() else
                   f"<br><b>{limit}行以内はJDL実機で未確認の設定です。保存はできますが、確認が済むまで変換されません。</b>")
            )
            self.over_label.setTextFormat(Qt.TextFormat.RichText)
        self.save_button.setEnabled(limit is not None and self.acknowledge.isChecked())

    def _save(self) -> None:
        limit = self.value.value()
        if not limit or not self.acknowledge.isChecked():
            return
        state = self.controller.confirm_company_voucher_row_limit(
            self.company_id, limit, explicitly_confirmed=True
        )
        if state.developer_error is not None:
            self.message.setText(state.user_message or "保存できませんでした。")
            return
        self.saved = limit
        self.accept()
