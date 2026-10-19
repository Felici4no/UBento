"""Dados públicos de mercado da Binance: preços sem chave, sem assinatura e sem segredo. A rede é sempre simulada nos testes."""

import json
import urllib.parse

import pytest

from ubento.conexoes.binance import ErroDeConexao
from ubento.conexoes.mercado import PARES, ClienteMercado


class Rede:
    def __init__(self, resposta):
        self.resposta, self.chamadas = resposta, []

    def __call__(self, url, cabecalhos, tempo_limite):
        self.chamadas.append((url, cabecalhos, tempo_limite))
        return self.resposta


def corpo(**precos):
    return (200, json.dumps([{"symbol": s, "price": p} for s, p in precos.items()]).encode())


COMPLETO = corpo(ETHUSDT="3852.93000000", SOLUSDT="184.62000000", AVAXUSDT="37.50000000", BNBUSDT="651.11000000", USDCUSDT="1.00040000")


def test_pede_so_os_pares_necessarios_sem_chave_nem_assinatura():
    rede = Rede(COMPLETO)
    ClienteMercado(rede).precos()
    (url, cabecalhos, _), = rede.chamadas
    assert url.startswith("https://api.binance.com/api/v3/ticker/price?")
    assert "signature" not in url and "timestamp" not in url and "X-MBX-APIKEY" not in cabecalhos  # endpoint público
    pedido = json.loads(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["symbols"][0])
    assert sorted(pedido) == sorted(PARES.values())


def test_converte_pares_em_usd_e_usdt_e_a_referencia_do_dolar():
    # USDC vale 1,0004 USDT (e USDT é a nossa referência de US$ 1,00): 1 USDC = US$ 1,0004
    p = ClienteMercado(Rede(COMPLETO)).precos()
    assert p == {"ETH": 3852.93, "SOL": 184.62, "AVAX": 37.5, "BNB": 651.11, "USDC": 1.0004, "USDT": 1.0, "USD": 1.0}


@pytest.mark.parametrize("ruim", ["0", "-5", "abc", "nan", "inf", ""])
def test_preco_invalido_e_recusado_e_nada_e_devolvido(ruim):
    with pytest.raises(ErroDeConexao, match="preço"):
        ClienteMercado(Rede(corpo(ETHUSDT=ruim, SOLUSDT="1", AVAXUSDT="1", BNBUSDT="1", USDCUSDT="1"))).precos()


def test_par_ausente_na_resposta_e_recusado_em_vez_de_misturar_preco_velho_com_novo():
    with pytest.raises(ErroDeConexao, match="ETHUSDT"):
        ClienteMercado(Rede(corpo(SOLUSDT="1", AVAXUSDT="1", BNBUSDT="1", USDCUSDT="1"))).precos()


@pytest.mark.parametrize("resposta, trecho", [
    ((429, b"{}"), "limitou"), ((418, b"{}"), "limitou"), ((503, b""), "indispon"), ((400, b'{"code":-1121,"msg":"Invalid symbol."}'), "recusou"),
    ((200, b"nao e json"), "resposta"), ((200, b'{"x":1}'), "resposta"),
])
def test_erros_viram_mensagens_claras(resposta, trecho):
    with pytest.raises(ErroDeConexao, match=trecho):
        ClienteMercado(Rede(resposta)).precos()
