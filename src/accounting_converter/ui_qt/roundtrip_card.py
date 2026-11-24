"""「出力・照合」ページの JDL往復照合カード. Read-only.

Phase 1: 弥生インポート形式の会社B. Phase 2: Money Forward companies enabled by an explicit pilot entry (disabled
by default); for those the fiscal year is chosen on the card (never taken from the CSV) and the re-export is optional
(without it only the regeneration of the candidate is checked: 未照合).

The card runs the existing check (controller.jdl_roundtrip_review → tools.yayoi_roundtrip_check.run_check) on the
existing BackgroundTask: one run at a time, the company selector is locked while it runs, and a result is shown only
if its request key (company, source, setting fingerprint, both files' path / size / mtime) still matches the current
selection. Nothing here records an acceptance or an approval. The window calls release() when it closes.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from accounting_converter.application import jdl_roundtrip_review as rr
from accounting_converter.ui import roundtrip_view as rv
from accounting_converter.ui.output_conflicts import refusal_message

from . import components as ui
from .file_dialogs import choose_new_file

TITLE = "JDLへの取込結果の照合（読み取りのみ）"


def _stat(path: Path | None):
    if path is None:
        return None
    try:
        info = path.stat()
        return str(path), info.st_size, info.st_mtime_ns
    except OSError:
        return str(path), None, None


class RoundTripCard(QFrame):
    def __init__(self, controller, *, base_key: Callable[[], tuple | None],
                 selection: Callable[[], tuple[str | None, str, Path | None]],
                 lock_selection: Callable[[bool], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._base_key, self._selection, self._lock_selection = base_key, selection, lock_selection
        self.candidate: Path | None = None
        self.reexport: Path | None = None
        self.result: tuple | None = None          # (request key, RoundTripReview)
        self._route: tuple | None = None          # (company id, supported, reason)
        self._period: tuple | None = None         # (company id, fiscal year end MM-DD or None): Money Forward pilot only
        # No Qt parent: the window's destruction must not destroy a running thread (see BackgroundTask.release).
        self.task = ui.BackgroundTask()
        self.task.finished.connect(self._on_finished)
        self.task.failed.connect(self._on_failed)
        self.task.busy_changed.connect(lambda _busy: self.refresh())

        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 22)
        layout.setSpacing(12)
        title = QLabel(TITLE)
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        intro = QLabel("JDLに取り込んだ後、同じ期間をJDLから再出力したCSVと、このアプリの出力CSV・元データを照合します。"
                       "既存の照合処理（コマンドラインと同じ判定）を使います。許容・承認はこの画面ではできません。")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        layout.addWidget(intro)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        self.company_label = QLabel()
        self.source_label = QLabel()
        self.candidate_label = QLabel("まだ選択されていません")
        self.reexport_label = QLabel("まだ選択されていません")
        for label in (self.company_label, self.source_label, self.candidate_label, self.reexport_label):
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.candidate_button = ui.make_button("出力CSVを選ぶ…", description="このアプリが作ったJDL向け出力CSVを選びます（読むだけ）")
        self.reexport_button = ui.make_button("再出力CSVを選ぶ…", description="JDLから同じ期間を再出力したCSVを選びます（読むだけ）")
        self.candidate_button.clicked.connect(self._choose_candidate)
        self.reexport_button.clicked.connect(self._choose_reexport)
        # Money Forward pilot: the fiscal year is chosen here, never taken from the candidate CSV. No default.
        self.period_combo = QComboBox()
        self.period_combo.setAccessibleName("対象の決算期")
        self.period_combo.currentIndexChanged.connect(lambda _index: self.refresh())
        self.period_caption = QLabel("対象の決算期")
        for row, (name, widget, button) in enumerate((
                ("対象会社", self.company_label, None), ("元データ", self.source_label, None),
                (self.period_caption, self.period_combo, None),
                ("JDL向け出力CSV", self.candidate_label, self.candidate_button),
                ("JDL再出力CSV", self.reexport_label, self.reexport_button))):
            caption = name if isinstance(name, QLabel) else QLabel(name)
            caption.setObjectName("muted")
            grid.addWidget(caption, row, 0)
            grid.addWidget(widget, row, 1)
            if button is not None:
                grid.addWidget(button, row, 2)
        self.period_caption.setVisible(False)
        self.period_combo.setVisible(False)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        self.guidance = QLabel("・" + "\n・".join(rv.GUIDANCE))
        self.guidance.setWordWrap(True)
        self.guidance.setObjectName("muted")
        layout.addWidget(self.guidance)

        actions = QHBoxLayout()
        self.scope_label = QLabel()
        self.scope_label.setWordWrap(True)
        self.run_button = ui.make_button("照合する", description="既存の照合処理を実行します（ファイルは変更しません）")
        self.run_button.clicked.connect(self.run)
        actions.addWidget(self.scope_label, 1)
        actions.addWidget(self.run_button)
        layout.addLayout(actions)

        self.message = ui.MessageBar()
        layout.addWidget(self.message)
        result_row = QHBoxLayout()
        self.badge = ui.StatusBadge("NOT_STARTED", "未照合")
        result_row.addWidget(self.badge)
        result_row.addStretch(1)
        self.save_button = ui.make_button("要約を保存…", description="判定と件数だけのJSONを保存します（摘要などの顧客の値は含みません。上書きしません）")
        self.save_button.clicked.connect(self._save)
        result_row.addWidget(self.save_button)
        layout.addLayout(result_row)
        self.reasons = QLabel()
        self.reasons.setWordWrap(True)
        layout.addWidget(self.reasons)
        self.counts = ui.JournalTable(("項目", "件数・結果"), name="照合の件数", numeric=(), stretch=(0,))
        layout.addWidget(self.counts)
        self.failures_heading = QLabel()
        self.failures_heading.setWordWrap(True)
        layout.addWidget(self.failures_heading)
        self.failures = ui.JournalTable(("行", "差分の種類", "列"), name="最初の20件の差分詳細", stretch=(1, 2))
        layout.addWidget(self.failures)
        self.position_note = QLabel(rv.POSITION_NOTE)
        self.position_note.setWordWrap(True)
        self.position_note.setObjectName("muted")
        layout.addWidget(self.position_note)
        self.refresh()

    # ------------------------------------------------------------------ selection and key
    def selected_period_end(self) -> date | None:
        if not self._period_fy():
            return None
        chosen = self.period_combo.currentData()
        return date.fromisoformat(chosen) if isinstance(chosen, str) and chosen else None

    def request_key(self):
        base = self._base_key()
        moneyforward = self._period_fy() is not None
        if base is None or self.candidate is None or (self.reexport is None and not moneyforward):
            return None
        period = self.selected_period_end() if moneyforward else None
        if moneyforward and period is None:
            return None
        return ("roundtrip", base, _stat(self.candidate), _stat(self.reexport), period)

    def _choose(self, caption: str) -> Path | None:
        chosen, _ = QFileDialog.getOpenFileName(self, caption, "", "CSV (*.csv);;すべてのファイル (*)")
        return Path(chosen) if chosen else None

    def _choose_candidate(self) -> None:
        path = self._choose("JDL向け出力CSVを選ぶ（読むだけ）")
        if path is not None:
            self.candidate = path
            self.refresh()

    def _choose_reexport(self) -> None:
        path = self._choose("JDLから再出力したCSVを選ぶ（読むだけ）")
        if path is not None:
            self.reexport = path
            self.refresh()

    def _route_for(self, company_id):
        if self._route is None or self._route[0] != company_id:
            supported, reason = self.controller.jdl_roundtrip_route(company_id)
            self._route = (company_id, supported, reason)
        return self._route[1], self._route[2]

    def _period_fy(self) -> str | None:
        """The Money Forward pilot's fiscal year end (MM-DD) for the selected company, else None."""
        company_id = self._selection()[0]
        if not company_id:
            return None
        if self._period is None or self._period[0] != company_id:
            fiscal_year_end = self.controller.jdl_roundtrip_period(company_id)
            self._period = (company_id, fiscal_year_end)
            self._fill_periods(fiscal_year_end)
        return self._period[1]

    def _fill_periods(self, fiscal_year_end: str | None) -> None:
        self.period_combo.blockSignals(True)
        self.period_combo.clear()
        if fiscal_year_end:
            month, day = (int(part) for part in fiscal_year_end.split("-"))
            self.period_combo.addItem("決算期を選んでください", None)
            this_year = date.today().year
            for year in range(this_year + 1, this_year - 7, -1):
                end = date(year, month, day)
                self.period_combo.addItem(rv.period_label(end), end.isoformat())  # stored as text, parsed back
        self.period_combo.setCurrentIndex(0)
        self.period_combo.blockSignals(False)

    # ------------------------------------------------------------------ run
    def run(self) -> bool:
        company_id, _text, source = self._selection()
        key = self.request_key()
        supported, _reason = self._route_for(company_id)
        if self.task.busy or key is None or source is None or not supported:
            return False
        controller, candidate, reexport = self.controller, self.candidate, self.reexport
        period_end = key[-1]
        self.result = None
        if period_end is None:   # 弥生インポート形式 (Phase 1): unchanged call
            work = lambda: controller.jdl_roundtrip_review(company_id, source, candidate, reexport)  # noqa: E731
        else:                    # Money Forward pilot (Phase 2): the fiscal year chosen on screen
            work = lambda: controller.jdl_roundtrip_review(  # noqa: E731
                company_id, source, candidate, reexport, period_end=period_end)
        started = self.task.start(key, work)
        if started:
            self._lock_selection(True)
            self.message.show_message("info", "照合しています…（ファイルを読むだけです。会社と元データは照合が終わるまで変更できません）")
        return started

    def _on_finished(self, key, review) -> None:
        self._lock_selection(False)
        if key != self.request_key():
            self.message.show_message("info", "照合中に対象が変わったため、この結果は表示しません。もう一度照合してください。")
            self.refresh()
            return
        self.result = (key, review)
        self.refresh()

    def _on_failed(self, key, error) -> None:
        # The service already turns read failures into READ_ERROR; anything else is shown as one, never as a PASS.
        # The exception message is not logged (it may quote file contents): only its type is shown.
        self._lock_selection(False)
        if key != self.request_key():
            self.refresh()
            return
        company_id = key[1][1] if isinstance(key[1], tuple) and len(key[1]) > 1 else ""
        self.result = (key, rr.RoundTripReview(rr.READ_ERROR, str(company_id or ""), reasons=("CHECK_RAISED",),
                                                error_type=type(error).__name__))
        self.refresh()

    def release(self) -> None:
        """The window is closing: drop any running result, never block the GUI (see BackgroundTask.release)."""
        self._lock_selection(False)
        self.task.release()

    # ------------------------------------------------------------------ rendering
    def current_review(self):
        if self.result is not None and self.result[0] == self.request_key():
            return self.result[1]
        return None

    def refresh(self) -> None:
        company_id, company_text, source = self._selection()
        self.company_label.setText(company_text or "会社が選択されていません")
        self.source_label.setText(source.name if source else "元データが選択されていません（データ取込で選んでください）")
        self.candidate_label.setText(self.candidate.name if self.candidate else "まだ選択されていません")
        fiscal_year_end = self._period_fy() if company_id else None
        moneyforward = fiscal_year_end is not None
        self.period_caption.setVisible(moneyforward)
        self.period_combo.setVisible(moneyforward)
        self.reexport_label.setText(self.reexport.name if self.reexport else (
            "未選択（出力CSVの再現だけ確認します）" if moneyforward else "まだ選択されていません"))
        self.guidance.setText("・" + "\n・".join(rv.guidance(moneyforward)))
        for label, path in ((self.candidate_label, self.candidate), (self.reexport_label, self.reexport)):
            label.setToolTip(str(path) if path else "")
        supported, reason = self._route_for(company_id) if company_id else (False, "COMPANY_SETTING_NOT_AVAILABLE")
        busy = self.task.busy
        if not supported:
            self.scope_label.setText("未対応: " + rv.REASON_TEXT.get(reason or "", "この会社では使えません。"))
        elif moneyforward and (source is None or self.candidate is None or self.selected_period_end() is None):
            self.scope_label.setText("元データ・対象の決算期・出力CSVがそろうと照合できます（MFパイロット）。")
        elif not moneyforward and (source is None or self.candidate is None or self.reexport is None):
            self.scope_label.setText("元データ・出力CSV・再出力CSVの3つがそろうと照合できます。")
        elif moneyforward:
            self.scope_label.setText("照合できます（Money Forwardパイロット。パイロットの有効化は税理士の承認ではありません）。")
        else:
            self.scope_label.setText("照合できます（弥生インポート形式）。")
        ready = supported and source is not None and self.request_key() is not None
        self.run_button.setEnabled(ready and not busy)
        self.candidate_button.setEnabled(not busy)
        self.reexport_button.setEnabled(not busy)
        self.period_combo.setEnabled(not busy)
        review = self.current_review()
        self.save_button.setEnabled(review is not None and not busy)
        if busy:
            self.badge.set_status("EVIDENCE", "照合中")
            return
        if review is None:
            if self.result is not None:
                self.message.show_message("info", "対象が変わったため、前の照合結果は表示していません。")
            elif self.message.level != "info":
                self.message.clear_message()
            self.badge.set_status("NOT_STARTED", "未照合")
            self.reasons.setText("")
            self.counts.set_rows(())
            self.failures_heading.setText("")
            self.failures.set_rows(())
            return
        level, badge, words, text = rv.headline(review)
        self.message.show_message(level, text)
        self.badge.set_status(badge, words)
        self.reasons.setText("\n".join(rv.reason_lines(review)))
        self.counts.set_rows(rv.count_rows(review))
        self.failures_heading.setText(rv.failures_heading(review) if review.reexport else "")
        self.failures.set_rows(rv.failure_rows(review))

    def _save(self) -> None:
        review = self.current_review()
        if review is None:
            return
        path, existing = choose_new_file(self, "照合結果の要約を保存", "JSON (*.json)", suffix=".json")
        if path is None:
            return
        if existing:
            self.message.show_message("warning", refusal_message(existing))
            return
        try:
            rr.save_summary(review, path)
        except FileExistsError:
            self.message.show_message("warning", refusal_message((path.name,)))
            return
        except OSError as exc:
            self.message.show_message("error", f"保存できませんでした（{type(exc).__name__}）。何も保存していません。")
            return
        self.message.show_message("success", f"要約を保存しました: {path.name}（判定と件数だけ。顧客の値は含みません）")
