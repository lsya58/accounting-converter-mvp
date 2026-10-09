from __future__ import annotations

from accounting_converter.ui.view_models import UserFacingStatus


COLORS = {
    "page": "#F4F6F8",
    "surface": "#FFFFFF",
    "border": "#DCE2E8",
    "text": "#1F2933",
    "muted": "#667481",
    "accent": "#1769AA",
    "accent_hover": "#0F5D98",
    "accent_pressed": "#0B4C7E",
    "ready": "#247A43",
    "ready_soft": "#E8F4EC",
    "confirm": "#996515",
    "confirm_soft": "#FFF4D8",
    "blocked": "#B33636",
    "blocked_soft": "#FBEAEA",
    "neutral": "#5E6C78",
    "neutral_soft": "#EAF0F5",
    "disabled_text": "#697681",
    "disabled_surface": "#E9EDF1",
    "focus": "#4B8FC5",
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
QFrame#card {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 10px;
}}
QLabel#title {{ font-size: 28px; font-weight: 700; }}
QLabel#subtitle, QLabel#muted {{ color: {COLORS['muted']}; }}
QLabel:disabled {{ color: {COLORS['disabled_text']}; }}
QLabel#sectionTitle {{ font-size: 17px; font-weight: 600; }}
QLabel#statusTitle {{ font-size: 20px; font-weight: 650; }}
QLabel#stepBadge {{
    color: white;
    background: {COLORS['accent']};
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
    border: 1px solid #C8D0D8;
    border-radius: 7px;
    background: #FFFFFF;
}}
QPushButton:hover {{ background: #F1F5F8; border-color: #9EABB7; }}
QPushButton:pressed {{ background: #E6EBF0; }}
QPushButton:focus {{ border: 2px solid {COLORS['focus']}; }}
QPushButton:disabled {{
    color: {COLORS['disabled_text']};
    background: {COLORS['disabled_surface']};
    border-color: #C8D0D8;
}}
QPushButton#primaryButton {{
    min-height: 52px;
    min-width: 210px;
    color: white;
    background: {COLORS['accent']};
    border: 0;
    border-radius: 8px;
    font-size: 16px;
    font-weight: 700;
}}
QPushButton#primaryButton:hover {{ background: {COLORS['accent_hover']}; }}
QPushButton#primaryButton:pressed {{ background: {COLORS['accent_pressed']}; }}
QPushButton#primaryButton:disabled {{ color: #8B959E; background: #D7DDE3; }}
QFrame#dropZone {{
    background: #FAFCFD;
    border: 2px dashed #AAB6C2;
    border-radius: 10px;
}}
QFrame#dropZone[dragActive="true"] {{
    background: #EAF3FA;
    border-color: {COLORS['accent']};
}}
QLineEdit, QComboBox, QListWidget, QTableWidget {{
    min-height: 38px;
    padding: 0 10px;
    color: {COLORS['text']};
    background: {COLORS['surface']};
    border: 1px solid #B8C3CD;
    border-radius: 6px;
    selection-background-color: #DCECF8;
    selection-color: {COLORS['text']};
}}
QLineEdit:focus, QComboBox:focus, QListWidget:focus, QTableWidget:focus {{
    border: 2px solid {COLORS['focus']};
}}
QLineEdit:disabled, QComboBox:disabled, QListWidget:disabled {{
    color: {COLORS['disabled_text']};
    background: {COLORS['disabled_surface']};
    border-color: #C8D0D8;
}}
QComboBox::drop-down {{
    width: 34px;
    border-left: 1px solid #C8D0D8;
    background: #F4F7F9;
}}
QComboBox QAbstractItemView {{
    color: {COLORS['text']};
    background: {COLORS['surface']};
    border: 1px solid #B8C3CD;
    selection-background-color: #DCECF8;
    selection-color: {COLORS['text']};
    outline: 0;
    padding: 4px;
}}
QTableWidget {{
    color: {COLORS['text']};
    background: {COLORS['surface']};
    alternate-background-color: #F7F9FB;
    gridline-color: {COLORS['border']};
    selection-background-color: #DCECF8;
    selection-color: {COLORS['text']};
}}
QHeaderView::section {{
    color: {COLORS['text']};
    background: #EAF0F5;
    border: 0;
    border-right: 1px solid {COLORS['border']};
    border-bottom: 1px solid #C8D0D8;
    padding: 9px 10px;
    font-weight: 600;
}}
QScrollBar:vertical {{
    width: 15px;
    background: #EEF2F5;
}}
QScrollBar::handle:vertical {{
    min-height: 34px;
    background: #AAB6C2;
    border-radius: 6px;
    margin: 2px;
}}
QLabel#warningCard {{
    color: #704A0A;
    background: {COLORS['confirm_soft']};
    border: 1px solid #E5C778;
    border-radius: 7px;
    padding: 12px;
}}
QStackedWidget {{ background: {COLORS['page']}; }}
"""
