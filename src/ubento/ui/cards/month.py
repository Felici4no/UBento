"""Cards "Resumo" e "Atividade" do mês."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QToolTip, QVBoxLayout, QWidget

from ...formatting import MONTHS, money
from .. import theme
from ..components import Card, Label, setup

W = theme.W
DAY_LETTERS = ["S", "T", "Q", "Q", "S", "S", "D"]


class SummaryRows(QWidget):
    """Três linhas com valor à direita e uma barra colorida sob o rótulo."""

    ROW = 39

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[tuple[str, str, float, str]] = []
        self.setFixedHeight(self.ROW * 3)

    def set_rows(self, rows: list[tuple[str, str, float, str]]) -> None:
        self._rows = rows
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        w = self.width()
        for i, (label, value, ratio, color) in enumerate(self._rows):
            y = i * self.ROW
            p.setFont(theme.font(15, W.Medium))
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(0, y, w, 22), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
            p.drawText(QRectF(0, y, w, 22), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, value)
            p.setBrush(QColor(color))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(0, y + 27, max(6.0, w * ratio), 3), 1.5, 1.5)


class SummaryCard(Card):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.rows = SummaryRows()
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 20)
        v.setSpacing(0)
        v.addWidget(Label("Este mês", 14, W.Normal, theme.MUTED))
        v.addWidget(Label("Resumo", 24, W.DemiBold))
        v.addStretch(1)
        v.addWidget(self.rows)
        store.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        s = self.store
        top = max(s.spent, s.income) or 1
        count = s.decisions_count()
        self.rows.set_rows([
            ("Gastos", money(s.spent).rsplit(",", 1)[0], 0.75 * math.sqrt(s.spent / top), "#EC6D58"),
            ("Receitas", money(s.income).rsplit(",", 1)[0], 0.75 * math.sqrt(s.income / top), theme.GREEN),
            ("Decisões", str(count), min(1.0, 0.75 * math.sqrt(count / 150)), theme.BLUE),
        ])


class ActivityGrid(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._weeks: list[list[tuple]] = []
        self._scale = 1.0
        self.setMouseTracking(True)
        self.setMinimumHeight(150)

    def set_weeks(self, weeks) -> None:
        self._weeks = weeks
        self.update()

    def _layout(self) -> tuple[float, float, float]:
        cols = 7
        cell_w = self.width() / cols
        rows = max(1, len(self._weeks))
        letters_h = 22.0
        cell_h = min(cell_w, (self.height() - letters_h) / rows)
        return cell_w, cell_h, letters_h

    def _radius(self, count: int | None) -> float:
        if count is None or count == 0:
            return 1.9 * self._scale
        return min(10.0, 2.6 + count * 1.15) * self._scale

    def mouseMoveEvent(self, e) -> None:
        cell_w, cell_h, _ = self._layout()
        r, c = int(e.position().y() // cell_h), int(e.position().x() // cell_w)
        if 0 <= r < len(self._weeks) and 0 <= c < 7:
            day, count = self._weeks[r][c]
            if day is not None and count is not None:
                text = f"{day.day} de {MONTHS[day.month - 1]} · {count} decis{'ão' if count == 1 else 'ões'}"
                QToolTip.showText(e.globalPosition().toPoint(), text, self)
                return
        QToolTip.hideText()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        cell_w, cell_h, _ = self._layout()
        self._scale = max(1.0, min(2.4, cell_w / 44))
        p.setPen(Qt.PenStyle.NoPen)
        for r, week in enumerate(self._weeks):
            for c, (day, count) in enumerate(week):
                if day is None:
                    continue
                cx, cy = c * cell_w + cell_w / 2, r * cell_h + cell_h / 2
                if count is None:  # dia futuro
                    p.setBrush(QColor("#24242B"))
                    p.drawEllipse(QPointF(cx, cy), 1.9, 1.9)
                    continue
                level = min(1.0, count / 8)
                color = QColor(theme.BLUE)
                color.setAlpha(int(70 + 185 * level) if count else 90)
                if count == 0:
                    color = QColor("#2B2B34")
                p.setBrush(color)
                p.drawEllipse(QPointF(cx, cy), self._radius(count), self._radius(count))
        p.setFont(theme.font(13, W.Medium))
        p.setPen(QColor(theme.DIM))
        for c, letter in enumerate(DAY_LETTERS):
            p.drawText(QRectF(c * cell_w, self.height() - 20, cell_w, 20), Qt.AlignmentFlag.AlignCenter, letter)


class ActivityCard(Card):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.grid = ActivityGrid()
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        v.setSpacing(0)
        v.addWidget(Label("Este mês", 14, W.Normal, theme.MUTED))
        v.addWidget(Label("Atividade", 24, W.DemiBold))
        v.addSpacing(8)
        v.addWidget(self.grid, 1)
        store.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self.grid.set_weeks(self.store.month_weeks())
