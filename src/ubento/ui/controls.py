"""Controles de formulário usados nas telas de configuração (slider, opções, chips)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from . import icons, theme
from .components import draw_asset, setup

W = theme.W


class ValueSlider(QWidget):
    """Controle deslizante com passos; mostra o valor à direita."""

    valueChanged = Signal(int)

    def __init__(self, minimum: int, maximum: int, step: int = 1, suffix: str = "", labels: dict[int, str] | None = None, parent=None):
        super().__init__(parent)
        self._min, self._max, self._step = minimum, maximum, step
        self._suffix, self._labels = suffix, labels or {}
        self._value = minimum
        self.setFixedSize(300, 34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def value(self) -> int:
        return self._value

    def set_value(self, value: int) -> None:
        """Atualiza sem emitir sinal (usado ao refletir o estado do agente na tela)."""
        steps = round((value - self._min) / self._step)
        self._value = max(self._min, min(self._max, self._min + steps * self._step))
        self.update()

    def _text(self, value: int) -> str:
        return self._labels.get(value, f"{value}{self._suffix}")

    def _label_width(self) -> int:
        longest = max((self._text(v) for v in (self._min, self._max, *self._labels)), key=len)
        return QFontMetrics(theme.font(14, W.Medium)).horizontalAdvance(longest) + 20

    def _track(self) -> QRectF:
        return QRectF(8, self.height() / 2 - 2, self.width() - 16 - self._label_width(), 4)

    def _from_x(self, x: float) -> int:
        track = self._track()
        ratio = max(0.0, min(1.0, (x - track.left()) / track.width()))
        steps = round(ratio * (self._max - self._min) / self._step)
        return self._min + steps * self._step

    def _commit(self, value: int) -> None:
        value = max(self._min, min(self._max, value))
        if value != self._value:
            self._value = value
            self.update()
            self.valueChanged.emit(value)

    def mousePressEvent(self, e) -> None:
        self.setFocus()
        self._commit(self._from_x(e.position().x()))

    def mouseMoveEvent(self, e) -> None:
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._commit(self._from_x(e.position().x()))

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Down):
            self._commit(self._value - self._step)
        elif e.key() in (Qt.Key.Key_Right, Qt.Key.Key_Up):
            self._commit(self._value + self._step)
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        track = self._track()
        ratio = (self._value - self._min) / (self._max - self._min)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#22222A"))
        p.drawRoundedRect(track, 2, 2)
        p.setBrush(QColor(theme.BLUE))
        p.drawRoundedRect(QRectF(track.left(), track.top(), track.width() * ratio, track.height()), 2, 2)
        cx = track.left() + track.width() * ratio
        if self.hasFocus():
            p.setBrush(QColor(59, 107, 255, 70))
            p.drawEllipse(QPointF(cx, track.center().y()), 12, 12)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QPointF(cx, track.center().y()), 8, 8)
        p.setPen(QColor(theme.TEXT))
        p.setFont(theme.font(14, W.Medium))
        width = self._label_width()
        p.drawText(QRectF(self.width() - width, 0, width, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self._text(self._value))


class OptionCard(QAbstractButton):
    """Opção selecionável com ícone, nome e descrição (escolha do algoritmo)."""

    def __init__(self, key: str, icon: str, title: str, description: str, parent=None):
        super().__init__(parent)
        self.key, self._icon, self._title, self._desc = key, icon, title, description
        self.setCheckable(True)
        self.setMinimumHeight(96)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        on, hot = self.isChecked(), self.underMouse()
        rect = QRectF(self.rect()).adjusted(0.8, 0.8, -0.8, -0.8)
        p.setBrush(QColor(59, 107, 255, 28) if on else QColor(255, 255, 255, 10 if hot else 0))
        p.setPen(QPen(QColor(theme.BLUE) if on else QColor(theme.PANEL_EDGE), 1.6 if on else 1.2))
        p.drawRoundedRect(rect, 16, 16)
        p.setBrush(QColor(theme.BLUE) if on else QColor("#16161C"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(rect.left() + 14, rect.top() + 14, 36, 36))
        p.drawPixmap(QPointF(rect.left() + 23, rect.top() + 23), icons.pixmap(self._icon, "white" if on else theme.MUTED, 18, 1.9))
        p.setPen(QColor(theme.TEXT))
        p.setFont(theme.font(16, W.Medium))
        p.drawText(QRectF(rect.left() + 62, rect.top() + 12, rect.width() - 74, 24), Qt.AlignmentFlag.AlignVCenter, self._title)
        p.setPen(QColor(theme.MUTED))
        p.setFont(theme.font(12, W.Normal))
        p.drawText(QRectF(rect.left() + 62, rect.top() + 38, rect.width() - 74, rect.height() - 44),
                   Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, self._desc)


class ToggleChip(QAbstractButton):
    """Chip liga/desliga com a medalha do ativo (ativos permitidos)."""

    def __init__(self, symbol: str, parent=None):
        super().__init__(parent)
        self.symbol = symbol
        self.setText(symbol)
        self.setCheckable(True)
        self.setFont(theme.font(14, W.Medium))
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(QFontMetrics(self.font()).horizontalAdvance(self.symbol) + 62, 40)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        on = self.isChecked()
        rect = QRectF(self.rect()).adjusted(0.8, 0.8, -0.8, -0.8)
        p.setBrush(QColor(59, 107, 255, 28) if on else QColor(255, 255, 255, 12 if self.underMouse() else 0))
        p.setPen(QPen(QColor(theme.BLUE) if on else QColor(theme.OUTLINE), 1.4))
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.setOpacity(1.0 if on else 0.45)
        draw_asset(p, QRectF(rect.left() + 8, rect.center().y() - 11, 22, 22), self.symbol)
        p.setPen(QColor(theme.TEXT if on else theme.MUTED))
        p.setFont(self.font())
        p.drawText(QRectF(rect.left() + 38, rect.top(), rect.width() - 44, rect.height()), Qt.AlignmentFlag.AlignVCenter, self.symbol)


class ColorSwatches(QWidget):
    picked = Signal(str)

    def __init__(self, colors: list[str], parent=None):
        super().__init__(parent)
        self._colors, self._current = colors, colors[0]
        self.setFixedSize(len(colors) * 34, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_current(self, color: str) -> None:
        self._current = color
        self.update()

    def mousePressEvent(self, e) -> None:
        i = int(e.position().x() // 34)
        if 0 <= i < len(self._colors):
            self._current = self._colors[i]
            self.update()
            self.picked.emit(self._colors[i])

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        for i, c in enumerate(self._colors):
            center = QPointF(i * 34 + 16, 16)
            if c.lower() == self._current.lower():
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor("#FFFFFF"), 2))
                p.drawEllipse(center, 14, 14)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(c))
            p.drawEllipse(center, 10, 10)


class Chip(QWidget):
    """Etiqueta pequena (estratégia, risco, status) com ponto colorido opcional."""

    def __init__(self, text="", dot: str | None = None, parent=None):
        super().__init__(parent)
        self._font = theme.font(12, W.Medium)
        self._text, self._dot = text, dot
        self.setFixedHeight(28)
        self.set_chip(text, dot)

    def set_chip(self, text: str, dot: str | None = None) -> None:
        self._text, self._dot = text, dot
        self.setFixedWidth(QFontMetrics(self._font).horizontalAdvance(text) + 24 + (14 if dot else 0))
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        rect = QRectF(self.rect()).adjusted(0.6, 0.6, -0.6, -0.6)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(theme.OUTLINE), 1.2))
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        x = 12.0
        if self._dot:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self._dot))
            p.drawEllipse(QPointF(x + 3, rect.center().y()), 3.5, 3.5)
            x += 14
        p.setPen(QColor(theme.MUTED))
        p.setFont(self._font)
        p.drawText(QRectF(x, 0, rect.width(), self.height()), Qt.AlignmentFlag.AlignVCenter, self._text)
