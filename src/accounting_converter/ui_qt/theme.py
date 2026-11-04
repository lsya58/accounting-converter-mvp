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
    "neutral": "#4B5568",
    "neutral_soft": "#EEF1F6",
    "disabled_text": "#6B7484",
    "disabled_surface": "#EDF0F4",
    "focus": "#2457D6",
    "input_border": "#C9D1DD",
    "header": "#F6F8FB",
}


def status_visual(status: UserFacingStatus) -> tuple[str, str, str]:
    return {
        UserFacingStatus.NEEDS_INPUT: ("未準備", COLORS["neutral"], COLORS["neutral_soft"]),
        UserFacingStatus.READY: ("準備完了", COLORS["ready"], COLORS["ready_soft"]),
        UserFacingStatus.CONFIRM: ("要確認", COLORS["confirm"], COLORS["confirm_soft"]),
        UserFacingStatus.BLOCKED: ("停止", COLORS["blocked"], COLORS["blocked_soft"]),
        UserFacingStatus.SUCCESS: ("完了", COLORS["ready"], COLORS["ready_soft"]),
    }[status]


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
    width: 34px;
    border: 0;
    border-left: 1px solid {COLORS['border']};
    border-top-right-radius: 9px;
    border-bottom-right-radius: 9px;
    background: {COLORS['header']};
}}
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
QTabBar::tab {{
    color: {COLORS['muted']};
    background: transparent;
    border: 0;
    border-bottom: 3px solid transparent;
    padding: 10px 16px;
    margin-right: 4px;
    min-height: 24px;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    color: {COLORS['accent']};
    border-bottom: 3px solid {COLORS['accent']};
    font-weight: 700;
}}
QTabBar::tab:hover:!selected {{
    color: {COLORS['text']};
    border-bottom: 3px solid {COLORS['border']};
}}
QTabBar::tab:disabled {{
    color: {COLORS['disabled_text']};
    background: transparent;
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
"""
