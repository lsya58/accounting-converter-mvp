"""Pages of the main window (left navigation + right content, docs/development/ui_ux_renewal_plan.md 2)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

READING_WIDTH = 960   # long text and cards; tables may use the full width


def scroll_page(title: str, subtitle: str = "", *, name: str) -> tuple[QScrollArea, QVBoxLayout]:
    """A page: title + subtitle on top, content that stretches with the window and scrolls vertically only."""
    scroll = QScrollArea()
    scroll.setObjectName("pageScroll")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setAccessibleName(title)
    page = QWidget()
    page.setObjectName("page")
    outer = QVBoxLayout(page)
    outer.setContentsMargins(24, 20, 24, 24)
    outer.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
    content = QWidget()
    content.setObjectName(name)
    content.setMaximumWidth(READING_WIDTH)
    content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    layout = QVBoxLayout(content)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(16)
    heading = QLabel(title)
    heading.setObjectName("pageTitle")
    heading.setAccessibleName(title)
    layout.addWidget(heading)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        layout.addWidget(sub)
    outer.addWidget(content)
    scroll.setWidget(page)
    return scroll, layout
