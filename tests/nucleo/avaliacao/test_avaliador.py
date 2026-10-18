import random
from datetime import timedelta
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ubento.nucleo.avaliacao import ErroDeAvaliacao, ErroDeEventos, MotivoAvaliacao as M, MotivoEscopo as E, avaliar_meta, estado_de
from ubento.nucleo.avaliacao.progresso import avaliar_escopo_orfao
from ubento.nucleo.avaliacao.reproducao import MomentoMeta, ativacao_de, carregar_reproducao_meta, executar_meta
from ubento.nucleo.conciliacao.modelos import ResultadoExterno
from ubento.nucleo.esquema import EstadoMeta, Evento, OrigemDado, TipoEvento
from ubento.nucleo.regras import Snapshot
from ubento.nucleo.tipos import Tri

from .fabrica import G, instante, montar, rodar, tipos, ultimo

ex, ext = G.ex, G.ext
PASTA = G.RAIZ / "exemplos" / "avaliacao"


# -- contrato imutável, avaliação coerente ---------------------------------------------------------------------------------------------------


def test_contrato_alterado_apos_a_ativacao_e_recusado():
    arquivo = montar([ex("ex-1", "10")], [ext("fill-1", "10")], ["11:00:00"])
    ativacao = ativacao_de(arquivo)
    alterada = arquivo.meta.model_copy(update={"recursos": arquivo.meta.recursos.model_copy(update={"orcamento": Decimal("5000"), "saldo_reservado": Decimal("5000")})})
    from ubento.nucleo.conciliacao import conciliar

    rel = conciliar(arquivo.execucoes, arquivo.registros_externos, politica=arquivo.politica_conciliacao, agora=instante("11:00:00"))
    with pytest.raises(ErroDeAvaliacao, match="imutáveis"):
        avaliar_meta(alterada, ativacao, [], [], rel, Snapshot(), instante("11:00:00"))


def test_avaliar_antes_da_ativacao_e_recusado():
    arquivo = montar([], [], ["11:00:00"])
    from ubento.nucleo.conciliacao import conciliar

    rel = conciliar([], [], politica=arquivo.politica_conciliacao, agora=instante("07:00:00"))
    with pytest.raises(ErroDeAvaliacao, match="anterior à ativação"):
        avaliar_meta(arquivo.meta, ativacao_de(arquivo), [], [], rel, Snapshot(), instante("07:00:00"))


def test_mesmas_entradas_mesma_avaliacao():
    a = rodar([ex("ex-1", "10")], [ext("fill-1", "10")], ["11:00:00"])
    b = rodar([ex("ex-1", "10")], [ext("fill-1", "10")], ["11:00:00"])
    assert ultimo(a).avaliacao == ultimo(b).avaliacao and [e.id for e in ultimo(a).eventos] == [e.id for e in ultimo(b).eventos]


# -- instante efetivo x instante da evidência ---------------------------------------------------------------------------------------------------


def test_atingida_usa_o_instante_da_execucao_e_registra_a_chegada_da_evidencia():
    passos = rodar([ex("ex-1", "10", h="13:00:00")], [ext("fill-1", "10", h="13:00:00", recebido="15:00:00")], ["15:30:00"], prazo="14:00:00")
    atingida = next(e for e in ultimo(passos).eventos if e.tipo is TipoEvento.ATINGIDA)
    assert atingida.horario_evidencia == instante("13:00:00")  # quando a execução ocorreu
    assert atingida.registrado_em == instante("15:30:00")  # quando o sistema soube


def test_execucao_depois_do_prazo_nao_conta_mesmo_com_evidencia_imediata():
    passos = rodar([ex("ex-1", "10", h="14:30:00")], [ext("fill-1", "10", h="14:30:00")], ["14:45:00"], prazo="14:00:00")
    p = ultimo(passos).progresso
    assert p.quantidade_comprovada == 0 and p.quantidade_fora_da_janela == 10
    assert ultimo(passos).estado is EstadoMeta.EXPIRADA


def test_execucao_anterior_a_ativacao_nao_conta():
    passos = rodar([ex("ex-1", "10", h="07:00:00")], [ext("fill-1", "10", h="07:00:00")], ["09:00:00"])
    p = ultimo(passos).progresso
    assert p.quantidade_comprovada == 0 and p.quantidade_fora_da_janela == 10


def test_estorno_depois_do_prazo_desfaz_compra_dentro_da_janela():
    passos = rodar([ex("ex-1", "10", h="10:00:00"), ex("ex-2", "4", h="17:00:00", lado="estorno_compra", estorna="ex-1")],
                   [ext("fill-1", "10", h="10:00:00"), ext("fill-2", "4", h="17:00:00", lado="estorno_compra", estorna="fill-1")], ["18:00:00"], prazo="16:00:00")
    assert ultimo(passos).progresso.quantidade_comprovada == 6


# -- história de eventos --------------------------------------------------------------------------------------------------------------------------------


def _ev(seq, tipo, **dados):
    t = instante("09:00:00")
    return Evento(id=f"e{seq}", meta_id="meta-tokx-001", sequencia=seq, tipo=tipo, horario_evidencia=t, registrado_em=t, autor="x" if tipo in (TipoEvento.RECONCILIADA, TipoEvento.CANCELADA) else None,
                  motivo="m" if tipo is TipoEvento.RECONCILIADA else None, dados=dados)


def test_estado_derivado_de_eventos():
    h = [_ev(1, TipoEvento.ATIVADA), _ev(2, TipoEvento.ATINGIDA), _ev(3, TipoEvento.RECONCILIADA, estado_resultante="ativa"), _ev(4, TipoEvento.EXPIRADA)]
    assert [estado_de(h[:i], "meta-tokx-001") for i in range(1, 5)] == [EstadoMeta.ATIVA, EstadoMeta.ATINGIDA, EstadoMeta.ATIVA, EstadoMeta.EXPIRADA]


@pytest.mark.parametrize("historia, trecho", [
    ([("ativada",), ("atingida",), ("atingida",)], "reconciliada"),  # atingida duas vezes sem reabrir
    ([("ativada",), ("reconciliada", "ativa")], "reconciliada"),  # só corrige estados terminais
    ([("ativada",), ("atingida",), ("reconciliada", "cancelada")], "cancelada"),
    ([("ativada",), ("atingida",), ("reconciliada",)], "estado_resultante"),
    ([("ativada",), ("cancelada",), ("atingida",)], "ativa"),
    ([("ativada",), ("ativada",)], "rascunho"),
    ([("avaliada",)], "ativa"),
])
def test_transicoes_ilegais(historia, trecho):
    eventos = []
    for i, (tipo, *resto) in enumerate(historia, 1):
        eventos.append(_ev(i, TipoEvento(tipo), **({"estado_resultante": resto[0]} if resto else {})))
    with pytest.raises(ErroDeEventos, match=trecho):
        estado_de(eventos, "meta-tokx-001")


def test_sequencia_com_buraco_ou_repeticao():
    with pytest.raises(ErroDeEventos, match="sequência"):
        estado_de([_ev(1, TipoEvento.ATIVADA), _ev(3, TipoEvento.ATINGIDA)], "meta-tokx-001")
    with pytest.raises(ErroDeEventos):
        estado_de([_ev(1, TipoEvento.ATIVADA), _ev(1, TipoEvento.ATINGIDA)], "meta-tokx-001")


def test_meta_cancelada_nunca_e_recalculada():
    arquivo = montar([ex("ex-1", "10")], [ext("fill-1", "10")], ["11:00:00"])
    from ubento.nucleo.conciliacao import conciliar

    rel = conciliar(arquivo.execucoes, arquivo.registros_externos, politica=arquivo.politica_conciliacao, agora=instante("11:00:00"))
    historia = [_ev(1, TipoEvento.ATIVADA), _ev(2, TipoEvento.CANCELADA)]
    r = avaliar_meta(arquivo.meta, ativacao_de(arquivo), historia, [], rel, Snapshot(), instante("11:00:00"))
    assert r.estado is EstadoMeta.CANCELADA and r.eventos == ()  # cancelamento é ato humano


# -- escopo dos registros externos sem dono -----------------------------------------------------------------------------------------------------------


def _orfao(**kw):
    base = dict(fonte_id="corretora-sim", id_externo="o-1", versao=1, ativo_id="tokx", lado="compra", quantidade="5", preco="9.5", moeda_cotacao_id="usd",
                mercado_id="bolsa-a", conta_id="conta-a", origem="simulado", status="confirmado", executado_em=instante("10:00:00"), recebido_em=instante("10:01:00"))
    base.update(kw)
    return ResultadoExterno(**base)


@pytest.mark.parametrize("campo, valor, relevante, motivo", [
    ({}, None, True, E.COMPRA_POSSIVELMENTE_DA_META),
    ("ativo_id", "abc", False, E.ATIVO_DIFERENTE),
    ("mercado_id", "bolsa-b", False, E.MERCADO_DIFERENTE),
    ("moeda_cotacao_id", "eur", False, E.MOEDA_COTACAO_DIFERENTE),
    ("conta_id", "conta-b", False, E.CONTA_DIFERENTE),
    ("origem", "observado", False, E.ORIGEM_DIFERENTE),
    ("executado_em", instante("07:59:59"), False, E.FORA_DO_PERIODO),
    ("executado_em", instante("16:00:01"), False, E.FORA_DO_PERIODO),
    ("executado_em", instante("08:00:00"), True, E.COMPRA_POSSIVELMENTE_DA_META),  # limites inclusivos
    ("executado_em", instante("16:00:00"), True, E.COMPRA_POSSIVELMENTE_DA_META),
])
def test_criterios_de_escopo_do_orfao(campo, valor, relevante, motivo):
    arquivo = montar([], [], ["11:00:00"])
    kw = {} if campo == {} else {campo: valor}
    r = avaliar_escopo_orfao(_orfao(**kw), arquivo.meta, ativacao_de(arquivo), set(), frozenset({OrigemDado.SIMULADO}))
    assert r.relevante is relevante and r.motivos[0] is motivo


def test_conta_desconhecida_nao_exclui_mas_e_sinalizada():
    arquivo = montar([], [], ["11:00:00"])
    r = avaliar_escopo_orfao(_orfao(conta_id=None), arquivo.meta, ativacao_de(arquivo), set(), frozenset({OrigemDado.SIMULADO}))
    assert r.relevante and E.CONTA_INDETERMINADA in r.motivos
    sem_conta = montar([], [], ["11:00:00"], conta=None)
    r2 = avaliar_escopo_orfao(_orfao(conta_id="conta-z"), sem_conta.meta, ativacao_de(sem_conta), set(), frozenset({OrigemDado.SIMULADO}))
    assert r2.relevante and E.CONTA_INDETERMINADA in r2.motivos  # a meta não informou a conta: não dá para excluir


def test_estorno_so_importa_se_aponta_para_registro_da_meta():
    arquivo = montar([], [], ["11:00:00"])
    meta, ativ, origens = arquivo.meta, ativacao_de(arquivo), frozenset({OrigemDado.SIMULADO})
    do_meta = avaliar_escopo_orfao(_orfao(lado="estorno_compra", estorna_id_externo="fill-1"), meta, ativ, {("corretora-sim", "fill-1")}, origens)
    de_outra = avaliar_escopo_orfao(_orfao(lado="estorno_compra", estorna_id_externo="fill-9"), meta, ativ, {("corretora-sim", "fill-1")}, origens)
    de_outra_fonte = avaliar_escopo_orfao(_orfao(lado="estorno_compra", estorna_id_externo="fill-1", fonte_id="outra-fonte"), meta, ativ, {("corretora-sim", "fill-1")}, origens)
    assert do_meta.relevante and E.ESTORNO_DE_REGISTRO_DA_META in do_meta.motivos
    assert not de_outra.relevante and not de_outra_fonte.relevante


def test_orfao_irrelevante_nao_cria_pendencia_nem_bloqueia():
    passos = rodar([ex("ex-1", "10")], [ext("fill-1", "10"), ext("o-x", "5", conta="conta-b", h="10:10:00")], ["11:00:00"])
    r = ultimo(passos)
    assert r.estado is EstadoMeta.ATINGIDA and r.progresso.completude.completa and r.progresso.orfaos[0].relevante is False


# -- orçamento (limite obrigatório) ---------------------------------------------------------------------------------------------------------------------


def _orc(execucoes, externos, **kw):
    return ultimo(rodar(execucoes, externos, ["11:00:00"], **kw)).progresso.orcamento


def test_orcamento_tri_valorado():
    cabe = _orc([ex("ex-1", "10", preco="9")], [ext("fill-1", "10", preco="9")], orcamento="100")
    assert cabe.resultado is Tri.VERDADEIRO and (cabe.gasto_minimo, cabe.gasto_maximo) == (90, 90)
    estoura = _orc([ex("ex-1", "10", preco="11")], [ext("fill-1", "10", preco="11")], orcamento="100")
    assert estoura.resultado is Tri.FALSO and MotivoOrc.EXCEDIDO in estoura.motivos
    incerto = _orc([ex("ex-1", "10", preco="9.9", custo_fixo_real="5")], [ext("fill-1", "10", preco="9.9")], orcamento="100")
    assert incerto.resultado is Tri.INDETERMINADO and (incerto.gasto_minimo, incerto.gasto_maximo) == (99, 104)
    assert M.CUSTOS_SEM_EVIDENCIA in incerto.motivos


class MotivoOrc:
    EXCEDIDO = M.ORCAMENTO_EXCEDIDO


def test_orcamento_com_moeda_diferente_e_indeterminado():
    execucao = ex("ex-1", "10", preco="9")
    execucao["moeda_cotacao_id"] = "eur"
    externo = ext("fill-1", "10", preco="9")
    externo["moeda_cotacao_id"] = "eur"
    r = ultimo(rodar([execucao], [externo], ["11:00:00"]))
    assert r.progresso.orcamento.resultado is Tri.INDETERMINADO and M.MOEDA_INCOMPATIVEL in r.progresso.orcamento.motivos


def test_custos_verificados_e_nao_verificados_ficam_separados():
    p = ultimo(rodar([ex("ex-1", "10", taxas_outros_ativos=[{"ativo_id": "bnb", "valor": "0.002"}], taxa_na_cotacao="1", custo_fixo_real="2")],
                     [ext("fill-1", "10", [("bnb", "0.002"), ("usd", "1")])], ["11:00:00"])).progresso
    custos = {c.ativo_id: (c.verificado, c.nao_verificado) for c in p.custos}
    assert custos == {"bnb": (Decimal("0.002"), 0), "usd": (1, 2)}  # taxa conferida; custo fixo SEM evidência


# -- quantidade, completude e elegibilidade são coisas diferentes --------------------------------------------------------------------------------------------


def test_pendencia_nao_apaga_progresso_ja_comprovado():
    passos = rodar([ex("ex-1", "6", h="10:00:00"), ex("ex-2", "6", h="11:00:00")], [ext("fill-1", "6", h="10:00:00"), ext("fill-2", "6", h="11:00:00", recebido="20:00:00")],
                   ["10:30:00", "12:00:00"])
    p = passos[1].resultado.progresso
    assert p.quantidade_comprovada == 6 and p.quantidade_pendente == 6 and not p.completude.completa  # nada foi apagado


def test_estorno_pendente_nao_reduz_mas_impede_concluir():
    passos = rodar([ex("ex-1", "10", h="10:00:00"), ex("ex-2", "3", h="10:30:00", lado="estorno_compra", estorna="ex-1")],
                   [ext("fill-1", "10", h="10:00:00"), ext("fill-2", "3", h="10:30:00", lado="estorno_compra", estorna="fill-1", recebido="20:00:00")], ["11:00:00"])
    r = ultimo(passos)
    assert r.progresso.quantidade_comprovada == 10  # o estorno ainda não foi comprovado
    assert r.progresso.elegibilidade.resultado is Tri.INDETERMINADO and r.estado is EstadoMeta.ATIVA
    assert M.PENDENCIA_PODE_REDUZIR_PROGRESSO in r.progresso.elegibilidade.motivos


def test_meta_atingida_nao_e_reaberta_por_estorno_apenas_pendente():
    passos = rodar([ex("ex-1", "10", h="10:00:00"), ex("ex-2", "3", h="11:00:00", lado="estorno_compra", estorna="ex-1")],
                   [ext("fill-1", "10", h="10:00:00"), ext("fill-2", "3", h="11:00:00", lado="estorno_compra", estorna="fill-1", recebido="20:00:00")],
                   ["10:30:00", "12:00:00"])
    assert passos[0].resultado.estado is EstadoMeta.ATINGIDA
    assert passos[1].resultado.estado is EstadoMeta.ATINGIDA and tipos(passos[1].resultado) == []


# -- proposta não é execução ----------------------------------------------------------------------------------------------------------------------------------------


def test_alerta_na_historia_nao_vira_progresso():
    """O avaliador só recebe execuções conciliadas: um alerta (ou uma proposta aprovada) não entra no progresso."""
    passos = rodar([], [], ["10:00:00", "11:00:00"], observacoes=[G.obs("o-preco", "preco_executavel", "9.4", "USD", "09:30:00"), G.obs("o-ret", "retorno_7d", "0.01", "razao", "09:30:00")])
    assert "alerta_emitido" in [t for p in passos for t in tipos(p.resultado)]
    assert ultimo(passos).progresso.quantidade_comprovada == 0 and ultimo(passos).estado is EstadoMeta.ATIVA


# -- alertas ------------------------------------------------------------------------------------------------------------------------------------------------------------


def test_sem_alerta_quando_o_orcamento_ja_foi_estourado():
    passos = rodar([ex("ex-1", "9", preco="12")], [ext("fill-1", "9", preco="12")], ["11:00:00"], orcamento="100",
                   observacoes=[G.obs("o-p", "preco_executavel", "9.4", "USD", "09:30:00"), G.obs("o-r", "retorno_7d", "0.01", "razao", "09:30:00")])
    assert "alerta_emitido" not in tipos(ultimo(passos)) and ultimo(passos).progresso.orcamento.resultado is Tri.FALSO


def test_sem_alerta_com_dados_bloqueados():
    passos = rodar([], [], ["11:00:00"], observacoes=[G.obs("o-p", "preco_executavel", "9.4", "USD", "09:30:00")])  # falta retorno_7d
    r = ultimo(passos)
    assert r.avaliacao.bloqueada_por_dados and "alerta_emitido" not in tipos(r) and "bloqueio_iniciado" in tipos(r)


# -- propriedades -----------------------------------------------------------------------------------------------------------------------------------------------------------

ARQUIVOS = sorted(PASTA.glob("*.yaml"))


@settings(max_examples=25, deadline=None)
@given(st.sampled_from(ARQUIVOS), st.lists(st.integers(0, 12 * 60), min_size=1, max_size=6))
def test_propriedades_em_qualquer_sequencia_de_reavaliacoes(arquivo, minutos):
    """Para qualquer cenário e qualquer sequência de momentos: reprocessar é limpo, a história é válida e o razão fecha."""
    base = carregar_reproducao_meta(arquivo)
    inicio = instante("08:30:00")
    cenario = base.model_copy(update={"momentos": tuple(MomentoMeta(agora=inicio + timedelta(minutes=m)) for m in sorted(minutos))})
    passos = executar_meta(cenario)
    eventos, soma = [], Decimal(0)
    for p in passos:
        assert p.reprocessamento_limpo
        eventos += p.resultado.eventos
        soma += sum((e.delta_progresso for e in p.resultado.eventos_conciliacao), Decimal(0))
        assert estado_de(eventos, cenario.meta.id) is p.resultado.estado  # a história derivada coincide com o estado reportado
    final = passos[-1].resultado.progresso
    assert soma == final.quantidade_comprovada + final.quantidade_fora_da_janela
    assert len({e.id for e in eventos}) == len(eventos)


@settings(max_examples=25, deadline=None)
@given(st.sampled_from([a for a in ARQUIVOS if "13" not in a.name]), st.integers(0, 10_000))
def test_ordem_das_entradas_nao_altera_o_resultado(arquivo, semente):
    base = carregar_reproducao_meta(arquivo)
    rng = random.Random(semente)
    execs, exts = list(base.execucoes), list(base.registros_externos)
    rng.shuffle(execs)
    rng.shuffle(exts)
    embaralhado = base.model_copy(update={"execucoes": tuple(execs), "registros_externos": tuple(exts)})
    a, b = executar_meta(base), executar_meta(embaralhado)
    assert [p.resultado.avaliacao.hash_saida for p in a] == [p.resultado.avaliacao.hash_saida for p in b]
    assert [[e.id for e in p.resultado.eventos] for p in a] == [[e.id for e in p.resultado.eventos] for p in b]
