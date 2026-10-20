"""Carteiras do mercado real persistem (ADR-001, passo 4): reiniciar o app não zera mais o capital, as posições, as decisões e o gráfico.

Só o mercado real persiste (a demonstração continua efêmera). Um "reinício" aqui é abrir de novo os mesmos arquivos: o `QSettings` (agentes e modo)
e o banco SQLite.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ubento import engine  # noqa: E402
from ubento.carteira_serial import estado_da_carteira  # noqa: E402
from ubento.cotacoes import Cotacoes  # noqa: E402
from ubento.metas import ServicoMetas  # noqa: E402
from ubento.persistencia import Repositorio  # noqa: E402
from ubento.persistencia.carteiras import RepositorioCarteiras  # noqa: E402
from ubento.persistencia_carteiras import PersistenciaCarteiras  # noqa: E402
from ubento.store import CAPITAL_INICIAL_REAL, Decision  # noqa: E402
from ubento.workspace import Workspace  # noqa: E402

T0 = datetime(2026, 10, 20, 12, 0, 0)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def cotacoes(eth=2000.0):
    return Cotacoes({"ETH": eth, "SOL": 100.0, "AVAX": 10.0, "BNB": 700.0, "USDC": 1.0, "USDT": 1.0, "USD": 1.0}, {"ETH": -4.0, "SOL": 3.0, "AVAX": 0.0, "BNB": 1.0})


class Relogio:
    def __init__(self, inicio):
        self.agora = inicio

    def __call__(self):
        return self.agora


class Sessao:
    """Uma execução do app sobre os mesmos arquivos. `abrir` de novo = reiniciar."""

    def __init__(self, pasta, relogio=None, atraso_ms=0):
        self.relogio = relogio or Relogio(T0)
        self.repo = Repositorio(pasta / "ubento.db")
        self.ws = Workspace(QSettings(str(pasta / "cfg.ini"), QSettings.Format.IniFormat), relogio=self.relogio)
        self.ctrl = PersistenciaCarteiras(self.ws, self.repo, atraso_ms=atraso_ms)
        self.avisos: list[str] = []
        self.ctrl.falhou.connect(self.avisos.append)
        QApplication.processEvents()  # os avisos da restauração inicial são entregues depois que alguém se conecta

    @property
    def agente(self):
        return self.ws.agents[0]

    def fechar(self):
        self.repo.fechar()


@pytest.fixture
def pasta(tmp_path):
    return tmp_path


def compra(sessao, usd=1000.0):
    d = engine._buy(sessao.ws.mercado, "ETH", usd, "Compra", sessao.relogio.agora)
    return Decision(**{**d.__dict__, "status": "executed", "pnl_usd": -d.trade.fee, "pnl_realizado": False})


def ligar_mercado_real(s):
    s.ws.set_pref("mercado", "real")
    s.ws.receber_cotacoes(cotacoes())


# -- o essencial -----------------------------------------------------------------------------------------------------------------------


def test_a_carteira_real_sobrevive_a_reiniciar(pasta, app):
    a = Sessao(pasta)
    ligar_mercado_real(a)
    agente_id = a.agente.id
    assert a.agente.store.add_decision(compra(a)) is None
    a.ws.receber_cotacoes(cotacoes(eth=2200.0))
    a.ctrl.salvar_tudo()
    esperado = (dict(a.agente.store.holdings), [d.uid for d in a.agente.store.decisions], list(a.agente.store.pontos))
    a.fechar()

    b = Sessao(pasta)  # o app abriu de novo
    assert b.agente.id == agente_id and b.ws.mercado_real
    s = b.agente.store
    assert (dict(s.holdings), [d.uid for d in s.decisions], list(s.pontos)) == esperado
    assert s.holdings["USD"] == 9000.0 and s.holdings["ETH"] == 0.4995  # não voltou aos US$ 10.000
    assert s.decisions[0].pnl_usd == -1.0 and s.decisions[0].trade.preco == 2000.0
    b.fechar()


def test_o_gafico_continua_do_ponto_onde_parou(pasta, app):
    a = Sessao(pasta)
    ligar_mercado_real(a)
    a.relogio.agora = T0 + timedelta(minutes=5)
    a.ws.receber_cotacoes(cotacoes(eth=2100.0))
    a.ctrl.salvar_tudo()
    pontos_antes = len(a.agente.store.pontos)
    a.fechar()
    b = Sessao(pasta, Relogio(T0 + timedelta(days=1)))
    assert len(b.agente.store.pontos) == pontos_antes >= 2
    b.ws.receber_cotacoes(cotacoes(eth=2100.0))
    assert len(b.agente.store.pontos) == pontos_antes + 1  # o novo ponto entra depois dos antigos
    assert b.agente.store.history("1S")[-1][1] == pytest.approx(b.agente.store.total_usd())
    b.fechar()


def test_a_demonstracao_nunca_grava(pasta, app):
    a = Sessao(pasta)
    a.agente.store.add_decision(compra(a))
    a.ctrl.salvar_tudo()
    assert a.repo.con.execute("SELECT COUNT(*) FROM carteiras").fetchone()[0] == 0
    assert a.repo.con.execute("SELECT COUNT(*) FROM carteira_pontos").fetchone()[0] == 0
    a.fechar()


def test_desligar_o_mercado_real_guarda_a_carteira_e_ligar_de_novo_a_devolve(pasta, app):
    a = Sessao(pasta)
    ligar_mercado_real(a)
    a.agente.store.add_decision(compra(a))
    antes = dict(a.agente.store.holdings)
    a.ws.set_pref("mercado", "simulado")  # a carteira real sai de cena (e é guardada na saída)
    assert a.agente.store.holdings["ETH"] == pytest.approx(2.9934)  # demonstração
    a.ctrl.salvar_tudo()  # não pode sobrescrever a carteira real com a demonstração
    a.ws.set_pref("mercado", "real")
    assert dict(a.agente.store.holdings) == antes
    a.fechar()


def test_nao_sobrescreve_a_carteira_guardada_antes_de_restaura_la(pasta, app):
    a = Sessao(pasta)
    ligar_mercado_real(a)
    a.agente.store.add_decision(compra(a))
    a.ctrl.salvar_tudo()
    guardado = a.ctrl.repo.carregar(a.agente.id)
    a.fechar()
    b = Sessao(pasta)  # abriu em mercado real: a carteira nova do início NÃO pode ir para o banco antes da restauração
    b.ctrl.salvar_tudo()
    assert b.ctrl.repo.carregar(b.agente.id) == guardado
    b.fechar()


def test_ultimo_preco_lido_volta_mas_vencido_e_nao_libera_operacao(pasta, app):
    a = Sessao(pasta)
    ligar_mercado_real(a)
    a.agente.store.add_decision(compra(a))
    a.ctrl.salvar_tudo()
    a.fechar()
    b = Sessao(pasta, Relogio(T0 + timedelta(hours=1)))
    assert b.ws.mercado.preco("ETH") == 2000.0  # o último preço lido, não o de demonstração
    assert b.agente.store.total_usd() == pytest.approx(9000.0 + 0.4995 * 2000.0)  # patrimônio coerente desde o primeiro quadro
    assert not b.ws.mercado.fresco()  # mas é de uma hora atrás
    b.ws.set_config(b.agente.id, strategy="dca", mode="auto")
    assert b.ws.run_agent(b.agente.id)[1].startswith("Aguardando")
    b.fechar()


# -- agentes ---------------------------------------------------------------------------------------------------------------------------


def test_agente_removido_tem_a_carteira_arquivada_e_as_metas_continuam(pasta, app, tmp_path):
    a = Sessao(pasta)
    ligar_mercado_real(a)
    a.agente.store.add_decision(compra(a))
    segundo = a.ws.agents[1]
    a.ctrl.salvar_tudo()
    removido = a.agente.id
    servico = ServicoMetas(a.repo)
    from pathlib import Path

    from ubento.nucleo.avaliacao.reproducao import carregar_reproducao_meta

    cenario = carregar_reproducao_meta(Path(__file__).resolve().parent.parent / "exemplos" / "avaliacao" / "01_parcial_ate_atingir.yaml")
    meta_id = servico.importar(cenario, agente_id=removido)
    a.ws.remove(removido)
    assert [x for x, _ in a.ctrl.repo.arquivadas()] == [removido]
    assert a.ctrl.repo.carregar(removido) is None and a.ctrl.repo.carregar(segundo.id) is not None
    assert meta_id in servico.repo.metas_ids() and servico.repo.agente_da_meta(meta_id) == removido  # a evidência não some
    a.fechar()


def test_restaurar_as_abas_padrao_arquiva_as_carteiras_antigas(pasta, app):
    a = Sessao(pasta)
    ligar_mercado_real(a)
    a.ctrl.salvar_tudo()
    antigos = sorted(x.id for x in a.ws.agents)
    a.ws.restore_default_agents()
    assert sorted(x for x, _ in a.ctrl.repo.arquivadas()) == antigos
    a.fechar()


def test_agente_duplicado_e_novo_sao_guardados_cada_um_na_sua_linha(pasta, app):
    a = Sessao(pasta)
    ligar_mercado_real(a)
    copia = a.ws.duplicate(a.agente.id)
    novo = a.ws.add("Novo")
    a.agente.store.add_decision(compra(a))
    a.ctrl.salvar_tudo()
    ids = {r[0] for r in a.repo.con.execute("SELECT agente_id FROM carteiras")}
    assert ids == {x.id for x in a.ws.agents} and {copia.id, novo.id} <= ids
    a.fechar()


# -- robustez --------------------------------------------------------------------------------------------------------------------------


def test_estado_ilegivel_nao_derruba_nao_e_sobrescrito_e_vira_aviso(pasta, app):
    a = Sessao(pasta)
    ligar_mercado_real(a)
    a.ctrl.salvar_tudo()
    ruim = {"versao": 99, "lixo": True}
    a.ctrl.repo.salvar(a.agente.id, ruim, "2026-10-20T12:00:00Z")
    a.fechar()
    b = Sessao(pasta)
    assert b.agente.store.holdings["USD"] == CAPITAL_INICIAL_REAL and any("ilegível" in x for x in b.avisos)
    b.agente.store.add_decision(compra(b))
    b.ctrl.salvar_tudo()
    assert b.ctrl.repo.carregar(b.agente.id) == ruim  # o dado antigo é preservado para análise, nunca apagado em silêncio
    b.fechar()


def test_json_corrompido_no_banco_tambem_e_tratado(pasta, app):
    a = Sessao(pasta)
    ligar_mercado_real(a)
    a.ctrl.salvar_tudo()
    a.repo.con.execute("UPDATE carteiras SET estado = '{nao e json' WHERE agente_id = ?", (a.agente.id,))
    a.repo.con.commit()
    a.fechar()
    b = Sessao(pasta)
    assert any("ilegível" in x for x in b.avisos) and b.agente.store.holdings["USD"] == CAPITAL_INICIAL_REAL
    b.fechar()


def test_falha_ao_gravar_vira_aviso_e_a_carteira_segue_intacta(pasta, app):
    a = Sessao(pasta)
    ligar_mercado_real(a)

    def quebra(*args, **kwargs):
        raise RuntimeError("disco cheio")

    a.ctrl.repo.salvar = quebra
    a.agente.store.add_decision(compra(a))
    a.ctrl.salvar_tudo()
    assert a.agente.store.holdings["ETH"] == 0.4995 and any("disco cheio" in x for x in a.avisos)
    a.ctrl.salvar_tudo()
    assert sum("disco cheio" in x for x in a.avisos) == 1  # avisa uma vez, não a cada tentativa
    a.fechar()


def test_estado_igual_nao_e_regravado(pasta, app):
    a = Sessao(pasta)
    ligar_mercado_real(a)
    chamadas = []
    original = a.ctrl.repo.salvar
    a.ctrl.repo.salvar = lambda *args, **kw: (chamadas.append(args[0]), original(*args, **kw))[1]
    a.ctrl.salvar_tudo()
    a.ctrl.salvar_tudo()
    a.ws.receber_cotacoes(cotacoes())  # só o preço mexeu: o estado da carteira (saldos e decisões) é o mesmo
    a.ctrl.salvar_tudo()
    assert len(chamadas) == len(a.ws.agents)  # uma vez por agente
    a.fechar()


def test_mudancas_sao_gravadas_sozinhas_depois_de_um_instante(pasta, app):
    a = Sessao(pasta, atraso_ms=10)
    ligar_mercado_real(a)
    a.agente.store.add_decision(compra(a))
    QTest.qWait(120)
    app.processEvents()
    estado = a.ctrl.repo.carregar(a.agente.id)
    assert estado is not None and estado["holdings"]["ETH"] == "0.4995"
    a.fechar()


def test_o_banco_guarda_texto_decimal_e_utc(pasta, app):
    a = Sessao(pasta)
    ligar_mercado_real(a)
    a.agente.store.add_decision(compra(a))
    a.ctrl.salvar_tudo()
    bruto = json.loads(a.repo.con.execute("SELECT estado FROM carteiras WHERE agente_id = ?", (a.agente.id,)).fetchone()[0])
    assert bruto["holdings"]["ETH"] == "0.4995" and bruto["decisions"][0]["momento"].endswith("Z")
    assert all(q.endswith("Z") for q, _ in a.ctrl.repo.pontos(a.agente.id))
    assert bruto == estado_da_carteira(a.agente.store)
    a.fechar()


def test_a_janela_liga_a_persistencia(pasta, app):
    from ubento.ui.main_window import MainWindow

    a = Sessao(pasta)
    janela = MainWindow(a.ws, animations=False, metas=ServicoMetas(a.repo))
    assert janela.persistencia_carteiras is not None
    janela.close()
    a.fechar()


def test_repositorio_de_carteiras_aceita_o_repositorio_de_metas_direto(pasta):
    r = Repositorio(pasta / "q.db")
    assert isinstance(PersistenciaCarteiras(Workspace(), r).repo, RepositorioCarteiras)
    r.fechar()
