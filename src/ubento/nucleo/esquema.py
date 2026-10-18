"""Modelos estritos do domínio (contrato da v0.2).

Regras gerais: campos em português sem acentos, `snake_case`; campos desconhecidos são erro;
modelos imutáveis; decimais só a partir de texto; datas só com fuso; listas obrigatórias não vazias.
Aqui há só **dados e validação estrutural**. Cálculo, avaliação e estado ficam nas fases seguintes.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .tipos import (
    Fracao, HashHex, Identificador, Inteiro, Instante, Numero, Positivo, Quantidade, Texto, Tri, Unidade,
)

SCHEMA_VERSAO = 1


class Modelo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


def _ids_unicos(itens, rotulo: str) -> None:
    repetidos = [i for i, n in Counter(getattr(x, "id") for x in itens).items() if n > 1]
    if repetidos:
        raise ValueError(f"{rotulo}: identificadores repetidos {repetidos}")


# -- enumerações --------------------------------------------------------------------------------


class QualidadeDado(StrEnum):
    DISPONIVEL = "disponivel"
    AUSENTE = "ausente"
    INVALIDA = "invalida"
    DIVERGENTE = "divergente"


class OrigemDado(StrEnum):
    OBSERVADO = "observado"
    SIMULADO = "simulado"  # arquivos de reprodução e fixtures: sempre explícito


class TipoAtivo(StrEnum):
    NATIVO = "nativo"
    TOKEN = "token"
    FIAT = "fiat"


class ResultadoAnalise(StrEnum):
    FAVORAVEL = "favoravel"
    DESFAVORAVEL = "desfavoravel"
    INCONCLUSIVO = "inconclusivo"


class NomeCenario(StrEnum):
    ADVERSO = "adverso"
    REFERENCIA = "referencia"
    FAVORAVEL = "favoravel"


class TipoAfirmacao(StrEnum):
    FATO = "fato"  # observado: exige observação ou evidência
    CALCULO = "calculo"  # derivado: exige indicador
    HIPOTESE = "hipotese"


class RelacaoEvidencia(StrEnum):
    SUSTENTA = "sustenta"
    CONTRADIZ = "contradiz"
    CONTEXTO = "contexto"


class TipoObjetivo(StrEnum):
    ACUMULAR_QUANTIDADE = "acumular_quantidade"


class TratamentoTaxa(StrEnum):
    COBRADA_NA_COTACAO = "cobrada_na_cotacao"  # somada ao valor pago, na moeda de cotação
    EMBUTIDA_NA_COTACAO = "embutida_na_cotacao"  # já está no preço; não descontar de novo
    COBRADA_NO_ATIVO = "cobrada_no_ativo"  # reduz a quantidade recebida


class LadoExecucao(StrEnum):
    COMPRA = "compra"
    ESTORNO_COMPRA = "estorno_compra"  # compensação; nunca se edita a execução original


class EstadoMeta(StrEnum):
    RASCUNHO = "rascunho"
    ATIVA = "ativa"
    ATINGIDA = "atingida"
    EXPIRADA = "expirada"
    INVALIDADA = "invalidada"
    CANCELADA = "cancelada"


class TipoEvento(StrEnum):
    CRIADA = "criada"
    ATIVADA = "ativada"
    AVALIADA = "avaliada"
    ALERTA_EMITIDO = "alerta_emitido"
    BLOQUEIO_INICIADO = "bloqueio_iniciado"
    BLOQUEIO_ENCERRADO = "bloqueio_encerrado"
    EXECUCAO_REGISTRADA = "execucao_registrada"
    ATINGIDA = "atingida"
    EXPIRADA = "expirada"
    INVALIDADA = "invalidada"
    CANCELADA = "cancelada"
    RECONCILIADA = "reconciliada"
    SUBSTITUIDA = "substituida"


PrioridadeEmpate = Literal["atingida", "invalidada", "expirada", "entrada"]
ORDEM_EMPATE_PADRAO: tuple[PrioridadeEmpate, ...] = ("atingida", "invalidada", "expirada", "entrada")
ValorSimples = str | int | bool | None  # conteúdo de explicações e eventos (decimais viajam como texto)


# -- ativo e métrica -------------------------------------------------------------------------------


class Ativo(Modelo):
    id: Identificador
    simbolo: Texto
    rede: Identificador
    tipo: TipoAtivo
    contrato: Texto | None = None
    casas_decimais: Annotated[Inteiro, Field(ge=0, le=36)]
    incremento_quantidade: Positivo

    @model_validator(mode="after")
    def _contrato_coerente(self) -> Ativo:
        if self.tipo is TipoAtivo.TOKEN and self.contrato is None:
            raise ValueError("token exige o endereço/identificador do contrato")
        if self.tipo is not TipoAtivo.TOKEN and self.contrato is not None:
            raise ValueError("só token tem contrato")
        return self


class Metrica(Modelo):
    id: Identificador
    nome: Texto
    unidade: Unidade
    formula_id: Identificador  # versionada, ex.: "retorno@1"; outro método = outro identificador
    parametros: dict[Identificador, Texto] = Field(default_factory=dict)
    dominio_minimo: Numero | None = None
    dominio_maximo: Numero | None = None
    validade_maxima_segundos: Annotated[Inteiro, Field(ge=1)]

    @model_validator(mode="after")
    def _dominio(self) -> Metrica:
        if None not in (self.dominio_minimo, self.dominio_maximo) and self.dominio_minimo > self.dominio_maximo:
            raise ValueError("dominio_minimo maior que dominio_maximo")
        return self


# -- dados da análise -------------------------------------------------------------------------------------


class Observacao(Modelo):
    id: Identificador
    ativo_id: Identificador
    metrica_id: Identificador
    fonte_id: Identificador
    mercado_id: Identificador
    unidade: Unidade
    valor: Numero | None
    qualidade: QualidadeDado
    origem: OrigemDado
    motivo_ausencia: Texto | None = None
    observado_em: Instante
    coletado_em: Instante
    periodo_inicio: Instante | None = None
    periodo_fim: Instante | None = None

    @model_validator(mode="after")
    def _coerencia(self) -> Observacao:
        if self.valor is None and self.qualidade is QualidadeDado.DISPONIVEL:
            raise ValueError("observação disponível precisa de valor")
        if self.valor is None and not self.motivo_ausencia:
            raise ValueError("ausência (valor nulo) exige motivo_ausencia")
        if self.qualidade is not QualidadeDado.DISPONIVEL and not self.motivo_ausencia:
            raise ValueError("qualidade diferente de 'disponivel' exige motivo_ausencia")
        if self.coletado_em < self.observado_em:
            raise ValueError("coletado_em anterior a observado_em")
        if (self.periodo_inicio is None) != (self.periodo_fim is None):
            raise ValueError("informe periodo_inicio e periodo_fim juntos")
        if self.periodo_inicio and self.periodo_fim and self.periodo_fim < self.periodo_inicio:
            raise ValueError("periodo_fim anterior a periodo_inicio")
        return self


class Indicador(Modelo):
    id: Identificador
    metrica_id: Identificador
    formula_id: Identificador
    parametros: dict[Identificador, Texto] = Field(default_factory=dict)
    entradas: Annotated[tuple[Identificador, ...], Field(min_length=1)]  # ids de observações
    resultado: Numero | None
    unidade: Unidade
    motivo_indisponivel: Texto | None = None

    @model_validator(mode="after")
    def _indisponivel(self) -> Indicador:
        if self.resultado is None and not self.motivo_indisponivel:
            raise ValueError("indicador indisponível exige motivo_indisponivel")
        return self


class Evidencia(Modelo):
    id: Identificador
    relacao: RelacaoEvidencia
    descricao: Texto
    referencia: Texto | None = None  # URL ou identificador no provedor
    conteudo_hash: HashHex | None = None  # SHA-256 do documento original, quando preservado
    coletada_em: Instante

    @model_validator(mode="after")
    def _origem(self) -> Evidencia:
        if self.referencia is None and self.conteudo_hash is None:
            raise ValueError("evidência precisa de referencia ou conteudo_hash")
        return self


class Afirmacao(Modelo):
    id: Identificador
    tipo: TipoAfirmacao
    texto: Texto
    referencias: tuple[Identificador, ...] = ()

    @model_validator(mode="after")
    def _referencias(self) -> Afirmacao:
        if self.tipo in (TipoAfirmacao.FATO, TipoAfirmacao.CALCULO) and not self.referencias:
            raise ValueError(f"{self.tipo.value} exige ao menos uma referência")
        return self


class ResultadoCondicional(Modelo):
    metrica_id: Identificador
    valor: Numero
    unidade: Unidade


class Cenario(Modelo):
    id: Identificador
    nome: NomeCenario
    horizonte_dias: Annotated[Inteiro, Field(ge=1)]
    premissas: Annotated[tuple[Texto, ...], Field(min_length=1)]
    custos: Quantidade | None = None
    resultados: tuple[ResultadoCondicional, ...] = ()
    probabilidade: Numero | None = None
    metodo_estimacao: Texto | None = None  # sem método documentado, não há probabilidade

    @model_validator(mode="after")
    def _probabilidade(self) -> Cenario:
        if self.probabilidade is not None:
            if not self.metodo_estimacao:
                raise ValueError("probabilidade exige metodo_estimacao documentado")
            if not (0 <= self.probabilidade <= 1):
                raise ValueError("probabilidade deve estar entre 0 e 1")
        return self


class Escopo(Modelo):
    ativos: Annotated[tuple[Identificador, ...], Field(min_length=1)]
    moeda_referencia: Identificador
    mercados: Annotated[tuple[Identificador, ...], Field(min_length=1)]
    horizonte_dias: Annotated[Inteiro, Field(ge=1)]
    pergunta: Texto

    @field_validator("ativos", "mercados", mode="after")
    @classmethod
    def _conjunto(cls, itens: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(itens)))  # conjunto: a ordem não pode alterar o hash


class Conclusao(Modelo):
    resultado: ResultadoAnalise
    escopo_texto: Texto  # "favorável" vale só dentro deste escopo
    justificativa: Texto
    autor: Texto


class Analise(Modelo):
    id: Identificador
    schema_versao: Literal[1] = SCHEMA_VERSAO
    versao: Annotated[Inteiro, Field(ge=1)]
    escopo: Escopo
    observacoes: tuple[Observacao, ...] = ()
    indicadores: tuple[Indicador, ...] = ()
    evidencias: tuple[Evidencia, ...] = ()
    afirmacoes: tuple[Afirmacao, ...] = ()
    cenarios: tuple[Cenario, ...] = ()
    lacunas: tuple[Texto, ...] = ()
    conclusao: Conclusao
    publicada_em: Instante | None = None  # None = rascunho

    @model_validator(mode="after")
    def _referencias(self) -> Analise:
        for rotulo, itens in (("observacoes", self.observacoes), ("indicadores", self.indicadores),
                              ("evidencias", self.evidencias), ("afirmacoes", self.afirmacoes), ("cenarios", self.cenarios)):
            _ids_unicos(itens, rotulo)
        obs = {o.id for o in self.observacoes}
        ind = {i.id for i in self.indicadores}
        evi = {e.id for e in self.evidencias}
        for indicador in self.indicadores:
            faltando = [e for e in indicador.entradas if e not in obs]
            if faltando:
                raise ValueError(f"indicador {indicador.id}: observações inexistentes {faltando}")
        for a in self.afirmacoes:
            alvo = {TipoAfirmacao.FATO: obs | evi, TipoAfirmacao.CALCULO: ind, TipoAfirmacao.HIPOTESE: obs | ind | evi}[a.tipo]
            faltando = [r for r in a.referencias if r not in alvo]
            if faltando:
                raise ValueError(f"afirmação {a.id} ({a.tipo.value}): referências inválidas {faltando}")
        nomes = Counter(c.nome for c in self.cenarios)
        if any(n > 1 for n in nomes.values()):
            raise ValueError("cenários com o mesmo nome")
        return self


# -- condições (apenas estrutura; a avaliação vem na fase 2) --------------------------------------------------------


class OperandoMetrica(Modelo):
    tipo: Literal["metrica"]
    metrica_id: Identificador
    ativo_id: Identificador
    mercado_id: Identificador | None = None
    janela_segundos: Annotated[Inteiro, Field(ge=1)] | None = None


class OperandoValor(Modelo):
    tipo: Literal["valor"]
    valor: Numero
    unidade: Unidade


Operando = Annotated[OperandoMetrica | OperandoValor, Field(discriminator="tipo")]


class Comparacao(Modelo):
    id: Identificador
    op: Literal["eq", "neq", "gt", "gte", "lt", "lte"]
    esquerda: Operando
    direita: Operando


class Todos(Modelo):
    id: Identificador
    op: Literal["all"]
    itens: Annotated[tuple[Condicao, ...], Field(min_length=1)]


class Algum(Modelo):
    id: Identificador
    op: Literal["any"]
    itens: Annotated[tuple[Condicao, ...], Field(min_length=1)]


class Nao(Modelo):
    id: Identificador
    op: Literal["not"]
    item: Condicao


Condicao = Annotated[Comparacao | Todos | Algum | Nao, Field(discriminator="op")]
for _classe in (Todos, Algum, Nao):
    _classe.model_rebuild()


def ids_da_condicao(condicao: Comparacao | Todos | Algum | Nao) -> list[str]:
    """Todos os ids da árvore, na ordem de percurso."""
    ids = [condicao.id]
    if isinstance(condicao, (Todos, Algum)):
        for filho in condicao.itens:
            ids += ids_da_condicao(filho)
    elif isinstance(condicao, Nao):
        ids += ids_da_condicao(condicao.item)
    return ids


# -- meta (o contrato congelado) -----------------------------------------------------------------------------------


class AprovacaoHumana(Modelo):
    """Premissa qualitativa aprovada por uma pessoa; o algoritmo não infere isso."""

    pergunta: Identificador
    autor: Texto
    justificativa: Annotated[Texto, Field(min_length=10)]
    analise_hash: HashHex
    em: Instante


class Objetivo(Modelo):
    tipo: Literal[TipoObjetivo.ACUMULAR_QUANTIDADE]
    ativo_id: Identificador
    moeda_cotacao_id: Identificador
    quantidade_alvo: Positivo  # quantidade LÍQUIDA recebida, somando execuções confirmadas vinculadas
    prazo: Instante


class MercadoContrato(Modelo):
    mercado_id: Identificador
    conta_id: Identificador | None = None  # conta/carteira em que a meta opera; None = não informada (escopo indeterminado)
    incremento_preco: Positivo
    incremento_quantidade: Positivo


class Custos(Modelo):
    custo_fixo: Quantidade
    taxa_proporcional: Fracao
    tratamento_taxa: TratamentoTaxa


class Recursos(Modelo):
    orcamento: Positivo
    moeda_orcamento_id: Identificador
    saldo_reservado: Positivo
    exposicao_maxima: Fracao

    @model_validator(mode="after")
    def _reserva(self) -> Recursos:
        if self.saldo_reservado > self.orcamento:
            raise ValueError("saldo_reservado maior que o orcamento")
        return self


class Regras(Modelo):
    bloqueios: Annotated[tuple[Condicao, ...], Field(min_length=1)]  # qualidade, liquidez, limites
    entrada: Annotated[tuple[Condicao, ...], Field(min_length=1)]
    invalidacao: Annotated[tuple[Condicao, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _ids(self) -> Regras:
        todos = [i for grupo in (self.bloqueios, self.entrada, self.invalidacao) for c in grupo for i in ids_da_condicao(c)]
        repetidos = [i for i, n in Counter(todos).items() if n > 1]
        if repetidos:
            raise ValueError(f"ids de condição repetidos nas regras: {repetidos}")
        return self


class ValidadeMetrica(Modelo):
    metrica_id: Identificador
    validade_maxima_segundos: Annotated[Inteiro, Field(ge=1)]


class Tolerancia(Modelo):
    """Divergência aceitável entre fontes de UMA métrica em UM mercado (D4)."""

    metrica_id: Identificador
    mercado_id: Identificador
    diferenca_maxima_horario_segundos: Annotated[Inteiro, Field(ge=0)]
    tolerancia_relativa: Fracao


class Politicas(Modelo):
    carencia_dados_segundos: Annotated[Inteiro, Field(ge=0)]  # só para receber evidências (D3)
    ordem_empate: tuple[PrioridadeEmpate, ...] = ORDEM_EMPATE_PADRAO
    validades: tuple[ValidadeMetrica, ...] = ()
    tolerancias: tuple[Tolerancia, ...] = ()

    @model_validator(mode="after")
    def _ordem(self) -> Politicas:
        if sorted(self.ordem_empate) != sorted(ORDEM_EMPATE_PADRAO):
            raise ValueError(f"ordem_empate deve conter exatamente {list(ORDEM_EMPATE_PADRAO)}")
        chaves = [(t.metrica_id, t.mercado_id) for t in self.tolerancias]
        if len(chaves) != len(set(chaves)):
            raise ValueError("tolerância repetida para a mesma métrica e mercado")
        return self


class Fundamentacao(Modelo):
    cenarios_origem: Annotated[tuple[Identificador, ...], Field(min_length=1)]
    justificativa: Texto
    aprovacoes: tuple[AprovacaoHumana, ...] = ()


class Reprodutibilidade(Modelo):
    versao_politica: Identificador
    versao_catalogo: Identificador
    versao_algoritmo: Identificador


class Meta(Modelo):
    """Termos congelados na ativação. Estado, progresso e ativação ficam FORA deste modelo e do hash."""

    id: Identificador
    schema_versao: Literal[1] = SCHEMA_VERSAO
    criada_em: Instante
    analise_id: Identificador
    analise_versao: Annotated[Inteiro, Field(ge=1)]
    analise_hash: HashHex
    substitui_meta_id: Identificador | None = None
    objetivo: Objetivo
    mercado: MercadoContrato
    custos: Custos
    recursos: Recursos
    regras: Regras
    politicas: Politicas
    fundamentacao: Fundamentacao
    reprodutibilidade: Reprodutibilidade

    @model_validator(mode="after")
    def _coerencia(self) -> Meta:
        if self.objetivo.prazo <= self.criada_em:
            raise ValueError("prazo deve ser posterior a criada_em")
        if self.substitui_meta_id == self.id:
            raise ValueError("uma meta não pode substituir a si mesma")
        return self


class Ativacao(Modelo):
    """Quem ativou e quando; referencia o hash do contrato, mas não faz parte dele."""

    meta_id: Identificador
    contrato_hash: HashHex
    ativada_em: Instante
    responsavel: Texto


# -- eventos, execuções e avaliações (formato dos registros) ----------------------------------------------------------


class ReferenciaExterna(Modelo):
    """Aponta, por identificador estável, para o registro de uma fonte externa que comprova a execução."""

    fonte_id: Identificador
    id_externo: Identificador
    # None = a execução usa o registro externo INTEIRO. Um valor permite dividir um registro entre execuções
    # (ex.: duas metas), desde que a soma das alocações não ultrapasse a quantidade do registro.
    quantidade_bruta_alocada: Positivo | None = None


class TaxaOutroAtivo(Modelo):
    """Taxa cobrada em um ativo que não é o recebido nem a moeda de cotação. Entra nos custos; nunca reduz unidades."""

    ativo_id: Identificador
    valor: Positivo


class Execucao(Modelo):
    """Operação CONFIRMADA. Aprovar uma proposta não cria execução (ver docs/ESPECIFICACAO_NUCLEO.md §2).

    É o registro INTERNO. A prova vem da conciliação com registros externos (docs/CONCILIACAO.md).
    """

    id: Identificador
    meta_id: Identificador
    ativo_id: Identificador
    lado: LadoExecucao
    quantidade_bruta: Positivo
    taxa_no_ativo: Quantidade = Decimal(0)
    quantidade_liquida: Positivo
    preco_executado: Positivo
    taxa_na_cotacao: Quantidade = Decimal(0)
    custo_fixo_real: Quantidade = Decimal(0)
    executada_em: Instante
    confirmada_em: Instante
    fonte_id: Identificador
    origem: OrigemDado
    estorna_execucao_id: Identificador | None = None
    moeda_cotacao_id: Identificador | None = None  # em que ativo estão taxa_na_cotacao e custo_fixo_real
    taxas_outros_ativos: tuple[TaxaOutroAtivo, ...] = ()
    referencias_externas: tuple[ReferenciaExterna, ...] = ()

    @model_validator(mode="after")
    def _coerencia(self) -> Execucao:
        if (self.taxa_na_cotacao > 0 or self.custo_fixo_real > 0) and self.moeda_cotacao_id is None:
            raise ValueError("taxa_na_cotacao/custo_fixo_real exigem moeda_cotacao_id")
        chaves = [(r.fonte_id, r.id_externo) for r in self.referencias_externas]
        if len(chaves) != len(set(chaves)):
            raise ValueError("referencias_externas repetidas")
        ativos_taxa = [t.ativo_id for t in self.taxas_outros_ativos]
        if len(ativos_taxa) != len(set(ativos_taxa)):
            raise ValueError("taxas_outros_ativos repetidas para o mesmo ativo")
        if {self.ativo_id, self.moeda_cotacao_id} & set(ativos_taxa):
            raise ValueError("taxas_outros_ativos não pode repetir o ativo recebido nem a moeda de cotação")
        if self.quantidade_liquida != self.quantidade_bruta - self.taxa_no_ativo:
            raise ValueError("quantidade_liquida deve ser quantidade_bruta - taxa_no_ativo")
        if self.confirmada_em < self.executada_em:
            raise ValueError("confirmada_em anterior a executada_em")
        if (self.lado is LadoExecucao.ESTORNO_COMPRA) != (self.estorna_execucao_id is not None):
            raise ValueError("estorno_compra exige estorna_execucao_id (e só ele pode tê-lo)")
        return self


class Evento(Modelo):
    id: Identificador
    meta_id: Identificador
    sequencia: Annotated[Inteiro, Field(ge=1)]
    tipo: TipoEvento
    horario_evidencia: Instante
    registrado_em: Instante
    autor: Texto | None = None
    motivo: Texto | None = None
    chave_idempotencia: HashHex | None = None
    dados: dict[Identificador, ValorSimples] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _coerencia(self) -> Evento:
        if self.registrado_em < self.horario_evidencia:
            raise ValueError("registrado_em anterior ao horario_evidencia")
        if self.tipo in (TipoEvento.RECONCILIADA, TipoEvento.CANCELADA) and not self.autor:
            raise ValueError(f"{self.tipo.value} exige autor")
        if self.tipo is TipoEvento.RECONCILIADA and not self.motivo:
            raise ValueError("reconciliada exige motivo")
        if self.tipo is TipoEvento.ALERTA_EMITIDO and not self.chave_idempotencia:
            raise ValueError("alerta_emitido exige chave_idempotencia")
        return self


class ResultadoCondicao(Modelo):
    condicao_id: Identificador
    resultado: Tri
    explicacao: dict[Identificador, ValorSimples] = Field(default_factory=dict)


class Avaliacao(Modelo):
    id: Identificador
    meta_id: Identificador
    avaliada_em: Instante
    versao_motor: Identificador
    snapshot_id: HashHex
    hash_entradas: HashHex
    estado: EstadoMeta
    bloqueada_por_dados: bool
    resultados: tuple[ResultadoCondicao, ...] = ()
    hash_saida: HashHex | None = None

