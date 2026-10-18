"""Decisões como log: valor aplicado, taxa e resultado (verde no lucro, vermelho na perda), com data e hora.

Os valores esperados foram calculados à mão (as contas estão nos comentários).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ubento import formatting  # noqa: E402
from ubento.engine import _trade  # noqa: E402
from ubento.store import ASSETS, Decision, Store, Trade  # noqa: E402
from ubento.ui import theme  # noqa: E402
from ubento.ui.cards.decisions import ROW_H, DecisionList, linha_de_log, resultado_cor, resultado_info, usd_texto  # noqa: E402

AGORA = datetime(2026, 10, 18, 15, 0, 5)


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(theme.APP_QSS)
    return a


@pytest.fixture
def store():
    s = Store(now=AGORA)
    s.holdings = {"USD": 10000.0, "ETH": 2.0}
    s.cost_basis = {"ETH": 6000.0}  # 2 ETH comprados por 6.000 no total: custo médio 3.000
    s.decisions = []
    return s


# -- o livro: resultado líquido de taxa ----------------------------------------------------------------------------------------------


def test_compra_resultado_no_ato_e_so_a_taxa_e_a_posicao_fica_em_aberto(store):
    # compra de 1.000 USD de ETH (3.852,93): taxa 0,10% = 1,00; entram (1.000 − 1,00) / 3.852,93 unidades
    t = _trade("buy", "ETH", 1000.0)
    assert t.fee == 1.00 and t.usd == 1000.0
    assert t.qty * ASSETS["ETH"].price == pytest.approx(999.0, abs=0.02)  # a taxa saiu do que se recebe (as unidades têm 5 casas)
    pnl = store.executar_trade(t)
    assert pnl == -1.00  # valor recebido (999,00) − pago (1.000,00): o custo de entrar é a taxa
    assert store.holdings["USD"] == 9000.0  # saiu exatamente o valor aplicado
    assert store.cost_basis["ETH"] == pytest.approx(7000.0)  # o custo inclui a taxa paga: 6.000 + 1.000


def test_venda_com_lucro_realizado_liquido_da_taxa(store):
    # vende 1 ETH a 3.852,93: taxa = 3,85; entram 3.849,08. Custo médio 3.000 → resultado = 3.849,08 − 3.000 = +849,08
    t = _trade("sell", "ETH", 3852.93)
    assert (t.qty, t.usd, t.fee) == (1.0, 3852.93, 3.85)
    assert store.executar_trade(t) == pytest.approx(849.08, abs=0.01)
    assert store.holdings["USD"] == pytest.approx(10000.0 + 3849.08)
    assert store.cost_basis["ETH"] == pytest.approx(3000.0)  # sobrou 1 ETH com o custo médio de 3.000


def test_venda_com_prejuizo_realizado(store):
    store.cost_basis["ETH"] = 10000.0  # 2 ETH custaram 10.000: custo médio 5.000
    # vende 1 ETH: entram 3.849,08; custo 5.000 → resultado = 3.849,08 − 5.000 = −1.150,92
    assert store.executar_trade(_trade("sell", "ETH", 3852.93)) == pytest.approx(-1150.92, abs=0.01)


def test_saldo_insuficiente_nao_altera_nada(store):
    antes = (dict(store.holdings), dict(store.cost_basis))
    assert store.executar_trade(Trade("sell", "ETH", 5.0, 19264.65, 19.26)) is None
    assert store.executar_trade(Trade("buy", "ETH", 1.0, 99999.0, 100.0)) is None
    assert (store.holdings, store.cost_basis) == antes


def test_swap_de_dolar_o_resultado_e_exatamente_a_soma_das_taxas(store):
    # 500 USD: taxa de serviço 2,3% = 11,50 + gás 1,32 = 12,82. Recebe o valor líquido (487,18), então resultado = −12,82
    assert store.execute("USD", "ETH", 500.0) is None
    d = store.decisions[0]
    assert (d.value_usd, d.fee_usd, d.pnl_usd, d.pnl_realizado) == (500.0, 12.82, -12.82, True)


def test_swap_de_cripto_realiza_o_ganho_pelo_custo_medio(store):
    # troca 1 ETH (custo 3.000, vale 3.852,93) por USD. Valor 3.852,93; serviço 2,3% = 88,62; gás 1,32; entram 3.762,99.
    # resultado = 3.762,99 − 3.000 = +762,99 (o ganho do ativo já descontadas as taxas de 89,94)
    assert store.execute("ETH", "USD", 1.0) is None
    d = store.decisions[0]
    assert d.fee_usd == pytest.approx(89.94, abs=0.01) and d.pnl_usd == pytest.approx(762.99, abs=0.02)
    assert store.cost_basis["ETH"] == pytest.approx(3000.0)


def test_decisao_executada_ganha_valor_taxa_e_resultado_e_a_proposta_so_estimativa(store):
    venda = Decision("sell", "Vendeu ETH", "teste", "- 1,00000 ETH", AGORA, trade=_trade("sell", "ETH", 3852.93), status="executed")
    proposta = Decision("sell", "Venderia ETH", "teste", "- 1,00000 ETH", AGORA, trade=_trade("sell", "ETH", 3852.93), status="proposed", value_usd=3852.93, fee_usd=3.85)
    store.add_decision(venda)
    store.add_decision(proposta)
    executada, pendente = store.decisions[1], store.decisions[0]
    assert (executada.value_usd, executada.fee_usd, executada.pnl_usd) == (3852.93, 3.85, pytest.approx(849.08, abs=0.01))
    assert pendente.pnl_usd is None and resultado_info(pendente) is None  # sem execução não há resultado
    store.resolve_decision(pendente.uid, True)
    assert store.decisions[0].pnl_usd is None  # aprovar não executa: segue sem resultado
    store.registrar_execucao(pendente.uid)
    # a venda anterior deixou 1 ETH com custo médio 3.000: executar a proposta vende esse ETH → 3.849,08 − 3.000 = +849,08
    assert store.decisions[0].status == "executed" and store.decisions[0].pnl_usd == pytest.approx(849.08, abs=0.01)


def test_historico_de_demonstracao_traz_valor_taxa_e_resultado_so_onde_ha_dinheiro():
    s = Store(now=AGORA)
    com_trade = [d for d in s.decisions if d.kind in ("buy", "sell")]
    sem_trade = [d for d in s.decisions if d.kind not in ("buy", "sell")]
    assert com_trade and sem_trade
    for d in com_trade:
        assert d.value_usd and d.fee_usd == round(d.value_usd * 0.001, 2) and d.pnl_usd is not None
        assert (d.pnl_realizado) == (d.kind == "sell")
        if d.kind == "buy":
            assert d.pnl_usd == -d.fee_usd  # compra: no ato só se perdeu a taxa
    assert all(d.value_usd is None and d.pnl_usd is None for d in sem_trade)
    assert any(d.pnl_usd > 0 for d in com_trade) and any(d.pnl_usd < 0 for d in com_trade)  # há lucro e há perda no histórico


# -- a apresentação ---------------------------------------------------------------------------------------------------------------------


def test_cores_verde_no_lucro_vermelho_na_perda_e_neutro_sem_resultado():
    assert resultado_cor(0.01) == theme.GREEN and resultado_cor(-0.01) == theme.RED
    assert resultado_cor(0.0) == theme.MUTED and resultado_cor(None) == theme.MUTED and resultado_cor(0.004) == theme.MUTED  # arredonda a centavos


def test_texto_com_sinal_e_modo_ocultar():
    assert usd_texto(1234.5) == "US$ 1.234,50" and usd_texto(15.9, sinal=True) == "+US$ 15,90" and usd_texto(-12.82, sinal=True) == "−US$ 12,82"
    formatting.set_hidden(True)
    try:
        assert usd_texto(-12.82, sinal=True) == f"US$ {formatting.MASK}"
    finally:
        formatting.set_hidden(False)


def test_linha_de_log_tem_data_hora_movimento_valor_e_taxa():
    d = Decision("sell", "Vendeu AVAX", "x", "- 4,000 AVAX", datetime(2026, 10, 17, 3, 31, 28), value_usd=150.0, fee_usd=0.15, pnl_usd=15.9)
    assert linha_de_log(d) == "17/10/2026 03:31:28  ·  - 4,000 AVAX  ·  Valor US$ 150,00  ·  Taxa US$ 0,15"
    hold = Decision("hold", "Manteve ETH", "x", "", datetime(2026, 10, 16, 10, 41, 28))
    assert linha_de_log(hold) == "16/10/2026 10:41:28"  # sem dinheiro: só quando
    assert resultado_info(d) == ("+US$ 15,90", theme.GREEN, "realizado, líquido da taxa")
    aberta = Decision("buy", "Comprou SOL", "x", "+ 1,0000 SOL", AGORA, value_usd=100.0, fee_usd=0.1, pnl_usd=-0.1, pnl_realizado=False)
    assert resultado_info(aberta) == ("−US$ 0,10", theme.RED, "em aberto, líquido da taxa")


def test_a_lista_pinta_lucro_de_verde_e_perda_de_vermelho(app):
    s = Store(now=AGORA)
    s.decisions = [
        Decision("sell", "Vendeu com perda", "stop", "- 1,0000 SOL", AGORA, value_usd=300.0, fee_usd=0.3, pnl_usd=-18.0),
        Decision("sell", "Vendeu com lucro", "meta", "- 1,0000 SOL", AGORA, value_usd=300.0, fee_usd=0.3, pnl_usd=24.0),
    ]
    lista = DecisionList(s)
    lista.resize(900, ROW_H * 2 + 20)
    lista.show()
    img: QImage = lista.grab().toImage()

    def cor_na_faixa(linha: int, predicado) -> bool:
        y0, y1 = int(linha * ROW_H * img.devicePixelRatio()), int((linha + 1) * ROW_H * img.devicePixelRatio())
        return any(predicado(img.pixelColor(x, y)) for y in range(y0, y1, 2) for x in range(int(img.width() * 0.8), img.width() - 4, 2))

    vermelho = lambda c: c.red() > 200 and c.green() < 110 and c.blue() < 110  # noqa: E731
    verde = lambda c: c.green() > 170 and c.red() < 110 and c.blue() < 140  # noqa: E731
    assert cor_na_faixa(0, vermelho) and not cor_na_faixa(0, verde)  # a perda é vermelha, só vermelha
    assert cor_na_faixa(1, verde) and not cor_na_faixa(1, vermelho)  # o lucro é verde, só verde
