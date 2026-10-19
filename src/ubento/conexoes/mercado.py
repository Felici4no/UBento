"""Dados PÚBLICOS de mercado da Binance (preços spot). Não usa chave, assinatura nem segredo: qualquer um pode consultar.

USDT é a referência do dólar (US$ 1,00): os preços em USDT valem como preços em USD. Todos os pares vêm numa única chamada e a resposta só é aceita
inteira: um par ausente ou inválido recusa tudo, para nunca misturar preço novo com preço velho.
"""

from __future__ import annotations

import json
import math
import urllib.parse

from .binance import BASE, TEMPO_LIMITE, ErroDeConexao, Transporte, transporte_http

# ativo do UBento -> par na Binance (cotado em USDT)
PARES: dict[str, str] = {"ETH": "ETHUSDT", "SOL": "SOLUSDT", "AVAX": "AVAXUSDT", "BNB": "BNBUSDT", "USDC": "USDCUSDT"}
FIXOS: dict[str, float] = {"USDT": 1.0, "USD": 1.0}


class ClienteMercado:
    def __init__(self, transporte: Transporte = transporte_http, base: str = BASE):
        self._transporte, self._base = transporte, base

    def _buscar(self, pares: list[str]) -> list:
        consulta = urllib.parse.urlencode({"symbols": json.dumps(pares, separators=(",", ":"))})
        status, corpo = self._transporte(f"{self._base}/api/v3/ticker/price?{consulta}", {}, TEMPO_LIMITE)
        if status in (418, 429):
            raise ErroDeConexao("A Binance limitou as requisições deste computador. Aguarde alguns minutos e tente de novo.", f"HTTP {status}")
        if status >= 500:
            raise ErroDeConexao("A Binance está indisponível no momento. Tente de novo em instantes.", f"HTTP {status}")
        if status != 200:
            raise ErroDeConexao("A Binance recusou o pedido de preços.", f"HTTP {status}: {corpo[:200]!r}")
        try:
            dados = json.loads(corpo.decode("utf-8"))
        except ValueError:
            dados = None
        if not isinstance(dados, list):
            raise ErroDeConexao("A Binance devolveu uma resposta que o UBento não entende.", f"corpo inesperado: {corpo[:200]!r}")
        return dados

    def precos(self) -> dict[str, float]:
        """Preço em USD de cada ativo do UBento. Levanta `ErroDeConexao` se faltar ou vier inválido qualquer par."""
        por_par = {item.get("symbol"): item.get("price") for item in self._buscar(list(PARES.values())) if isinstance(item, dict)}
        resultado: dict[str, float] = {}
        for ativo, par in PARES.items():
            if par not in por_par:
                raise ErroDeConexao(f"A resposta da Binance não trouxe o par {par}.", f"par ausente: {par}")
            try:
                valor = float(por_par[par])
            except (TypeError, ValueError):
                valor = math.nan
            if not math.isfinite(valor) or valor <= 0:
                raise ErroDeConexao(f"A Binance devolveu um preço inválido para {par}.", f"{par}={por_par[par]!r}")
            resultado[ativo] = valor
        return {**resultado, **FIXOS}
