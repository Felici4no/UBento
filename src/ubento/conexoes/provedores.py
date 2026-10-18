"""Catálogo de provedores de conexão. Para adicionar outro: um `Provedor` aqui, um cliente com `verificar()` e o desenho do logo na interface."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .binance import ClienteBinance, Transporte, Verificacao, transporte_http


@dataclass(frozen=True)
class Campo:
    nome: str
    rotulo: str
    secreto: bool
    dica: str


@dataclass(frozen=True)
class Provedor:
    id: str
    nome: str
    descricao: str
    cor: str
    campos: tuple[Campo, ...]
    como_conectar: str
    criar_cliente: Callable[[dict[str, str], Transporte], Any] | None = None  # -> objeto com .verificar() -> Verificacao
    disponivel: bool = True  # False = lugar reservado: aparece na tela como "em breve" e ainda não conecta


def _binance(credenciais: dict[str, str], transporte: Transporte) -> ClienteBinance:
    return ClienteBinance(credenciais["api_key"], credenciais["api_secret"], transporte)


PROVEDORES: dict[str, Provedor] = {
    "binance": Provedor(
        id="binance", nome="Binance", descricao="Corretora de criptoativos (spot)", cor="#F0B90B",
        campos=(
            Campo("api_key", "API Key", False, "cole a chave inteira"),
            Campo("api_secret", "API Secret", True, "cole o segredo; ele fica só no cofre do sistema"),
        ),
        como_conectar=(
            "Na Binance: Gerenciamento de API → Criar API. Deixe habilitada SOMENTE a leitura (\"Enable Reading\"): "
            "nada de saques, transferências nem negociação. Se puder, restrinja a chave ao IP deste computador. "
            "O UBento recusa chaves com qualquer outro poder."
        ),
        criar_cliente=_binance,
    ),
    # Lugar reservado: não pede nem guarda nada ainda. Quando existir, entra aqui o campo do token do bot e um cliente com `verificar()`.
    "telegram": Provedor(
        id="telegram", nome="Telegram", descricao="Bot para avisos e consultas pelo celular", cor="#27A0DF", campos=(),
        como_conectar="Em breve: conecte um bot do Telegram para receber avisos e consultar suas metas pelo celular. Por enquanto nada é pedido, enviado nem guardado.",
        disponivel=False,
    ),
}

__all__ = ["Campo", "PROVEDORES", "Provedor", "Verificacao", "transporte_http"]
