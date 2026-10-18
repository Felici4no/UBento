"""Card "Agentes" (aba Geral): quanto do patrimônio cada agente tem e como está indo."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QToolTip, QVBoxLayout, QWidget

from ...formatting import money, pct
from ...workspace import Workspace
from .. import icons, theme
from ..components import Card, Label, setup

W = theme.W
ROW_H = 78


def _signed_money(value: float) -> str:
    return ("+" if value >= 0 else "-") + money(abs(value))


class AgentList(QWidget):
    clicked = Signal(str)

    def __init__(self, workspace: Workspace, parent=None):
        super().__init__(parent)
        self.ws = workspace
        self.range_key = "1M"
        self._offset = 0.0
        self._hover = -1
        self.setMouseTracking(True)

    # -- dados -------------------------------------------------------------

    def rows(self) -> list[dict]:
        total = sum(a.store.total_usd() for a in self.ws.agents) or 1.0
        out = []
        for a in self.ws.agents:
            value = a.store.total_usd()
            change, delta = self.ws.performance(a, self.range_key)
            out.append({"id": a.id, "name": a.name, "color": a.color, "value": value, "share": value / total, "change": change, "delta": delta})
        return out

    def _max_offset(self) -> float:
        return max(0.0, len(self.ws.agents) * ROW_H - (self.height() - 14) + 8)

    # -- interação ---------------------------------------------------------

    def wheelEvent(self, e) -> None:
        self._offset = min(self._max_offset(), max(0.0, self._offset - e.angleDelta().y() / 2))
        self.update()

    def _index_at(self, y: float) -> int:
        i = int((y - 14 + self._offset) // ROW_H)
        return i if 0 <= i < len(self.ws.agents) and y >= 14 else -1

    def mouseMoveEvent(self, e) -> None:
        self._hover = self._index_at(e.position().y())
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._hover >= 0 else Qt.CursorShape.ArrowCursor)
        self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            i = self._index_at(e.position().y())
            if i >= 0:
                self.clicked.emit(self.ws.agents[i].id)

    def leaveEvent(self, _e) -> None:
        self._hover = -1
        self.update()

    # -- desenho -----------------------------------------------------------

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        w = self.width()
        for i, r in enumerate(self.rows()):
            y = 14 + i * ROW_H - self._offset
            if y + ROW_H < 0 or y > self.height():
                continue
            self._paint_row(p, r, y, w, hovered=i == self._hover)
        fade = QLinearGradient(0, self.height() - 60, 0, self.height())
        fade.setColorAt(0, QColor(6, 6, 8, 0))
        fade.setColorAt(1, QColor(theme.CARD))
        if self._max_offset() - self._offset > 1:
            p.fillRect(QRectF(0, self.height() - 60, w, 60), fade)

    def _paint_row(self, p: QPainter, r: dict, y: float, w: int, hovered: bool) -> None:
        if hovered:
            p.setBrush(QColor(255, 255, 255, 10))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(-8, y - 6, w + 16, ROW_H - 4), 14, 14)
        color = QColor(r["color"])

        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(5, y + 12), 5, 5)
        p.setPen(QColor(theme.TEXT))
        p.setFont(theme.font(16, W.Medium))
        name = p.fontMetrics().elidedText(r["name"], Qt.TextElideMode.ElideRight, int(w * 0.5))
        p.drawText(QRectF(20, y, w * 0.55, 24), Qt.AlignmentFlag.AlignVCenter, name)
        p.drawText(QRectF(0, y, w, 24), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, money(r["value"]))

        track = QRectF(0, y + 33, w, 5)
        p.setBrush(QColor("#17171C"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(track, 2.5, 2.5)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(0, track.y(), max(5.0, w * r["share"]), 5), 2.5, 2.5)

        p.setFont(theme.font(13, W.Normal))
        p.setPen(QColor(theme.MUTED))
        p.drawText(QRectF(0, y + 44, w * 0.5, 20), Qt.AlignmentFlag.AlignVCenter, f"{pct(r['share'] * 100)} do patrimônio")

        up = r["change"] >= 0
        good = QColor(theme.GREEN if up else theme.RED)
        delta_text = _signed_money(r["delta"])
        fm = p.fontMetrics()
        delta_w = fm.horizontalAdvance(delta_text)
        p.setPen(QColor(theme.MUTED))
        p.drawText(QRectF(w - delta_w - 2, y + 44, delta_w + 4, 20), Qt.AlignmentFlag.AlignVCenter, delta_text)
        p.setFont(theme.font(13, W.DemiBold))
        pct_text = pct(r["change"])
        pw = p.fontMetrics().horizontalAdvance(pct_text)
        px = w - delta_w - 14 - pw
        p.setPen(good)
        p.drawText(QRectF(px, y + 44, pw + 4, 20), Qt.AlignmentFlag.AlignVCenter, pct_text)
        p.drawPixmap(QPointF(px - 16, y + 48), icons.pixmap("arrow-up" if up else "arrow-down", good, 12, 2.4))


class AgentsCard(Card):
    agent_clicked = Signal(str)

    def __init__(self, workspace: Workspace, parent=None):
        super().__init__(parent)
        self.ws = workspace
        self.subtitle = Label("", 14, W.Normal, theme.MUTED)
        self.period = Label("", 13, W.Medium, theme.MUTED)
        self.alloc = _ShareBar(workspace)
        self.list = AgentList(workspace)
        self.list.clicked.connect(self.agent_clicked)

        head = QHBoxLayout()
        head.addWidget(Label("Agentes", 26, W.DemiBold))
        head.addStretch()
        head.addWidget(self.period, 0, Qt.AlignmentFlag.AlignBottom)

        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 0)
        v.setSpacing(0)
        v.addLayout(head)
        v.addWidget(self.subtitle)
        v.addSpacing(16)
        v.addWidget(self.alloc)
        v.addSpacing(4)
        v.addWidget(self.list, 1)
        self.set_range("1M")
        self.refresh()

    def set_range(self, key: str) -> None:
        self.list.range_key = key
        self.period.setText(f"Variação · {key}")
        self.list.update()

    def refresh(self) -> None:
        rows = self.list.rows()
        if rows:
            best = max(rows, key=lambda r: r["change"])
            self.subtitle.setText(f"{len(rows)} agentes · melhor: {best['name']} {'+' if best['change'] >= 0 else '-'}{pct(best['change'])}")
        else:
            self.subtitle.setText("Nenhum agente")
        self.alloc.update()
        self.list.update()


class _ShareBar(QWidget):
    """Barra segmentada com a fatia de cada agente no patrimônio."""

    def __init__(self, workspace: Workspace, parent=None):
        super().__init__(parent)
        self.ws = workspace
        self._hover = -1
        self.setFixedHeight(12)
        self.setMouseTracking(True)

    def _segments(self):
        agents = self.ws.agents
        total = sum(a.store.total_usd() for a in agents) or 1.0
        gap = 5.0
        usable = self.width() - gap * max(0, len(agents) - 1)
        x, out = 0.0, []
        for a in agents:
            share = a.store.total_usd() / total
            out.append((a, share, QRectF(x, 3, max(6.0, usable * share), 6)))
            x += max(6.0, usable * share) + gap
        return out

    def mouseMoveEvent(self, e) -> None:
        for i, (a, share, rect) in enumerate(self._segments()):
            if rect.adjusted(-3, -6, 3, 6).contains(e.position()):
                self._hover = i
                QToolTip.showText(e.globalPosition().toPoint(), f"{a.name} · {pct(share * 100)}", self)
                self.update()
                return
        self._hover = -1
        QToolTip.hideText()
        self.update()

    def leaveEvent(self, _e) -> None:
        self._hover = -1
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        for i, (a, _, rect) in enumerate(self._segments()):
            c = QColor(a.color)
            if self._hover >= 0 and i != self._hover:
                c.setAlpha(90)
            p.setPen(QPen(c, 6 if i != self._hover else 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(rect.left() + 3, 6), QPointF(rect.right() - 3, 6))
