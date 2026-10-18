"""Header fixo: marca + abas (Geral e um agente por aba) + botão de novo agente."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import icons, theme
from .components import setup

W = theme.W
HEIGHT = 72
TAB_H = 38
PAD_X = 32


@dataclass(frozen=True)
class Tab:
    key: str
    name: str
    color: str | None  # None = aba "Geral"


class TabHeader(QWidget):
    selected = Signal(str)
    add_requested = Signal()
    rename_requested = Signal(str)
    context_requested = Signal(object, QPoint)  # (chave ou None, posição global)
    reordered = Signal(str, int)  # (chave do agente, novo índice entre os agentes)
    settings_requested = Signal()
    privacy_toggled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tabs: list[Tab] = []
        self._current = ""
        self._hover: str | None = None  # chave, "+" ou None
        self._press: tuple[str, QPointF] | None = None
        self._dragging = False
        self._font = theme.font(15, W.Medium)
        self._greeting = ""
        self._hidden = False
        self.setMouseTracking(True)
        self.setFixedHeight(HEIGHT)

    # -- dados -------------------------------------------------------------

    def set_tabs(self, tabs: list[Tab], current: str) -> None:
        self._tabs, self._current = tabs, current
        self.update()

    def set_greeting(self, name: str) -> None:
        self._greeting = f"Olá, {name}" if name else ""
        self.update()

    def set_hidden(self, hidden: bool) -> None:
        self._hidden = hidden
        self.update()

    def set_current(self, key: str) -> None:
        self._current = key
        self.update()

    # -- geometria ---------------------------------------------------------

    def _brand_width(self) -> float:
        return 34 + 10 + QFontMetrics(theme.font(18, W.DemiBold)).horizontalAdvance("UBento")

    def _natural(self, tab: Tab) -> float:
        fm = QFontMetrics(self._font)
        return fm.horizontalAdvance(tab.name) + 18 + (24 if tab.color is None else 18) + 18 + 2

    def _rects(self) -> tuple[list[tuple[Tab, QRectF]], QRectF]:
        left = PAD_X + self._brand_width() + 36
        plus_w = TAB_H
        avail = self.width() - left - self._right_width() - plus_w - 24
        gap = 6.0
        widths = [self._natural(t) for t in self._tabs]
        need = sum(widths) + gap * max(0, len(widths) - 1)
        if need > avail > 0:  # muitas abas: encolhe todas proporcionalmente
            factor = (avail - gap * max(0, len(widths) - 1)) / sum(widths)
            widths = [max(64.0, w * factor) for w in widths]
        y = (HEIGHT - TAB_H) / 2
        out, x = [], left
        for tab, w in zip(self._tabs, widths):
            out.append((tab, QRectF(x, y, w, TAB_H)))
            x += w + gap
        return out, QRectF(x + 6, y, plus_w, TAB_H)

    def _greeting_width(self) -> float:
        return QFontMetrics(theme.font(14, W.Normal)).horizontalAdvance(self._greeting) if self._greeting else 0.0

    def _right_width(self) -> float:
        greet = self._greeting_width()
        return PAD_X + TAB_H * 2 + 8 + (greet + 16 if greet else 0)

    def _right_rects(self) -> tuple[QRectF, QRectF]:
        y = (HEIGHT - TAB_H) / 2
        gear = QRectF(self.width() - PAD_X - TAB_H, y, TAB_H, TAB_H)
        eye = QRectF(gear.left() - 8 - TAB_H, y, TAB_H, TAB_H)
        return eye, gear

    def _hit(self, pos: QPointF) -> str | None:
        eye, gear = self._right_rects()
        if gear.contains(pos):
            return "gear"
        if eye.contains(pos):
            return "eye"
        rects, plus = self._rects()
        if plus.contains(pos):
            return "+"
        for tab, r in rects:
            if r.contains(pos):
                return tab.key
        return None

    # -- mouse -------------------------------------------------------------

    def mousePressEvent(self, e) -> None:
        hit = self._hit(e.position())
        if e.button() == Qt.MouseButton.LeftButton:
            if hit == "+":
                self.add_requested.emit()
            elif hit == "gear":
                self.settings_requested.emit()
            elif hit == "eye":
                self.privacy_toggled.emit()
            elif hit:
                self._press, self._dragging = (hit, e.position()), False
                self.selected.emit(hit)
        elif e.button() == Qt.MouseButton.RightButton:
            self.context_requested.emit(None if hit in (None, "+", "gear", "eye") else hit, e.globalPosition().toPoint())

    def mouseDoubleClickEvent(self, e) -> None:
        hit = self._hit(e.position())
        if e.button() == Qt.MouseButton.LeftButton and hit and hit not in ("+", "gear", "eye"):
            self.rename_requested.emit(hit)

    def mouseMoveEvent(self, e) -> None:
        hit = self._hit(e.position())
        if hit != self._hover:
            self._hover = hit
            self.update()
        if self._press and e.buttons() & Qt.MouseButton.LeftButton and self._press[0] != "overview":
            if not self._dragging and abs(e.position().x() - self._press[1].x()) > 8:
                self._dragging = True
            if self._dragging:
                self._drag_to(e.position().x())
        self.setCursor(Qt.CursorShape.ClosedHandCursor if self._dragging else (Qt.CursorShape.PointingHandCursor if hit else Qt.CursorShape.ArrowCursor))

    def _drag_to(self, x: float) -> None:
        key = self._press[0]
        rects, _ = self._rects()
        others = [r for t, r in rects if t.key not in (key, "overview")]
        index = sum(1 for r in others if r.center().x() < x)
        agents = [t.key for t, _ in rects if t.key != "overview"]
        if agents.index(key) != index:
            self.reordered.emit(key, index)

    def mouseReleaseEvent(self, _e) -> None:
        self._press, self._dragging = None, False
        self.unsetCursor()

    def leaveEvent(self, _e) -> None:
        self._hover = None
        self.update()

    # -- desenho -----------------------------------------------------------

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        self._paint_brand(p)
        rects, plus = self._rects()
        fm = QFontMetrics(self._font)
        for tab, r in rects:
            active = tab.key == self._current
            hovered = tab.key == self._hover and not active
            if active:
                p.setBrush(QColor("#FFFFFF"))
                p.setPen(Qt.PenStyle.NoPen)
            else:
                p.setBrush(QColor(255, 255, 255, 14 if hovered else 0))
                p.setPen(QPen(QColor(theme.OUTLINE), 1.2))
            p.drawRoundedRect(r.adjusted(0.6, 0.6, -0.6, -0.6), TAB_H / 2, TAB_H / 2)

            fg = QColor("#0A0A0C" if active else (theme.TEXT if hovered else theme.MUTED))
            x = r.left() + 18
            if tab.color is None:
                p.drawPixmap(QPointF(x, r.center().y() - 8), icons.pixmap("grid", fg, 16, 1.9))
                x += 24
            else:
                p.setBrush(QColor(tab.color))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QPointF(x + 4, r.center().y()), 4.5, 4.5)
                x += 18
            p.setPen(fg)
            p.setFont(self._font)
            text = fm.elidedText(tab.name, Qt.TextElideMode.ElideRight, int(r.right() - 18 - x))
            p.drawText(QRectF(x, r.top(), r.right() - x, r.height()), Qt.AlignmentFlag.AlignVCenter, text)

        hot = self._hover == "+"
        p.setBrush(QColor(255, 255, 255, 18 if hot else 0))
        p.setPen(QPen(QColor(theme.OUTLINE), 1.2))
        p.drawEllipse(plus.adjusted(0.6, 0.6, -0.6, -0.6))
        p.drawPixmap(QPointF(plus.center().x() - 9, plus.center().y() - 9), icons.pixmap("plus", theme.TEXT if hot else theme.MUTED, 18, 2.0))
        self._paint_right(p)

    def _paint_right(self, p: QPainter) -> None:
        eye, gear = self._right_rects()
        if self._greeting:
            p.setFont(theme.font(14, W.Normal))
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(eye.left() - 16 - self._greeting_width() - 4, 0, self._greeting_width() + 8, HEIGHT),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self._greeting)
        for key, rect, icon in (('eye', eye, 'eye-off' if self._hidden else 'eye'), ('gear', gear, 'settings')):
            active = key == 'gear' and self._current == 'settings'
            on = key == 'eye' and self._hidden
            hot = self._hover == key
            if active:
                p.setBrush(QColor('#FFFFFF'))
                p.setPen(Qt.PenStyle.NoPen)
            else:
                p.setBrush(QColor(255, 255, 255, 18 if hot else (10 if on else 0)))
                p.setPen(QPen(QColor(theme.OUTLINE), 1.2))
            p.drawEllipse(rect.adjusted(0.6, 0.6, -0.6, -0.6))
            fg = '#0A0A0C' if active else (theme.TEXT if (hot or on) else theme.MUTED)
            p.drawPixmap(QPointF(rect.center().x() - 9, rect.center().y() - 9), icons.pixmap(icon, fg, 18, 1.9))

    def _paint_brand(self, p: QPainter) -> None:
        y = (HEIGHT - 34) / 2
        pm = _logo()
        p.drawPixmap(QPointF(PAD_X, y), pm)
        p.setPen(QColor(theme.TEXT))
        p.setFont(theme.font(18, W.DemiBold))
        p.drawText(QRectF(PAD_X + 44, 0, 200, HEIGHT), Qt.AlignmentFlag.AlignVCenter, "UBento")


_LOGO = None


def _logo():
    """Marca do app (mosaico "bento") renderizada uma vez."""
    global _LOGO
    if _LOGO is None:
        from PySide6.QtCore import QByteArray
        from PySide6.QtGui import QGuiApplication, QPixmap
        from PySide6.QtSvg import QSvgRenderer
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><rect width="256" height="256" rx="58" fill="#3B6BFF"/>'
            '<rect x="48" y="48" width="86" height="160" rx="22" fill="#fff"/>'
            '<rect x="146" y="48" width="62" height="74" rx="18" fill="#fff" fill-opacity=".7"/>'
            '<rect x="146" y="134" width="62" height="74" rx="18" fill="#fff" fill-opacity=".4"/></svg>'
        )
        screen = QGuiApplication.primaryScreen()
        dpr = max(2.0, screen.devicePixelRatio() if screen else 1.0)
        pm = QPixmap(int(34 * dpr), int(34 * dpr))
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        QSvgRenderer(QByteArray(svg.encode())).render(painter)
        painter.end()
        pm.setDevicePixelRatio(dpr)
        _LOGO = pm
    return _LOGO
