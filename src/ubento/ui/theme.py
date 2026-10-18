"""Tokens visuais do UBento (tema escuro)."""

from __future__ import annotations

from PySide6.QtGui import QFont

BG_TOP = "#1B1B20"
BG_BOTTOM = "#121215"
CARD = "#060608"
CARD_EDGE = "#17171C"
PANEL = "#0F0F13"
PANEL_EDGE = "#1A1A20"
TEXT = "#F2F2F5"
MUTED = "#8A8A93"
DIM = "#55555D"
LINE = "#1E1E24"
BAR = "#34343A"
BAR_LIGHT = "#56565E"
GREEN = "#34D86B"
RED = "#EF4B3F"
BLUE = "#3B6BFF"
BLUE_SOFT = "#5C8BFF"
OUTLINE = "#3A3A41"
TOOLTIP_BG = "#26262B"

ASSET_COLORS = {
    "USD": "#3B6BFF",
    "SOL": "#B14CF0",
    "AVAX": "#E8453C",
    "ETH": "#5B8DEF",
    "BNB": "#F2B01E",
    "USDT": "#2EE081",
    "USDC": "#2F76E6",
}

APP_QSS = f"""
QToolTip {{
    background: {TOOLTIP_BG}; color: {TEXT}; border: 1px solid #34343B;
    padding: 6px 9px; border-radius: 8px; font-size: 12px;
}}
QMenu {{
    background: #141418; color: {TEXT}; border: 1px solid #2A2A31;
    padding: 6px; border-radius: 12px;
}}
QMenu::item {{ padding: 8px 20px 8px 14px; border-radius: 8px; font-size: 14px; }}
QMenu::item:selected {{ background: #25252C; }}
QScrollArea {{ background: transparent; }}
QDialog, QMessageBox, QInputDialog {{ background: #141418; }}
QDialog QLabel {{ color: {TEXT}; font-size: 14px; }}
QDialog QLineEdit {{ background: #0F0F13; color: {TEXT}; border: 1px solid #2A2A31; border-radius: 10px; padding: 8px 10px; font-size: 15px; selection-background-color: {BLUE}; }}
QDialog QPushButton {{ background: #1E1E25; color: {TEXT}; border: 1px solid #2E2E36; border-radius: 10px; padding: 8px 18px; font-size: 14px; min-width: 70px; }}
QDialog QPushButton:hover {{ background: #26262E; }}
QDialog QPushButton:default {{ background: {BLUE}; border-color: {BLUE}; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: #2E2E36; border-radius: 4px; min-height: 40px; }}
QScrollBar::handle:vertical:hover {{ background: #3D3D47; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px 4px; }}
QScrollBar::handle:horizontal {{ background: #2E2E36; border-radius: 4px; min-width: 40px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
"""

FONT_FAMILIES = ["Inter", "Segoe UI Variable Display", "Segoe UI", "Arial"]

W = QFont.Weight


def font(px: int, weight: QFont.Weight = W.Normal) -> QFont:
    f = QFont()
    f.setFamilies(FONT_FAMILIES)
    f.setPixelSize(px)
    f.setWeight(weight)
    return f
