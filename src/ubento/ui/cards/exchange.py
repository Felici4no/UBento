"""Card "Trocar": converte entre moedas com cotação, taxas e saldo em tempo real."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QRegularExpression, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QLinearGradient, QPainter, QPen, QRegularExpressionValidator
from PySide6.QtWidgets import QAbstractButton, QFrame, QHBoxLayout, QLineEdit, QMenu, QVBoxLayout, QWidget

from ...formatting import amount, money, number
from ...store import ASSETS, Store
from .. import icons, theme
from ..components import Card, Label, RoundButton, draw_asset, hover_color, setup

W = theme.W
DEFAULT_AMOUNT = "488,34"


def parse_amount(text: str) -> float:
    try:
        return float(text.replace(",", ".")) if text else 0.0
    except ValueError:
        return 0.0


class AssetSelector(QAbstractButton):
    selected = Signal(str)

    def __init__(self, symbol: str, store: Store, parent=None):
        super().__init__(parent)
        self.symbol = symbol
        self._store = store
        self.setFont(theme.font(24, W.Medium))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(40)
        self.clicked.connect(self._open_menu)
        self.set_symbol(symbol)

    def set_symbol(self, symbol: str) -> None:
        self.symbol = symbol
        self.setFixedWidth(QFontMetrics(self.font()).horizontalAdvance(symbol) + 16 + 12 + 34 + 10)
        self.update()

    def _open_menu(self) -> None:
        menu = QMenu(self)
        for sym, asset in ASSETS.items():
            held = self._store.holdings.get(sym, 0.0)
            menu.addAction(f"{sym}  ·  {asset.name}  ·  {amount(held, asset.decimals)}").setData(sym)
        chosen = menu.exec(self.mapToGlobal(self.rect().bottomRight()) - QPointF(220, 0).toPoint())
        if chosen:
            self.selected.emit(chosen.data())

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        p.setPen(QPen(QColor(theme.MUTED if not self.underMouse() else theme.TEXT), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPixmap(QPointF(0, (self.height() - 14) / 2), icons.pixmap("chevron-down", theme.MUTED, 14, 2.2))
        p.setFont(self.font())
        p.setPen(QColor(theme.TEXT))
        text_x = 22
        tw = p.fontMetrics().horizontalAdvance(self.symbol)
        p.drawText(QRectF(text_x, 0, tw + 4, self.height()), Qt.AlignmentFlag.AlignVCenter, self.symbol)
        draw_asset(p, QRectF(text_x + tw + 12, (self.height() - 28) / 2, 28, 28), self.symbol)

    def enterEvent(self, e) -> None:
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self.update()
        super().leaveEvent(e)


class AmountPanel(QFrame):
    def __init__(self, title: str, store: Store, symbol: str, editable: bool, parent=None):
        super().__init__(parent)
        self.store = store
        self.selector = AssetSelector(symbol, store)
        self.title = Label(title, 13, W.Normal, theme.MUTED)
        self.avail_label = Label("Disponível", 13, W.Normal, theme.MUTED)
        self.avail_value = Label("", 13, W.Medium, theme.TEXT)

        if editable:
            self.input = QLineEdit()
            self.input.setValidator(QRegularExpressionValidator(QRegularExpression(r"^\d{0,9}([.,]\d{0,8})?$")))
            self.input.setPlaceholderText("0,00")
            self.input.setStyleSheet(
                f"QLineEdit {{ background: transparent; border: none; color: {theme.TEXT};"
                f" font-size: 30px; font-weight: 500; selection-background-color: {theme.BLUE}; }}"
                f"QLineEdit::placeholder {{ color: {theme.DIM}; }}"
            )
            self.input.setFont(theme.font(30, W.Medium))
            self.out = None
        else:
            self.input = None
            self.out = Label("0", 30, W.Medium)

        top = QHBoxLayout()
        top.addWidget(self.title)
        top.addStretch()
        top.addWidget(self.avail_label)
        top.addWidget(self.avail_value)
        bottom = QHBoxLayout()
        bottom.addWidget(self.input or self.out, 1)
        bottom.addWidget(self.selector)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 10)
        v.setSpacing(2)
        v.addLayout(top)
        v.addLayout(bottom)
        self.setMinimumHeight(88)

    def set_available(self, symbol: str, value: float) -> None:
        decimals = ASSETS[symbol].decimals
        self.avail_value.setText(money(value) if symbol == "USD" else f"{amount(value, decimals)} {symbol}")

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(QColor(theme.PANEL))
        p.setPen(QPen(QColor(theme.PANEL_EDGE), 1))
        p.drawRoundedRect(rect, 18, 18)


class SwapButton(RoundButton):
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setBrush(hover_color(QColor("#1C1C22")) if self.underMouse() else QColor("#1C1C22"))
        p.setPen(QPen(QColor("#050507"), 3))
        p.drawRoundedRect(rect, 10, 10)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPixmap(QPointF((self.width() - 18) / 2, (self.height() - 18) / 2), icons.pixmap("swap", theme.TEXT, 18, 2.0))


class _Divider(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.LINE))


class ExchangeButton(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._reason: str | None = None
        self.setFont(theme.font(18, W.DemiBold))
        self.setFixedHeight(60)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_reason(self, reason: str | None) -> None:
        self._reason = reason
        self.setCursor(Qt.CursorShape.ForbiddenCursor if reason else Qt.CursorShape.PointingHandCursor)
        self.update()

    def enterEvent(self, e) -> None:
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self._reason:
            p.setBrush(QColor("#16161B"))
            p.setPen(QPen(QColor("#202027"), 1))
            p.drawRoundedRect(rect, 20, 20)
            p.setPen(QColor(theme.MUTED))
            label = self._reason
        else:
            g = QLinearGradient(0, rect.top(), 0, rect.bottom())
            top = QColor("#5B87FF")
            bottom = QColor("#3A66F2")
            if self.underMouse():
                top, bottom = top.lighter(108), bottom.lighter(108)
            if self.isDown():
                top, bottom = top.darker(110), bottom.darker(110)
            g.setColorAt(0, top)
            g.setColorAt(1, bottom)
            p.setBrush(g)
            p.setPen(QPen(QColor(255, 255, 255, 40), 1))
            p.drawRoundedRect(rect, 20, 20)
            p.setPen(QColor("white"))
            label = "Swap"
        p.setFont(self.font())
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)


class ExchangeCard(Card):
    notify = Signal(str, bool)

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.send_panel = AmountPanel("Você envia", store, "USD", editable=True)
        self.recv_panel = AmountPanel("Você recebe", store, "ETH", editable=False)
        self.swap = SwapButton("swap", size=36)
        self.swap.setParent(self)
        self.send_panel.input.setText(DEFAULT_AMOUNT)
        self.rate = Label("", 14, W.Medium)
        self.service = Label("", 14, W.Medium)
        self.gas = Label("", 14, W.Medium)
        self.button = ExchangeButton()

        self.send_panel.input.textChanged.connect(self.refresh)
        self.send_panel.selector.selected.connect(lambda s: self._pick("send", s))
        self.recv_panel.selector.selected.connect(lambda s: self._pick("receive", s))
        self.swap.clicked.connect(self.swap_sides)
        self.button.clicked.connect(self._submit)
        store.changed.connect(self.refresh)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 20, 18, 18)
        v.setSpacing(0)
        v.addWidget(Label("Swap", 26, W.DemiBold), 0, Qt.AlignmentFlag.AlignLeft)
        v.addSpacing(8)
        v.addWidget(self.send_panel)
        v.addSpacing(6)
        v.addWidget(self.recv_panel)
        v.addSpacing(14)
        v.addWidget(_Divider())
        v.addSpacing(10)
        for text, value in (("Cotação", self.rate), ("Taxa de serviço", self.service), ("Taxa de rede (gas)", self.gas)):
            row = QHBoxLayout()
            row.setContentsMargins(4, 0, 4, 0)
            row.addWidget(Label(text, 14, W.Normal, theme.MUTED))
            row.addStretch()
            row.addWidget(value)
            v.addLayout(row)
            v.addSpacing(10)
        v.addWidget(_Divider())
        v.addStretch(1)
        v.addSpacing(10)
        v.addWidget(self.button)
        self.refresh()

    # -- estado ------------------------------------------------------------

    @property
    def send(self) -> str:
        return self.send_panel.selector.symbol

    @property
    def receive(self) -> str:
        return self.recv_panel.selector.symbol

    def amount(self) -> float:
        return parse_amount(self.send_panel.input.text())

    def prefill(self, send: str, receive: str) -> None:
        """Usado por atalhos de outros cards (ex.: botão + do USDC)."""
        self.send_panel.selector.set_symbol(send)
        self.recv_panel.selector.set_symbol(receive)
        self.refresh()
        self.send_panel.input.setFocus()
        self.send_panel.input.selectAll()

    def _pick(self, side: str, symbol: str) -> None:
        mine, other = (self.send_panel, self.recv_panel) if side == "send" else (self.recv_panel, self.send_panel)
        if symbol == other.selector.symbol:  # escolher a moeda do outro lado inverte
            other.selector.set_symbol(mine.selector.symbol)
        mine.selector.set_symbol(symbol)
        self.refresh()

    def swap_sides(self) -> None:
        a, b = self.send, self.receive
        quote = self.store.quote(a, b, self.amount())
        self.send_panel.selector.set_symbol(b)
        self.recv_panel.selector.set_symbol(a)
        if quote.receive_amount > 0:  # leva o valor recebido para o campo de envio
            self.send_panel.input.setText(number(quote.receive_amount, ASSETS[b].decimals).replace(".", ""))
        self.refresh()

    def refresh(self) -> None:
        send, receive = self.send, self.receive
        q = self.store.quote(send, receive, self.amount())
        self.send_panel.set_available(send, self.store.holdings.get(send, 0.0))
        self.recv_panel.set_available(receive, self.store.holdings.get(receive, 0.0))
        self.recv_panel.out.setText(number(q.receive_amount, ASSETS[receive].decimals))
        self.rate.setText(f"1 {receive} = {number(q.rate, 2 if q.rate >= 1 else 6)} {send}")
        self.service.setText(f"{number(q.service_fee_usd, 2)} USD")
        self.gas.setText(f"{number(q.gas_fee_usd, 2)} USD")
        self.button.set_reason(self.store.validate(send, receive, self.amount()))
        self.button.update()

    def _submit(self) -> None:
        send, receive, amount = self.send, self.receive, self.amount()
        problem = self.store.execute(send, receive, amount)
        if problem:
            self.notify.emit(problem, False)
            return
        self.notify.emit(f"Swap de {send} para {receive} concluído", True)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._place_swap()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._place_swap()

    def _place_swap(self) -> None:
        gap_y = (self.send_panel.geometry().bottom() + self.recv_panel.geometry().top()) // 2
        self.swap.move((self.width() - self.swap.width()) // 2, gap_y - self.swap.height() // 2)
        self.swap.raise_()
