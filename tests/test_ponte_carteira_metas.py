"""Ponte carteira → núcleo: uma COMPRA executada pelo agente vira uma execução da meta do mesmo agente, em `Decimal` e UTC.

Regras (ADR-001): só decisão executada com movimento; só compra (o núcleo mede aquisição, não tem venda); só meta do mesmo agente, do mesmo
ativo e ainda aberta; a execução nasce SIMULADA e SEM registro externo, então registrar não comprova nada.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timezone  # noqa: E402
from decimal import Decimal  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from ubento import engine  # noqa: E402
from ubento.metas import ServicoMetas  # noqa: E402
from ubento.nucleo.avaliacao.reproducao import carregar_reproducao_meta  # noqa: E402
from ubento.nucleo.esquema import EstadoMeta, Execucao, LadoExecucao, OrigemDado  # noqa: E402
from ubento.ponte_metas import FONTE_CARTEIRA, NaoAplicavel, PonteCarteiraMetas, execucao_da_decisao  # noqa: E402
from ubento.mercado import Mercado  # noqa: E402
from ubento.store import Decision, Trade  # noqa: E402
from ubento.workspace import Workspace  # noqa: E402

UTC = timezone.utc
CENARIO = Path(__file__).resolve().parent.parent / "exemplos" / "avaliacao" / "01_parcial_ate_atingir.yaml"
DENTRO = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)  # a meta vai de 20/10 08:00Z a 16:00Z


def local(instante_utc: datetime) -> datetime:
    """A carteira guarda a hora local ingênua; este é o mesmo instante nesse formato (o teste vale em qualquer fuso)."""
    return instante_utc.astimezone().replace(tzinfo=None)


class Atual:
    """O mercado do teste em curso (cada teste tem o seu; não existe mercado global)."""

    mercado: Mercado


@pytest.fixture(autouse=True)
def mercado_do_teste():
    Atual.mercado = Mercado()
    yield Atual.mercado


@pytest.fixture
def arquivo_eth(tmp_path):
    """O cenário 01, com o ativo trocado para ETH (cotado em USD)."""
    destino = tmp_path / "eth.yaml"
    destino.write_text(CENARIO.read_text(encoding="utf-8").replace("tokx", "eth"), encoding="utf-8")
    base = carregar_reproducao_meta(destino)
    return base.model_copy(update={"execucoes": (), "registros_externos": (), "coberturas_execucoes": ()})


def com_preco(preco: float) -> None:
    Atual.mercado.aplicar({"ETH": preco}, {}, DENTRO)


def compra_executada(usd=1000.0, quando=DENTRO, simbolo="ETH") -> Decision:
    d = engine._buy(Atual.mercado, simbolo, usd, "Compra recorrente", local(quando))
    return Decision(**{**d.__dict__, "status": "executed", "pnl_usd": -d.trade.fee, "pnl_realizado": False})


def painel_de(servico, meta_id):
    return servico.painel(meta_id)


# -- a conversão, com contas à mão -----------------------------------------------------------------------------------------------------


def test_compra_vira_execucao_em_decimal_e_utc(arquivo_eth):
    com_preco(2000.0)  # compra de US$ 1.000: taxa 0,10% = 1,00 sai do que se recebe → entram (1000 − 1) / 2000 = 0,4995 ETH
    d = compra_executada(1000.0)
    ex = execucao_da_decisao(d, arquivo_eth.meta, DENTRO.replace(hour=8))
    assert (ex.id, ex.meta_id, ex.ativo_id, ex.lado) == (f"dec-{d.uid}", arquivo_eth.meta.id, "eth", LadoExecucao.COMPRA)
    assert ex.quantidade_liquida == Decimal("0.4995")  # o que a carteira recebeu
    assert ex.taxa_no_ativo == Decimal("0.0005")  # 1,00 USD de taxa ÷ 2.000 = 0,0005 ETH, cobrada no próprio ativo
    assert ex.quantidade_bruta == Decimal("0.5000")  # bruta = líquida + taxa
    assert ex.preco_executado == Decimal("2000")
    assert ex.quantidade_bruta * ex.preco_executado == Decimal("1000")  # fecha com o caixa que saiu
    assert (ex.taxa_na_cotacao, ex.custo_fixo_real, ex.referencias_externas) == (0, 0, ())


def test_arredondamento_das_unidades_nao_perde_mais_que_o_ultimo_digito(arquivo_eth):
    com_preco(3852.93)  # 999 / 3.852,93 = 0,25928 ETH (5 casas); taxa 1,00 / 3.852,93 = 0,00026
    ex = execucao_da_decisao(compra_executada(1000.0), arquivo_eth.meta, DENTRO.replace(hour=8))
    assert (ex.quantidade_liquida, ex.taxa_no_ativo, ex.quantidade_bruta) == (Decimal("0.25928"), Decimal("0.00026"), Decimal("0.25954"))
    assert abs(ex.quantidade_bruta * ex.preco_executado - Decimal("1000")) < Decimal("0.05")  # só a sobra do arredondamento a 5 casas


def test_instantes_saem_em_utc_com_fuso(arquivo_eth):
    com_preco(2000.0)
    ex = execucao_da_decisao(compra_executada(quando=DENTRO), arquivo_eth.meta, DENTRO.replace(hour=8))
    assert ex.executada_em == ex.confirmada_em == DENTRO and ex.executada_em.utcoffset().total_seconds() == 0


def test_a_execucao_nasce_simulada_sem_registro_externo(arquivo_eth):
    com_preco(2000.0)
    ex = execucao_da_decisao(compra_executada(), arquivo_eth.meta, DENTRO.replace(hour=8))
    assert ex.origem is OrigemDado.SIMULADO and ex.fonte_id == FONTE_CARTEIRA and ex.moeda_cotacao_id == "usd"


def test_o_preco_vem_da_ordem_e_nao_do_preco_de_hoje(arquivo_eth):
    com_preco(2000.0)
    d = compra_executada(1000.0)
    com_preco(2500.0)  # o mercado andou depois da ordem
    assert execucao_da_decisao(d, arquivo_eth.meta, DENTRO.replace(hour=8)).preco_executado == Decimal("2000")


# -- o que NÃO vira execução -------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("mudar, trecho", [
    (dict(status="proposed"), "executada"),
    (dict(status="approved"), "executada"),
    (dict(trade=None), "movimento"),
])
def test_so_decisao_executada_com_movimento(arquivo_eth, mudar, trecho):
    com_preco(2000.0)
    d = compra_executada()
    with pytest.raises(NaoAplicavel, match=trecho):
        execucao_da_decisao(Decision(**{**d.__dict__, **mudar}), arquivo_eth.meta, DENTRO.replace(hour=8))


def test_venda_nao_entra_porque_o_nucleo_mede_aquisicao(arquivo_eth):
    com_preco(2000.0)
    venda = engine._sell(Atual.mercado, "ETH", 500.0, "Realizou lucro", local(DENTRO))
    with pytest.raises(NaoAplicavel, match="venda"):
        execucao_da_decisao(Decision(**{**venda.__dict__, "status": "executed"}), arquivo_eth.meta, DENTRO.replace(hour=8))


def test_outro_ativo_nao_entra(arquivo_eth):
    Atual.mercado.aplicar({"SOL": 100.0}, {}, DENTRO)
    with pytest.raises(NaoAplicavel, match="ativo"):
        execucao_da_decisao(compra_executada(simbolo="SOL"), arquivo_eth.meta, DENTRO.replace(hour=8))


def test_moeda_de_cotacao_diferente_do_dolar_nao_entra(arquivo_eth):
    com_preco(2000.0)
    em_reais = arquivo_eth.meta.model_copy(update={"objetivo": arquivo_eth.meta.objetivo.model_copy(update={"moeda_cotacao_id": "brl"})})
    with pytest.raises(NaoAplicavel, match="moeda"):
        execucao_da_decisao(compra_executada(), em_reais, DENTRO.replace(hour=8))


def test_antes_da_ativacao_e_depois_do_prazo_nao_entra(arquivo_eth):
    com_preco(2000.0)
    ativada = DENTRO.replace(hour=8)
    with pytest.raises(NaoAplicavel, match="antes da ativação"):
        execucao_da_decisao(compra_executada(quando=DENTRO.replace(hour=7, minute=59)), arquivo_eth.meta, ativada)
    with pytest.raises(NaoAplicavel, match="depois do prazo"):
        execucao_da_decisao(compra_executada(quando=DENTRO.replace(hour=16, minute=1)), arquivo_eth.meta, ativada)
    assert execucao_da_decisao(compra_executada(quando=DENTRO.replace(hour=16)), arquivo_eth.meta, ativada)  # no instante do prazo ainda vale


# -- de ponta a ponta --------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def mundo(arquivo_eth):
    ws = Workspace()
    Atual.mercado = ws.mercado  # as ordens do teste usam o mesmo mercado da carteira
    servico = ServicoMetas()
    agente = ws.agents[0]
    agente.store.holdings, agente.store.cost_basis, agente.store.decisions = {"USD": 10_000.0}, {}, []
    meta_id = servico.importar(arquivo_eth, agente_id=agente.id)
    ponte = PonteCarteiraMetas(ws, servico)
    com_preco(2000.0)
    return ws, servico, agente, meta_id, ponte


def test_decisao_executada_pelo_agente_aparece_na_meta_e_nao_comprova_nada(mundo):
    ws, servico, agente, meta_id, ponte = mundo
    registradas = []
    ponte.registrada.connect(lambda m, e: registradas.append((m, e)))
    ws.set_config(agente.id, strategy="dca", mode="auto", reserve_pct=20, trade_size_pct=25, assets=["ETH"])
    ws.run_agent(agente.id, DENTRO.astimezone().replace(tzinfo=None))
    (d,) = agente.store.decisions
    (registrada,) = servico.painel(meta_id).execucoes
    assert registrada.execucao.id == f"dec-{d.uid}" and registradas == [(meta_id, f"dec-{d.uid}")]
    assert registrada.execucao.quantidade_liquida > 0
    assert servico.painel(meta_id).progresso is None or servico.painel(meta_id).progresso.quantidade_comprovada == 0  # registrar não comprova


def test_aprovar_nao_registra_so_a_execucao_registra(mundo):
    ws, servico, agente, meta_id, ponte = mundo
    ws.set_config(agente.id, strategy="dca", mode="approve", reserve_pct=20, trade_size_pct=25, assets=["ETH"])
    ws.run_agent(agente.id, local(DENTRO))
    (d,) = agente.store.decisions
    assert d.status == "proposed" and servico.painel(meta_id).execucoes == ()
    ws.resolve_decision(d.uid, True)
    assert servico.painel(meta_id).execucoes == ()  # aprovada, ainda não executada
    agente.store.registrar_execucao(d.uid, now=local(DENTRO))
    assert [r.execucao.id for r in servico.painel(meta_id).execucoes] == [f"dec-{d.uid}"]


def test_venda_executada_nao_vira_execucao_e_nao_gera_erro(mundo):
    ws, servico, agente, meta_id, ponte = mundo
    erros = []
    ponte.falhou.connect(erros.append)
    agente.store.holdings = {"USD": 0.0, "ETH": 2.0}
    agente.store.add_decision(Decision(**{**engine._sell(Atual.mercado, "ETH", 1000.0, "x", local(DENTRO)).__dict__, "status": "executed"}))
    assert servico.painel(meta_id).execucoes == () and erros == []


def test_meta_de_outro_agente_nao_recebe(mundo, arquivo_eth):
    ws, servico, agente, meta_id, ponte = mundo
    outro = ws.agents[1]
    outro.store.holdings, outro.store.decisions = {"USD": 10_000.0}, []
    outro.store.add_decision(compra_executada())
    assert servico.painel(meta_id).execucoes == ()  # a meta é do primeiro agente


def test_meta_real_nao_recebe_execucao_simulada(arquivo_eth):
    ws, servico = Workspace(), ServicoMetas()
    Atual.mercado = ws.mercado
    agente = ws.agents[0]
    agente.store.holdings, agente.store.decisions = {"USD": 10_000.0}, []
    meta_id = servico.importar(arquivo_eth, agente_id=agente.id, cenario=False)  # meta do mundo real
    ponte = PonteCarteiraMetas(ws, servico)  # precisa de dono: sem referência o QObject some e o teste passaria sem testar nada
    avisos = []
    ponte.falhou.connect(avisos.append)
    com_preco(2000.0)
    agente.store.add_decision(compra_executada())
    assert avisos == []
    assert servico.repo.entradas(meta_id, "execucoes", Execucao) == []  # uma ordem simulada não polui a meta real (lê direto do banco)


def test_meta_encerrada_nao_recebe_mais(mundo):
    ws, servico, agente, meta_id, ponte = mundo
    servico.reavaliar(meta_id, DENTRO.replace(hour=17))  # passou do prazo sem nada comprovado: a meta expira
    assert servico.painel(meta_id).estado is EstadoMeta.EXPIRADA
    agente.store.add_decision(compra_executada(quando=DENTRO.replace(hour=15)))  # mesmo dentro da janela, a meta já terminou
    assert servico.painel(meta_id).execucoes == ()


def test_falha_do_servico_nao_quebra_a_carteira_e_vira_aviso(mundo):
    ws, servico, agente, meta_id, ponte = mundo
    avisos = []
    ponte.falhou.connect(avisos.append)

    def quebra(*a, **k):
        raise RuntimeError("banco indisponível")

    servico.registrar_execucao = quebra
    erro = agente.store.add_decision(compra_executada())
    assert erro is None and agente.store.holdings["USD"] < 10_000.0  # a compra aconteceu na carteira
    assert avisos and "banco indisponível" in avisos[0]


def test_registrar_de_novo_a_mesma_decisao_nao_duplica(mundo):
    ws, servico, agente, meta_id, ponte = mundo
    agente.store.add_decision(compra_executada())
    (d,) = agente.store.decisions
    ponte.ao_executar(agente.id, d)  # o mesmo evento chegando outra vez
    assert len(servico.painel(meta_id).execucoes) == 1


def test_a_janela_liga_a_ponte_e_atualiza_a_tela_de_metas(arquivo_eth):
    from PySide6.QtWidgets import QApplication

    from ubento.ui import theme
    from ubento.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme.APP_QSS)
    ws, servico = Workspace(), ServicoMetas()
    Atual.mercado = ws.mercado
    agente = ws.agents[0]
    agente.store.holdings, agente.store.decisions = {"USD": 10_000.0}, []
    meta_id = servico.importar(arquivo_eth, agente_id=agente.id)
    janela = MainWindow(ws, animations=False, metas=servico)
    janela.show()
    janela.open_metas(agente.id)
    app.processEvents()
    com_preco(2000.0)
    agente.store.add_decision(compra_executada())
    app.processEvents()
    assert len(servico.painel(meta_id).execucoes) == 1 and janela.ponte is not None
    janela.close()


def test_trade_guarda_o_preco_da_ordem():
    t = engine._trade(Atual.mercado, "buy", "ETH", 1000.0)
    assert t.preco == Atual.mercado.preco("ETH") and Trade("sell", "ETH", 1.0, 100.0, 0.1).preco == 0.0  # trades antigos seguem válidos
