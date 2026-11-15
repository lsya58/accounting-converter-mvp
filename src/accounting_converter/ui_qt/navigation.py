"""Left navigation (Fluent NavigationView built from Qt Widgets).

One checkable button per page in an exclusive group: Tab reaches the current item, Up/Down move between items,
Ctrl+1..6 jump to a page from anywhere in the window. Each button's accessible name is its page name (plus the count
shown next to it). Switching pages only changes what is visible: it never reads or writes any setting.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QButtonGroup, QFrame, QLabel, QPushButton, QSizePolicy, QVBoxLayout


class NavigationRail(QFrame):
    current_changed = Signal(str)

    def __init__(self, items, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("navRail")
        self.setAccessibleName("ナビゲーション")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(176)
        self.setMaximumWidth(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 16, 8, 16)
        layout.setSpacing(2)
        brand = QLabel("会計データ変換")
        brand.setObjectName("navBrand")
        layout.addWidget(brand)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        self.labels: dict[str, str] = {}
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
            self.buttons[key], self.labels[key] = button, label
            self.keys.append(key)
            if number <= 9 and parent is not None:
                QShortcut(QKeySequence(f"Ctrl+{number}"), parent, activated=lambda k=key: self.set_current(k))
        layout.addStretch(1)
        self.current = ""

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
        number; the description is read aloud and shown as the tooltip."""
        button = self.buttons[key]
        button.setText(text)
        button.setAccessibleName(text)
        number = self.keys.index(key) + 1
        detail = f"{description}（Ctrl+{number}）" if description else f"{self.labels[key]}（Ctrl+{number}）"
        button.setToolTip(detail)
        button.setAccessibleDescription(detail)

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
