"""Estado de uma meta derivado de eventos. O contrato é imutável; o estado é uma função da história."""

from __future__ import annotations

from typing import Sequence

from ..esquema import EstadoMeta, Evento, TipoEvento

TERMINAIS = frozenset({EstadoMeta.ATINGIDA, EstadoMeta.EXPIRADA, EstadoMeta.INVALIDADA, EstadoMeta.CANCELADA})
RECONCILIAVEIS = frozenset({EstadoMeta.ATINGIDA, EstadoMeta.EXPIRADA, EstadoMeta.INVALIDADA})  # `cancelada` é ato humano: não se recalcula

_ENCERRAMENTOS = {TipoEvento.ATINGIDA: EstadoMeta.ATINGIDA, TipoEvento.EXPIRADA: EstadoMeta.EXPIRADA, TipoEvento.INVALIDADA: EstadoMeta.INVALIDADA}
_NEUTROS = (TipoEvento.AVALIADA, TipoEvento.ALERTA_EMITIDO, TipoEvento.BLOQUEIO_INICIADO, TipoEvento.BLOQUEIO_ENCERRADO, TipoEvento.EXECUCAO_REGISTRADA)


class ErroDeEventos(ValueError):
    """A história da meta é inconsistente (sequência, dono ou transição ilegal)."""


def validar_historico(meta_id: str, eventos: Sequence[Evento]) -> list[Evento]:
    """Eventos em ordem de sequência, sem repetição, todos da mesma meta e sem buracos."""
    ordenados = sorted(eventos, key=lambda e: e.sequencia)
    for esperado, e in enumerate(ordenados, start=1):
        if e.meta_id != meta_id:
            raise ErroDeEventos(f"evento {e.id} pertence a outra meta ({e.meta_id})")
        if e.sequencia != esperado:
            raise ErroDeEventos(f"sequência inválida: esperava {esperado}, veio {e.sequencia} (evento {e.id})")
    if len({e.id for e in ordenados}) != len(ordenados):
        raise ErroDeEventos("ids de evento repetidos")
    return ordenados


def estado_de(eventos: Sequence[Evento], meta_id: str) -> EstadoMeta:
    estado = EstadoMeta.RASCUNHO
    for e in validar_historico(meta_id, eventos):
        t = e.tipo
        if t is TipoEvento.CRIADA:
            if estado is not EstadoMeta.RASCUNHO:
                raise ErroDeEventos("`criada` só vale em rascunho")
        elif t is TipoEvento.ATIVADA:
            if estado is not EstadoMeta.RASCUNHO:
                raise ErroDeEventos("`ativada` só vale em rascunho")
            estado = EstadoMeta.ATIVA
        elif t in _ENCERRAMENTOS:
            if estado is not EstadoMeta.ATIVA:
                raise ErroDeEventos(f"`{t.value}` só vale em meta ativa (estado atual: {estado.value}); use `reconciliada`")
            estado = _ENCERRAMENTOS[t]
        elif t is TipoEvento.CANCELADA:
            if estado not in (EstadoMeta.RASCUNHO, EstadoMeta.ATIVA):
                raise ErroDeEventos("`cancelada` só vale em rascunho ou meta ativa")
            estado = EstadoMeta.CANCELADA
        elif t is TipoEvento.RECONCILIADA:
            if estado not in RECONCILIAVEIS:
                raise ErroDeEventos(f"`reconciliada` só corrige estados atingida/expirada/invalidada (atual: {estado.value})")
            try:
                estado = EstadoMeta(str(e.dados.get("estado_resultante")))
            except ValueError as erro:
                raise ErroDeEventos("`reconciliada` exige dados.estado_resultante válido") from erro
            if estado in (EstadoMeta.RASCUNHO, EstadoMeta.CANCELADA):
                raise ErroDeEventos("`reconciliada` não pode levar a rascunho nem a cancelada")
        elif t is TipoEvento.SUBSTITUIDA:
            if estado is not EstadoMeta.CANCELADA:
                raise ErroDeEventos("`substituida` só vale em meta cancelada")
        elif t in _NEUTROS:
            if estado is not EstadoMeta.ATIVA:
                raise ErroDeEventos(f"`{t.value}` só vale em meta ativa (estado atual: {estado.value})")
    return estado


def bloqueada_por_dados(eventos: Sequence[Evento], meta_id: str) -> bool:
    """Condição operacional (não é estado): vale o último entre `bloqueio_iniciado` e `bloqueio_encerrado`."""
    aberta = False
    for e in validar_historico(meta_id, eventos):
        if e.tipo is TipoEvento.BLOQUEIO_INICIADO:
            aberta = True
        elif e.tipo is TipoEvento.BLOQUEIO_ENCERRADO:
            aberta = False
    return aberta


def ultima_sequencia(eventos: Sequence[Evento]) -> int:
    return max((e.sequencia for e in eventos), default=0)


def sequencia_do_ultimo_estado(eventos: Sequence[Evento]) -> int:
    """Sequência do último evento que mudou o estado; distingue 'atingida' de gerações diferentes da mesma meta."""
    muda = {TipoEvento.ATIVADA, TipoEvento.ATINGIDA, TipoEvento.EXPIRADA, TipoEvento.INVALIDADA, TipoEvento.CANCELADA, TipoEvento.RECONCILIADA}
    return max((e.sequencia for e in eventos if e.tipo in muda), default=0)
