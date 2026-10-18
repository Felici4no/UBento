"""Camada que expande um card até ocupar a área da página, com animação."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QVBoxLayout, QWidget

from . import theme
from .components import CornerButton, Label, setup

W = theme.W
MAX_WIDTH = 940
MARGIN = (32, 8, 32, 28)  # esquerda, topo, direita, base


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


class ExpandOverlay(QWidget):
    """Escurece o fundo e faz o painel crescer da posição do card até a área toda.

    Estados: closed → opening → open → closing → closed.
    """

    collapsed = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.state = "closed"
        self._progress = 0.0
        self._from = QRectF()
        self._snapshot: QPixmap | None = None
        self._from_fn: Callable[[], QRect] | None = None
        self._body: QWidget | None = None
        self._effect: QGraphicsOpacityEffect | None = None
        self._animate = True

        self._grow = QVariantAnimation(self)
        self._grow.valueChanged.connect(self._on_progress)
        self._grow.finished.connect(self._on_grow_finished)
        self._fade: QPropertyAnimation | None = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.hide()

    # -- API ---------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self.state != "closed"

    def open(self, title: str, subtitle: str, content: QWidget, from_rect: QRect, snapshot: QPixmap,
             from_fn: Callable[[], QRect] | None = None, animate: bool = True) -> None:
        if self.is_open:
            self.collapse(animate=False)
        self._animate = animate
        self._from = QRectF(from_rect)
        self._from_fn = from_fn
        self._snapshot = snapshot
        self._build_body(title, subtitle, content)
        self.state = "opening"
        self.show()
        self.raise_()
        self.setFocus()
        self._place_body()
        if animate:
            self._body_opacity(0.0)
            self._start_grow(0.0, 1.0, QEasingCurve.Type.OutCubic, 380)
        else:
            self._progress = 1.0
            self._body_opacity(1.0)
            self.state = "open"
            self.update()

    def collapse(self, animate: bool = True) -> None:
        if self.state in ("closed", "closing"):
            return
        self._grow.stop()
        if self._fade:
            self._fade.stop()
        if not (animate and self._animate):
            self._finish_close()
            return
        self.state = "closing"
        self._start_fade(0.0, 110, then=lambda: self._start_grow(self._progress, 0.0, QEasingCurve.Type.InCubic, 280))

    # -- geometria ---------------------------------------------------------

    def target_rect(self) -> QRectF:
        l, t, r, b = MARGIN
        area = QRectF(self.rect()).adjusted(l, t, -r, -b)
        width = min(area.width(), MAX_WIDTH)
        return QRectF(area.center().x() - width / 2, area.top(), width, area.height())

    def panel_rect(self) -> QRectF:
        a, b, t = self._from, self.target_rect(), self._progress
        return QRectF(_lerp(a.x(), b.x(), t), _lerp(a.y(), b.y(), t), _lerp(a.width(), b.width(), t), _lerp(a.height(), b.height(), t))

    def _place_body(self) -> None:
        if self._body:
            self._body.setGeometry(self.target_rect().toRect())

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._place_body()
        self.update()

    # -- construção --------------------------------------------------------

    def _build_body(self, title: str, subtitle: str, content: QWidget) -> None:
        body = QWidget(self)
        close = CornerButton("arrow-down-left", "Recolher (Esc)")
        close.clicked.connect(lambda: self.collapse())
        close.setParent(body)

        heads = QVBoxLayout()
        heads.setSpacing(2)
        heads.addWidget(Label(title, 30, W.DemiBold))
        if subtitle:
            heads.addWidget(Label(subtitle, 14, W.Normal, theme.MUTED))
        top = QHBoxLayout()
        top.addLayout(heads, 1)
        top.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)

        v = QVBoxLayout(body)
        v.setContentsMargins(26, 24, 18, 26)
        v.setSpacing(18)
        v.addLayout(top)
        v.addWidget(content, 1)

        self._effect = QGraphicsOpacityEffect(body)
        body.setGraphicsEffect(self._effect)
        body.show()
        self._body = body

    def _body_opacity(self, value: float) -> None:
        if self._effect:
            self._effect.setOpacity(value)

    # -- animação ----------------------------------------------------------

    def _start_grow(self, start: float, end: float, curve: QEasingCurve.Type, ms: int) -> None:
        self._grow.stop()
        self._grow.setStartValue(start)
        self._grow.setEndValue(end)
        self._grow.setDuration(ms)
        self._grow.setEasingCurve(curve)
        self._grow.start()

    def _start_fade(self, end: float, ms: int, then: Callable[[], None] | None = None) -> None:
        if self._effect is None:
            return
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(ms)
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(end)
        if then:
            self._fade.finished.connect(then)
        self._fade.start()

    def _on_progress(self, value) -> None:
        self._progress = float(value)
        if self.state == "closing" and self._from_fn:
            self._from = QRectF(self._from_fn())  # acompanha o card se ele mudou de lugar
        self.update()

    def _on_grow_finished(self) -> None:
        if self.state == "opening":
            self.state = "open"
            self._progress = 1.0
            self._start_fade(1.0, 180)
        elif self.state == "closing":
            self._finish_close()

    def _finish_close(self) -> None:
        self.state = "closed"
        self._progress = 0.0
        if self._body:
            self._body.hide()
            self._body.deleteLater()
            self._body = None
            self._effect = None
        self._snapshot = None
        self.hide()
        self.collapsed.emit()

    # -- eventos -----------------------------------------------------------

    def mousePressEvent(self, e) -> None:
        if self.state in ("open", "opening") and not self.panel_rect().contains(e.position()):
            self.collapse()
        e.accept()

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.collapse()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _e) -> None:
        if self.state == "closed":
            return
        p = QPainter(self)
        setup(p)
        p.fillRect(self.rect(), QColor(0, 0, 0, int(170 * self._progress)))
        rect = self.panel_rect()
        path = QPainterPath()
        path.addRoundedRect(rect, 24, 24)
        p.fillPath(path, QColor(theme.CARD))
        if self._snapshot is not None and self._progress < 0.8:
            p.save()
            p.setClipPath(path)
            p.setOpacity(max(0.0, 1.0 - self._progress / 0.8))
            p.drawPixmap(rect, self._snapshot, QRectF(self._snapshot.rect()))
            p.restore()
        p.setPen(QPen(QColor("#22222A"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 24, 24)
