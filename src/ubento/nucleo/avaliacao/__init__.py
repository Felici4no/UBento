"""Avaliador de metas: integra conciliação, progresso, regras, estado e eventos. Contrato em `docs/AVALIACAO_META.md`."""

from .avaliador import ErroDeAvaliacao, avaliar_meta
from .estado import ErroDeEventos, bloqueada_por_dados, estado_de
from .modelos import (
    VERSAO_MOTOR, Completude, Elegibilidade, LimiteOrcamento, MotivoAvaliacao, MotivoEscopo, OrfaoAvaliado, Pendencia, ProgressoAvaliado,
    ResultadoAvaliacao,
)

__all__ = [
    "Completude", "Elegibilidade", "ErroDeAvaliacao", "ErroDeEventos", "LimiteOrcamento", "MotivoAvaliacao", "MotivoEscopo",
    "OrfaoAvaliado", "Pendencia", "ProgressoAvaliado", "ResultadoAvaliacao", "VERSAO_MOTOR", "avaliar_meta", "bloqueada_por_dados", "estado_de",
]
