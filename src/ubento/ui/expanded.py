"""Conteúdo das visões expandidas: uma função por card, devolvendo (título, subtítulo, widget)."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from ..formatting import amount, is_hidden, money, number, pct, short_date
from ..store import ASSETS, RANGES
from . import theme
from .cards.agents import AgentList
from .cards.coin import Sparkline
from .cards.decisions import KIND_LABELS, DecisionList
from .cards.month import ActivityGrid
from .cards.total import BarChart
from .components import DeltaLabel, Label, MoneyText, PillButton, StatTile, draw_asset, setup

W = theme.W
EXPAND_KINDS = ("crypto", "total", "summary", "activity", "decisions", "agents", "coin")


def _tiles(tiles: list[StatTile], columns: int | None = None) -> QWidget:
    box = QWidget()
    grid = QGridLayout(box)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(12)
    columns = columns or len(tiles)
    for i, tile in enumerate(tiles):
        grid.addWidget(tile, i // columns, i % columns)
    return box


def _signed(value: float) -> str:
    return ("+" if value >= 0 else "-") + money(abs(value))


def _color(value: float) -> str:
    return theme.GREEN if value >= 0 else theme.RED


def _pills(keys: list[str], current: str | None, on_pick, labels: dict[str, str] | None = None) -> QWidget:
    box = QWidget()
    h = QHBoxLayout(box)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(8)
    group = QButtonGroup(box)
    group.setExclusive(True)
    for key in keys:
        btn = PillButton((labels or {}).get(key, key), height=36, pad=16, px=14)
        btn.setChecked(key == current)
        btn.clicked.connect(lambda _=False, k=key: on_pick(k))
        group.addButton(btn)
        h.addWidget(btn)
    h.addStretch(1)
    return box


# -- cripto ------------------------------------------------------------------------


class AssetTable(QWidget):
    ROW = 62

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setMinimumHeight(30 + self.ROW * 4)

    def rows(self) -> list[tuple[str, float, float, float, float]]:
        total = self.store.total_usd() or 1.0
        out = []
        for sym, qty in self.store.holdings.items():
            if qty > 0:
                price = ASSETS[sym].price
                out.append((sym, qty, price, qty * price, qty * price / total))
        return sorted(out, key=lambda r: r[3], reverse=True)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        w = self.width()
        right = {"qty": w * 0.40, "price": w * 0.56, "value": w * 0.75}
        p.setFont(theme.font(12, W.DemiBold))
        p.setPen(QColor(theme.DIM))
        p.drawText(QRectF(0, 0, 200, 28), Qt.AlignmentFlag.AlignVCenter, "ATIVO")
        for key, label in (("qty", "QUANTIDADE"), ("price", "PREÇO"), ("value", "VALOR")):
            p.drawText(QRectF(right[key] - 140, 0, 140, 28), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, label)
        p.drawText(QRectF(w * 0.79, 0, 200, 28), Qt.AlignmentFlag.AlignVCenter, "PARTICIPAÇÃO")

        for i, (sym, qty, price, value, share) in enumerate(self.rows()):
            y = 30 + i * self.ROW
            p.setPen(QColor(theme.LINE))
            p.drawLine(0, int(y), w, int(y))
            draw_asset(p, QRectF(0, y + (self.ROW - 34) / 2, 34, 34), sym)
            p.setPen(QColor(theme.TEXT))
            p.setFont(theme.font(16, W.Medium))
            p.drawText(QRectF(48, y + 10, 160, 22), Qt.AlignmentFlag.AlignVCenter, sym)
            p.setPen(QColor(theme.MUTED))
            p.setFont(theme.font(12, W.Normal))
            p.drawText(QRectF(48, y + 32, 160, 18), Qt.AlignmentFlag.AlignVCenter, ASSETS[sym].name)

            p.setFont(theme.font(15, W.Medium))
            cells = {"qty": amount(qty, ASSETS[sym].decimals), "price": f"${number(price, 2)}", "value": money(value)}
            for key, text in cells.items():
                p.setPen(QColor(theme.TEXT if key == "value" else theme.MUTED))
                p.drawText(QRectF(right[key] - 140, y, 140, self.ROW), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, text)

            bar_x, bar_w = w * 0.79, w * 0.21 - 58
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#17171C"))
            p.drawRoundedRect(QRectF(bar_x, y + self.ROW / 2 - 3, bar_w, 6), 3, 3)
            p.setBrush(QColor(theme.ASSET_COLORS.get(sym, theme.BLUE)))
            p.drawRoundedRect(QRectF(bar_x, y + self.ROW / 2 - 3, max(6.0, bar_w * share), 6), 3, 3)
            p.setPen(QColor(theme.TEXT))
            p.setFont(theme.font(14, W.Medium))
            p.drawText(QRectF(w - 52, y, 52, self.ROW), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, pct(share * 100))


def crypto_view(dash, _ws):
    store = dash.store
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(10)
    top = QHBoxLayout()
    total = MoneyText(36)
    total.set_amount(store.crypto_total())
    delta = DeltaLabel(14)
    delta.set_value(store.crypto_change)
    top.addWidget(total)
    top.addWidget(delta, 0, Qt.AlignmentFlag.AlignBottom)
    top.addStretch(1)
    v.addLayout(top)
    v.addWidget(AssetTable(store), 1)
    return "Saldo em cripto", "Posição por ativo, com cotação atual", box


# -- saldo total ------------------------------------------------------------------------


class TotalExpanded(QWidget):
    def __init__(self, store, range_key: str, parent=None):
        super().__init__(parent)
        self.store, self.range_key = store, range_key
        self.total, self.delta, self.chart = MoneyText(36), DeltaLabel(14), BarChart()
        self.tiles = [StatTile("Início do período", ""), StatTile("Máxima", ""), StatTile("Mínima", ""), StatTile("Variação", "")]
        self.chart.setMinimumHeight(260)

        head = QHBoxLayout()
        head.addWidget(self.total)
        head.addWidget(self.delta, 0, Qt.AlignmentFlag.AlignBottom)
        head.addStretch(1)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)
        v.addLayout(head)
        v.addWidget(_pills(list(RANGES), range_key, self.set_range))
        v.addWidget(self.chart, 1)
        v.addWidget(_tiles(self.tiles))
        self.refresh(animate=False)

    def set_range(self, key: str) -> None:
        self.range_key = key
        self.refresh(animate=True)

    def refresh(self, animate: bool) -> None:
        points = self.store.history(self.range_key)
        values = [v for _, v in points]
        first, last = values[0], values[-1]
        self.total.set_amount(last)
        self.delta.set_value((last / first - 1) * 100 if first else 0.0)
        self.chart.set_points(points, with_year=self.range_key in ("1A", "Tudo"), animate=animate)
        hi, lo = max(values), min(values)
        hi_day = points[values.index(hi)][0]
        lo_day = points[values.index(lo)][0]
        self.tiles[0].value.setText(money(first))
        self.tiles[1].value.setText(money(hi))
        self.tiles[2].value.setText(money(lo))
        self.tiles[3].value.setText(_signed(last - first))
        self.tiles[3].value.set_color(_color(last - first))
        self.tiles[1].setToolTip(short_date(hi_day, True))
        self.tiles[2].setToolTip(short_date(lo_day, True))


def total_view(dash, _ws):
    return "Saldo total", "Evolução do patrimônio no período", TotalExpanded(dash.store, dash.total.range_key)


# -- resumo ------------------------------------------------------------------------------


class CompareBars(QWidget):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setMinimumHeight(110)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        top = max(self.store.income, self.store.spent, 1.0)
        for i, (label, value, color) in enumerate((("Receitas", self.store.income, theme.GREEN), ("Gastos", self.store.spent, "#EC6D58"))):
            y = i * 54
            p.setFont(theme.font(14, W.Medium))
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(0, y, 140, 24), Qt.AlignmentFlag.AlignVCenter, label)
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(0, y, self.width(), 24), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, money(value))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#17171C"))
            p.drawRoundedRect(QRectF(0, y + 30, self.width(), 10), 5, 5)
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(0, y + 30, max(10.0, self.width() * value / top), 10), 5, 5)


def summary_view(dash, _ws):
    s = dash.store
    net = s.income - s.spent
    rate = net / s.income * 100 if s.income else 0.0
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(18)
    v.addWidget(_tiles([
        StatTile("Receitas", money(s.income), theme.GREEN),
        StatTile("Gastos", money(s.spent), "#EC6D58"),
        StatTile("Resultado do mês", _signed(net), _color(net)),
        StatTile("Taxa de poupança", "••" if is_hidden() else pct(rate), _color(rate)),
    ], columns=2))
    v.addWidget(CompareBars(s))
    v.addWidget(_tiles([StatTile("Decisões no mês", str(s.decisions_count()))], columns=1))
    v.addStretch(1)
    return "Resumo do mês", "Entradas, saídas e quanto sobrou", box


# -- atividade -----------------------------------------------------------------------------


def activity_view(dash, _ws):
    s = dash.store
    counts = {d: c for d, c in s.activity.items()}
    active = sum(1 for c in counts.values() if c > 0)
    total = sum(counts.values())
    best_day, best = max(counts.items(), key=lambda kv: kv[1], default=(None, 0))
    grid = ActivityGrid()
    grid.set_weeks(s.month_weeks())
    grid.setMinimumHeight(330)
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(18)
    v.addWidget(grid, 1)
    v.addWidget(_tiles([
        StatTile("Dias com decisões", str(active)),
        StatTile("Decisões no mês", str(total)),
        StatTile("Média por dia ativo", number(total / active, 1) if active else "0"),
        StatTile("Dia mais intenso", f"{short_date(best_day)} · {best}" if best_day else "—"),
    ]))
    return "Atividade do mês", "Decisões por dia · passe o mouse para ver os detalhes", box


# -- decisões --------------------------------------------------------------------------------


def decisions_view(dash, ws):
    store = dash.store
    lookup = (lambda i: (a.name, a.color) if (a := ws.agent(i)) else None) if store.readonly else None
    lst = DecisionList(store, lookup)
    lst.setMinimumHeight(360)
    kinds = ["all", *KIND_LABELS]
    labels = {"all": "Todas", **KIND_LABELS}
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(14)
    v.addWidget(_pills(kinds, "all", lambda k: lst.set_filter(None if k == "all" else k), labels))
    v.addWidget(lst, 1)
    return "Decisões", f"{len(store.decisions)} decisões registradas", box


# -- agentes ------------------------------------------------------------------------------------


def agents_view(dash, ws):
    lst = AgentList(ws, detailed=True)
    lst.range_key = dash.total.range_key
    lst.setMinimumHeight(300)
    lst.clicked.connect(dash.open_agent)  # abrir um agente fecha a visão expandida
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(14)
    v.addWidget(Label("Variação no período", 13, W.Normal, theme.MUTED))

    def pick(key: str) -> None:
        lst.range_key = key
        lst.update()

    v.addWidget(_pills(list(RANGES), lst.range_key, pick))
    v.addWidget(lst, 1)
    return "Agentes", "Clique num agente para abrir a aba dele", box


# -- moeda (USDC) --------------------------------------------------------------------------------


def coin_view(dash, _ws):
    s = dash.store
    series = s.usdc_series()
    spark = Sparkline()
    spark.set_values(series)
    spark.setMinimumHeight(300)
    held = s.holdings.get("USDC", 0.0)
    price = ASSETS["USDC"].price
    change = (series[-1] / series[0] - 1) * 100
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(18)
    v.addWidget(spark, 1)
    v.addWidget(_tiles([
        StatTile("Cotação", f"1 USDC = ${number(price, 3)}"),
        StatTile("Variação", ("↑ " if change >= 0 else "↓ ") + pct(change), _color(change)),
        StatTile("Máxima", f"${number(max(series), 4)}"),
        StatTile("Mínima", f"${number(min(series), 4)}"),
    ]))
    v.addWidget(_tiles([
        StatTile("Seu saldo", f"{amount(held, 2)} USDC"),
        StatTile("Valor em dólar", money(held * price)),
    ], columns=2))
    return "USD Coin", "Cotação em relação ao dólar", box


BUILDERS = {
    "crypto": crypto_view, "total": total_view, "summary": summary_view, "activity": activity_view,
    "decisions": decisions_view, "agents": agents_view, "coin": coin_view,
}


def build(kind: str, dash, workspace) -> tuple[str, str, QWidget]:
    return BUILDERS[kind](dash, workspace)

