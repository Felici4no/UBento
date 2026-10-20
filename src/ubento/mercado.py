"""O mercado de uma carteira: cadastro dos ativos, preços, sinais, frescor da leitura e o relógio (ADR-001, passo 3).

Nada aqui é global. Cada `Workspace` tem o seu `Mercado` e o entrega aos seus `Store`; um `Store` avulso (testes, capturas de tela) cria o próprio.
Assim dois mundos convivem (por exemplo, demonstração e mercado real) e o tempo é o que quem constrói disser (`relogio`), não o do sistema.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

PRECO_VALIDO_S = 120  # sem cotação mais nova que isso, o modo real não opera
AGUARDANDO_PRECOS = "Aguardando os preços ao vivo da Binance"


@dataclass(frozen=True)
class Ativo:
    """Cadastro de um ativo. Não tem preço: o preço é do `Mercado`."""

    symbol: str
    name: str
    decimals: int


ATIVOS: dict[str, Ativo] = {
    a.symbol: a
    for a in (
        Ativo("USD", "Dólar", 2),
        Ativo("ETH", "Ethereum", 5),
        Ativo("SOL", "Solana", 4),
        Ativo("AVAX", "Avalanche", 3),
        Ativo("BNB", "BNB", 4),
        Ativo("USDT", "Tether", 2),
        Ativo("USDC", "USD Coin", 2),
    )
}

# preços de exemplo (USD) da demonstração; nunca são alterados, cada `Mercado` parte de uma cópia
PRECOS_DEMO: dict[str, float] = {"USD": 1.0, "ETH": 3852.93, "SOL": 184.62, "AVAX": 37.50, "BNB": 651.11, "USDT": 1.0, "USDC": 0.996}


class Mercado:
    """Preços em USD, sinais de 7 dias, frescor da última leitura e relógio.

    Ligado (`ativo`), os preços vêm da Binance e os sinais dos agentes são a variação real; desligado, valem os de demonstração.
    Leitura velha (mais de `PRECO_VALIDO_S`) ou ausente bloqueia qualquer operação.
    """

    def __init__(self, relogio: Callable[[], datetime] = datetime.now):
        self._relogio = relogio
        self.precos: dict[str, float] = dict(PRECOS_DEMO)
        self.ativo = False
        self.variacao_7d: dict[str, float] = {}
        self.atualizado_em: datetime | None = None
        self.erro: str | None = None

    def agora(self) -> datetime:
        """Hora local ingênua, a mesma convenção da carteira. É o único relógio do domínio."""
        return self._relogio()

    def preco(self, simbolo: str) -> float:
        return self.precos[simbolo]

    def ligar(self) -> None:
        self.ativo = True

    def desativar(self) -> None:
        """Desliga e volta aos preços de demonstração."""
        self.ativo = False
        self.precos = dict(PRECOS_DEMO)
        self.variacao_7d, self.atualizado_em, self.erro = {}, None, None

    def aplicar(self, precos: dict[str, float], variacao_7d: dict[str, float], agora: datetime | None = None) -> None:
        self.precos.update({s: p for s, p in precos.items() if s in ATIVOS})
        self.variacao_7d = dict(variacao_7d)
        self.atualizado_em, self.erro = agora or self.agora(), None

    def fresco(self, agora: datetime | None = None) -> bool:
        agora = agora or self.agora()
        return self.ativo and self.atualizado_em is not None and timedelta(0) <= agora - self.atualizado_em <= timedelta(seconds=PRECO_VALIDO_S)
