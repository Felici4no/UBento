"""Agendador (ADR-001, passo 6): os agentes rodam sozinhos na frequência configurada, enquanto o app estiver aberto.

O relógio é o do `Mercado` do Workspace (injetável), então nada aqui espera tempo de verdade. Regras:
- vence o horário seguinte ao último `last_run` (ou, sem execução anterior, ao instante em que o agendador nasceu);
- vários horários perdidos viram UMA execução, não uma rajada;
- só conta como executado o que o `Workspace.run_agent` de fato rodou: sem preço fresco (mercado real) tenta de novo no próximo ciclo, sem alarde.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ubento.agendador import Agendador  # noqa: E402
from ubento.agent_config import AgentConfig, vencida  # noqa: E402
from ubento.cotacoes import Cotacoes  # noqa: E402
from ubento.workspace import Workspace  # noqa: E402

TER = datetime(2026, 10, 20, 12, 0)  # terça-feira


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class Relogio:
    def __init__(self, inicio):
        self.agora = inicio

    def __call__(self):
        return self.agora


def cotacoes():
    return Cotacoes({"ETH": 2000.0, "SOL": 100.0, "AVAX": 10.0, "BNB": 700.0, "USDC": 1.0, "USDT": 1.0, "USD": 1.0}, {"ETH": 1.0, "SOL": 1.0, "AVAX": 1.0, "BNB": 1.0})


# -- quando um horário vence (puro) ------------------------------------------------------------------------------------------------------


def cfg(frequencia, **extra):
    return AgentConfig(strategy="dca", frequency=frequencia, **extra).validated()


@pytest.mark.parametrize("agora, esperado", [
    (datetime(2026, 10, 20, 10, 59, 59), False),  # antes das 11h
    (datetime(2026, 10, 20, 11, 0, 0), True),  # no instante, já venceu
    (datetime(2026, 10, 20, 15, 0, 0), True),
])
def test_de_hora_em_hora_vence_na_virada_da_hora_seguinte(agora, esperado):
    assert vencida(cfg("hourly"), datetime(2026, 10, 20, 10, 30), agora) is esperado


@pytest.mark.parametrize("referencia, agora, esperado", [
    (datetime(2026, 10, 20, 8, 0), datetime(2026, 10, 20, 8, 59, 59), False),  # roda às 9h do mesmo dia
    (datetime(2026, 10, 20, 8, 0), datetime(2026, 10, 20, 9, 0, 0), True),
    (datetime(2026, 10, 20, 9, 0), datetime(2026, 10, 20, 23, 59, 59), False),  # rodou às 9h: o próximo é amanhã
    (datetime(2026, 10, 20, 9, 0), datetime(2026, 10, 21, 9, 0, 0), True),
    (datetime(2026, 10, 20, 12, 0), datetime(2026, 10, 21, 8, 59, 59), False),
])
def test_diaria_vence_as_9h(referencia, agora, esperado):
    assert vencida(cfg("daily"), referencia, agora) is esperado


@pytest.mark.parametrize("agora, esperado", [
    (datetime(2026, 10, 25, 23, 59, 59), False),  # domingo
    (datetime(2026, 10, 26, 9, 0, 0), True),  # segunda-feira, 9h
])
def test_semanal_vence_na_segunda_as_9h(agora, esperado):
    assert vencida(cfg("weekly"), TER, agora) is esperado  # a referência é a terça 20/10


def test_agente_pausado_ou_manual_nunca_vence():
    assert not vencida(cfg("hourly", active=False), TER, TER + timedelta(days=9))
    assert not vencida(AgentConfig(strategy="manual", frequency="hourly").validated(), TER, TER + timedelta(days=9))


# -- o agendador -----------------------------------------------------------------------------------------------------------------------


def montar(relogio=None, **cfg_extra):
    relogio = relogio or Relogio(TER)
    ws = Workspace(relogio=relogio)
    agente = ws.agents[0]
    agente.store.holdings, agente.store.cost_basis, agente.store.decisions = {"USD": 10_000.0}, {}, []
    ws.set_config(agente.id, strategy="dca", mode=cfg_extra.pop("mode", "auto"), frequency=cfg_extra.pop("frequency", "daily"), reserve_pct=20, trade_size_pct=25, **cfg_extra)
    for outro in ws.agents[1:]:
        ws.set_config(outro.id, active=False)  # só o primeiro participa dos testes
    ag = Agendador(ws)
    execucoes: list[tuple] = []
    ag.executou.connect(lambda a, n, m: execucoes.append((a, n, m)))
    return ws, ag, agente, relogio, execucoes


def marcar_ultima(ws, agente, quando):
    ws.agent(agente.id).config.last_run = quando.isoformat(timespec="seconds")


def test_agente_vencido_roda_uma_vez_e_registra_o_horario(app):
    ws, ag, agente, relogio, execucoes = montar()
    marcar_ultima(ws, agente, datetime(2026, 10, 19, 9, 0))  # rodou ontem às 9h; o horário de hoje (9h) já passou
    ag.verificar()
    assert len(agente.store.decisions) == 1 and execucoes[0][:2] == (agente.id, 1)
    assert ws.agent(agente.id).config.last_run == TER.isoformat(timespec="seconds")
    ag.verificar()  # no mesmo instante: nada novo
    assert len(agente.store.decisions) == 1 and len(execucoes) == 1


def test_ainda_nao_venceu_nao_roda(app):
    ws, ag, agente, relogio, execucoes = montar()
    marcar_ultima(ws, agente, datetime(2026, 10, 20, 9, 0))  # já rodou hoje às 9h
    ag.verificar()
    assert agente.store.decisions == [] and execucoes == []


def test_roda_de_novo_no_proximo_horario(app):
    ws, ag, agente, relogio, execucoes = montar()
    marcar_ultima(ws, agente, datetime(2026, 10, 20, 9, 0))
    relogio.agora = datetime(2026, 10, 21, 8, 59)
    ag.verificar()
    assert execucoes == []
    relogio.agora = datetime(2026, 10, 21, 9, 0)
    ag.verificar()
    assert len(execucoes) == 1


def test_horarios_perdidos_com_o_app_fechado_viram_uma_execucao_so(app):
    ws, ag, agente, relogio, execucoes = montar()
    marcar_ultima(ws, agente, TER - timedelta(days=7))  # sete 9h perdidas
    ag.verificar()
    ag.verificar()
    assert len(execucoes) == 1 and len(agente.store.decisions) == 1


def test_sem_execucao_anterior_a_referencia_e_o_nascimento_do_agendador(app):
    ws, ag, agente, relogio, execucoes = montar()  # nasceu terça 12h, nunca rodou
    relogio.agora = datetime(2026, 10, 21, 8, 59)
    ag.verificar()
    assert execucoes == []  # o 9h de hoje (terça) passou ANTES de o app abrir: não conta
    relogio.agora = datetime(2026, 10, 21, 9, 0)
    ag.verificar()
    assert len(execucoes) == 1


def test_pausado_manual_e_agendador_desligado_nao_rodam(app):
    ws, ag, agente, relogio, execucoes = montar()
    marcar_ultima(ws, agente, TER - timedelta(days=3))
    ws.set_config(agente.id, active=False)
    ag.verificar()
    ws.set_config(agente.id, active=True, strategy="manual")
    ag.verificar()
    ws.set_config(agente.id, strategy="dca")
    ws.set_pref("agendador", False)
    ag.verificar()
    assert execucoes == [] and agente.store.decisions == []
    ws.set_pref("agendador", True)
    ag.verificar()
    assert len(execucoes) == 1  # religado, o que estava vencido roda


def test_modo_aprovacao_propoe_e_a_mensagem_diz_quantas(app):
    ws, ag, agente, relogio, execucoes = montar(mode="approve")
    marcar_ultima(ws, agente, TER - timedelta(days=2))
    ag.verificar()
    assert agente.store.decisions[0].status == "proposed" and execucoes[0][2] == "1 propostas aguardando você"


def test_mercado_real_sem_preco_fresco_tenta_de_novo_sem_alarde(app):
    ws, ag, agente, relogio, execucoes = montar()
    ws.set_pref("mercado", "real")
    marcar_ultima(ws, agente, TER - timedelta(days=2))
    for _ in range(3):
        ag.verificar()  # sem leitura da Binance ainda
    assert execucoes == [] and ws.agent(agente.id).config.last_run == (TER - timedelta(days=2)).isoformat(timespec="seconds")
    ws.receber_cotacoes(cotacoes())
    ag.verificar()
    assert len(execucoes) == 1  # chegou o preço: roda uma vez, sem ter feito barulho antes


def test_falha_numa_execucao_nao_derruba_os_outros_agentes_e_avisa_uma_vez(app):
    ws, ag, agente, relogio, execucoes = montar()
    segundo = ws.agents[1]
    segundo.store.holdings, segundo.store.decisions = {"USD": 10_000.0}, []
    ws.set_config(segundo.id, active=True, strategy="dca", mode="auto", frequency="daily", reserve_pct=20, trade_size_pct=25)
    marcar_ultima(ws, agente, TER - timedelta(days=2))
    marcar_ultima(ws, segundo, TER - timedelta(days=2))
    original, falhas = ws.run_agent, []
    ag.falhou.connect(falhas.append)

    def quebra(agent_id, *args, **kwargs):
        if agent_id == agente.id:
            raise RuntimeError("bug no algoritmo")
        return original(agent_id, *args, **kwargs)

    ws.run_agent = quebra
    ag.verificar()
    ag.verificar()
    assert len(falhas) == 1 and "bug no algoritmo" in falhas[0]  # avisa uma vez, não a cada ciclo
    assert [e[0] for e in execucoes] == [segundo.id]  # o outro agente rodou normalmente


def test_o_horario_executado_sobrevive_a_reiniciar(tmp_path, app):
    ini = str(tmp_path / "cfg.ini")
    relogio = Relogio(TER)
    ws = Workspace(QSettings(ini, QSettings.Format.IniFormat), relogio=relogio)
    agente = ws.agents[0]
    agente.store.holdings, agente.store.decisions = {"USD": 10_000.0}, []
    ws.set_config(agente.id, strategy="dca", mode="auto", frequency="daily")
    for outro in ws.agents[1:]:
        ws.set_config(outro.id, active=False)
    marcar_ultima(ws, agente, TER - timedelta(days=2))
    Agendador(ws).verificar()
    outra = Workspace(QSettings(ini, QSettings.Format.IniFormat), relogio=Relogio(TER + timedelta(hours=1)))
    assert outra.agent(agente.id).config.last_run == TER.isoformat(timespec="seconds")
    ag2, rodou = Agendador(outra), []
    ag2.executou.connect(lambda a, n, m: rodou.append(a))
    ag2.verificar()
    assert rodou == []  # o horário de hoje já foi cumprido antes de reiniciar: não roda de novo


# -- com o relógio de verdade (timer) ------------------------------------------------------------------------------------------------------


def test_o_timer_verifica_sozinho_depois_do_atraso_inicial(app):
    ws, _, agente, relogio, _ = montar()
    marcar_ultima(ws, agente, TER - timedelta(days=2))
    ag = Agendador(ws, intervalo_ms=20, atraso_inicial_ms=150)
    feitas = []
    ag.executou.connect(lambda a, n, m: feitas.append(a))
    ag.iniciar()
    try:
        QTest.qWait(60)
        assert feitas == []  # ainda no atraso inicial: dá tempo de os preços chegarem antes de operar
        QTest.qWait(300)
        assert feitas == [agente.id]
    finally:
        ag.parar()


def test_parar_para_de_verificar(app):
    ws, _, agente, relogio, _ = montar()
    ag = Agendador(ws, intervalo_ms=10, atraso_inicial_ms=0)
    ag.iniciar()
    ag.parar()
    marcar_ultima(ws, agente, TER - timedelta(days=2))
    QTest.qWait(80)
    assert agente.store.decisions == []


# -- a janela e as telas -------------------------------------------------------------------------------------------------------------------


def test_a_janela_liga_o_agendador_e_avisa_quando_um_agente_roda(app):
    from ubento.ui.main_window import MainWindow

    relogio = Relogio(TER)
    ws = Workspace(relogio=relogio)
    agente = ws.agents[0]
    agente.store.holdings, agente.store.decisions = {"USD": 10_000.0}, []
    ws.set_config(agente.id, strategy="dca", mode="auto", frequency="daily")
    marcar_ultima(ws, agente, TER - timedelta(days=2))
    janela = MainWindow(ws, animations=False)
    avisos = []
    janela.toast.show_message = lambda m, ok=True: avisos.append((m, ok))
    assert janela.agendador is not None
    janela.agendador.verificar()
    assert avisos and "decisões executadas" in avisos[0][0] and avisos[0][1] is True and avisos[0][0].startswith("Pessoal: ")
    janela.close()


def test_interruptor_do_agendador_em_configuracoes(app):
    from ubento.ui.settings import SettingsPage

    ws = Workspace()
    page = SettingsPage(ws)
    assert page.agendador_ligado.isChecked() and ws.pref("agendador") is True
    page.agendador_ligado.setChecked(False)
    assert ws.pref("agendador") is False
    ws.set_pref("agendador", True)
    assert page.agendador_ligado.isChecked()  # a tela acompanha a preferência


def test_a_pagina_do_agente_diz_a_verdade_sobre_a_proxima_execucao(app):
    from ubento.ui.agent_page import AgentConfigPage

    relogio = Relogio(TER)
    ws = Workspace(relogio=relogio)
    agente = ws.agents[0]
    ws.set_config(agente.id, strategy="dca", frequency="daily")
    page = AgentConfigPage(ws, agente.id)
    marcar_ultima(ws, agente, TER - timedelta(days=2))
    page.sync()
    assert "vencida" in page.schedule.text() and "roda só com o app aberto" in page.schedule.text()
    marcar_ultima(ws, agente, datetime(2026, 10, 20, 9, 0))
    page.sync()
    assert "amanhã, 09:00" in page.schedule.text()
    ws.set_pref("agendador", False)
    page.sync()
    assert "automática desligada" in page.schedule.text()
