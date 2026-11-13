"""Small layout helpers for the table-centred review screens."""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# Logical pixels; Qt scales them for 125% / 150% displays.
ROW_HEIGHT = 34


def dense_table(table: QTableWidget) -> QTableWidget:
    """A compact, scrollable review table (style: QTableWidget#denseTable)."""
    table.setObjectName("denseTable")
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
    table.verticalHeader().setMinimumSectionSize(ROW_HEIGHT - 6)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setMinimumHeight(ROW_HEIGHT * 4)
    return table


def checkbox_cell(checkbox: QCheckBox) -> QWidget:
    """Centre a checkbox inside a table cell."""
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(6, 0, 6, 0)
    layout.addWidget(checkbox, 0, Qt.AlignmentFlag.AlignCenter)
    return holder


def count_item(value: int, suffix: str = "件") -> QTableWidgetItem:
    """Right-aligned number that sorts numerically."""
    cell = QTableWidgetItem()
    cell.setData(Qt.ItemDataRole.DisplayRole, f"{value:,}{suffix}")
    cell.setData(Qt.ItemDataRole.UserRole + 1, value)
    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return cell


def text_item(text: str, *, editable: bool = False) -> QTableWidgetItem:
    cell = QTableWidgetItem(text)
    cell.setToolTip(text)
    flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
    if editable:
        flags |= Qt.ItemFlag.ItemIsEditable
    cell.setFlags(flags)
    return cell


class CollapsibleSection(QWidget):
    """A one-line toggle that shows or hides longer notes and warnings."""

    def __init__(self, title: str, body: QWidget, *, expanded: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.body = body
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.toggle = QToolButton()
        self.toggle.setObjectName("disclosure")
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setText(title)
        self.toggle.toggled.connect(self.set_expanded)
        layout.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(body)
        self.set_expanded(expanded)

    def set_expanded(self, expanded: bool) -> None:
        if self.toggle.isChecked() != expanded:
            self.toggle.setChecked(expanded)
            return
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.body.setVisible(expanded)

    def is_expanded(self) -> bool:
        return self.toggle.isChecked()


SETTINGS_FILE_ENV = "ACCOUNTING_CONVERTER_SETTINGS_FILE"


def app_settings() -> QSettings:
    """The app's UI preferences (pane visibility, remembered toggles).

    Normally the Windows registry (QSettings native format). When ACCOUNTING_CONVERTER_SETTINGS_FILE names a file,
    an INI file there is used instead; the test suite sets it so that GUI tests never write the real user settings.
    """
    import os

    path = os.environ.get(SETTINGS_FILE_ENV)
    if path:
        return QSettings(path, QSettings.Format.IniFormat)
    return QSettings("AccountingConverter", "AccountingConverter")


def remembered_toggle(text: str, key: str, default: bool) -> QToolButton:
    """A checkable button whose state is remembered between sessions."""
    button = QToolButton()
    button.setObjectName("paneToggle")
    button.setCheckable(True)
    button.setText(text)
    value = app_settings().value(key, default)
    button.setChecked(value in (True, "true", "1", 1))
    # A fresh QSettings per change: keeping one alive in the closure can
    # outlive the application and crash on exit.
    button.toggled.connect(
        lambda checked: app_settings().setValue(key, bool(checked))
    )
    return button
