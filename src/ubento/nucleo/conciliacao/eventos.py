"""Eventos compensatórios: o que mudou entre dois relatórios de conciliação.

Nada é reescrito. Quando uma execução deixa de estar comprovada (correção ou cancelamento externo), o evento
`conciliacao_revertida` devolve exatamente o que o evento anterior havia somado. Os identificadores são determinísticos
(derivados do conteúdo da transição), então aplicar o mesmo evento duas vezes não duplica nada.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from ..canonico import hash_canonico
from ..esquema import Modelo
from ..tipos import HashHex, Identificador, Instante, Numero
from .modelos import Motivo, RelatorioConciliacao, ResultadoExecucao, StatusConciliacao

DOMINIO_EVENTO = "ubento.conciliacao.evento.v1"


class TipoEventoConciliacao(StrEnum):
    EXECUCAO_CONCILIADA = "execucao_conciliada"  # +progresso
    CONCILIACAO_REVERTIDA = "conciliacao_revertida"  # −progresso (compensa um evento anterior)
    DIVERGENCIA_ABERTA = "divergencia_aberta"
    DIVERGENCIA_ENCERRADA = "divergencia_encerrada"
    REVISAO_ABERTA = "revisao_aberta"
    REVISAO_ENCERRADA = "revisao_encerrada"
    ORFAO_DETECTADO = "orfao_detectado"


class EventoConciliacao(Modelo):
    id: HashHex
    tipo: TipoEventoConciliacao
    meta_id: Identificador | None = None
    alvo: Identificador  # id da execução, ou id_externo do órfão
    delta_progresso: Numero = Decimal(0)
    motivos: tuple[Motivo, ...] = ()
    horario_evidencia: Instante  # `agora` do relatório que revelou a mudança
    relatorio_hash: HashHex  # hash_saida do relatório de origem (auditoria)


def _evento(tipo, resultado: ResultadoExecucao | None, antes, depois, delta, relatorio, alvo=None, meta=None, motivos=()):
    ident = hash_canonico({"tipo": tipo, "alvo": alvo or resultado.execucao_id, "de": antes, "para": depois}, DOMINIO_EVENTO)
    return EventoConciliacao(
        id=ident, tipo=tipo, meta_id=meta or (resultado.meta_id if resultado else None), alvo=alvo or resultado.execucao_id,
        delta_progresso=delta, motivos=tuple(motivos), horario_evidencia=relatorio.agora, relatorio_hash=relatorio.hash_saida or "0" * 64,
    )


def _hash(resultado: ResultadoExecucao | None) -> str | None:
    return None if resultado is None else hash_canonico(resultado, DOMINIO_EVENTO)


def diferenciar(anterior: RelatorioConciliacao | None, atual: RelatorioConciliacao) -> tuple[EventoConciliacao, ...]:
    antes = {r.execucao_id: r for r in (anterior.execucoes if anterior else ())}
    depois = {r.execucao_id: r for r in atual.execucoes}
    eventos: list[EventoConciliacao] = []
    for id_ in sorted(set(antes) | set(depois)):
        a, d = antes.get(id_), depois.get(id_)
        if a == d:
            continue
        sa = a.status if a else None
        sd = d.status if d else None
        ha, hd = _hash(a), _hash(d)
        efeito_a = a.efeito_no_progresso if a else Decimal(0)
        efeito_d = d.efeito_no_progresso if d else Decimal(0)

        # progresso: reverter o que estava comprovado e, se for o caso, comprovar de novo com os valores atuais
        if sa is StatusConciliacao.CONCILIADA and (sd is not StatusConciliacao.CONCILIADA or efeito_d != efeito_a):
            eventos.append(_evento(TipoEventoConciliacao.CONCILIACAO_REVERTIDA, a, ha, hd, -efeito_a, atual, motivos=(d.motivos if d else ())))
        if sd is StatusConciliacao.CONCILIADA and (sa is not StatusConciliacao.CONCILIADA or efeito_d != efeito_a):
            eventos.append(_evento(TipoEventoConciliacao.EXECUCAO_CONCILIADA, d, ha, hd, efeito_d, atual))

        # divergências e revisões abertas/encerradas (sem efeito no progresso)
        for status, abre, fecha in (
            (StatusConciliacao.DIVERGENTE, TipoEventoConciliacao.DIVERGENCIA_ABERTA, TipoEventoConciliacao.DIVERGENCIA_ENCERRADA),
            (StatusConciliacao.REVISAO, TipoEventoConciliacao.REVISAO_ABERTA, TipoEventoConciliacao.REVISAO_ENCERRADA),
        ):
            if sd is status and sa is not status:
                eventos.append(_evento(abre, d, ha, hd, Decimal(0), atual, motivos=d.motivos))
            elif sa is status and sd is not status:
                eventos.append(_evento(fecha, a, ha, hd, Decimal(0), atual))

    novos = {(o.fonte_id, o.id_externo): o for o in atual.orfaos}
    velhos = {(o.fonte_id, o.id_externo) for o in (anterior.orfaos if anterior else ())}
    for chave in sorted(set(novos) - velhos):
        o = novos[chave]
        eventos.append(_evento(TipoEventoConciliacao.ORFAO_DETECTADO, None, None, hash_canonico(o, DOMINIO_EVENTO), Decimal(0), atual,
                               alvo=o.id_externo, motivos=o.motivos))
    return tuple(eventos)
