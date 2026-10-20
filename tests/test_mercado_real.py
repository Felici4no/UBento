"""Modo mercado real: preços ao vivo da Binance, carteira nova e nenhum dado simulado misturado.

As contas esperadas foram feitas à mão (estão nos comentários). A rede nunca é tocada: as cotações entram pelo mesmo caminho do atualizador.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime, timedelta  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402

from ubento import engine  # noqa: E402
from ubento.cotacoes import Cotacoes  # noqa: E402
from ubento.engine import _trade  # noqa: E402
from ubento.store import ASSETS, CAPITAL_INICIAL_REAL, MERCADO  # noqa: E402
from ubento.workspace import Workspace  # noqa: E402

T0 = datetime(2026, 10, 19, 12, 0, 0)


def cotacoes(eth=2000.0, var_eth=-4.0, **outros):
    precos = {"ETH": eth, "SOL": 100.0, "AVAX": 10.0, "BNB": 700.0, "USDC": 1.001, "USDT": 1.0, "USD": 1.0, **outros}
    var = {"ETH": var_eth, "SOL": 3.0, "AVAX": -9.0, "BNB": -2.5, "USDC": 0.0, "USDT": 0.0, "USD": 0.0}
    return Cotacoes(precos, var)


@pytest.fixture(autouse=True)
def limpo():
    MERCADO.desativar()
    yield
    MERCADO.desativar()  # preços e estado global voltam ao normal para os outros testes


@pytest.fixture
def ws():
    w = Workspace()
    w.set_pref("mercado", "real")
    return w


# -- carteira nova, sem simulação ------------------------------------------------------------------------------------------------------


def test_ligar_o_mercado_real_zera_a_demonstracao_e_cria_carteira_nova(ws):
    for a in ws.agents:
        s = a.store
        assert s.real and s.holdings["USD"] == CAPITAL_INICIAL_REAL == 10_000.0
        assert all(q == 0 for k, q in s.holdings.items() if k != "USD") and s.cost_basis == {}
        assert s.decisions == [] and s.spent == 0 and s.income == 0 and sum(s.activity.values()) == 0
    assert ws.overview.total_usd() == 20_000.0  # a soma das duas carteiras novas, sem nenhum saldo de demonstração


def test_desligar_volta_a_demonstracao_e_aos_precos_originais(ws):
    ws.receber_cotacoes(cotacoes(eth=2000.0), agora=T0)
    assert ASSETS["ETH"].price == 2000.0
    ws.set_pref("mercado", "simulado")
    assert ASSETS["ETH"].price == 3852.93 and not MERCADO.ativo
    s = ws.agents[0].store
    assert not s.real and s.holdings["ETH"] == 2.9934 and s.decisions  # a demonstração está de volta


def test_valor_invalido_do_modo_e_ignorado(ws):
    ws.set_pref("mercado", "qualquer")
    assert ws.pref("mercado") == "real"


def test_agente_novo_nasce_com_carteira_real(ws):
    novo = ws.add("Novo")
    assert novo.store.real and novo.store.holdings["USD"] == 10_000.0 and novo.store.decisions == []


# -- preços ao vivo --------------------------------------------------------------------------------------------------------------------


def test_cotacoes_viram_precos_da_carteira_e_o_patrimonio_acompanha(ws):
    ws.receber_cotacoes(cotacoes(eth=2000.0), agora=T0)
    s = ws.agents[0].store
    t = _trade("buy", "ETH", 1000.0)  # taxa 0,10% = 1,00; entram (1000 − 1,00) / 2000 = 0,4995 ETH
    assert (t.fee, t.qty) == (1.0, 0.4995)
    assert s.executar_trade(t) == -1.0
    assert s.holdings["USD"] == 9000.0 and s.total_usd() == pytest.approx(9000.0 + 0.4995 * 2000.0)  # 9.999,00
    ws.receber_cotacoes(cotacoes(eth=2200.0), agora=T0 + timedelta(minutes=1))
    assert s.total_usd() == pytest.approx(9000.0 + 0.4995 * 2200.0)  # 10.098,90: o saldo é o do mercado, não o do cenário


def test_historico_e_a_serie_observada_e_nao_um_passeio_sintetico(ws):
    s = ws.agents[0].store
    ws.receber_cotacoes(cotacoes(), agora=T0)
    s.executar_trade(_trade("buy", "ETH", 1000.0))
    ws.receber_cotacoes(cotacoes(eth=2200.0), agora=T0 + timedelta(days=1))
    pontos = s.history("1S")
    assert [d for d, _ in pontos] == sorted(d for d, _ in pontos) and len(pontos) >= 2
    assert pontos[-1] == (date(2026, 10, 20), pytest.approx(10098.9))
    assert pontos[-2] == (date(2026, 10, 19), pytest.approx(10000.0))  # o último ponto observado do dia anterior (a compra só entra na próxima leitura)
    assert s.history("1S") == pontos  # determinístico: a mesma pergunta, a mesma resposta


def test_historico_de_carteira_recem_criada_e_uma_linha_reta_com_o_capital(ws):
    pontos = ws.agents[0].store.history("1M")
    assert len(pontos) >= 2 and {v for _, v in pontos} == {10_000.0}


def test_variacao_da_carteira_cripto_e_a_real_de_7_dias_ponderada_pelo_que_se_tem(ws):
    s = ws.agents[0].store
    ws.receber_cotacoes(cotacoes(eth=2000.0, var_eth=-4.0), agora=T0)
    assert s.crypto_change == 0.0  # nada em cripto ainda
    s.executar_trade(_trade("buy", "ETH", 1000.0))
    ws.receber_cotacoes(cotacoes(eth=2000.0, var_eth=-4.0), agora=T0 + timedelta(seconds=30))
    assert s.crypto_change == pytest.approx(-4.0)  # só ETH em carteira
    s.executar_trade(_trade("buy", "SOL", 1000.0))  # (1000 − 1,00) / 100 = 9,99 SOL (≈ US$ 999): peso igual ao do ETH
    ws.receber_cotacoes(cotacoes(eth=2000.0, var_eth=-4.0), agora=T0 + timedelta(seconds=60))
    assert s.crypto_change == pytest.approx((999.0 * -4.0 + 999.0 * 3.0) / (999.0 + 999.0))  # −0,5%


def test_serie_do_usdc_e_observada(ws):
    s = ws.agents[0].store
    assert len(s.usdc_series()) >= 2
    for i, p in enumerate((1.0, 1.001, 0.999)):
        ws.receber_cotacoes(cotacoes(USDC=p), agora=T0 + timedelta(minutes=i))
    assert s.usdc_series()[-3:] == [1.0, 1.001, 0.999]


# -- nada de sinal simulado ------------------------------------------------------------------------------------------------------------


def test_o_sinal_dos_agentes_e_a_variacao_real_sem_cortes(ws):
    ws.receber_cotacoes(cotacoes(var_eth=31.7), agora=T0)
    assert engine.momentum("ETH", date(2026, 10, 19)) == 31.7  # a demonstração limitaria a 20; o mercado real não
    assert engine.momentum("AVAX", date(2026, 10, 19)) == -9.0
    ws.set_pref("mercado", "simulado")
    assert -15.0 <= engine.momentum("ETH", date(2026, 10, 19)) <= 20.0  # de volta ao sinal simulado, determinístico


def test_agente_momentum_decide_com_o_mercado_real(ws):
    ws.set_config(ws.agents[0].id, strategy="momentum", mode="auto", assets=["SOL", "ETH"])
    ws.receber_cotacoes(cotacoes(var_eth=-4.0), agora=T0)  # SOL +3% e ETH −4%: nada passa do limiar de compra, e não há posição para vender
    feitas, _ = ws.run_agent(ws.agents[0].id, T0)
    (d,) = ws.agents[0].store.decisions
    assert d.kind == "hold" and feitas == 1


# -- sem preço fresco não se opera -----------------------------------------------------------------------------------------------------


def test_sem_preco_ao_vivo_o_agente_nao_decide_e_o_swap_nao_executa(ws):
    ws.set_config(ws.agents[0].id, strategy="dca", mode="auto")
    assert ws.run_agent(ws.agents[0].id, T0) == (0, "Aguardando os preços ao vivo da Binance")
    assert ws.agents[0].store.decisions == []
    assert "Aguardando" in ws.agents[0].store.validate("USD", "ETH", 100.0)


def test_preco_velho_tambem_bloqueia_e_a_volta_da_rede_libera(ws):
    ws.set_config(ws.agents[0].id, strategy="dca", mode="auto")
    ws.receber_cotacoes(cotacoes(), agora=T0)
    assert MERCADO.fresco(T0 + timedelta(seconds=119))
    assert ws.run_agent(ws.agents[0].id, T0 + timedelta(seconds=119))[0] == 1
    assert not MERCADO.fresco(T0 + timedelta(seconds=121))
    assert ws.run_agent(ws.agents[0].id, T0 + timedelta(seconds=121)) == (0, "Aguardando os preços ao vivo da Binance")
    ws.receber_cotacoes(cotacoes(), agora=T0 + timedelta(seconds=125))
    assert ws.run_agent(ws.agents[0].id, T0 + timedelta(seconds=126))[0] == 1


def test_falha_de_rede_mantem_o_ultimo_preco_e_avisa(ws):
    ws.receber_cotacoes(cotacoes(eth=2000.0), agora=T0)
    ws.receber_falha("A Binance está indisponível no momento.")
    assert ASSETS["ETH"].price == 2000.0 and MERCADO.erro == "A Binance está indisponível no momento."
    assert "indispon" in ws.status_mercado(T0 + timedelta(seconds=30))
    ws.receber_cotacoes(cotacoes(eth=2100.0), agora=T0 + timedelta(seconds=40))
    assert MERCADO.erro is None and "12:00:40" in ws.status_mercado(T0 + timedelta(seconds=45))


def test_status_do_modo_simulado_nao_fala_em_binance():
    w = Workspace()
    assert "simulad" in w.status_mercado(T0).lower()


# -- persistência do modo --------------------------------------------------------------------------------------------------------------


def test_o_modo_sobrevive_a_reiniciar_mas_a_carteira_nasce_nova_de_novo(tmp_path):
    caminho = tmp_path / "x.ini"
    primeira = Workspace(QSettings(str(caminho), QSettings.Format.IniFormat))
    primeira.set_pref("mercado", "real")
    primeira.receber_cotacoes(cotacoes(), agora=T0)
    primeira.agents[0].store.executar_trade(_trade("buy", "ETH", 1000.0))
    MERCADO.desativar()
    segunda = Workspace(QSettings(str(caminho), QSettings.Format.IniFormat))
    assert segunda.pref("mercado") == "real" and MERCADO.ativo
    s = segunda.agents[0].store
    assert s.real and s.holdings["USD"] == 10_000.0 and s.decisions == []  # limitação conhecida: as carteiras reais ainda não persistem


# -- tela de configurações -------------------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    from ubento.ui import theme

    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(theme.APP_QSS)
    return a


def test_interruptor_pede_confirmacao_e_so_liga_se_o_usuario_confirmar(app):
    from ubento.ui.settings import SettingsPage

    w = Workspace()
    page = SettingsPage(w)
    perguntas = []
    page._confirm = lambda titulo, texto, botao: perguntas.append(texto) or False
    page.mercado_real.setChecked(True)  # o usuário clica e cancela
    assert w.pref("mercado") == "simulado" and not page.mercado_real.isChecked()
    assert "NOVA" in perguntas[0] and "nada é enviado" in perguntas[0]
    page._confirm = lambda *a: True
    page.mercado_real.setChecked(True)
    assert w.pref("mercado") == "real" and MERCADO.ativo and page.mercado_real.isChecked()
    assert "Buscando" in page._mercado_linha.desc.text()
    w.receber_cotacoes(cotacoes(), agora=datetime.now())
    assert "Preços ao vivo da Binance" in page._mercado_linha.desc.text()  # a linha acompanha as leituras
    page.mercado_real.setChecked(False)
    assert w.pref("mercado") == "simulado" and not MERCADO.ativo


def test_a_interface_inteira_abre_no_mercado_real_e_atualiza_com_as_leituras(app):
    from ubento.ui.main_window import MainWindow

    w = Workspace()
    w.set_pref("mercado", "real")
    janela = MainWindow(w, animations=False)
    janela.show()
    app.processEvents()
    w.receber_cotacoes(cotacoes(eth=2000.0), agora=datetime.now())
    w.agents[0].store.executar_trade(_trade("buy", "ETH", 1000.0))
    w.receber_cotacoes(cotacoes(eth=2100.0), agora=datetime.now() + timedelta(minutes=2))
    app.processEvents()
    from ubento.ui.components import MoneyText

    cartao = janela.dashboard(w.agents[0].id).total
    mostrado = [x._main + x._dec for x in cartao.findChildren(MoneyText)]
    assert "$10.048,95" in mostrado  # 9.000,00 de caixa + 0,4995 ETH × 2.100: o saldo na tela é o do mercado real
    janela.close()


def test_geral_pondera_a_variacao_pelo_valor_de_cada_carteira(ws):
    ws.receber_cotacoes(cotacoes(eth=2000.0, var_eth=-4.0), agora=T0)
    ws.agents[0].store.executar_trade(_trade("buy", "ETH", 1000.0))  # 999 em ETH (−4%)
    ws.agents[1].store.executar_trade(_trade("buy", "SOL", 3000.0))  # 2.997 em SOL (+3%)
    ws.receber_cotacoes(cotacoes(eth=2000.0, var_eth=-4.0), agora=T0 + timedelta(minutes=2))
    esperado = (999.0 * -4.0 + 2997.0 * 3.0) / (999.0 + 2997.0)  # +1,2%: a média simples das duas carteiras (−0,5%) estaria errada
    assert ws.overview.crypto_change == pytest.approx(esperado)


def test_historico_ocupa_a_janela_inteira_com_o_capital_antes_da_carteira_existir(ws):
    ws.receber_cotacoes(cotacoes(), agora=T0)
    ws.receber_cotacoes(cotacoes(eth=2200.0), agora=T0 + timedelta(days=1))
    pontos = ws.agents[0].store.history("1M")
    assert len(pontos) == 30 and pontos[-1][0] == date(2026, 10, 20) and pontos[0][0] == date(2026, 9, 21)
    assert {v for _, v in pontos[:-2]} == {10_000.0}  # antes da carteira existir, a linha é o capital inicial (reta)
