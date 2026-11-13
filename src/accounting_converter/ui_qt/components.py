"""Shared UI components (design system, docs/development/ui_ux_renewal_plan.md 3.x).

Every component sets an accessible name (and description where useful), keeps a visible focus, never relies on
colour alone (each status carries a symbol and words) and is laid out to stretch (no fixed pixel widths except
minimums). Nothing here touches accounting logic or writes anything.

BackgroundTask runs ONE read-only job at a time off the UI thread. The job function must not touch widgets or write
settings; its result is delivered back on the UI thread together with the request key it was started with, and the
caller drops a result whose key no longer matches the screen (company, source, settings, selection).
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton, QSizePolicy, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .review_layout import CollapsibleSection

# ---------------------------------------------------------------- status (symbol + words + tone)
@dataclass(frozen=True)
class Status:
    symbol: str
    text: str
    tone: str   # ready / block / pending / evidence / error / neutral


STATUSES = {
    "READY": Status("✓", "変換できる", "ready"),
    "BLOCK": Status("‖", "変換できない", "block"),
    "PENDING": Status("?", "税理士の判断待ち", "pending"),
    "UNDECIDED": Status("?", "未判断", "pending"),
    "EVIDENCE": Status("⧗", "JDLでの確認待ち", "evidence"),
    "NOT_STARTED": Status("○", "未対応", "neutral"),
    "MANUAL_PLANNED": Status("✎", "手入力予定", "pending"),
    "MANUAL_ENTERED": Status("◐", "入力済み（照合待ち）", "block"),
    "RECONCILED": Status("✔", "照合済み", "ready"),
    "NOT_REQUIRED": Status("–", "対応不要", "neutral"),
    "ERROR": Status("✕", "使えません", "error"),
}

# migration tracker status code -> STATUSES key (application/migration_tracker.STATES)
TRACKER_STATUS = {
    None: "NOT_STARTED", "NOT_STARTED": "NOT_STARTED", "PLANNING": "PENDING", "AWAITING_TAX_ACCOUNTANT": "PENDING",
    "AWAITING_TECHNICAL": "EVIDENCE", "MANUAL_ENTRY_PLANNED": "MANUAL_PLANNED",
    "MANUAL_ENTERED_UNRECONCILED": "MANUAL_ENTERED", "RECONCILED": "RECONCILED", "NOT_REQUIRED": "NOT_REQUIRED",
}


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class StatusBadge(QLabel):
    """A status shown as symbol + words (+ tone colour). The words are also its accessible name."""

    def __init__(self, key: str = "NOT_STARTED", text: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("statusBadge")
        self.set_status(key, text)

    def set_status(self, key: str, text: str | None = None) -> None:
        status = STATUSES.get(key, STATUSES["NOT_STARTED"])
        words = text or status.text
        self.setText(f"{status.symbol} {words}")
        self.setProperty("tone", status.tone)
        self.setAccessibleName(words)
        self.key = key
        _repolish(self)


def badge_text(key: str, text: str | None = None) -> str:
    status = STATUSES.get(key, STATUSES["NOT_STARTED"])
    return f"{status.symbol} {text or status.text}"


# ---------------------------------------------------------------- headings, buttons, banners, messages
class SectionHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("sectionTitle")
        self.title.setAccessibleName(title)
        layout.addWidget(self.title)
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("muted")
        self.subtitle.setWordWrap(True)
        self.subtitle.setVisible(bool(subtitle))
        layout.addWidget(self.subtitle)


BUTTON_KINDS = {"primary": "primaryButton", "secondary": "", "danger": "dangerButton", "subtle": "subtleButton"}


def make_button(text: str, kind: str = "secondary", *, description: str = "", shortcut: str = "") -> QPushButton:
    """Primary (one per screen) / secondary / danger (irreversible only) / subtle. Shortcut shown in the tooltip."""
    if kind not in BUTTON_KINDS:
        raise ValueError(f"unknown button kind: {kind}")
    button = QPushButton(text)
    if BUTTON_KINDS[kind]:
        button.setObjectName(BUTTON_KINDS[kind])
    button.setAccessibleName(text.rstrip("…"))
    if description:
        button.setAccessibleDescription(description)
    if shortcut:
        button.setShortcut(shortcut)
        button.setToolTip(f"{description + '　' if description else ''}（{shortcut}）")
    elif description:
        button.setToolTip(description)
    button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    button.setAutoDefault(False)
    return button


MODES = {
    "view": "◇ 閲覧のみ（保存しません）",
    "trial": "◆ 試算（承認・保存していません）",
    "unapproved": "? 未承認（承認は台帳CLIの正式手順で記録します）",
}


class ModeBanner(QLabel):
    """Says what kind of operation the area is: view only / trial / unapproved (docs 3.11)."""

    def __init__(self, mode: str = "view", extra: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("modeBanner")
        self.setWordWrap(True)
        self.set_mode(mode, extra)

    def set_mode(self, mode: str, extra: str = "") -> None:
        text = MODES[mode] + (f"　{extra}" if extra else "")
        self.setText(text)
        self.setProperty("mode", mode)
        self.setAccessibleName(text)
        self.mode = mode
        _repolish(self)


LEVEL_PREFIX = {"info": "ℹ", "success": "✓", "warning": "!", "error": "✕"}


class MessageBar(QLabel):
    """Info / success / warning / error line. Hidden when empty. Errors say what happened and what did not change."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("messageBar")
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.level = ""
        self.setVisible(False)

    def show_message(self, level: str, text: str, *, html: bool = False) -> None:
        if level not in LEVEL_PREFIX:
            raise ValueError(level)
        body = text if html else escape(text).replace("\n", "<br>")
        self.setText(f"<b>{LEVEL_PREFIX[level]}</b> {body}")
        self.setProperty("level", level)
        self.setAccessibleName({"info": "お知らせ", "success": "完了", "warning": "注意", "error": "エラー"}[level])
        self.setAccessibleDescription(text if not html else "")
        self.level = level
        self.setVisible(True)
        _repolish(self)

    def clear_message(self) -> None:
        self.level = ""
        self.setText("")
        self.setVisible(False)


# ---------------------------------------------------------------- metric card, detail card, collapsible text
class MetricCard(QFrame):
    def __init__(self, label: str, value: str = "—", hint: str = "", tone: str = "neutral", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("metricCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)
        self.label = QLabel(label)
        self.label.setObjectName("metricCardLabel")
        self.value = QLabel(value)
        self.value.setObjectName("metricCardValue")
        self.hint = QLabel(hint)
        self.hint.setObjectName("metricCardHint")
        self.hint.setWordWrap(True)
        for widget in (self.label, self.value, self.hint):
            layout.addWidget(widget)
        self._name = label
        self.set_value(value, hint, tone)

    def set_value(self, value: str, hint: str = "", tone: str | None = None) -> None:
        self.value.setText(value)
        self.hint.setText(hint)
        self.hint.setVisible(bool(hint))
        if tone is not None:
            self.setProperty("tone", tone)
            _repolish(self)
        self.setAccessibleName(f"{self._name} {value}")


class DetailCard(QFrame):
    """A titled block of plain text lines (one decision fact per card)."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("detailCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        self.title = QLabel(title)
        self.title.setObjectName("detailCardTitle")
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.title)
        layout.addWidget(self.body)
        self.setAccessibleName(title)
        self._title = title

    def set_lines(self, lines, *, bullet: bool = True) -> None:
        lines = [line for line in lines if line]
        self.body.setText("<br>".join(("・" if bullet else "") + escape(line) for line in lines) or "—")
        self.setAccessibleDescription(" ".join(lines))
        self.setVisible(True)

    def plain_text(self) -> str:
        return self._title + "\n" + self.accessibleDescription()


def collapsible_text(title: str, *, expanded: bool = False) -> tuple[CollapsibleSection, QLabel]:
    """Reuses review_layout.CollapsibleSection: a disclosure with a rich-text body (long or technical text)."""
    body = QLabel()
    body.setWordWrap(True)
    body.setTextFormat(Qt.TextFormat.RichText)
    body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    body.setObjectName("detailText")
    section = CollapsibleSection(title, body, expanded=expanded)
    section.setAccessibleName(title)
    return section, body


# ---------------------------------------------------------------- journal table (sortable by value)
class SortItem(QTableWidgetItem):
    """A cell that sorts by its key (numbers / dates by value, not by the displayed text)."""

    def __init__(self, text: str, key=None) -> None:
        super().__init__(text)
        self._key = key if key is not None else text
        self.setFlags(self.flags() & ~Qt.ItemFlag.ItemIsEditable)

    def __lt__(self, other) -> bool:
        if isinstance(other, SortItem):
            mine, theirs = self._key, other._key
            if type(mine) is type(theirs):
                return mine < theirs
            return str(mine) < str(theirs)
        return super().__lt__(other)


class JournalTable(QTableWidget):
    """Read-only, sortable, selectable by row, stretching last column; numbers right-aligned."""

    def __init__(self, columns, *, name: str, numeric=(), stretch=(), parent=None) -> None:
        super().__init__(0, len(columns), parent)
        self.setObjectName("journalTable")
        self.setHorizontalHeaderLabels(list(columns))
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.setWordWrap(False)
        self.setAccessibleName(name)
        self.numeric = set(numeric)
        # Long text columns share the width (elided, full text in the tooltip); the others fit their content. This
        # keeps the table inside the window instead of scrolling sideways.
        self.stretch = set(stretch)
        header = self.horizontalHeader()
        for column in range(len(columns)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch if column in self.stretch
                                        else QHeaderView.ResizeMode.ResizeToContents)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setMinimumSectionSize(72)
        if self.stretch:
            header.setStretchLastSection(False)
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setSortingEnabled(True)

    def set_rows(self, rows) -> None:
        """rows: sequences of cells, each a str or (text, sort_key) or (text, sort_key, tooltip)."""
        self.setSortingEnabled(False)       # filling a sorting table reorders rows half-way
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                text, key, tip = (cell, None, "") if isinstance(cell, str) else (tuple(cell) + ("", ""))[:3]
                item = SortItem(text, key)
                item.setToolTip("\n".join(x for x in (text, tip) if x))   # the full text, even when elided
                if c in self.numeric:
                    item.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
                self.setItem(r, c, item)
        self.setSortingEnabled(True)


def fit_to_screen(dialog, width: int, height: int) -> None:
    """Preferred size, never larger than the available screen (existing pattern, now shared)."""
    dialog.resize(width, height)
    screen = dialog.screen()
    if screen is not None:
        size = screen.availableGeometry().size()
        dialog.resize(min(width, size.width()), min(height, size.height()))


# ---------------------------------------------------------------- background task (read-only jobs only)
class _Worker(QObject):
    finished = Signal(object, object)       # key, result
    failed = Signal(object, object)         # key, exception

    def __init__(self, key, job) -> None:
        super().__init__()
        self.key, self.job = key, job

    @Slot()
    def run(self) -> None:
        try:
            result = self.job()
        except Exception as error:  # noqa: BLE001 - reported on the UI thread, never swallowed
            self.failed.emit(self.key, error)
            return
        self.finished.emit(self.key, result)


class BackgroundTask(QObject):
    """One read-only job at a time, off the UI thread. Results come back on the UI thread with their key.

    start() refuses (returns False) while a job runs. invalidate() makes the running job's result stale: it is
    dropped when it arrives. The job must not touch widgets and must not write settings."""

    finished = Signal(object, object)
    failed = Signal(object, object)
    busy_changed = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _Worker | None = None
        self._current = None
        self.dropped = 0

    @property
    def busy(self) -> bool:
        return self._thread is not None

    def start(self, key, job) -> bool:
        if self.busy:
            return False
        self._current = key
        thread, worker = QThread(), _Worker(key, job)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._done, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._error, Qt.ConnectionType.QueuedConnection)
        self._thread, self._worker = thread, worker
        self.busy_changed.emit(True)
        thread.start()
        return True

    def invalidate(self) -> None:
        self._current = None

    def _stop(self) -> None:
        thread = self._thread
        self._thread = self._worker = None
        if thread is not None:
            thread.quit()
            thread.wait()
            thread.deleteLater()
        self.busy_changed.emit(False)

    @Slot(object, object)
    def _done(self, key, result) -> None:
        current = self._current
        self._stop()
        if key == current and key is not None:
            self.finished.emit(key, result)
        else:
            self.dropped += 1

    @Slot(object, object)
    def _error(self, key, error) -> None:
        current = self._current
        self._stop()
        if key == current and key is not None:
            self.failed.emit(key, error)
        else:
            self.dropped += 1

    def shutdown(self) -> None:
        """On close: the running job's result is ignored and the thread is joined (never left running)."""
        self.invalidate()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread.deleteLater()
            self._thread = self._worker = None
