"""Mercado e relógio injetáveis (ADR-001, passo 3): nada de preço global mutável nem de `datetime.now()` escondido no domínio.

Cada `Workspace` tem o seu `Mercado` (preços, sinais, frescor e relógio). Dois mundos convivem sem se tocar, e o tempo é o que o teste disser.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

import ubento.mercado as modulo_mercado  # noqa: E402
import ubento.store as modulo_store  # noqa: E402
from ubento import engine  # noqa: E402
from ubento.cotacoes import Cotacoes  # noqa: E402
from ubento.mercado import ATIVOS, PRECOS_DEMO, Mercado  # noqa: E402
from ubento.store import Store  # noqa: E402
from ubento.workspace import Workspace  # noqa: E402

T0 = datetime(2026, 10, 20, 12, 0, 0)
SRC = Path(__file__).resolve().parent.parent / "src" / "ubento"


class Relogio:
    def __init__(self, inicio):
        self.agora = inicio

    def __call__(self):
        return self.agora


def cotacoes(eth=2000.0):
    return Cotacoes({"ETH": eth, "SOL": 100.0, "AVAX": 10.0, "BNB": 700.0, "USDC": 1.0, "USDT": 1.0, "USD": 1.0}, {"ETH": -4.0, "SOL": 3.0, "AVAX": 0.0, "BNB": 1.0})


# -- sem estado global -----------------------------------------------------------------------------------------------------------------


def test_nao_ha_preco_nem_mercado_globais_no_modulo_da_carteira():
    assert not hasattr(modulo_store, "ASSETS") and not hasattr(modulo_store, "MERCADO")
    assert not hasattr(modulo_mercado, "MERCADO")


def test_dois_mercados_sao_independentes():
    a, b = Mercado(), Mercado()
    a.aplicar({"ETH": 100.0}, {}, T0)
    assert a.preco("ETH") == 100.0 and b.preco("ETH") == PRECOS_DEMO["ETH"] == 3852.93
    assert dict(modulo_mercado.PRECOS_DEMO)["ETH"] == 3852.93  # a tabela de demonstração nunca é tocada


def test_a_tabela_de_ativos_e_so_cadastro_e_nao_muda():
    assert (ATIVOS["ETH"].name, ATIVOS["ETH"].decimals) == ("Ethereum", 5)
    with pytest.raises(AttributeError):
        ATIVOS["ETH"].decimals = 2  # frozen


def test_dois_workspaces_convivem_um_real_e_um_de_demonstracao():
    real, demo = Workspace(), Workspace()
    real.set_pref("mercado", "real")
    real.receber_cotacoes(cotacoes(eth=2000.0), agora=T0)
    assert real.mercado.preco("ETH") == 2000.0 and demo.mercado.preco("ETH") == 3852.93
    assert real.agents[0].store.value_usd("ETH") == 0.0 and demo.agents[0].store.value_usd("ETH") == pytest.approx(2.9934 * 3852.93)
    assert real.mercado.ativo and not demo.mercado.ativo


def test_um_store_avulso_tem_o_seu_proprio_mercado_de_demonstracao():
    s1, s2 = Store(), Store()
    s1.mercado.aplicar({"ETH": 1.0}, {}, T0)
    assert s2.mercado.preco("ETH") == 3852.93 and s1.mercado is not s2.mercado


def test_os_stores_de_um_workspace_e_o_geral_compartilham_o_mesmo_mercado():
    ws = Workspace()
    assert all(a.store.mercado is ws.mercado for a in ws.agents) and ws.overview.mercado is ws.mercado
    assert ws.add("Novo").store.mercado is ws.mercado


# -- relógio injetado ------------------------------------------------------------------------------------------------------------------


def test_o_agente_roda_no_horario_do_relogio_injetado_sem_receber_now():
    relogio = Relogio(T0)
    ws = Workspace(relogio=relogio)
    agente = ws.agents[0]
    agente.store.holdings, agente.store.cost_basis, agente.store.decisions = {"USD": 10_000.0}, {}, []
    ws.set_config(agente.id, strategy="dca", mode="auto", reserve_pct=20, trade_size_pct=25)
    ws.run_agent(agente.id)
    assert agente.store.decisions[0].moment == T0
    relogio.agora = T0 + timedelta(hours=3)
    ws.run_agent(agente.id)
    assert agente.store.decisions[0].moment == T0 + timedelta(hours=3)


def test_o_frescor_do_preco_usa_o_relogio_injetado():
    relogio = Relogio(T0)
    ws = Workspace(relogio=relogio)
    ws.set_pref("mercado", "real")
    ws.set_config(ws.agents[0].id, strategy="dca", mode="auto")
    assert ws.run_agent(ws.agents[0].id)[1].startswith("Aguardando")
    ws.receber_cotacoes(cotacoes())  # sem `agora`: usa o relógio
    assert ws.mercado.atualizado_em == T0
    relogio.agora = T0 + timedelta(seconds=119)
    assert ws.run_agent(ws.agents[0].id)[0] == 1
    relogio.agora = T0 + timedelta(seconds=121)
    assert ws.run_agent(ws.agents[0].id)[1].startswith("Aguardando")  # venceu


def test_o_swap_registra_a_hora_do_relogio_e_conta_a_atividade_do_dia():
    relogio = Relogio(T0)
    s = Store(mercado=Mercado(relogio))
    s.holdings = {"USD": 1000.0}
    antes = s.activity.get(T0.date(), 0)
    assert s.execute("USD", "ETH", 500.0) is None
    assert s.decisions[0].moment == T0 and s.activity[T0.date()] == antes + 1


def test_o_swap_no_modo_real_respeita_o_frescor_pelo_relogio():
    relogio = Relogio(T0)
    ws = Workspace(relogio=relogio)
    ws.set_pref("mercado", "real")
    ws.receber_cotacoes(cotacoes())
    assert ws.agents[0].store.validate("USD", "ETH", 100.0) is None
    relogio.agora = T0 + timedelta(minutes=5)
    assert "Aguardando" in ws.agents[0].store.validate("USD", "ETH", 100.0)


def test_o_motor_sem_now_usa_o_relogio_do_mercado():
    relogio = Relogio(T0)
    s = Store(mercado=Mercado(relogio))
    from ubento.agent_config import AgentConfig

    (d,) = engine.decide(AgentConfig(strategy="dca", trade_size_pct=25, reserve_pct=20), s)
    assert d.moment == T0


def test_o_momentum_usa_a_variacao_real_do_mercado_recebido():
    m = Mercado()
    m.ligar()
    m.aplicar({"ETH": 2000.0}, {"ETH": 31.7}, T0)
    assert engine.momentum("ETH", T0.date(), m) == 31.7
    assert -15.0 <= engine.momentum("ETH", T0.date(), Mercado()) <= 20.0  # demonstração: simulado e limitado


# -- o domínio não lê o relógio do sistema ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("arquivo", ["store.py", "engine.py", "workspace.py", "mercado.py", "ponte_metas.py", "ui/agent_page.py", "ui/cards/decisions.py"])
def test_dominio_e_telas_nao_chamam_datetime_now(arquivo):
    codigo = (SRC / arquivo).read_text(encoding="utf-8")
    assert "datetime.now()" not in codigo and "datetime.utcnow()" not in codigo
