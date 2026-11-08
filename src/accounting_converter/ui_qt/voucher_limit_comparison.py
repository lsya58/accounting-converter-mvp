"""Read-only comparison; no confirmation or persistence actions."""
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHeaderView,
    QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout,
)


class VoucherLimitComparisonDialog(QDialog):
    def __init__(self, report, parent=None):
        super().__init__(parent)
        self.report = report
        self.setWindowTitle("16行・64行の比較診断")
        self.resize(980, 660)
        if self.screen():
            size = self.screen().availableGeometry().size()
            self.resize(min(980, size.width()), min(660, size.height()))
        layout = QVBoxLayout(self)
        total = len(report.journals)
        label = QLabel(
            f"保存中の設定: {report.saved_limit or '未確認'}行 / 正式READY {report.formal.ready_journals}/{total}件\n"
            "保存済みの確認結果による比較です。画面上の未保存の変更は含みません。\n"
            "異なる設定の結果は条件付き試算です。実際のJDL設定との一致確認が必要です。\n"
            "16行は既存の保守的判定、64行は借方・貸方の多い側の明細数で判定します。")
        label.setWordWrap(True)
        layout.addWidget(label)
        from accounting_converter.application.readiness_breakdown import describe
        codes = sorted(set().union(*(t.assessment.blocker_counts() for t in report.trials)))
        self.summary = QTableWidget(5 + len(codes), 3)
        self.summary.setHorizontalHeaderLabels(["判定", "16行", "64行"])
        self.summary.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        names = ["READY", "BLOCK", "上限超過（分割等の対応が必要）", "分割候補", "分割承認待ち"]
        for row, name in enumerate(names):
            self.summary.setItem(row, 0, QTableWidgetItem(name))
        for col, trial in enumerate(report.trials, 1):
            values = [trial.assessment.ready_journals, total - trial.assessment.ready_journals,
                      trial.over_limit, trial.split_candidates, trial.approval_required]
            for row, value in enumerate(values):
                self.summary.setItem(row, col, QTableWidgetItem(str(value)))
            for row, code in enumerate(codes, 5):
                name = QTableWidgetItem(describe(code)[0])
                name.setToolTip(describe(code)[1] + "\n" + code)
                self.summary.setItem(row, 0, name)
                self.summary.setItem(row, col, QTableWidgetItem(str(trial.assessment.blocker_counts().get(code, 0))))
        self.summary.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.summary, 1)
        released64 = sum(bool(j.blockers16) and not j.blockers64 for j in report.journals)
        released16 = sum(bool(j.blockers64) and not j.blockers16 for j in report.journals)
        counts = QLabel(f"64行のみREADY: {released64}件 / 16行のみREADY: {released16}件 / "
                        f"両設定でBLOCK: {report.both_blocked}件\nBLOCK理由・分割関連の件数は重複を含みます。")
        counts.setWordWrap(True)
        layout.addWidget(counts)
        self.filter = QComboBox()
        self.filter.addItems(["全仕訳", "設定でREADYが変わる仕訳", "両設定でBLOCK"])
        self.filter.currentIndexChanged.connect(self._populate)
        layout.addWidget(self.filter)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["仕訳ID", "借方明細", "貸方明細", "16行", "64行", "条件付き比較"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 160)
        for col in (3, 4, 5):
            self.table.setColumnWidth(col, 260)
        layout.addWidget(self.table, 3)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._populate()

    def _populate(self):
        from accounting_converter.application.readiness_breakdown import describe

        mode = self.filter.currentIndex()
        rows = [j for j in self.report.journals if mode == 0
                or mode == 1 and bool(j.blockers16) != bool(j.blockers64)
                or mode == 2 and j.blockers16 and j.blockers64]
        self.table.setRowCount(len(rows))
        for row, journal in enumerate(rows):
            def result(codes):
                return "READY" if not codes else "BLOCK: " + " / ".join(describe(c)[0] for c in sorted(codes))
            values = [journal.journal_id, str(journal.debit_lines), str(journal.credit_lines),
                      result(journal.blockers16), result(journal.blockers64), journal.outcome]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                codes = journal.blockers16 if col == 3 else journal.blockers64
                item.setToolTip(value + ("\n" + "\n".join(
                    describe(code)[1] + " (" + code + ")" for code in sorted(codes)) if col in (3, 4) else ""))
                self.table.setItem(row, col, item)
        self.table.resizeRowsToContents()
