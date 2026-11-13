from __future__ import annotations

from accounting_converter.ui.view_models import UserFacingStatus


# Design tokens (docs/development/ui_ux_renewal_plan.md 3.1, Fluent 2 x Modern Enterprise). Measured contrast:
# body text >= 14:1 on page/surface, status text >= 5.6:1 on its own background, control borders >= 3:1.
TOKENS = {
    "bg.page": "#F7F8FA", "bg.surface": "#FFFFFF", "bg.subtle": "#F1F3F6",
    "border.default": "#E1E5EB", "border.control": "#828C9B",
    "text.primary": "#1B2433", "text.secondary": "#505B6B", "text.disabled": "#6F7988", "bg.disabled": "#EEF1F4",
    "accent": "#1F3A68", "accent.hover": "#18305A", "accent.pressed": "#12264A", "accent.soft": "#E8EDF5",
    "focus": "#3D6FD1",
    "status.ready": "#146C43", "status.ready.bg": "#E6F4EC",
    "status.block": "#8A4B00", "status.block.bg": "#FFF3DC", "status.block.border": "#F0C985",
    "status.pending": "#1F3A68", "status.pending.bg": "#EEF1F6",
    "status.evidence": "#57409B", "status.evidence.bg": "#F1EDFA",
    "status.error": "#B3261E", "status.error.bg": "#FDECEA",
    "status.neutral": "#505B6B", "status.neutral.bg": "#EEF1F6",
}
SPACING = {"xs": 4, "s": 8, "m": 12, "l": 16, "xl": 24, "xxl": 32}
RADIUS = {"control": 4, "card": 8}

# The original keys (the UI contract and older screens use them), now taking their values from the tokens.
COLORS = {
    "page": TOKENS["bg.page"],
    "surface": TOKENS["bg.surface"],
    "border": TOKENS["border.default"],
    "text": TOKENS["text.primary"],
    "muted": TOKENS["text.secondary"],
    "accent": TOKENS["accent"],
    "accent_hover": TOKENS["accent.hover"],
    "accent_pressed": TOKENS["accent.pressed"],
    "accent_soft": TOKENS["accent.soft"],
    "ready": TOKENS["status.ready"],
    "ready_soft": TOKENS["status.ready.bg"],
    "confirm": TOKENS["status.block"],          # amber: needs a person / BLOCK
    "confirm_soft": TOKENS["status.block.bg"],
    "blocked": TOKENS["status.error"],          # red: stopped / error
    "blocked_soft": TOKENS["status.error.bg"],
    "evidence": TOKENS["status.evidence"],
    "evidence_soft": TOKENS["status.evidence.bg"],
    "neutral": TOKENS["status.neutral"],
    "neutral_soft": TOKENS["status.neutral.bg"],
    "disabled_text": TOKENS["text.disabled"],
    "disabled_surface": TOKENS["bg.disabled"],
    "focus": TOKENS["focus"],
    "input_border": TOKENS["border.control"],
    "header": TOKENS["bg.subtle"],
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
    border-radius: 8px;
}}
QLabel#title {{ font-size: 22px; font-weight: 600; }}
QLabel#subtitle, QLabel#muted {{ color: {COLORS['muted']}; }}
QLabel:disabled {{ color: {COLORS['disabled_text']}; }}
QLabel#sectionTitle {{ font-size: 16px; font-weight: 600; }}
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
    min-height: 32px;
    padding: 0 16px;
    color: {COLORS['text']};
    border: 1px solid {COLORS['input_border']};
    border-radius: 4px;
    background: {COLORS['surface']};
    font-weight: 600;
}}
QPushButton:hover {{ background: {COLORS['neutral_soft']}; border-color: {COLORS['text']}; }}
QPushButton:pressed {{ background: #E3E8F0; }}
QPushButton:focus {{ border: 2px solid {COLORS['focus']}; }}
QPushButton:disabled {{
    color: {COLORS['disabled_text']};
    background: {COLORS['disabled_surface']};
    border-color: {COLORS['border']};
}}
QPushButton#primaryButton {{
    min-height: 36px;
    min-width: 160px;
    color: white;
    background: {COLORS['accent']};
    border: 0;
    border-radius: 4px;
    font-size: 15px;
    font-weight: 700;
}}
QPushButton#primaryButton:hover {{ background: {COLORS['accent_hover']}; }}
QPushButton#primaryButton:pressed {{ background: {COLORS['accent_pressed']}; }}
QPushButton#primaryButton:focus {{ border: 2px solid {COLORS['focus']}; }}
QPushButton#primaryButton:disabled {{ color: {COLORS['disabled_text']}; background: {COLORS['disabled_surface']}; }}
QFrame#dropZone {{
    background: {COLORS['surface']};
    border: 2px dashed {COLORS['input_border']};
    border-radius: 8px;
}}
QFrame#dropZone[dragActive="true"] {{
    background: {COLORS['accent_soft']};
    border-color: {COLORS['accent']};
}}
QLineEdit, QComboBox, QListWidget, QTableWidget {{
    min-height: 32px;
    padding: 0 10px;
    color: {COLORS['text']};
    background: {COLORS['surface']};
    border: 1px solid {COLORS['input_border']};
    border-radius: 4px;
    selection-background-color: {COLORS['accent_soft']};
    selection-color: {COLORS['text']};
}}
QLineEdit:hover, QComboBox:hover {{ border-color: {COLORS['text']}; }}
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
    alternate-background-color: {COLORS['header']};
    gridline-color: {COLORS['border']};
    selection-background-color: {COLORS['accent_soft']};
    selection-color: {COLORS['text']};
    border-radius: 8px;
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
    border-radius: 8px;
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
    background: {COLORS['input_border']};
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
    background: {COLORS['input_border']};
    border-radius: 4px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QLabel#warningCard {{
    color: {COLORS['confirm']};
    background: {COLORS['confirm_soft']};
    border: 1px solid {TOKENS['status.block.border']};
    border-radius: 8px;
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
    border-radius: 8px;
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
    border-radius: 8px;
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
    border: 1px solid {COLORS['accent_soft']};
    border-radius: 8px;
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
/* ---- shared components (ui_qt/components.py) ---- */
QPushButton#dangerButton {{ color: {TOKENS['status.error']}; border: 1px solid {TOKENS['status.error']}; }}
QPushButton#dangerButton:hover {{ background: {TOKENS['status.error.bg']}; }}
QPushButton#subtleButton {{ color: {COLORS['accent']}; background: transparent; border: 1px solid transparent; }}
QPushButton#subtleButton:hover {{ background: {COLORS['accent_soft']}; }}
QPushButton#subtleButton:focus {{ border: 2px solid {COLORS['focus']}; }}
QLabel#statusBadge {{ border-radius: 4px; padding: 2px 8px; font-size: 12px; font-weight: 600; }}
QLabel#statusBadge[tone="ready"] {{ color: {TOKENS['status.ready']}; background: {TOKENS['status.ready.bg']}; }}
QLabel#statusBadge[tone="block"] {{ color: {TOKENS['status.block']}; background: {TOKENS['status.block.bg']}; }}
QLabel#statusBadge[tone="pending"] {{ color: {TOKENS['status.pending']}; background: {TOKENS['status.pending.bg']}; }}
QLabel#statusBadge[tone="evidence"] {{ color: {TOKENS['status.evidence']}; background: {TOKENS['status.evidence.bg']}; }}
QLabel#statusBadge[tone="error"] {{ color: {TOKENS['status.error']}; background: {TOKENS['status.error.bg']}; }}
QLabel#statusBadge[tone="neutral"] {{ color: {TOKENS['status.neutral']}; background: {TOKENS['status.neutral.bg']}; }}
QFrame#metricCard {{ background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 8px; }}
QFrame#metricCard[tone="ready"] {{ border-left: 4px solid {TOKENS['status.ready']}; }}
QFrame#metricCard[tone="block"] {{ border-left: 4px solid {TOKENS['status.block']}; }}
QFrame#metricCard[tone="pending"] {{ border-left: 4px solid {TOKENS['status.pending']}; }}
QFrame#metricCard[tone="neutral"] {{ border-left: 4px solid {TOKENS['border.control']}; }}
QLabel#metricCardLabel {{ color: {COLORS['muted']}; font-size: 12px; font-weight: 600; }}
QLabel#metricCardValue {{ font-size: 24px; font-weight: 600; }}
QLabel#metricCardHint {{ color: {COLORS['muted']}; font-size: 12px; }}
QLabel#messageBar {{ border-radius: 4px; padding: 8px 12px; }}
QLabel#messageBar[level="info"] {{ color: {TOKENS['accent']}; background: {TOKENS['accent.soft']}; border: 1px solid {TOKENS['border.default']}; }}
QLabel#messageBar[level="success"] {{ color: {TOKENS['status.ready']}; background: {TOKENS['status.ready.bg']}; border: 1px solid {TOKENS['status.ready.bg']}; }}
QLabel#messageBar[level="warning"] {{ color: {TOKENS['status.block']}; background: {TOKENS['status.block.bg']}; border: 1px solid {TOKENS['status.block.border']}; }}
QLabel#messageBar[level="error"] {{ color: {TOKENS['status.error']}; background: {TOKENS['status.error.bg']}; border: 1px solid {TOKENS['status.error']}; }}
QLabel#modeBanner {{ border-radius: 4px; padding: 6px 10px; font-weight: 600; }}
QLabel#modeBanner[mode="view"] {{ color: {TOKENS['text.secondary']}; background: {TOKENS['bg.subtle']}; border: 1px solid {TOKENS['border.default']}; }}
QLabel#modeBanner[mode="trial"] {{ color: {TOKENS['accent']}; background: {TOKENS['accent.soft']}; border: 1px dashed {TOKENS['accent']}; }}
QLabel#modeBanner[mode="unapproved"] {{ color: {TOKENS['status.block']}; background: {TOKENS['status.block.bg']}; border: 1px solid {TOKENS['status.block.border']}; }}
QFrame#detailCard {{ background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 8px; }}
QLabel#detailCardTitle {{ font-size: 14px; font-weight: 600; }}
QTableWidget#journalTable::item {{ padding: 4px 8px; }}
/* ---- main window: left navigation + pages (Phase 3A) ---- */
QFrame#navRail {{ background: {TOKENS['bg.subtle']}; border: none; border-right: 1px solid {TOKENS['border.default']}; }}
QLabel#navBrand {{ color: {TOKENS['text.primary']}; font-size: 14px; font-weight: 600; padding: 4px 12px 12px 12px; }}
QPushButton#navButton {{
    text-align: left; padding: 8px 12px; min-height: 20px; border: 1px solid transparent; border-radius: 4px;
    background: transparent; color: {TOKENS['text.primary']}; font-weight: 400;
}}
QPushButton#navButton:hover {{ background: {TOKENS['accent.soft']}; }}
QPushButton#navButton:checked {{
    background: {TOKENS['bg.surface']}; color: {TOKENS['accent']}; font-weight: 600;
    border: 1px solid {TOKENS['border.default']}; border-left: 3px solid {TOKENS['accent']};
}}
QPushButton#navButton:focus {{ border: 2px solid {TOKENS['focus']}; }}
QFrame#contextBar {{ background: {TOKENS['bg.surface']}; border: none; border-bottom: 1px solid {TOKENS['border.default']}; }}
QLabel#pageTitle {{ color: {TOKENS['text.primary']}; font-size: 20px; font-weight: 600; }}
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
        QPalette.ColorRole.AlternateBase: COLORS["header"],
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
