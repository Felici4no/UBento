"""Dados públicos de mercado da Binance: preço e variação de 7 dias sem chave, sem assinatura e sem segredo. A rede é sempre simulada nos testes."""

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


def item(par, preco, variacao="1.5"):
    return {"symbol": par, "lastPrice": preco, "priceChangePercent": variacao}


def corpo(itens):
    return 200, json.dumps(itens).encode()


def completo(**mudar):
    base = {"ETHUSDT": ("3852.93000000", "-4.786"), "SOLUSDT": ("184.62000000", "2.1"), "AVAXUSDT": ("37.50000000", "0.0"),
            "BNBUSDT": ("651.11000000", "12.5"), "USDCUSDT": ("1.00040000", "-0.001")}
    base.update(mudar)
    return [item(par, *dados) for par, dados in base.items() if dados is not None]


def test_pede_so_os_pares_necessarios_sem_chave_nem_assinatura():
    rede = Rede(corpo(completo()))
    ClienteMercado(rede).cotacoes()
    (url, cabecalhos, _), = rede.chamadas
    consulta = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert url.startswith("https://api.binance.com/api/v3/ticker?") and consulta["windowSize"] == ["7d"]
    assert "signature" not in url and "timestamp" not in url and "X-MBX-APIKEY" not in cabecalhos  # endpoint público
    assert sorted(json.loads(consulta["symbols"][0])) == sorted(PARES.values())


def test_converte_pares_em_usd_e_traz_a_variacao_real_de_7_dias():
    # USDC vale 1,0004 USDT (e USDT é a nossa referência de US$ 1,00): 1 USDC = US$ 1,0004. Dólar e USDT não variam.
    c = ClienteMercado(Rede(corpo(completo()))).cotacoes()
    assert c.precos == {"ETH": 3852.93, "SOL": 184.62, "AVAX": 37.5, "BNB": 651.11, "USDC": 1.0004, "USDT": 1.0, "USD": 1.0}
    assert c.variacao_7d == {"ETH": -4.786, "SOL": 2.1, "AVAX": 0.0, "BNB": 12.5, "USDC": -0.001, "USDT": 0.0, "USD": 0.0}


@pytest.mark.parametrize("ruim", ["0", "-5", "abc", "nan", "inf", "", None])
def test_preco_invalido_e_recusado_e_nada_e_devolvido(ruim):
    with pytest.raises(ErroDeConexao, match="preço"):
        ClienteMercado(Rede(corpo(completo(ETHUSDT=(ruim, "1"))))).cotacoes()


@pytest.mark.parametrize("ruim", ["abc", "nan", "inf", "", None])
def test_variacao_invalida_tambem_recusa_tudo(ruim):
    with pytest.raises(ErroDeConexao, match="inválido"):
        ClienteMercado(Rede(corpo(completo(SOLUSDT=("184.62", ruim))))).cotacoes()


def test_par_ausente_na_resposta_e_recusado_em_vez_de_misturar_preco_velho_com_novo():
    with pytest.raises(ErroDeConexao, match="ETHUSDT"):
        ClienteMercado(Rede(corpo(completo(ETHUSDT=None)))).cotacoes()


@pytest.mark.parametrize("resposta, trecho", [
    ((429, b"{}"), "limitou"), ((418, b"{}"), "limitou"), ((503, b""), "indispon"), ((400, b'{"code":-1121,"msg":"Invalid symbol."}'), "recusou"),
    ((200, b"nao e json"), "resposta"), ((200, b'{"x":1}'), "resposta"),
])
def test_erros_viram_mensagens_claras(resposta, trecho):
    with pytest.raises(ErroDeConexao, match=trecho):
        ClienteMercado(Rede(resposta)).cotacoes()
