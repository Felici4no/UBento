"""Carteira ↔ texto/UTC: o estado de uma carteira vira dados que o SQLite guarda e volta idêntico.

Valores são texto decimal (o `repr` do float vai e volta sem perder um bit) e instantes são UTC com `Z`; a carteira em memória continua em
`float` e hora local ingênua. Também cobre o repositório das carteiras (tabelas próprias, no mesmo banco das metas).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime, timezone  # noqa: E402

import pytest  # noqa: E402

from ubento import engine  # noqa: E402
from ubento.carteira_serial import ErroDeEstado, aplicar_estado, estado_da_carteira, pontos_da_carteira  # noqa: E402
from ubento.mercado import Mercado  # noqa: E402
from ubento.persistencia import Repositorio  # noqa: E402
from ubento.persistencia.carteiras import RepositorioCarteiras  # noqa: E402
from ubento.store import Decision, Store, Trade  # noqa: E402

UTC = timezone.utc
T0 = datetime(2026, 10, 20, 12, 0, 0)


def carteira_com_historia() -> Store:
    s = Store(now=T0, real=True, mercado=Mercado())
    s.mercado.aplicar({"ETH": 2000.0}, {"ETH": -4.0}, T0)
    s.executar_trade(engine._trade(s.mercado, "buy", "ETH", 1000.0))
    s.holdings["USD"] = 9000.0 + 0.1 + 0.2  # um float que não é "redondo"
    s.cost_basis["ETH"] = 1000.0 / 3
    s.decisions = [
        Decision("buy", "Comprou ETH", "Tendência", "+ 0,49950 ETH", T0, trade=engine._trade(s.mercado, "buy", "ETH", 1000.0), value_usd=1000.0, fee_usd=1.0, pnl_usd=-1.0, pnl_realizado=False),
        Decision("hold", "Manteve", "Sem sinal", "", datetime(2026, 10, 20, 9, 30, 15)),
        Decision("sell", "Proposta", "x", "- 1 ETH", datetime(2026, 10, 19, 22, 0), status="proposed", trade=Trade("sell", "ETH", 1.0, 2000.0, 2.0, 2000.0)),
    ]
    s.activity[date(2026, 10, 20)] = 3
    s.registrar_ponto(T0)
    s.registrar_ponto(datetime(2026, 10, 20, 12, 5))
    return s


# -- estado ↔ dados --------------------------------------------------------------------------------------------------------------------


def test_ida_e_volta_devolve_exatamente_o_mesmo_estado():
    origem = carteira_com_historia()
    destino = Store(now=T0, real=True, mercado=Mercado())
    aplicar_estado(destino, estado_da_carteira(origem), pontos_da_carteira(origem))
    assert destino.holdings == origem.holdings and destino.cost_basis == origem.cost_basis  # bit a bit, inclusive 9000.3000000000001
    assert destino.decisions == origem.decisions
    assert destino.activity == origem.activity and destino.pontos == origem.pontos


def test_o_estado_so_tem_texto_e_numeros_de_json():
    import json

    dados = estado_da_carteira(carteira_com_historia())
    assert json.loads(json.dumps(dados)) == dados  # cabe no SQLite sem adaptador
    assert isinstance(dados["holdings"]["USD"], str) and dados["holdings"]["ETH"] == "0.4995"  # texto decimal, não float


def test_instantes_vao_para_utc_com_z_e_voltam_para_a_hora_local():
    s = Store(now=T0, real=True, mercado=Mercado())
    s.decisions = [Decision("hold", "x", "y", "", T0)]
    dados = estado_da_carteira(s)
    esperado = T0.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert dados["decisions"][0]["momento"] == esperado
    outro = Store(now=T0, real=True, mercado=Mercado())
    aplicar_estado(outro, dados, [])
    assert outro.decisions[0].moment == T0


def test_preco_da_ordem_e_o_resultado_da_decisao_sobrevivem():
    origem = carteira_com_historia()
    destino = Store(now=T0, real=True, mercado=Mercado())
    aplicar_estado(destino, estado_da_carteira(origem), pontos_da_carteira(origem))
    compra = destino.decisions[0]
    assert (compra.trade.preco, compra.trade.fee, compra.pnl_usd, compra.pnl_realizado, compra.status, compra.uid) == (2000.0, 1.0, -1.0, False, "executed", origem.decisions[0].uid)


@pytest.mark.parametrize("estrago", [
    lambda d: d.update(versao=99),
    lambda d: d.pop("holdings"),
    lambda d: d["holdings"].update(USD="não é número"),
    lambda d: d["holdings"].update(USD="NaN"),
    lambda d: d["holdings"].update(USD="-5"),
    lambda d: d["decisions"][0].update(momento="ontem"),
    lambda d: d["decisions"][0].update(status="inventado"),
    lambda d: d["decisions"][0]["trade"].update(side="short"),
    lambda d: d.update(activity={"2026-13-45": 1}),
])
def test_estado_ilegivel_e_recusado_sem_tocar_na_carteira(estrago):
    dados = estado_da_carteira(carteira_com_historia())
    estrago(dados)
    alvo = Store(now=T0, real=True, mercado=Mercado())
    antes = (dict(alvo.holdings), list(alvo.decisions))
    with pytest.raises(ErroDeEstado):
        aplicar_estado(alvo, dados, [])
    assert (alvo.holdings, alvo.decisions) == antes  # tudo ou nada


def test_ativo_desconhecido_no_estado_e_descartado_e_nao_derruba():
    dados = estado_da_carteira(carteira_com_historia())
    dados["holdings"]["DOGE"] = "10"
    alvo = Store(now=T0, real=True, mercado=Mercado())
    aplicar_estado(alvo, dados, [])
    assert "DOGE" not in alvo.holdings


# -- repositório -----------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path):
    r = Repositorio(tmp_path / "x.db")
    yield RepositorioCarteiras(r)
    r.fechar()


def test_salvar_e_carregar_e_sobrescrever(repo):
    repo.salvar("a1", {"versao": 1, "holdings": {"USD": "10"}}, "2026-10-20T12:00:00Z")
    assert repo.carregar("a1")["holdings"]["USD"] == "10"
    repo.salvar("a1", {"versao": 1, "holdings": {"USD": "11"}}, "2026-10-20T12:01:00Z")
    assert repo.carregar("a1")["holdings"]["USD"] == "11" and repo.carregar("outro") is None


def test_pontos_acumulam_e_o_ultimo_pode_ser_corrigido(repo):
    repo.gravar_pontos("a1", [("2026-10-20T12:00:00Z", "10000"), ("2026-10-20T12:01:00Z", "10001")])
    repo.gravar_pontos("a1", [("2026-10-20T12:01:00Z", "10002"), ("2026-10-20T12:02:00Z", "10003")])  # o do minuto 1 foi corrigido
    assert repo.pontos("a1") == [("2026-10-20T12:00:00Z", "10000"), ("2026-10-20T12:01:00Z", "10002"), ("2026-10-20T12:02:00Z", "10003")]


def test_arquivar_tira_do_carregamento_mas_guarda_os_dados(repo):
    repo.salvar("a1", {"versao": 1}, "2026-10-20T12:00:00Z")
    repo.arquivar("a1", "2026-10-21T08:00:00Z")
    assert repo.carregar("a1") is None
    assert repo.arquivadas() == [("a1", "2026-10-21T08:00:00Z")]  # os dados continuam no banco


def test_ultimo_preco_do_mercado(repo):
    assert repo.carregar_mercado() is None
    repo.salvar_mercado({"precos": {"ETH": "2000"}, "variacao_7d": {"ETH": "-4"}}, "2026-10-20T12:00:00Z")
    assert repo.carregar_mercado() == ({"precos": {"ETH": "2000"}, "variacao_7d": {"ETH": "-4"}}, "2026-10-20T12:00:00Z")


def test_sobrevive_a_fechar_e_reabrir_o_banco(tmp_path):
    caminho = tmp_path / "y.db"
    r1 = Repositorio(caminho)
    RepositorioCarteiras(r1).salvar("a1", {"versao": 1, "k": "v"}, "2026-10-20T12:00:00Z")
    r1.fechar()
    r2 = Repositorio(caminho)
    assert RepositorioCarteiras(r2).carregar("a1")["k"] == "v"
    r2.fechar()


def test_conexao_somente_leitura_nao_cria_nem_grava_carteiras(tmp_path):
    caminho = tmp_path / "z.db"
    Repositorio(caminho).fechar()
    ro = Repositorio(caminho, somente_leitura=True)
    with pytest.raises(Exception):
        RepositorioCarteiras(ro).salvar("a1", {"versao": 1}, "2026-10-20T12:00:00Z")
    ro.fechar()
