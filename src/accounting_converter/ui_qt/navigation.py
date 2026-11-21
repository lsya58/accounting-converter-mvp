"""Left navigation (Fluent NavigationView built from Qt Widgets).

One checkable button per page in an exclusive group: Tab reaches the current item, Up/Down move between items,
Ctrl+1..6 jump to a page from anywhere in the window. Each button's accessible name is its page name (plus the count
shown next to it). Switching pages only changes what is visible: it never reads or writes any setting.

Two widths (Phase 5B): expanded (the page names) and compact (a symbol and a short name per page, for narrow windows).
The window switches automatically by its width until the user chooses with the toggle at the top; the user's choice
then holds for the session (it is not saved). Changing the width never changes the current page, never emits
current_changed and never moves the focus to another page.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QButtonGroup, QFrame, QLabel, QPushButton, QSizePolicy, QVBoxLayout

EXPANDED_WIDTH = (176, 220)
COMPACT_WIDTH = 80
COMPACT_BELOW = 1200          # window width (logical px) below which the navigation is compact by default


class NavigationRail(QFrame):
    current_changed = Signal(str)
    compact_changed = Signal(bool)

    def __init__(self, items, parent=None, *, compact_items: dict | None = None, pending_mark: str = "●") -> None:
        super().__init__(parent)
        self.setObjectName("navRail")
        self.setAccessibleName("ナビゲーション")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(EXPANDED_WIDTH[0])
        self.setMaximumWidth(EXPANDED_WIDTH[1])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 16)
        layout.setSpacing(2)
        self.toggle = QPushButton()
        self.toggle.setObjectName("navToggle")
        self.toggle.setAutoDefault(False)
        self.toggle.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle.clicked.connect(lambda _checked=False: self.set_compact(not self.compact, user=True))
        layout.addWidget(self.toggle)
        self.brand = QLabel("会計データ変換")
        self.brand.setObjectName("navBrand")
        layout.addWidget(self.brand)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        self.labels: dict[str, str] = {}
        self.texts: dict[str, str] = {}          # what the expanded item shows (set_status may add counts)
        self.compact_items = dict(compact_items or {})
        self.pending_mark = pending_mark
        self.keys: list[str] = []
        for number, (key, label) in enumerate(items, start=1):
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setAutoDefault(False)
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(f"{label}（Ctrl+{number}）")
            button.setAccessibleName(label)
            button.setAccessibleDescription(f"{label}のページを表示します（Ctrl+{number}）")
            button.clicked.connect(lambda _checked=False, k=key: self.set_current(k))
            self.group.addButton(button)
            button.installEventFilter(self)
            layout.addWidget(button)
            self.buttons[key], self.labels[key], self.texts[key] = button, label, label
            self.keys.append(key)
            if number <= 9 and parent is not None:
                QShortcut(QKeySequence(f"Ctrl+{number}"), parent, activated=lambda k=key: self.set_current(k))
        layout.addStretch(1)
        self.current = ""
        self.compact = False
        self.user_choice: bool | None = None     # None: follows the window width
        self._apply()

    def set_current(self, key: str) -> None:
        if key not in self.buttons:
            raise KeyError(key)
        if any(button.hasFocus() for button in self.buttons.values()):
            self.buttons[key].setFocus()      # the focus ring never stays on a page that is not shown
        self.buttons[key].setChecked(True)
        if key != self.current:
            self.current = key
            self.current_changed.emit(key)

    def set_status(self, key: str, text: str, description: str = "") -> None:
        """Replace the item's text (e.g. 要確認（設定2件 / 判断22仕訳）). Words with units, never a bare or summed
        number; the description is read aloud and shown as the tooltip (in both widths)."""
        button = self.buttons[key]
        self.texts[key] = text
        button.setAccessibleName(text.replace("\n", " "))
        number = self.keys.index(key) + 1
        detail = f"{description}（Ctrl+{number}）" if description else f"{self.labels[key]}（Ctrl+{number}）"
        button.setToolTip(f"{self.labels[key]}: {detail}" if description else detail)
        button.setAccessibleDescription(detail)
        button.setText(self._text(key))

    # ------------------------------------------------------------------ width
    def set_compact(self, compact: bool, *, user: bool = False) -> None:
        """Show the compact (symbol + short name) or the expanded rail. `user`: the toggle was used (it then holds)."""
        if user:
            self.user_choice = compact
        if compact == self.compact:
            return
        self.compact = compact
        self._apply()
        self.compact_changed.emit(compact)

    def follow_width(self, window_width: int) -> None:
        """The window's width changed: compact below COMPACT_BELOW unless the user chose. The page never changes."""
        self.set_compact(self.user_choice if self.user_choice is not None else window_width < COMPACT_BELOW)

    def _text(self, key: str) -> str:
        if not self.compact or key not in self.compact_items:
            return self.texts[key]
        symbol, short = self.compact_items[key]
        pending = self.texts[key] != self.labels[key]        # set_status added counts: keep it visible
        return f"{symbol}\n{short}" + (f"\n{self.pending_mark}" if pending else "")

    def _apply(self) -> None:
        if self.compact:
            self.setMinimumWidth(COMPACT_WIDTH)
            self.setMaximumWidth(COMPACT_WIDTH)
        else:
            self.setMinimumWidth(EXPANDED_WIDTH[0])
            self.setMaximumWidth(EXPANDED_WIDTH[1])
        self.brand.setVisible(not self.compact)
        self.toggle.setText("»" if self.compact else "« 縮小")
        name = "ナビゲーションを展開する" if self.compact else "ナビゲーションを縮小する"
        self.toggle.setAccessibleName(name)
        self.toggle.setToolTip(name + "（ページ名だけの表示と、記号＋短い名前の表示を切り替えます）")
        for widget in (self, self.toggle, *self.buttons.values()):
            widget.setProperty("compact", self.compact)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        for key, button in self.buttons.items():
            button.setText(self._text(key))

    def eventFilter(self, watched, event) -> bool:
        """Up / Down on a navigation item moves to the previous / next page (the button would only move focus)."""
        if event.type() == QEvent.Type.KeyPress and watched in self.buttons.values():
            step = {Qt.Key.Key_Down: 1, Qt.Key.Key_Up: -1}.get(event.key())
            if step is not None:
                key = next(k for k, b in self.buttons.items() if b is watched)
                target = self.keys[(self.keys.index(key) + step) % len(self.keys)]
                self.buttons[target].setFocus()
                self.set_current(target)
                return True
        return super().eventFilter(watched, event)
