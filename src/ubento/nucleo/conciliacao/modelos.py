"""Modelos da conciliação: entradas (registros externos) e saídas (resultados). Contrato em docs/CONCILIACAO.md."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from ..esquema import LadoExecucao, Modelo, OrigemDado
from ..tipos import Fracao, HashHex, Identificador, Inteiro, Instante, Numero, Positivo, Quantidade, Texto

Natural = Annotated[Inteiro, Field(ge=0)]


# -- enumerações -------------------------------------------------------------------------------------


class StatusRegistroExterno(StrEnum):
    CONFIRMADO = "confirmado"
    PENDENTE = "pendente"
    CANCELADO = "cancelado"


class TipoMovimentacao(StrEnum):
    EXECUCAO = "execucao"
    TAXA = "taxa"
    DEPOSITO = "deposito"
    RETIRADA = "retirada"
    TRANSFERENCIA_ENTRADA = "transferencia_entrada"
    TRANSFERENCIA_SAIDA = "transferencia_saida"
    AJUSTE = "ajuste"


class StatusConciliacao(StrEnum):
    CONCILIADA = "conciliada"
    DIVERGENTE = "divergente"
    PENDENTE = "pendente"
    SEM_REGISTRO_EXTERNO = "sem_registro_externo"  # ausência PROVADA: a consulta cobria o período
    NAO_VERIFICAVEL = "nao_verificavel"  # ausência NÃO provada: a consulta não cobria o período
    REVISAO = "revisao"


class StatusSaldo(StrEnum):
    EXPLICADA = "explicada"
    NAO_EXPLICADA = "nao_explicada"
    DADOS_INSUFICIENTES = "dados_insuficientes"


class Confirmacao(StrEnum):
    CONFIRMADA = "confirmada"
    INCOMPLETA = "incompleta"


class Motivo(StrEnum):
    # dados ausentes ou atrasados
    AGUARDANDO_REGISTRO_EXTERNO = "aguardando_registro_externo"
    REGISTRO_EXTERNO_PENDENTE = "registro_externo_pendente"
    REGISTRO_EXTERNO_NAO_ENCONTRADO = "registro_externo_nao_encontrado"
    # correspondência incerta ou conflitante
    SEM_IDENTIFICADOR_EXTERNO = "sem_identificador_externo"
    VERSAO_EXTERNA_CONFLITANTE = "versao_externa_conflitante"
    ID_INTERNO_DUPLICADO_CONTEUDO_DIFERENTE = "id_interno_duplicado_conteudo_diferente"
    REGISTRO_EXTERNO_EM_VARIAS_EXECUCOES = "registro_externo_em_varias_execucoes"
    REGISTRO_EXTERNO_EM_METAS_DIFERENTES = "registro_externo_em_metas_diferentes"
    ALOCACAO_EXCEDE_REGISTRO_EXTERNO = "alocacao_excede_registro_externo"
    # divergências de conteúdo
    CANCELADO_EXTERNAMENTE = "cancelado_externamente"
    ATIVO_DIFERENTE = "ativo_diferente"
    LADO_DIFERENTE = "lado_diferente"
    MOEDA_COTACAO_DIFERENTE = "moeda_cotacao_diferente"
    QUANTIDADE_BRUTA_DIFERENTE = "quantidade_bruta_diferente"
    TAXA_NO_ATIVO_DIFERENTE = "taxa_no_ativo_diferente"
    QUANTIDADE_LIQUIDA_DIFERENTE = "quantidade_liquida_diferente"
    PRECO_DIFERENTE = "preco_diferente"
    TAXA_NA_COTACAO_DIFERENTE = "taxa_na_cotacao_diferente"
    TAXA_OUTRO_ATIVO_NAO_REGISTRADA = "taxa_outro_ativo_nao_registrada"
    TAXA_OUTRO_ATIVO_DIFERENTE = "taxa_outro_ativo_diferente"
    HORARIO_FORA_DA_TOLERANCIA = "horario_fora_da_tolerancia"
    # estornos
    ESTORNO_SEM_ORIGINAL = "estorno_sem_original"
    ESTORNO_DE_OUTRA_META = "estorno_de_outra_meta"
    ESTORNO_DE_ORIGINAL_NAO_CONCILIADA = "estorno_de_original_nao_conciliada"
    ESTORNO_EXCEDE_ORIGINAL = "estorno_excede_original"
    ESTORNO_EXTERNO_APONTA_PARA_OUTRA_EXECUCAO = "estorno_externo_aponta_para_outra_execucao"
    # informativos (não bloqueiam)
    CORRIGIDO_EXTERNAMENTE = "corrigido_externamente"
    DUPLICATA_IDENTICA = "duplicata_identica"
    # externos e saldos
    SEM_REGISTRO_INTERNO = "sem_registro_interno"
    DIFERENCA_NAO_EXPLICADA = "diferenca_nao_explicada"
    COBERTURA_INSUFICIENTE = "cobertura_insuficiente"
    SALDO_AUSENTE = "saldo_ausente"
    MOVIMENTO_DE_EXECUCAO_AUSENTE = "movimento_de_execucao_ausente"
    MOVIMENTO_DE_EXECUCAO_DIVERGENTE = "movimento_de_execucao_divergente"


INFORMATIVOS = frozenset({Motivo.CORRIGIDO_EXTERNAMENTE, Motivo.DUPLICATA_IDENTICA})


# -- entradas ----------------------------------------------------------------------------------------------


class TaxaExterna(Modelo):
    ativo_id: Identificador
    valor: Quantidade


class RegistroExterno(Modelo):
    """Uma versão de uma execução reportada por uma fonte. Nunca é alterado: correção = nova `versao`."""

    fonte_id: Identificador
    id_externo: Identificador
    versao: Annotated[Inteiro, Field(ge=1)] = 1
    id_ordem: Identificador | None = None  # agrupa execuções parciais de uma mesma ordem
    mercado_id: Identificador
    conta_id: Identificador | None = None  # conta/carteira na fonte; None = desconhecida
    ativo_id: Identificador
    moeda_cotacao_id: Identificador
    lado: LadoExecucao
    quantidade: Positivo  # bruta, antes das taxas cobradas no ativo
    preco: Positivo
    taxas: tuple[TaxaExterna, ...] = ()
    status: StatusRegistroExterno
    executado_em: Instante
    recebido_em: Instante
    origem: OrigemDado
    estorna_id_externo: Identificador | None = None

    @model_validator(mode="after")
    def _coerencia(self) -> RegistroExterno:
        if (self.lado is LadoExecucao.ESTORNO_COMPRA) != (self.estorna_id_externo is not None):
            raise ValueError("estorno_compra exige estorna_id_externo (e só ele pode tê-lo)")
        ativos = [t.ativo_id for t in self.taxas]
        if len(ativos) != len(set(ativos)):
            raise ValueError("taxas repetidas para o mesmo ativo (some-as na origem)")
        if self.recebido_em < self.executado_em:
            raise ValueError("recebido_em anterior a executado_em")
        return self

    @property
    def chave(self) -> tuple[str, str]:
        return (self.fonte_id, self.id_externo)


class VinculoManual(Modelo):
    """Decisão humana que liga uma execução a um registro externo (resolve correspondência incerta)."""

    execucao_id: Identificador
    fonte_id: Identificador
    id_externo: Identificador
    quantidade_bruta_alocada: Positivo | None = None
    autor: Texto
    justificativa: Annotated[Texto, Field(min_length=10)]
    em: Instante


class RevogacaoVinculo(Modelo):
    """Correção AUDITÁVEL de um vínculo manual: o vínculo original é preservado e deixa de valer a partir de `em`.

    Não cria execução nem estorno: só retira a correspondência decidida por um humano. `substituido_por_id` aponta para o
    vínculo que passa a valer no lugar (substituição); vazio = revogação simples. A identidade do vínculo é o hash do seu conteúdo
    (`id_do_vinculo`), então uma revogação nunca se aplica a outro vínculo.
    """

    vinculo_id: HashHex
    autor: Texto
    justificativa: Annotated[Texto, Field(min_length=10)]
    em: Instante
    substituido_por_id: HashHex | None = None


class Movimentacao(Modelo):
    fonte_id: Identificador
    id_externo: Identificador
    ativo_id: Identificador
    tipo: TipoMovimentacao
    quantidade: Numero  # com sinal: crédito > 0, débito < 0
    em: Instante
    recebido_em: Instante
    origem: OrigemDado
    referencia_execucao_externa: Identificador | None = None

    @model_validator(mode="after")
    def _coerencia(self) -> Movimentacao:
        if self.quantidade == 0:
            raise ValueError("movimentação de quantidade zero")
        if self.tipo in (TipoMovimentacao.DEPOSITO, TipoMovimentacao.TRANSFERENCIA_ENTRADA) and self.quantidade < 0:
            raise ValueError(f"{self.tipo.value} deve ter quantidade positiva")
        if self.tipo in (TipoMovimentacao.RETIRADA, TipoMovimentacao.TRANSFERENCIA_SAIDA, TipoMovimentacao.TAXA) and self.quantidade > 0:
            raise ValueError(f"{self.tipo.value} deve ter quantidade negativa")
        if self.recebido_em < self.em:
            raise ValueError("recebido_em anterior a em")
        return self


class SaldoObservado(Modelo):
    fonte_id: Identificador
    ativo_id: Identificador
    quantidade: Quantidade
    observado_em: Instante
    recebido_em: Instante
    origem: OrigemDado


class Cobertura(Modelo):
    """Intervalo em que a fonte garante ter informado TODAS as movimentações do ativo."""

    fonte_id: Identificador
    ativo_id: Identificador
    inicio: Instante
    fim: Instante

    @model_validator(mode="after")
    def _intervalo(self) -> Cobertura:
        if self.fim <= self.inicio:
            raise ValueError("fim deve ser posterior a inicio")
        return self


class CoberturaExecucoes(Modelo):
    """A fonte garante que a consulta feita em `consultada_em` devolveu TODAS as execuções do período.

    Só com isto a ausência de um registro externo prova que ele não existe. Sem cobertura, a ausência é
    "não verificável": nem confirma nem desmente a execução (e não apaga prova anterior).
    """

    fonte_id: Identificador
    ativo_id: Identificador | None = None  # None = todos os ativos da fonte
    inicio: Instante
    fim: Instante
    consultada_em: Instante

    @model_validator(mode="after")
    def _intervalo(self) -> CoberturaExecucoes:
        if self.fim <= self.inicio:
            raise ValueError("fim deve ser posterior a inicio")
        if self.consultada_em < self.fim:
            raise ValueError("consultada_em anterior ao fim do período coberto")
        return self


class PoliticaConciliacao(Modelo):
    """Parâmetros explícitos; não existe limite universal."""

    janela_atraso_segundos: Natural
    tolerancia_horario_segundos: Natural
    janela_candidatos_segundos: Natural = 0
    tolerancia_preco_relativa: Fracao = Decimal(0)
    tolerancias_quantidade: dict[Identificador, Quantidade] = Field(default_factory=dict)
    tolerancia_quantidade_padrao: Quantidade = Decimal(0)
    tolerancia_saldo: Quantidade = Decimal(0)
    orfaos_bloqueiam_confirmacao: bool = True

    def tolerancia_de(self, ativo_id: str) -> Decimal:
        return self.tolerancias_quantidade.get(ativo_id, self.tolerancia_quantidade_padrao)


# -- saídas -------------------------------------------------------------------------------------------------


class RefResolvida(Modelo):
    fonte_id: Identificador
    id_externo: Identificador
    versao: Annotated[Inteiro, Field(ge=1)]


class Diferenca(Modelo):
    campo: Identificador
    interno: Texto | None
    externo: Texto | None


class CustoPorAtivo(Modelo):
    """Custos (taxas e custo fixo) em UM ativo. Ativos diferentes nunca são somados nem convertidos.

    `verificado`: taxas conferidas contra registro externo de uma execução conciliada.
    `nao_verificado`: o que não tem evidência externa (custo fixo, ou custos de execuções ainda não conciliadas).
    """

    ativo_id: Identificador
    verificado: Quantidade
    nao_verificado: Quantidade


class GastoPorAtivo(Modelo):
    """Gasto total na moeda de cotação (valor pago nas compras + taxas + custo fixo, menos estornos)."""

    ativo_id: Identificador
    comprovado: Numero  # execuções conciliadas: valor pago e taxa na cotação, líquidos de estornos
    nao_comprovado: Quantidade  # custo fixo e tudo o que ainda não foi conciliado (limite superior)


class ResultadoExecucao(Modelo):
    execucao_id: Identificador
    meta_id: Identificador
    ativo_id: Identificador
    lado: LadoExecucao
    executada_em: Instante
    status: StatusConciliacao
    motivos: tuple[Motivo, ...] = ()
    externos: tuple[RefResolvida, ...] = ()
    candidatos: tuple[RefResolvida, ...] = ()
    diferencas: tuple[Diferenca, ...] = ()
    efeito_no_progresso: Numero = Decimal(0)  # com sinal; 0 se não conciliada
    declarado: Numero = Decimal(0)  # com sinal; o que foi registrado internamente
    origem: OrigemDado = OrigemDado.SIMULADO
    estorna_execucao_id: Identificador | None = None
    moeda_gasto: Identificador | None = None
    gasto_comprovado: Numero = Decimal(0)
    gasto_nao_comprovado: Quantidade = Decimal(0)


class ResultadoExterno(Modelo):
    """Registro externo que nenhuma execução interna referencia."""

    fonte_id: Identificador
    id_externo: Identificador
    versao: Annotated[Inteiro, Field(ge=1)]
    ativo_id: Identificador
    lado: LadoExecucao
    quantidade: Positivo
    preco: Positivo
    moeda_cotacao_id: Identificador
    taxas: tuple[TaxaExterna, ...] = ()
    mercado_id: Identificador
    conta_id: Identificador | None = None
    origem: OrigemDado
    status: StatusRegistroExterno
    executado_em: Instante
    recebido_em: Instante
    estorna_id_externo: Identificador | None = None
    motivos: tuple[Motivo, ...] = (Motivo.SEM_REGISTRO_INTERNO,)


class ResultadoSaldo(Modelo):
    ativo_id: Identificador
    fonte_id: Identificador
    inicio: Instante | None
    fim: Instante | None
    status: StatusSaldo
    saldo_inicial: Quantidade | None = None
    saldo_final: Quantidade | None = None
    variacao_observada: Numero | None = None
    variacao_explicada: Numero | None = None
    residuo: Numero | None = None
    por_tipo: dict[Identificador, Numero] = Field(default_factory=dict)
    motivos: tuple[Motivo, ...] = ()
    inconsistencias: tuple[Texto, ...] = ()


class ProgressoMeta(Modelo):
    meta_id: Identificador
    ativo_id: Identificador | None
    comprovado: Numero  # só execuções conciliadas
    declarado: Numero  # tudo que foi registrado internamente
    nao_comprovado: Numero
    por_status: dict[Identificador, Natural]
    taxas_no_ativo: Numero  # líquida: estornos devolvem
    custos: tuple[CustoPorAtivo, ...]
    gasto: tuple[GastoPorAtivo, ...] = ()
    confirmacao: Confirmacao  # só das execuções da meta; órfãos são avaliados com o escopo do contrato
    pendencias: tuple[Texto, ...] = ()


class RelatorioConciliacao(Modelo):
    agora: Instante
    hash_entradas: HashHex
    execucoes: tuple[ResultadoExecucao, ...]
    orfaos: tuple[ResultadoExterno, ...]
    saldos: tuple[ResultadoSaldo, ...]
    progresso: tuple[ProgressoMeta, ...]
    confirmacao: Confirmacao
    hash_saida: HashHex | None = None
