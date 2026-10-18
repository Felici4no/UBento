"""Reimportação pelo caminho do app: reimportar a mesma evidência não desfaz progresso, nem reabre meta, e a rastreabilidade fica."""

from datetime import timedelta
from decimal import Decimal

from test_correcao_vinculo import CENARIO
from ubento.metas import EvidenciaExterna, ServicoMetas
from ubento.nucleo.avaliacao.reproducao import carregar_reproducao_meta
from ubento.nucleo.conciliacao import RegistroExterno

O = carregar_reproducao_meta(CENARIO)
FIM = O.momentos[-1].agora


def test_reimportar_a_mesma_evidencia_com_outro_recebido_em_nao_reverte_a_meta_atingida():
    sv = ServicoMetas()
    mid = sv.importar(O.model_copy(update={"execucoes": (), "registros_externos": (), "coberturas_execucoes": ()}))
    for e in O.execucoes:
        sv.registrar_execucao(mid, e)
    sv.importar_evidencia(mid, EvidenciaExterna(registros_externos=O.registros_externos))
    sv.reavaliar(mid, FIM)
    antes = sv.painel(mid)
    assert antes.estado.value == "atingida" and str(antes.progresso.quantidade_comprovada) == "10.05"
    eventos, razao = sv.repo.eventos(mid), sv.repo.razao(mid)

    reimportados = tuple(x.model_copy(update={"recebido_em": FIM + timedelta(hours=1)}) for x in O.registros_externos)
    assert sv.importar_evidencia(mid, EvidenciaExterna(registros_externos=reimportados)) == 3  # cada importação fica registrada (rastreabilidade)
    resultado = sv.reavaliar(mid, FIM + timedelta(hours=2))

    depois = sv.painel(mid)
    assert depois.estado.value == "atingida" and depois.progresso.quantidade_comprovada == antes.progresso.quantidade_comprovada
    assert not resultado.eventos and not resultado.eventos_conciliacao  # nada foi revertido, nada novo
    assert (sv.repo.eventos(mid), sv.repo.razao(mid)) == (eventos, razao)
    todos = sv.repo.entradas(mid, "registros_externos", RegistroExterno)
    assert len(todos) == 6 and len({(r.fonte_id, r.id_externo) for r in todos}) == 3  # as 6 chegadas estão guardadas; são 3 operações
    assert {r.recebido_em for r in todos if r.id_externo == "fill-1"} == {O.registros_externos[0].recebido_em, FIM + timedelta(hours=1)}


def test_mudanca_real_na_reimportacao_continua_sendo_detectada_pelo_app():
    sv = ServicoMetas()
    mid = sv.importar(O.model_copy(update={"execucoes": (), "registros_externos": (), "coberturas_execucoes": ()}))
    for e in O.execucoes:
        sv.registrar_execucao(mid, e)
    sv.importar_evidencia(mid, EvidenciaExterna(registros_externos=O.registros_externos))
    sv.reavaliar(mid, FIM)
    corrigido = O.registros_externos[0].model_copy(update={"preco": Decimal("9.6"), "recebido_em": FIM + timedelta(hours=1)})  # mesma versão, preço diferente
    sv.importar_evidencia(mid, EvidenciaExterna(registros_externos=(corrigido,)))
    sv.reavaliar(mid, FIM + timedelta(hours=2))
    assert sv.painel(mid).estado.value != "atingida"  # um conflito real continua desfazendo a prova
