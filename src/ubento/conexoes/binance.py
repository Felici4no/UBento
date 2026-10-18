"""Cliente SOMENTE LEITURA da Binance (API REST, spot). Só verifica a chave e as permissões dela por enquanto.

O UBento não opera pela Binance: ele exige uma chave de API com **apenas leitura**. Se a chave puder sacar, transferir ou negociar,
a conexão é recusada (um app de acompanhamento não precisa desse poder, e uma chave vazada com ele custa dinheiro).
Sem dependências: usa `urllib`. O transporte é injetável, então os testes nunca falam com a rede.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

BASE = "https://api.binance.com"
TEMPO_LIMITE = 10.0

# (status HTTP, corpo) devolvido pelo transporte; `Transporte(url, cabecalhos, tempo_limite)`
Transporte = Callable[[str, dict[str, str], float], tuple[int, bytes]]

# o que uma chave NÃO pode ter. A leitura é o único poder aceito.
PERMISSOES_PERIGOSAS = {
    "enableWithdrawals": "saques",
    "enableInternalTransfer": "transferências internas",
    "permitsUniversalTransfer": "transferência universal",
    "enableSpotAndMarginTrading": "negociação (spot/margem)",
    "enableMargin": "margem",
    "enableFutures": "futuros",
    "enableVanillaOptions": "opções",
}


class ErroDeConexao(Exception):
    """Falha ao falar com a Binance. `str(erro)` é uma mensagem para o usuário e nunca traz a chave nem o segredo."""

    def __init__(self, mensagem: str, tecnico: str = ""):
        super().__init__(mensagem)
        self.tecnico = tecnico  # detalhe para o log (já sem segredos)


def transporte_http(url: str, cabecalhos: dict[str, str], tempo_limite: float) -> tuple[int, bytes]:
    requisicao = urllib.request.Request(url, headers=cabecalhos, method="GET")
    try:
        with urllib.request.urlopen(requisicao, timeout=tempo_limite) as resposta:  # noqa: S310 - URL fixa https
            return resposta.status, resposta.read()
    except urllib.error.HTTPError as erro:  # a Binance explica o erro no corpo
        return erro.code, erro.read()
    except (urllib.error.URLError, TimeoutError, OSError) as erro:
        raise ErroDeConexao("Não foi possível falar com a Binance. Confira a conexão com a internet e tente de novo.", type(erro).__name__) from erro


@dataclass(frozen=True)
class Verificacao:
    somente_leitura: bool
    permissoes: dict[str, bool]
    excessos: tuple[str, ...] = ()
    mensagem: str = ""
    criada_em_ms: int | None = None
    restricao_de_ip: bool | None = None
    extras: dict = field(default_factory=dict)


MENSAGENS = {
    -2014: "A chave de API está com formato inválido. Copie a chave inteira, sem espaços.",
    -2015: "A Binance recusou a chave: ela é inválida, foi apagada ou não aceita o IP deste computador (restrição de IP).",
    -1022: "A assinatura foi recusada: confira se o segredo (API Secret) está completo e é o desta chave.",
    -1021: "O relógio do computador está fora de sincronia com o da Binance. Ajuste a data e a hora do Windows e tente de novo.",
    -2008: "A Binance não reconhece esta chave de API.",
}


class ClienteBinance:
    def __init__(self, api_key: str, api_secret: str, transporte: Transporte = transporte_http, base: str = BASE, relogio: Callable[[], float] = time.time):
        self._chave, self._segredo = api_key, api_secret
        self._transporte, self._base, self._relogio = transporte, base, relogio

    def _limpar(self, texto: str) -> str:
        return texto.replace(self._chave, "***").replace(self._segredo, "***")

    def _assinado(self, caminho: str) -> dict:
        consulta = urllib.parse.urlencode({"timestamp": int(self._relogio() * 1000), "recvWindow": 5000})
        assinatura = hmac.new(self._segredo.encode("utf-8"), consulta.encode("utf-8"), hashlib.sha256).hexdigest()
        status, corpo = self._transporte(f"{self._base}{caminho}?{consulta}&signature={assinatura}", {"X-MBX-APIKEY": self._chave}, TEMPO_LIMITE)
        try:
            dados = json.loads(corpo.decode("utf-8")) if corpo else {}
        except ValueError:
            dados = {}
        if status == 200 and isinstance(dados, dict):
            return dados
        codigo = dados.get("code") if isinstance(dados, dict) else None
        tecnico = self._limpar(f"HTTP {status} código {codigo}: {dados.get('msg') if isinstance(dados, dict) else ''}")
        if codigo in MENSAGENS:
            raise ErroDeConexao(MENSAGENS[codigo], tecnico)
        if status in (418, 429):
            raise ErroDeConexao("A Binance limitou as requisições deste computador. Aguarde alguns minutos e tente de novo.", tecnico)
        if status >= 500:
            raise ErroDeConexao("A Binance está indisponível no momento. Tente de novo em instantes.", tecnico)
        raise ErroDeConexao("A Binance recusou o pedido. Confira a chave e o segredo.", tecnico)

    def verificar(self) -> Verificacao:
        """Pergunta à Binance o que ESTA chave pode fazer. Só `enableReading` é aceito; qualquer outro poder reprova a chave."""
        r = self._assinado("/sapi/v1/account/apiRestrictions")
        permissoes = {k: bool(r.get(k)) for k in ("enableReading", *PERMISSOES_PERIGOSAS)}
        excessos = tuple(nome for chave, nome in PERMISSOES_PERIGOSAS.items() if permissoes[chave])
        restricao_ip = bool(r["ipRestrict"]) if "ipRestrict" in r else None
        if not permissoes["enableReading"]:
            return Verificacao(False, permissoes, excessos, "A chave não tem a permissão de leitura habilitada.", r.get("createTime"), restricao_ip)
        if excessos:
            return Verificacao(False, permissoes, excessos, "A chave tem poderes além da leitura: " + ", ".join(excessos) + ". Crie outra chave só com leitura.", r.get("createTime"), restricao_ip)
        return Verificacao(True, permissoes, (), "Chave somente leitura confirmada.", r.get("createTime"), restricao_ip)
