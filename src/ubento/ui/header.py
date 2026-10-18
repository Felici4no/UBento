"""Header fixo: marca + abas (Geral e um agente por aba) + botão de novo agente.

Numa janela sem moldura o header também é a barra da janela: arrastar pelo espaço vazio move a janela, duplo clique alterna maximizar e,
no canto, ficam minimizar, maximizar/restaurar e fechar.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import icons, theme
from .components import setup

W = theme.W
HEIGHT = 72
TAB_H = 38
PAD_X = 32
CTRL_W, CTRL_H, CTRL_GAP, CTRL_MARGEM = 42, 36, 2, 10  # botões da janela
CONTROLES = ("min", "max", "close")
HITS_FIXOS = ("+", "gear", "eye", *CONTROLES)


@dataclass(frozen=True)
class Tab:
    key: str
    name: str
    color: str | None  # None = aba "Geral"
    pending: int = 0  # propostas de decisão aguardando aprovação


class TabHeader(QWidget):
    selected = Signal(str)
    add_requested = Signal()
    rename_requested = Signal(str)
    context_requested = Signal(object, QPoint)  # (chave ou None, posição global)
    reordered = Signal(str, int)  # (chave do agente, novo índice entre os agentes)
    settings_requested = Signal()
    privacy_toggled = Signal()
    drag_requested = Signal()  # arrastar a janela (só com janela sem moldura)
    minimize_requested = Signal()
    maximize_requested = Signal()  # alterna maximizar/restaurar
    close_requested = Signal()

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
        self._controles = False  # janela sem moldura: o header desenha minimizar/maximizar/fechar
        self._maximizada = False
        self.animate = True
        self._appear: dict[str, float] = {}
        self._anims: dict[str, QVariantAnimation] = {}
        self.setMouseTracking(True)
        self.setFixedHeight(HEIGHT)

    # -- dados -------------------------------------------------------------

    def set_tabs(self, tabs: list[Tab], current: str) -> None:
        known = {t.key for t in self._tabs}
        self._tabs, self._current = tabs, current
        if known and self.animate:
            for tab in tabs:
                if tab.key not in known:
                    self._grow(tab.key)
        self.update()

    def _grow(self, key: str) -> None:
        """Aba nova: cresce de largura zero com um pequeno estouro no fim."""
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(520)
        curve = QEasingCurve(QEasingCurve.Type.OutBack)
        curve.setOvershoot(1.5)
        anim.setEasingCurve(curve)
        self._appear[key] = 0.0
        self._anims[key] = anim
        anim.valueChanged.connect(lambda v, k=key: self._set_appear(k, float(v)))
        anim.finished.connect(lambda k=key: (self._appear.pop(k, None), self._anims.pop(k, None), self.update()))
        anim.start()

    def _set_appear(self, key: str, value: float) -> None:
        self._appear[key] = value
        self.update()

    def set_greeting(self, name: str) -> None:
        self._greeting = f"Olá, {name}" if name else ""
        self.update()

    def set_hidden(self, hidden: bool) -> None:
        self._hidden = hidden
        self.update()

    def set_window_controls(self, ativos: bool) -> None:
        self._controles = ativos
        self.update()

    def set_maximized(self, maximizada: bool) -> None:
        self._maximizada = maximizada
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
        widths = [w * max(0.0, self._appear.get(t.key, 1.0)) for w, t in zip(widths, self._tabs)]
        y = (HEIGHT - TAB_H) / 2
        out, x = [], left
        for tab, w in zip(self._tabs, widths):
            out.append((tab, QRectF(x, y, w, TAB_H)))
            x += w + gap
        return out, QRectF(x + 6, y, plus_w, TAB_H)

    def _greeting_width(self) -> float:
        return QFontMetrics(theme.font(14, W.Normal)).horizontalAdvance(self._greeting) if self._greeting else 0.0

    def _controles_largura(self) -> float:
        return (len(CONTROLES) * CTRL_W + (len(CONTROLES) - 1) * CTRL_GAP + CTRL_MARGEM + 16) if self._controles else 0.0

    def _controles_rects(self) -> dict[str, QRectF]:
        if not self._controles:
            return {}
        y = (HEIGHT - CTRL_H) / 2
        x = self.width() - CTRL_MARGEM - len(CONTROLES) * CTRL_W - (len(CONTROLES) - 1) * CTRL_GAP
        return {nome: QRectF(x + i * (CTRL_W + CTRL_GAP), y, CTRL_W, CTRL_H) for i, nome in enumerate(CONTROLES)}

    def _right_width(self) -> float:
        greet = self._greeting_width()
        return PAD_X + TAB_H * 2 + 8 + (greet + 16 if greet else 0) + self._controles_largura() - (PAD_X if self._controles else 0)

    def _right_rects(self) -> tuple[QRectF, QRectF]:
        y = (HEIGHT - TAB_H) / 2
        gear = QRectF(self.width() - (0 if self._controles else PAD_X) - TAB_H - self._controles_largura(), y, TAB_H, TAB_H)
        eye = QRectF(gear.left() - 8 - TAB_H, y, TAB_H, TAB_H)
        return eye, gear

    def _hit(self, pos: QPointF) -> str | None:
        for nome, r in self._controles_rects().items():
            if r.contains(pos):
                return nome
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
            elif hit == "min":
                self.minimize_requested.emit()
            elif hit == "max":
                self.maximize_requested.emit()
            elif hit == "close":
                self.close_requested.emit()
            elif hit:
                self._press, self._dragging = (hit, e.position()), False
                self.selected.emit(hit)
            elif self._controles:  # espaço vazio de uma janela sem moldura: é a barra de título
                self.drag_requested.emit()
        elif e.button() == Qt.MouseButton.RightButton:
            self.context_requested.emit(None if hit in (None, *HITS_FIXOS) else hit, e.globalPosition().toPoint())

    def mouseDoubleClickEvent(self, e) -> None:
        hit = self._hit(e.position())
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if hit is None and self._controles:
            self.maximize_requested.emit()
        elif hit and hit not in HITS_FIXOS:
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
            if r.width() < 6:
                continue
            p.setOpacity(min(1.0, self._appear.get(tab.key, 1.0) * 1.6))
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
            if tab.pending:
                p.setBrush(QColor(theme.WARNING))
                p.setPen(QPen(QColor('#FFFFFF' if active else theme.BG_TOP), 2))
                p.drawEllipse(QPointF(r.right() - 9, r.top() + 8), 4.5, 4.5)
            p.setPen(fg)
            p.setFont(self._font)
            text = fm.elidedText(tab.name, Qt.TextElideMode.ElideRight, int(r.right() - 18 - x))
            p.drawText(QRectF(x, r.top(), r.right() - x, r.height()), Qt.AlignmentFlag.AlignVCenter, text)

        p.setOpacity(1.0)
        self._paint_controles(p)
        hot = self._hover == "+"
        p.setBrush(QColor(255, 255, 255, 18 if hot else 0))
        p.setPen(QPen(QColor(theme.OUTLINE), 1.2))
        p.drawEllipse(plus.adjusted(0.6, 0.6, -0.6, -0.6))
        p.drawPixmap(QPointF(plus.center().x() - 9, plus.center().y() - 9), icons.pixmap("plus", theme.TEXT if hot else theme.MUTED, 18, 2.0))
        self._paint_right(p)

    def _paint_controles(self, p: QPainter) -> None:
        """Minimizar, maximizar/restaurar e fechar: só o traço, sem contorno; o fundo só aparece sob o mouse (fechar fica vermelho)."""
        for nome, r in self._controles_rects().items():
            quente = self._hover == nome
            fundo = QColor("#E5484D") if (quente and nome == "close") else QColor(255, 255, 255, 22 if quente else 0)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fundo)
            p.drawRoundedRect(r, 9, 9)
            cor = QColor("#FFFFFF" if quente and nome == "close" else theme.TEXT if quente else theme.MUTED)
            p.setPen(QPen(cor, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            c = r.center()
            if nome == "min":
                p.drawLine(QPointF(c.x() - 6, c.y() + 3), QPointF(c.x() + 6, c.y() + 3))
            elif nome == "max" and not self._maximizada:
                p.drawRoundedRect(QRectF(c.x() - 6, c.y() - 6, 12, 12), 2.5, 2.5)
            elif nome == "max":  # restaurar: dois quadrados sobrepostos
                p.drawRoundedRect(QRectF(c.x() - 6, c.y() - 3, 9, 9), 2, 2)
                p.drawLine(QPointF(c.x() - 3, c.y() - 6), QPointF(c.x() + 4, c.y() - 6))
                p.drawLine(QPointF(c.x() + 4, c.y() - 6), QPointF(c.x() + 6, c.y() - 4))
                p.drawLine(QPointF(c.x() + 6, c.y() - 4), QPointF(c.x() + 6, c.y() + 3))
            else:
                p.drawLine(QPointF(c.x() - 5.5, c.y() - 5.5), QPointF(c.x() + 5.5, c.y() + 5.5))
                p.drawLine(QPointF(c.x() - 5.5, c.y() + 5.5), QPointF(c.x() + 5.5, c.y() - 5.5))

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
