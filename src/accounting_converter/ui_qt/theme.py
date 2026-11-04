from __future__ import annotations

from accounting_converter.ui.view_models import UserFacingStatus


# Calm, professional palette: one accent, soft neutrals, clear status colors.
# Readability first: body text contrast >= 7:1 on surface, status text >= 4.5:1.
COLORS = {
    "page": "#F3F5F9",
    "surface": "#FFFFFF",
    "border": "#E2E7EF",
    "text": "#172033",
    "muted": "#5B6577",
    "accent": "#2457D6",
    "accent_hover": "#1D49B8",
    "accent_pressed": "#183C99",
    "accent_soft": "#EAF0FD",
    "ready": "#16703A",
    "ready_soft": "#E5F5EA",
    "confirm": "#8A5300",
    "confirm_soft": "#FFF4DC",
    "blocked": "#B42323",
    "blocked_soft": "#FDECEC",
    "evidence": "#5133A6",
    "evidence_soft": "#F0ECFB",
    "neutral": "#4B5568",
    "neutral_soft": "#EEF1F6",
    "disabled_text": "#6B7484",
    "disabled_surface": "#EDF0F4",
    "focus": "#2457D6",
    "input_border": "#C9D1DD",
    "header": "#F6F8FB",
}


# Blocker owners as shown to the user: (label, foreground, background).
OWNER_VISUALS = {
    "READY": ("正式変換できる", COLORS["ready"], COLORS["ready_soft"]),
    "HUMAN": ("人の確認が必要", COLORS["confirm"], COLORS["confirm_soft"]),
    "SYSTEM_EVIDENCE": ("JDL実機での確認不足", COLORS["evidence"], COLORS["evidence_soft"]),
    "SYSTEM_IMPLEMENTATION": ("システム未対応", COLORS["blocked"], COLORS["blocked_soft"]),
}


def pill_style(foreground: str, background: str) -> str:
    return f"color: {foreground}; background: {background};"


def status_visual(status: UserFacingStatus) -> tuple[str, str, str]:
    return {
        UserFacingStatus.NEEDS_INPUT: ("未準備", COLORS["neutral"], COLORS["neutral_soft"]),
        UserFacingStatus.READY: ("準備完了", COLORS["ready"], COLORS["ready_soft"]),
        UserFacingStatus.CONFIRM: ("要確認", COLORS["confirm"], COLORS["confirm_soft"]),
        UserFacingStatus.BLOCKED: ("停止", COLORS["blocked"], COLORS["blocked_soft"]),
        UserFacingStatus.SUCCESS: ("完了", COLORS["ready"], COLORS["ready_soft"]),
    }[status]


def _chevron(color: str, name: str) -> str:
    """A small chevron for combo boxes. Qt style sheets need an image file."""
    from pathlib import Path
    import tempfile

    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
           f'<path d="M2.5 4.5 L6 8 L9.5 4.5" fill="none" stroke="{color}" stroke-width="1.6" '
           f'stroke-linecap="round" stroke-linejoin="round"/></svg>')
    path = Path(tempfile.gettempdir()) / f"accounting_converter_{name}.svg"
    try:
        if not path.exists() or path.read_text(encoding="utf-8") != svg:
            path.write_text(svg, encoding="utf-8")
    except OSError:
        return ""
    return path.as_posix()


_ARROW = _chevron(COLORS["muted"], "chevron")
_ARROW_DISABLED = _chevron(COLORS["disabled_text"], "chevron_disabled")

APP_STYLE_SHEET = f"""
QMainWindow, QDialog, QMessageBox, QScrollArea, QWidget#page {{
    background: {COLORS['page']};
    color: {COLORS['text']};
}}
QWidget {{ color: {COLORS['text']}; font-size: 14px; }}
QToolTip {{
    color: {COLORS['surface']};
    background: {COLORS['text']};
    border: 0;
    border-radius: 6px;
    padding: 6px 8px;
}}
QFrame#card {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 14px;
}}
QLabel#title {{ font-size: 26px; font-weight: 700; letter-spacing: 0.2px; }}
QLabel#subtitle, QLabel#muted {{ color: {COLORS['muted']}; }}
QLabel:disabled {{ color: {COLORS['disabled_text']}; }}
QLabel#sectionTitle {{ font-size: 16px; font-weight: 700; }}
QLabel#statusTitle {{ font-size: 20px; font-weight: 700; }}
QLabel#stepBadge {{
    color: {COLORS['accent']};
    background: {COLORS['accent_soft']};
    border-radius: 13px;
    min-width: 26px;
    max-width: 26px;
    min-height: 26px;
    max-height: 26px;
    font-weight: 700;
}}
QPushButton {{
    min-height: 38px;
    padding: 0 18px;
    color: {COLORS['text']};
    border: 1px solid {COLORS['input_border']};
    border-radius: 9px;
    background: {COLORS['surface']};
    font-weight: 600;
}}
QPushButton:hover {{ background: {COLORS['neutral_soft']}; border-color: #AEB8C7; }}
QPushButton:pressed {{ background: #E3E8F0; }}
QPushButton:focus {{ border: 2px solid {COLORS['focus']}; }}
QPushButton:disabled {{
    color: {COLORS['disabled_text']};
    background: {COLORS['disabled_surface']};
    border-color: {COLORS['border']};
}}
QPushButton#primaryButton {{
    min-height: 50px;
    min-width: 210px;
    color: white;
    background: {COLORS['accent']};
    border: 0;
    border-radius: 11px;
    font-size: 16px;
    font-weight: 700;
}}
QPushButton#primaryButton:hover {{ background: {COLORS['accent_hover']}; }}
QPushButton#primaryButton:pressed {{ background: {COLORS['accent_pressed']}; }}
QPushButton#primaryButton:focus {{ border: 3px solid #9DB7F2; }}
QPushButton#primaryButton:disabled {{ color: #8B93A1; background: #DCE1E8; }}
QFrame#dropZone {{
    background: #FAFBFD;
    border: 2px dashed #B6C1D1;
    border-radius: 14px;
}}
QFrame#dropZone[dragActive="true"] {{
    background: {COLORS['accent_soft']};
    border-color: {COLORS['accent']};
}}
QLineEdit, QComboBox, QListWidget, QTableWidget {{
    min-height: 38px;
    padding: 0 12px;
    color: {COLORS['text']};
    background: {COLORS['surface']};
    border: 1px solid {COLORS['input_border']};
    border-radius: 9px;
    selection-background-color: {COLORS['accent_soft']};
    selection-color: {COLORS['text']};
}}
QLineEdit:hover, QComboBox:hover {{ border-color: #AEB8C7; }}
QLineEdit:focus, QComboBox:focus, QListWidget:focus, QTableWidget:focus {{
    border: 2px solid {COLORS['focus']};
}}
QLineEdit:disabled, QComboBox:disabled, QListWidget:disabled {{
    color: {COLORS['disabled_text']};
    background: {COLORS['disabled_surface']};
    border-color: {COLORS['border']};
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 30px;
    border: 0;
}}
QComboBox::down-arrow {{
    image: url("{_ARROW}");
    width: 12px;
    height: 12px;
}}
QComboBox::down-arrow:disabled {{ image: url("{_ARROW_DISABLED}"); }}
QComboBox QAbstractItemView {{
    color: {COLORS['text']};
    background: {COLORS['surface']};
    border: 1px solid {COLORS['input_border']};
    border-radius: 8px;
    selection-background-color: {COLORS['accent_soft']};
    selection-color: {COLORS['text']};
    outline: 0;
    padding: 6px;
}}
QCheckBox {{
    min-height: 32px;
    spacing: 10px;
}}
QCheckBox::indicator {{
    width: 20px;
    height: 20px;
}}
QTableWidget {{
    color: {COLORS['text']};
    background: {COLORS['surface']};
    alternate-background-color: #F9FAFC;
    gridline-color: {COLORS['border']};
    selection-background-color: {COLORS['accent_soft']};
    selection-color: {COLORS['text']};
    border-radius: 12px;
    padding: 0;
}}
QTableWidget::item {{ padding: 8px 10px; border-bottom: 1px solid {COLORS['border']}; }}
QAbstractScrollArea::corner {{
    background: {COLORS['page']};
}}
QHeaderView::section {{
    color: {COLORS['muted']};
    background: {COLORS['header']};
    border: 0;
    border-bottom: 1px solid {COLORS['border']};
    padding: 10px 12px;
    font-weight: 700;
}}
QTabWidget::pane {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 12px;
    top: -1px;
}}
QTabBar {{ background: {COLORS['surface']}; }}
QTabWidget::tab-bar {{ left: 4px; }}
QTabBar::tab {{
    color: {COLORS['muted']};
    background: {COLORS['surface']};
    border: 0;
    border-bottom: 3px solid transparent;
    padding: 10px 16px;
    margin-right: 4px;
    min-height: 24px;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    color: {COLORS['accent']};
    background: {COLORS['accent_soft']};
    border-bottom: 3px solid {COLORS['accent']};
    font-weight: 700;
}}
QTabBar::tab:hover:!selected {{
    color: {COLORS['text']};
    border-bottom: 3px solid {COLORS['border']};
}}
QTabBar::tab:disabled {{
    color: {COLORS['disabled_text']};
    background: {COLORS['surface']};
}}
QTabBar QToolButton {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
}}
QScrollBar:vertical {{
    width: 12px;
    background: transparent;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    min-height: 34px;
    background: #C3CBD8;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{ background: #9DA8B9; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    height: 12px;
    background: transparent;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    min-width: 34px;
    background: #C3CBD8;
    border-radius: 4px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QLabel#warningCard {{
    color: {COLORS['confirm']};
    background: {COLORS['confirm_soft']};
    border: 1px solid #F1D49A;
    border-radius: 10px;
    padding: 12px 14px;
}}
QWidget#reviewDetailPane {{ background: {COLORS['page']}; }}
QFrame#dialogFooter {{
    background: {COLORS['surface']};
    border-top: 1px solid {COLORS['border']};
}}
QSplitter::handle {{ background: {COLORS['page']}; width: 8px; }}
QStackedWidget {{ background: {COLORS['page']}; }}
QFrame#appHeader {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 16px;
}}
QLabel#brandMark {{
    color: white;
    background: {COLORS['accent']};
    border-radius: 12px;
    min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px;
    font-size: 18px;
    font-weight: 800;
}}
QFrame#metricTile {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 14px;
}}
QLabel#metricLabel {{ color: {COLORS['muted']}; font-size: 12px; font-weight: 600; }}
QLabel#metricValue {{ font-size: 17px; font-weight: 700; }}
QLabel#metricHint {{ color: {COLORS['muted']}; font-size: 12px; }}
QLabel#pill {{
    border-radius: 11px;
    padding: 3px 10px;
    font-size: 12px;
    font-weight: 700;
}}
QFrame#recognitionPanel {{
    background: {COLORS['header']};
    border: 1px solid {COLORS['border']};
    border-radius: 12px;
}}
QLabel#infoCard {{
    color: {COLORS['accent_pressed']};
    background: {COLORS['accent_soft']};
    border: 1px solid #C9D7F8;
    border-radius: 10px;
    padding: 10px 14px;
}}
/* Table-centred review screens: compact rows and in-cell controls. */
QTableWidget#denseTable {{ padding: 0; }}
QTableWidget#denseTable::item {{ padding: 2px 8px; }}
QTableWidget#denseTable QComboBox, QTableWidget#denseTable QLineEdit {{
    min-height: 26px;
    max-height: 30px;
    padding: 0 8px;
    border-radius: 6px;
}}
QTableWidget#denseTable QCheckBox {{ min-height: 24px; spacing: 6px; }}
QTableWidget#denseTable QHeaderView::section {{ padding: 6px 8px; }}
QFrame#reviewHeader {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 10px;
}}
QLabel#statusStrip {{ font-size: 13px; }}
QLabel#hintLine {{ color: {COLORS['muted']}; font-size: 12px; }}
QLabel#detailText {{
    color: {COLORS['text']};
    background: {COLORS['header']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 13px;
}}
QToolButton#disclosure {{
    color: {COLORS['accent']};
    background: transparent;
    border: 0;
    padding: 2px 4px;
    font-size: 13px;
    font-weight: 600;
}}
QToolButton#paneToggle {{
    color: {COLORS['text']};
    background: {COLORS['surface']};
    border: 1px solid {COLORS['input_border']};
    border-radius: 8px;
    padding: 6px 10px;
}}
QToolButton#paneToggle:checked {{
    color: {COLORS['accent']};
    background: {COLORS['accent_soft']};
    border-color: {COLORS['accent']};
}}
QTabWidget#reviewTabs QTabBar::tab {{ padding: 8px 12px; margin-right: 2px; }}
"""


def apply_light_theme(app) -> None:
    """Fusion style + an explicit light palette, then the style sheet.

    Windows dark mode otherwise hands Qt a dark palette, which shows through
    wherever the style sheet does not paint (e.g. tab bars, viewports).
    """
    from PySide6.QtGui import QColor, QPalette

    app.setStyle("Fusion")
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: COLORS["page"],
        QPalette.ColorRole.WindowText: COLORS["text"],
        QPalette.ColorRole.Base: COLORS["surface"],
        QPalette.ColorRole.AlternateBase: "#F9FAFC",
        QPalette.ColorRole.Text: COLORS["text"],
        QPalette.ColorRole.Button: COLORS["surface"],
        QPalette.ColorRole.ButtonText: COLORS["text"],
        QPalette.ColorRole.ToolTipBase: COLORS["text"],
        QPalette.ColorRole.ToolTipText: COLORS["surface"],
        QPalette.ColorRole.Highlight: COLORS["accent_soft"],
        QPalette.ColorRole.HighlightedText: COLORS["text"],
        QPalette.ColorRole.PlaceholderText: COLORS["muted"],
        QPalette.ColorRole.Link: COLORS["accent"],
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(COLORS["disabled_text"]))
    app.setPalette(palette)
    app.setStyleSheet(APP_STYLE_SHEET)
