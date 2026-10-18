from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ubento.nucleo.conciliacao import (
    Cobertura, Motivo, Movimentacao, SaldoObservado, StatusConciliacao, StatusSaldo, TipoEventoConciliacao, carregar_reproducao,
    diferenciar, executar_momento,
)

from .fabrica import AGORA, BASE, FONTE, POLITICA, comprovado, d, execucao, externo, rodar, status

PASTA = Path(__file__).resolve().parents[3] / "exemplos" / "conciliacao"
T = TipoEventoConciliacao


# -- eventos compensatórios ----------------------------------------------------------------------------------------------------


def _soma(eventos):
    total: dict[str, Decimal] = defaultdict(Decimal)
    vistos = set()
    for e in eventos:
        if e.id in vistos:  # aplicar o mesmo evento duas vezes é inofensivo
            continue
        vistos.add(e.id)
        if e.meta_id:
            total[e.meta_id] += e.delta_progresso
    return dict(total)


def test_primeiro_relatorio_gera_um_evento_por_execucao_conciliada():
    r = rodar([execucao(), execucao("ex-2", refs=("fill-002",), minutos=10, preco="9.9")], [externo(), externo("fill-002", minutos=10)])
    ev = diferenciar(None, r)
    assert [e.tipo for e in ev] == [T.EXECUCAO_CONCILIADA, T.DIVERGENCIA_ABERTA]
    assert ev[0].delta_progresso == d("9.95") and ev[1].delta_progresso == 0


def test_relatorios_iguais_nao_geram_eventos():
    r = rodar([execucao()], [externo()])
    assert diferenciar(r, r) == () and diferenciar(r, rodar([execucao()], [externo()])) == ()


def test_correcao_gera_evento_compensatorio_exato():
    antes = rodar([execucao()], [externo()], agora=BASE + timedelta(minutes=30))
    depois = rodar([execucao()], [externo(), externo(versao=2, taxas=(("tokx", "0.06"),), recebido_min=40)], agora=BASE + timedelta(hours=1))
    ev = diferenciar(antes, depois)
    assert [e.tipo for e in ev] == [T.CONCILIACAO_REVERTIDA, T.DIVERGENCIA_ABERTA]
    assert ev[0].delta_progresso == -d("9.95") and Motivo.TAXA_NO_ATIVO_DIFERENTE in ev[0].motivos


def test_ids_dos_eventos_sao_deterministicos_e_distintos_por_transicao():
    a = rodar([execucao()], [externo()], agora=BASE + timedelta(minutes=30))
    b = rodar([execucao()], [externo(), externo(versao=2, taxas=(("tokx", "0.06"),), recebido_min=40)], agora=BASE + timedelta(hours=1))
    assert [e.id for e in diferenciar(a, b)] == [e.id for e in diferenciar(a, b)]
    assert len({e.id for e in diferenciar(None, a) + diferenciar(a, b)}) == 3


def test_evento_reaplicado_nao_duplica_progresso():
    r = rodar([execucao()], [externo()])
    ev = diferenciar(None, r)
    assert _soma(ev + ev + ev) == {META_ID: d("9.95")} == _soma(ev)


META_ID = "meta-tokx-001"


def test_orfao_novo_gera_evento_uma_vez():
    a = rodar([execucao()], [externo()])
    b = rodar([execucao()], [externo(), externo("fill-9", minutos=30)])
    assert [e.tipo for e in diferenciar(a, b)] == [T.ORFAO_DETECTADO]
    assert diferenciar(b, b) == ()


@pytest.mark.parametrize("cenario", ["10_dados_atrasados", "11_correcao_externa", "12_cancelamento_externo", "13_estorno",
                                     "14_estorno_excedente", "17_alocacao_parcial_entre_metas"])
@settings(max_examples=40, deadline=None)
@given(st.lists(st.integers(0, 360), min_size=1, max_size=7))
def test_soma_dos_eventos_e_sempre_o_progresso_comprovado_final(cenario, minutos):
    """Para qualquer sequência de reprocessamentos, Σ delta dos eventos = progresso comprovado do último relatório."""
    arquivo = carregar_reproducao(PASTA / f"{cenario}.yaml")
    inicio = min(m.agora for m in arquivo.momentos).replace(hour=9, minute=0)
    anterior, eventos, relatorio = None, [], None
    for minuto in sorted(minutos):
        relatorio = executar_momento(arquivo, inicio + timedelta(minutes=minuto))
        eventos += diferenciar(anterior, relatorio)
        anterior = relatorio
    esperado = {p.meta_id: p.comprovado for p in relatorio.progresso}
    soma = _soma(eventos)
    assert {k: v for k, v in soma.items() if v != 0 or esperado.get(k)} == {k: v for k, v in esperado.items() if v != 0}


@settings(max_examples=30, deadline=None)
@given(st.permutations(range(4)))
def test_resultado_nao_depende_da_ordem_de_entrada(ordem):
    execs = [execucao(f"ex-{i}", refs=(f"fill-{i}",), minutos=i) for i in range(4)]
    exts = [externo(f"fill-{i}", minutos=i) for i in range(4)]
    base = rodar(execs, exts)
    assert rodar([execs[i] for i in ordem], [exts[i] for i in ordem]).hash_saida == base.hash_saida


# -- saldos: separados das execuções --------------------------------------------------------------------------------------------------------


def _saldo(qtd, minutos):
    t = BASE + timedelta(minutes=minutos)
    return SaldoObservado(fonte_id=FONTE, ativo_id="tokx", quantidade=qtd, observado_em=t, recebido_em=t, origem="simulado")


def _mov(id_, tipo, qtd, minutos, ref=None):
    t = BASE + timedelta(minutes=minutos)
    return Movimentacao(fonte_id=FONTE, id_externo=id_, ativo_id="tokx", tipo=tipo, quantidade=qtd, em=t, recebido_em=t, origem="simulado", referencia_execucao_externa=ref)


COBERTURA = [Cobertura(fonte_id=FONTE, ativo_id="tokx", inicio=BASE - timedelta(hours=1), fim=BASE + timedelta(hours=2))]


def test_saldo_explicado_por_deposito_mais_execucao():
    r = rodar([execucao()], [externo()], saldos=[_saldo("100", -60), _saldo("159.95", 60)], coberturas=COBERTURA,
              movimentacoes=[_mov("m1", "deposito", "50", -30), _mov("m2", "execucao", "10", 0, "fill-001"), _mov("m3", "taxa", "-0.05", 0, "fill-001")])
    s = r.saldos[0]
    assert s.status is StatusSaldo.EXPLICADA and s.residuo == 0 and s.por_tipo == {"deposito": d("50"), "execucao": d("10"), "taxa": d("-0.05")}
    assert comprovado(r) == d("9.95")  # o depósito explica saldo, nunca vira progresso
    assert s.inconsistencias == ()


def test_residuo_de_saldo_nao_altera_o_status_da_execucao():
    com = rodar([execucao()], [externo()], saldos=[_saldo("100", -60), _saldo("500", 60)], coberturas=COBERTURA)
    sem = rodar([execucao()], [externo()])
    assert com.saldos[0].status is StatusSaldo.NAO_EXPLICADA and com.saldos[0].residuo == d("400")
    assert status(com, "ex-1") == status(sem, "ex-1") and comprovado(com) == comprovado(sem) and com.confirmacao == sem.confirmacao


def test_execucao_divergente_nao_depende_do_saldo_estar_certo():
    r = rodar([execucao(preco="9.9")], [externo()], saldos=[_saldo("100", -60), _saldo("109.95", 60)], coberturas=COBERTURA,
              movimentacoes=[_mov("m2", "execucao", "10", 0, "fill-001"), _mov("m3", "taxa", "-0.05", 0, "fill-001")])
    assert r.saldos[0].status is StatusSaldo.EXPLICADA and status(r, "ex-1").status is StatusConciliacao.DIVERGENTE


def test_sem_cobertura_nao_se_afirma_nada():
    curta = [Cobertura(fonte_id=FONTE, ativo_id="tokx", inicio=BASE - timedelta(hours=1), fim=BASE)]
    r = rodar([], [], saldos=[_saldo("100", -60), _saldo("500", 60)], coberturas=curta)
    s = r.saldos[0]
    assert s.status is StatusSaldo.DADOS_INSUFICIENTES and s.residuo is None and Motivo.COBERTURA_INSUFICIENTE in s.motivos
    assert s.variacao_observada == d("400")


def test_um_unico_saldo_nao_permite_conciliar():
    r = rodar([], [], saldos=[_saldo("100", 0)], coberturas=COBERTURA)
    assert r.saldos[0].status is StatusSaldo.DADOS_INSUFICIENTES and Motivo.SALDO_AUSENTE in r.saldos[0].motivos


def test_tolerancia_de_saldo_explicita():
    saldos = [_saldo("100", -60), _saldo("100.000001", 60)]
    assert rodar([], [], saldos=saldos, coberturas=COBERTURA).saldos[0].status is StatusSaldo.NAO_EXPLICADA
    folga = POLITICA.model_copy(update={"tolerancia_saldo": Decimal("0.00001")})
    assert rodar([], [], saldos=saldos, coberturas=COBERTURA, politica=folga).saldos[0].status is StatusSaldo.EXPLICADA


def test_varios_intervalos_consecutivos_e_movimento_no_limite():
    saldos = [_saldo("100", -60), _saldo("110", 0), _saldo("115", 60)]
    movs = [_mov("m1", "deposito", "10", -30), _mov("m2", "deposito", "5", 0)]  # m2 cai no fim do 1º intervalo? não: em 0 pertence a (-60, 0]
    r = rodar([], [], saldos=saldos, coberturas=COBERTURA, movimentacoes=movs)
    assert [s.status for s in r.saldos] == [StatusSaldo.NAO_EXPLICADA, StatusSaldo.NAO_EXPLICADA]
    assert r.saldos[0].variacao_explicada == d("15") and r.saldos[1].variacao_explicada == d("0")  # intervalo é (início, fim]


def test_movimento_de_execucao_inconsistente_e_apenas_informativo():
    r = rodar([execucao()], [externo()], saldos=[_saldo("100", -60), _saldo("109", 60)], coberturas=COBERTURA,
              movimentacoes=[_mov("m2", "execucao", "9", 0, "fill-001")])
    s = r.saldos[0]
    assert Motivo.MOVIMENTO_DE_EXECUCAO_DIVERGENTE in s.motivos and s.inconsistencias
    assert status(r, "ex-1").status is StatusConciliacao.CONCILIADA  # informativo: não muda a execução


def test_movimento_ainda_nao_recebido_nao_entra():
    tarde = Movimentacao(fonte_id=FONTE, id_externo="m1", ativo_id="tokx", tipo="deposito", quantidade="50", em=BASE, recebido_em=BASE + timedelta(days=1), origem="simulado")
    r = rodar([], [], saldos=[_saldo("100", -60), _saldo("150", 60)], coberturas=COBERTURA, movimentacoes=[tarde])
    assert r.saldos[0].status is StatusSaldo.NAO_EXPLICADA


def test_agora_e_so_um_parametro():
    assert AGORA > BASE and POLITICA.janela_atraso_segundos == 3600


def test_movimentacao_valida_sinais():
    with pytest.raises(Exception):
        _mov("x", "deposito", "-5", 0)
    with pytest.raises(Exception):
        _mov("x", "retirada", "5", 0)
    with pytest.raises(Exception):
        _mov("x", "ajuste", "0", 0)
