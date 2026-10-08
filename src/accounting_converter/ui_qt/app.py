from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
from PySide6.QtWidgets import QApplication

from accounting_converter.ui_qt.main_window import AccountingConverterMainWindow
from accounting_converter.ui_qt.theme import APP_STYLE_SHEET


def _preferred_font() -> QFont:
    available = set(QFontDatabase.families())
    family = next(
        (name for name in ("Yu Gothic UI", "Meiryo UI", "Segoe UI") if name in available),
        QApplication.font().family(),
    )
    return QFont(family, 10)


def main() -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("AccountingConverter")
    app.setOrganizationName("AccountingConverter")
    app.setFont(_preferred_font())
    app.setStyleSheet(APP_STYLE_SHEET)
    window = AccountingConverterMainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
