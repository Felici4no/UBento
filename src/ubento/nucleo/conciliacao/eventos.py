"""Eventos compensatórios: o que mudou entre dois relatórios de conciliação.

Nada é reescrito. Quando uma execução deixa de estar comprovada (correção ou cancelamento externo), o evento
`conciliacao_revertida` devolve exatamente o que o evento anterior havia somado. Os identificadores são determinísticos
(derivados do conteúdo da transição), então aplicar o mesmo evento duas vezes não duplica nada.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Sequence

from ..canonico import hash_canonico
from ..esquema import LadoExecucao, Modelo
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
    horario_evidencia: Instante  # `agora` do relatório que revelou a mudança (quando a evidência CHEGOU)
    relatorio_hash: HashHex  # hash_saida do relatório de origem (auditoria)
    # instante EFETIVO da execução, distinto de quando a evidência foi recebida (prazo e carência usam este)
    executada_em: Instante | None = None
    lado: LadoExecucao | None = None
    estorna_execucao_id: Identificador | None = None
    delta_gasto: Numero = Decimal(0)  # gasto comprovado que este evento soma (ou devolve), na moeda de cotação
    moeda_gasto: Identificador | None = None


def _evento(tipo, resultado: ResultadoExecucao | None, antes, depois, delta, relatorio, alvo=None, meta=None, motivos=(), delta_gasto=Decimal(0)):
    ident = hash_canonico({"tipo": tipo, "alvo": alvo or resultado.execucao_id, "de": antes, "para": depois}, DOMINIO_EVENTO)
    return EventoConciliacao(
        id=ident, tipo=tipo, meta_id=meta or (resultado.meta_id if resultado else None), alvo=alvo or resultado.execucao_id,
        delta_progresso=delta, motivos=tuple(motivos), horario_evidencia=relatorio.agora, relatorio_hash=relatorio.hash_saida or "0" * 64,
        executada_em=resultado.executada_em if resultado else None, lado=resultado.lado if resultado else None,
        estorna_execucao_id=resultado.estorna_execucao_id if resultado else None,
        delta_gasto=delta_gasto, moeda_gasto=resultado.moeda_gasto if resultado else None,
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
            eventos.append(_evento(TipoEventoConciliacao.CONCILIACAO_REVERTIDA, a, ha, hd, -efeito_a, atual, motivos=(d.motivos if d else ()),
                                   delta_gasto=-a.gasto_comprovado))
        if sd is StatusConciliacao.CONCILIADA and (sa is not StatusConciliacao.CONCILIADA or efeito_d != efeito_a):
            eventos.append(_evento(TipoEventoConciliacao.EXECUCAO_CONCILIADA, d, ha, hd, efeito_d, atual, delta_gasto=d.gasto_comprovado))

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


# -- compensação contra o razão (usada pelo avaliador de metas) ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EfeitoExecucao:
    """O que vale para uma execução depois de aplicar o relatório ao razão."""

    execucao_id: str
    lado: LadoExecucao | None
    executada_em: datetime | None
    estorna_execucao_id: str | None
    efeito: Decimal  # quantidade líquida (com sinal) que vale agora
    gasto_comprovado: Decimal  # idem, na moeda de cotação
    moeda_gasto: str | None
    preservado: bool  # True: sem reverificação agora; vale a prova anterior do razão
    status: StatusConciliacao | None  # None: só existe no razão
    anterior: Decimal = Decimal(0)  # efeito que o razão já tinha aplicado ANTES deste relatório


_PROGRESSO = (TipoEventoConciliacao.EXECUCAO_CONCILIADA, TipoEventoConciliacao.CONCILIACAO_REVERTIDA)
# contradição POSITIVA da prova anterior: o registro mudou, foi cancelado, ficou ambíguo ou sumiu de uma consulta completa
_CONTRADIZ = (StatusConciliacao.DIVERGENTE, StatusConciliacao.REVISAO, StatusConciliacao.SEM_REGISTRO_EXTERNO)
# falta de verificação: não contradiz nada, então a prova anterior permanece
_SEM_VERIFICACAO = (StatusConciliacao.PENDENTE, StatusConciliacao.NAO_VERIFICAVEL)


def efeitos_aplicados(razao: Sequence[EventoConciliacao], meta_id: str) -> dict[str, dict]:
    """Soma, por execução, o que o razão já aplicou (ids repetidos contam uma vez)."""
    vistos: set[str] = set()
    saida: dict[str, dict] = {}
    for e in sorted(razao, key=lambda e: (e.horario_evidencia, e.id)):
        if e.id in vistos or e.meta_id != meta_id or e.tipo not in _PROGRESSO:
            continue
        vistos.add(e.id)
        item = saida.setdefault(e.alvo, {"efeito": Decimal(0), "gasto": Decimal(0), "executada_em": None, "lado": None, "estorna": None, "moeda": None})
        item["efeito"] += e.delta_progresso
        item["gasto"] += e.delta_gasto
        for chave, valor in (("executada_em", e.executada_em), ("lado", e.lado), ("estorna", e.estorna_execucao_id), ("moeda", e.moeda_gasto)):
            if valor is not None:
                item[chave] = valor
    return saida


def compensar(razao: Sequence[EventoConciliacao], relatorio: RelatorioConciliacao, meta_id: str) -> tuple[tuple[EventoConciliacao, ...], dict[str, EfeitoExecucao]]:
    """Eventos que faltam no razão para refletir o relatório, e o efeito vigente de cada execução da meta.

    - Prova nova (conciliada): soma.
    - Contradição positiva (divergente, revisão, ausência PROVADA por consulta completa): reverte, com evento compensatório.
    - Falta de verificação (pendente, não verificável, ou fora do relatório): NÃO reverte. A prova anterior vale e a
      execução fica marcada como `preservado`. Uma janela de consulta nunca apaga histórico válido.
    Reaplicar o mesmo relatório não gera nada: a diferença contra o razão já é zero.
    """
    aplicado = efeitos_aplicados(razao, meta_id)
    existentes = {e.id for e in razao}
    resultados = {r.execucao_id: r for r in relatorio.execucoes if r.meta_id == meta_id}
    eventos: list[EventoConciliacao] = []
    efeitos: dict[str, EfeitoExecucao] = {}

    for id_ in sorted(set(aplicado) | set(resultados)):
        ap = aplicado.get(id_, {})
        efeito_ap, gasto_ap = ap.get("efeito", Decimal(0)), ap.get("gasto", Decimal(0))
        r = resultados.get(id_)
        if r is None:
            alvo, gasto, preservado = efeito_ap, gasto_ap, efeito_ap != 0
        elif r.status is StatusConciliacao.CONCILIADA:
            alvo, gasto, preservado = r.efeito_no_progresso, r.gasto_comprovado, False
        elif r.status in _CONTRADIZ:
            alvo, gasto, preservado = Decimal(0), Decimal(0), False
        else:  # sem verificação
            alvo, gasto, preservado = efeito_ap, gasto_ap, efeito_ap != 0

        executada_em = r.executada_em if r else ap.get("executada_em")
        lado = r.lado if r else ap.get("lado")
        estorna = r.estorna_execucao_id if r else ap.get("estorna")
        moeda = (r.moeda_gasto if r else None) or ap.get("moeda")
        efeitos[id_] = EfeitoExecucao(id_, lado, executada_em, estorna, alvo, gasto, moeda, preservado, r.status if r else None, anterior=efeito_ap)

        if alvo == efeito_ap and gasto == gasto_ap:
            continue
        marca = hash_canonico(r, DOMINIO_EVENTO) if r else None
        base = dict(meta_id=meta_id, alvo=id_, horario_evidencia=relatorio.agora, relatorio_hash=relatorio.hash_saida or "0" * 64,
                    executada_em=executada_em, lado=lado, estorna_execucao_id=estorna, moeda_gasto=moeda, motivos=tuple(r.motivos) if r else ())

        def novo(tipo, delta, delta_gasto):
            ident = hash_canonico({"tipo": tipo, "alvo": id_, "de": str(efeito_ap), "para": str(alvo), "resultado": marca, "gasto": str(delta_gasto)}, DOMINIO_EVENTO)
            return EventoConciliacao(id=ident, tipo=tipo, delta_progresso=delta, delta_gasto=delta_gasto, **base)

        if efeito_ap != 0 or gasto_ap != 0:
            eventos.append(novo(TipoEventoConciliacao.CONCILIACAO_REVERTIDA, -efeito_ap, -gasto_ap))
        if alvo != 0 or gasto != 0:
            eventos.append(novo(TipoEventoConciliacao.EXECUCAO_CONCILIADA, alvo, gasto))
    return tuple(e for e in eventos if e.id not in existentes), efeitos
