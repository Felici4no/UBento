"""Modelos do avaliador de metas. Contrato em docs/AVALIACAO_META.md.

Quatro coisas distintas, nunca fundidas em um único número:
  - quantidade líquida comprovada     (o que a conciliação confirmou, dentro da janela da meta)
  - completude da conciliação         (há pendências? quais podem reduzir o progresso?)
  - custos verificados                (taxas conferidas x custo fixo e demais, sem evidência)
  - elegibilidade para concluir       (verdadeiro / falso / indeterminado, com motivos)
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from ..conciliacao.eventos import EventoConciliacao
from ..conciliacao.modelos import CustoPorAtivo
from ..esquema import Avaliacao, EstadoMeta, Evento, Modelo
from ..tipos import Identificador, Instante, Numero, Positivo, Texto, Tri

VERSAO_MOTOR = "motor-0.3.0"
AUTOR_SISTEMA = "sistema:avaliador"


class MotivoAvaliacao(StrEnum):
    # elegibilidade para concluir
    QUANTIDADE_INSUFICIENTE = "quantidade_insuficiente"
    PENDENCIA_PODE_REDUZIR_PROGRESSO = "pendencia_pode_reduzir_progresso"
    ORCAMENTO_EXCEDIDO = "orcamento_excedido"
    ORCAMENTO_INDETERMINADO = "orcamento_indeterminado"
    # orçamento
    CUSTOS_SEM_EVIDENCIA = "custos_sem_evidencia"
    MOEDA_INCOMPATIVEL = "moeda_incompativel"
    MOEDA_DO_GASTO_DESCONHECIDA = "moeda_do_gasto_desconhecida"
    # pendências
    ESTORNO_NAO_CONCILIADO = "estorno_nao_conciliado"
    ESTORNO_POSSIVEL_NAO_VINCULADO = "estorno_possivel_nao_vinculado"
    COMPRA_NAO_CONCILIADA = "compra_nao_conciliada"
    COMPRA_POSSIVEL_NAO_VINCULADA = "compra_possivel_nao_vinculada"
    EVIDENCIA_PRESERVADA_SEM_REVERIFICACAO = "evidencia_preservada_sem_reverificacao"
    PROVA_ANTERIOR_CONTRADITA = "prova_anterior_contradita"
    EXECUCAO_SEM_REGISTRO_INTERNO = "execucao_sem_registro_interno"
    # janela e prazo
    EXECUCAO_FORA_DA_JANELA = "execucao_fora_da_janela"
    PRAZO_ENCERRADO = "prazo_encerrado"
    PRAZO_SEM_EVIDENCIA = "prazo_sem_evidencia"


class MotivoEscopo(StrEnum):
    """Por que um registro externo sem execução interna bloqueia (ou não) uma meta."""

    # relevantes
    COMPRA_POSSIVELMENTE_DA_META = "compra_possivelmente_da_meta"
    ESTORNO_DE_REGISTRO_DA_META = "estorno_de_registro_da_meta"
    CONTA_INDETERMINADA = "conta_indeterminada"  # conservador: sem conta, não dá para excluir
    # irrelevantes
    ATIVO_DIFERENTE = "ativo_diferente"
    MERCADO_DIFERENTE = "mercado_diferente"
    MOEDA_COTACAO_DIFERENTE = "moeda_cotacao_diferente"
    CONTA_DIFERENTE = "conta_diferente"
    ORIGEM_DIFERENTE = "origem_diferente"
    FORA_DO_PERIODO = "fora_do_periodo"
    ESTORNO_DE_OUTRA_COMPRA = "estorno_de_outra_compra"
    JA_ENCERRADO = "ja_encerrado"


class Pendencia(Modelo):
    """Algo na conciliação que ainda não está resolvido para esta meta."""

    referencia: Texto  # id da execução ou do registro externo
    origem: Annotated[str, Field(pattern="^(execucao|registro_externo)$")]
    status: Texto
    motivos: tuple[Texto, ...] = ()
    pode_reduzir_progresso: bool = False  # se resolver mal pode DIMINUIR o que já está comprovado
    motivo_avaliacao: MotivoAvaliacao


class OrfaoAvaliado(Modelo):
    fonte_id: Identificador
    id_externo: Identificador
    relevante: bool
    motivos: tuple[MotivoEscopo, ...]


class LimiteOrcamento(Modelo):
    """Limite obrigatório. Só é verdadeiro se NEM o pior caso dos custos sem evidência o estoura."""

    moeda_id: Identificador
    orcamento: Positivo
    gasto_minimo: Numero  # só o que está comprovado
    gasto_maximo: Numero  # comprovado + custo fixo + tudo o que ainda não foi conciliado + possíveis compras sem dono
    resultado: Tri
    motivos: tuple[MotivoAvaliacao, ...] = ()


class Elegibilidade(Modelo):
    resultado: Tri
    motivos: tuple[MotivoAvaliacao, ...] = ()


class Completude(Modelo):
    completa: bool
    pendencias: tuple[Pendencia, ...] = ()


class ProgressoAvaliado(Modelo):
    quantidade_alvo: Positivo
    quantidade_comprovada: Numero  # líquida, dentro da janela da meta (ativação .. prazo)
    quantidade_fora_da_janela: Numero  # comprovada, mas executada fora da janela: não conta
    quantidade_preservada: Numero  # parte de `comprovada` que vale por prova anterior, sem reverificação agora
    quantidade_pendente: Numero  # declarada e ainda não comprovada (potencial)
    instante_atingimento: Instante | None  # instante EFETIVO da execução que fechou a meta (não o da evidência)
    completude: Completude
    custos: tuple[CustoPorAtivo, ...]
    orcamento: LimiteOrcamento
    elegibilidade: Elegibilidade
    orfaos: tuple[OrfaoAvaliado, ...] = ()
    aguardando_evidencia: bool = False
    em_carencia: bool = False


class ResultadoAvaliacao(Modelo):
    avaliacao: Avaliacao
    estado_anterior: EstadoMeta
    estado: EstadoMeta
    progresso: ProgressoAvaliado
    eventos: tuple[Evento, ...] = ()  # novos eventos da meta
    eventos_conciliacao: tuple[EventoConciliacao, ...] = ()  # novas entradas para o razão de conciliação

