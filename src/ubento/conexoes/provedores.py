"""Catálogo de provedores de conexão. Para adicionar outro: um `Provedor` aqui, um cliente com `verificar()` e o desenho do logo na interface."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .binance import ClienteBinance, Verificacao, transporte_http
from .telegram import ClienteTelegram


@dataclass(frozen=True)
class Campo:
    nome: str
    rotulo: str
    secreto: bool
    dica: str
    padrao: str = r"[A-Za-z0-9]{16,128}"  # formato aceito (expressão regular, valor inteiro)
    erro_de_formato: str = "use só letras e números, sem espaços"


@dataclass(frozen=True)
class Provedor:
    id: str
    nome: str
    descricao: str
    cor: str
    campos: tuple[Campo, ...]
    como_conectar: str
    criar_cliente: Callable[[dict[str, str], Any], Any] | None = None  # -> objeto com .verificar() -> Verificacao
    disponivel: bool = True  # False = lugar reservado: aparece na tela como "em breve" e ainda não conecta
    garantia: str = ("A chave e o segredo ficam só no cofre deste computador (Windows) e nunca no banco do UBento. "
                     "O UBento só lê dados: não negocia nem saca.")


def _binance(credenciais: dict[str, str], transporte) -> ClienteBinance:
    return ClienteBinance(credenciais["api_key"], credenciais["api_secret"], transporte)


def _telegram(credenciais: dict[str, str], transporte) -> ClienteTelegram:
    return ClienteTelegram(credenciais["token"], transporte)


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
    "telegram": Provedor(
        id="telegram", nome="Telegram", descricao="Bot para consultar suas metas pelo celular", cor="#27A0DF",
        campos=(Campo("token", "Token do bot", True, "123456789:AA… (do @BotFather)", r"\d{6,14}:[A-Za-z0-9_-]{30,64}",
                      "copie o token inteiro, com o número, os dois-pontos e o resto"),),
        como_conectar=(
            "No Telegram, abra o @BotFather, envie /newbot, escolha um nome e copie o token que ele mostra. Cole aqui. "
            "Depois de conectar, vincule o seu chat com um código: só o chat vinculado é atendido; qualquer outra pessoa que achar o bot é ignorada."
        ),
        criar_cliente=_telegram,
        garantia=("O token fica só no cofre deste computador e nunca no banco. O bot só responde CONSULTAS de leitura (suas metas), e só ao chat que você vincular, "
                  "enquanto o UBento estiver aberto. Atenção: as respostas passam pelos servidores do Telegram (conversas com bots não têm criptografia de ponta a ponta)."),
    ),
}

__all__ = ["Campo", "PROVEDORES", "Provedor", "Verificacao", "transporte_http"]
