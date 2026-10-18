"""Componentes visuais compartilhados, todos desenhados com QPainter."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QGraphicsOpacityEffect, QLabel, QSizePolicy, QWidget,
)

from ..formatting import pct, split_money
from . import icons, theme

W = theme.W


def setup(p: QPainter) -> None:
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)


def hover_color(color: QColor) -> QColor:
    c = QColor(color)
    if c.alpha() < 255:
        c.setAlpha(min(255, c.alpha() + 40))
        return c
    return c.lighter(118) if c.lightness() < 140 else c.darker(108)


class Label(QLabel):
    def __init__(self, text="", px=13, weight=W.Normal, color=theme.TEXT, parent=None):
        super().__init__(text, parent)
        self.setFont(theme.font(px, weight))
        self.set_color(color)

    def set_color(self, color) -> None:
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.WindowText, QColor(color))
        self.setPalette(pal)


class Card(QFrame):
    """Superfície escura arredondada com borda sutil."""

    def __init__(self, parent=None, radius=24):
        super().__init__(parent)
        self._radius = radius
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(QColor(theme.CARD))
        p.setPen(QPen(QColor(theme.CARD_EDGE), 1))
        p.drawRoundedRect(rect, self._radius, self._radius)


class MoneyText(QWidget):
    """Valor monetário com os centavos em cinza, como no modelo."""

    def __init__(self, px=28, weight=W.DemiBold, parent=None):
        super().__init__(parent)
        self._font = theme.font(px, weight)
        self._main, self._dec = "$0", ",00"
        self._fit()

    def set_amount(self, value: float) -> None:
        self._main, self._dec = split_money(value)
        self._fit()
        self.update()

    def _fit(self) -> None:
        fm = QFontMetrics(self._font)
        self.setFixedSize(fm.horizontalAdvance(self._main + self._dec) + 2, fm.height())

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        p.setFont(self._font)
        fm = p.fontMetrics()
        p.setPen(QColor(theme.TEXT))
        p.drawText(QPointF(0, fm.ascent()), self._main)
        p.setPen(QColor(theme.MUTED))
        p.drawText(QPointF(fm.horizontalAdvance(self._main), fm.ascent()), self._dec)


class DeltaLabel(QWidget):
    """Variação percentual com seta, verde se positiva e vermelha se negativa."""

    def __init__(self, px=13, parent=None):
        super().__init__(parent)
        self._font = theme.font(px, W.DemiBold)
        self._px = px
        self._value = 0.0
        self.set_value(0.0)

    def set_value(self, value: float) -> None:
        self._value = value
        fm = QFontMetrics(self._font)
        self.setFixedSize(fm.horizontalAdvance(pct(value)) + self._px + 6, fm.height())
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        color = QColor(theme.GREEN if self._value >= 0 else theme.RED)
        p.setFont(self._font)
        p.setPen(color)
        text = pct(self._value)
        p.drawText(QPointF(0, p.fontMetrics().ascent()), text)
        size = self._px - 2
        x = p.fontMetrics().horizontalAdvance(text) + 4
        p.drawPixmap(QPointF(x, (self.height() - size) / 2), icons.pixmap("arrow-up" if self._value >= 0 else "arrow-down", color, size, 2.4))


class RoundButton(QAbstractButton):
    def __init__(self, icon: str, *, size=44, icon_size=18, bg="#1B1B20", fg=theme.TEXT,
                 border=None, stroke=1.8, parent=None):
        super().__init__(parent)
        self._icon, self._icon_size, self._stroke = icon, icon_size, stroke
        self._bg, self._fg = QColor(bg), QColor(fg)
        self._border = QColor(border) if border else None
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def enterEvent(self, e) -> None:
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        p.setBrush(hover_color(self._bg) if self.underMouse() else self._bg)
        p.setPen(QPen(self._border, 1.2) if self._border else Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(self.rect()).adjusted(0.6, 0.6, -0.6, -0.6))
        pm = icons.pixmap(self._icon, self._fg, self._icon_size, self._stroke)
        p.drawPixmap(QPointF((self.width() - self._icon_size) / 2, (self.height() - self._icon_size) / 2), pm)


class PillButton(QAbstractButton):
    """Cápsula de texto; no estado marcado fica branca com texto escuro."""

    def __init__(self, text: str, *, height=38, pad=18, px=15, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self._pad = pad
        self.setFont(theme.font(px, W.Medium))
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(QFontMetrics(self.font()).horizontalAdvance(self.text()) + 2 * self._pad, self.height())

    def enterEvent(self, e) -> None:
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        on = self.isChecked()
        rect = QRectF(self.rect()).adjusted(0.6, 0.6, -0.6, -0.6)
        r = rect.height() / 2
        if on:
            p.setBrush(QColor("#FFFFFF"))
            p.setPen(Qt.PenStyle.NoPen)
        else:
            p.setBrush(QColor(255, 255, 255, 14 if self.underMouse() else 0))
            p.setPen(QPen(QColor(theme.OUTLINE), 1.2))
        p.drawRoundedRect(rect, r, r)
        p.setPen(QColor("#0A0A0C" if on else theme.TEXT))
        p.setFont(self.font())
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())


def draw_asset(p: QPainter, rect: QRectF, symbol: str) -> None:
    """Medalha circular de um ativo (USD ganha uma bandeira simplificada)."""
    path = QPainterPath()
    path.addEllipse(rect)
    p.save()
    p.setClipPath(path)
    if symbol == "USD":
        stripe = rect.height() / 7
        for i in range(7):
            p.fillRect(QRectF(rect.left(), rect.top() + i * stripe, rect.width(), stripe + 0.5),
                       QColor("#E8E8EC" if i % 2 else "#D8343B"))
        p.fillRect(QRectF(rect.left(), rect.top(), rect.width() * 0.55, stripe * 4), QColor("#2B4C9B"))
    else:
        p.fillRect(rect, QColor(theme.ASSET_COLORS.get(symbol, "#555")))
        p.setPen(QColor("white"))
        p.setFont(theme.font(max(8, int(rect.height() * 0.42)), W.Bold))
        glyph = {"ETH": "◆", "USDC": "$", "USDT": "₮", "SOL": "S", "AVAX": "A", "BNB": "B"}.get(symbol, symbol[:1])
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, glyph)
    p.restore()


class Toast(QWidget):
    """Aviso flutuante breve, centralizado na parte de baixo do pai."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._text, self._ok = "", True
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._anim.setDuration(220)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self._anim.finished.connect(lambda: self.hide() if self._fx.opacity() == 0 else None)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def show_message(self, text: str, ok: bool = True) -> None:
        self._text, self._ok = text, ok
        fm = QFontMetrics(theme.font(14, W.Medium))
        self.setFixedSize(fm.horizontalAdvance(text) + 68, 46)
        self.reposition()
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setStartValue(self._fx.opacity())
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._timer.start(2400)
        self.update()

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent:
            self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - 28)

    def _fade_out(self) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._fx.opacity())
        self._anim.setEndValue(0.0)
        self._anim.start()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(QColor("#1D1D23"))
        p.setPen(QPen(QColor("#33333B"), 1))
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        color = theme.GREEN if self._ok else theme.RED
        p.drawPixmap(QPointF(16, (self.height() - 20) / 2), icons.pixmap("check-circle" if self._ok else "alert", color, 20))
        p.setPen(QColor(theme.TEXT))
        p.setFont(theme.font(14, W.Medium))
        p.drawText(QRectF(46, 0, self.width() - 56, self.height()), Qt.AlignmentFlag.AlignVCenter, self._text)



class Switch(QAbstractButton):
    """Interruptor liga/desliga."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(46, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        on = self.isChecked()
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        track = QColor(theme.BLUE) if on else QColor("#26262D")
        p.setBrush(hover_color(track) if self.underMouse() and not on else track)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        knob = rect.height() - 6
        x = rect.right() - knob - 3 if on else rect.left() + 3
        p.setBrush(QColor("#FFFFFF" if on else "#A2A2AB"))
        p.drawEllipse(QRectF(x, rect.top() + 3, knob, knob))


class ActionButton(QAbstractButton):
    """Botão em cápsula com contorno; `danger` pinta o texto de vermelho."""

    def __init__(self, text: str, *, danger=False, primary=False, height=38, pad=18, parent=None):
        super().__init__(parent)
        self.setText(text)
        self._danger, self._primary, self._pad = danger, primary, pad
        self.setFont(theme.font(14, W.Medium))
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(QFontMetrics(self.font()).horizontalAdvance(self.text()) + 2 * self._pad, self.height())

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        rect = QRectF(self.rect()).adjusted(0.6, 0.6, -0.6, -0.6)
        hot = self.underMouse()
        if self._primary:
            p.setBrush(hover_color(QColor(theme.BLUE)) if hot else QColor(theme.BLUE))
            p.setPen(Qt.PenStyle.NoPen)
            fg = QColor("white")
        else:
            p.setBrush(QColor(255, 255, 255, 14 if hot else 0))
            p.setPen(QPen(QColor("#5A2B2B" if self._danger else theme.OUTLINE), 1.2))
            fg = QColor(theme.RED if self._danger else theme.TEXT)
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.setPen(fg)
        p.setFont(self.font())
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())
