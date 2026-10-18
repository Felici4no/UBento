"""Gera exemplos/avaliacao/*.yaml: a meta acompanhada de ponta a ponta com dados de reprodução (SIMULADOS).

    python scripts/gerar_cenarios_meta.py

Cada cenário tem a meta, as execuções internas, os registros externos e o resultado esperado por momento.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "exemplos" / "avaliacao"
FONTE = "corretora-sim"
META = "meta-tokx-001"
DIA = "2026-10-20"


def t(hora: str) -> str:
    return f"{DIA}T{hora}Z"


def s(valor) -> str:
    texto = format(Decimal(str(valor)).normalize(), "f")
    return texto


def cmp(id_, op, metrica, valor, unidade, janela=None):
    esquerda = {"tipo": "metrica", "metrica_id": metrica, "ativo_id": "tokx", "mercado_id": "bolsa-a"}
    if janela:
        esquerda["janela_segundos"] = janela
    return {"id": id_, "op": op, "esquerda": esquerda, "direita": {"tipo": "valor", "valor": valor, "unidade": unidade}}


def meta(alvo="10", prazo="16:00:00", carencia=7200, orcamento="1000", conta="conta-a", ordem=None, exposicao="1"):
    politicas = {
        "carencia_dados_segundos": carencia,
        "validades": [{"metrica_id": "preco_executavel", "validade_maxima_segundos": 86400}, {"metrica_id": "retorno_7d", "validade_maxima_segundos": 86400}],
    }
    if ordem:
        politicas["ordem_empate"] = ordem
    return {
        "id": META, "criada_em": t("07:30:00"), "analise_id": "analise-tokx-001", "analise_versao": 1, "analise_hash": "a" * 64,
        "objetivo": {"tipo": "acumular_quantidade", "ativo_id": "tokx", "moeda_cotacao_id": "usd", "quantidade_alvo": alvo, "prazo": t(prazo)},
        "mercado": {"mercado_id": "bolsa-a", "conta_id": conta, "incremento_preco": "0.0001", "incremento_quantidade": "0.01"},
        "custos": {"custo_fixo": "0", "taxa_proporcional": "0.005", "tratamento_taxa": "cobrada_na_cotacao"},
        "recursos": {"orcamento": orcamento, "moeda_orcamento_id": "usd", "saldo_reservado": orcamento, "exposicao_maxima": exposicao},
        "regras": {
            "bloqueios": [cmp("bq-preco", "gt", "preco_executavel", "0", "USD")],
            "entrada": [cmp("en-preco", "lte", "preco_executavel", "9.9", "USD")],
            "invalidacao": [cmp("inv-queda", "lt", "retorno_7d", "-0.30", "razao", 604800)],
        },
        "politicas": politicas,
        "fundamentacao": {"cenarios_origem": ["cen-referencia"], "justificativa": "Cenário de reprodução (simulado)."},
        "reprodutibilidade": {"versao_politica": "politica-1", "versao_catalogo": "catalogo-1", "versao_algoritmo": "motor-0.3.0"},
    }


def obs(id_, metrica, valor, unidade, hora):
    return {"id": id_, "ativo_id": "tokx", "metrica_id": metrica, "fonte_id": "fonte-sim", "mercado_id": "bolsa-a", "unidade": unidade,
            "valor": valor, "qualidade": "disponivel", "origem": "simulado", "observado_em": t(hora), "coletado_em": t(hora)}


OBS_BASE = [obs("o-preco-0", "preco_executavel", "12", "USD", "08:30:00"), obs("o-ret-0", "retorno_7d", "0.01", "razao", "08:30:00")]


def ex(id_, bruta, taxa="0", h="10:00:00", preco="9.5", refs=None, lado="compra", estorna=None, minutos_conf=1, fonte=FONTE, **extra):
    hh, mm, ss = (int(x) for x in h.split(":"))
    total = hh * 3600 + mm * 60 + ss + minutos_conf * 60
    conf = f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"
    registro = {
        "id": id_, "meta_id": META, "ativo_id": "tokx", "lado": lado, "quantidade_bruta": s(bruta), "taxa_no_ativo": s(taxa),
        "quantidade_liquida": s(Decimal(str(bruta)) - Decimal(str(taxa))), "preco_executado": s(preco), "moeda_cotacao_id": "usd",
        "executada_em": t(h), "confirmada_em": t(conf), "fonte_id": "registro-manual", "origem": "simulado",
        "referencias_externas": [{"fonte_id": fonte, "id_externo": r} for r in (refs or [f"fill-{id_.split('-')[-1]}"])],
    }
    if estorna:
        registro["estorna_execucao_id"] = estorna
    registro.update(extra)
    return registro


def ext(id_, qtd, taxas=(), h="10:00:00", recebido=None, preco="9.5", lado="compra", estorna=None, conta="conta-a", mercado="bolsa-a", ativo="tokx",
        origem="simulado", status="confirmado", versao=1, fonte=FONTE):
    hh, mm, ss = (int(x) for x in h.split(":"))
    total = hh * 3600 + mm * 60 + ss + 30
    padrao = f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"
    registro = {
        "fonte_id": fonte, "id_externo": id_, "versao": versao, "mercado_id": mercado, "conta_id": conta, "ativo_id": ativo, "moeda_cotacao_id": "usd",
        "lado": lado, "quantidade": s(qtd), "preco": s(preco), "taxas": [{"ativo_id": a, "valor": s(v)} for a, v in taxas], "status": status,
        "executado_em": t(h), "recebido_em": t(recebido or padrao), "origem": origem,
    }
    if estorna:
        registro["estorna_id_externo"] = estorna
    return registro


def m(hora, ocultar=None, **esperado):
    momento = {"agora": t(hora), "esperado": esperado}
    if ocultar:
        momento["ocultar"] = ocultar
    return momento


POLITICA = {"janela_atraso_segundos": 3600, "tolerancia_horario_segundos": 60}


def politica(conta="conta-a"):
    """A fonte que comprova é declarada por (conta, mercado). Sem conta no contrato não há fonte a autorizar."""
    return {**POLITICA, "fontes_autorizadas": [{"conta_id": conta, "mercado_id": "bolsa-a", "fonte_id": FONTE}] if conta else []}


def cenario(descricao, execucoes, externos, momentos, alvo="10", prazo="16:00:00", carencia=7200, orcamento="1000", observacoes=None, conta="conta-a",
            ordem=None, exposicao="1", **extra):
    return {
        "schema_versao": 1, "origem": "simulado", "descricao": descricao, "meta": meta(alvo, prazo, carencia, orcamento, conta, ordem, exposicao),
        "ativada_em": t("08:00:00"), "responsavel": "Pessoa de exemplo", "politica_conciliacao": politica(conta), "execucoes": execucoes,
        "registros_externos": externos, "observacoes": OBS_BASE if observacoes is None else observacoes, "momentos": momentos, **extra,
    }


C: dict[str, dict] = {}

# 01 --------------------------------------------------------------------------------------------------------------------------------------
C["01_parcial_ate_atingir"] = cenario(
    "Três preenchimentos parciais (3,98 + 2,985 + 3,085 líquidos). Só o último fecha a meta; o instante efetivo é o da execução (12:00).",
    [ex("ex-1", "4", "0.02", "10:00:00"), ex("ex-2", "3", "0.015", "11:00:00"), ex("ex-3", "3.1", "0.015", "12:00:00")],
    [ext("fill-1", "4", [("tokx", "0.02")], "10:00:00"), ext("fill-2", "3", [("tokx", "0.015")], "11:00:00"), ext("fill-3", "3.1", [("tokx", "0.015")], "12:00:00")],
    [
        m("10:30:00", estado="ativa", eventos=["ativada", "execucao_registrada"], quantidade_comprovada="3.98", elegibilidade="falso",
          motivos_elegibilidade=["quantidade_insuficiente"], completa=True, bloqueada_por_dados=False),
        m("11:30:00", estado="ativa", eventos=["execucao_registrada"], quantidade_comprovada="6.965", elegibilidade="falso"),
        m("12:30:00", estado="atingida", eventos=["execucao_registrada", "atingida"], quantidade_comprovada="10.05", elegibilidade="verdadeiro",
          orcamento="verdadeiro", evidencia_em={"atingida": t("12:00:00")}, completa=True),
        m("14:00:00", estado="atingida", eventos=[], eventos_conciliacao=[], quantidade_comprovada="10.05"),
    ],
)

# 02 --------------------------------------------------------------------------------------------------------------------------------------
C["02_taxa_no_ativo_reduz_a_quantidade"] = cenario(
    "Comprar 10 não basta: a taxa de 0,05 TOKX cobrada no ativo deixa 9,95 líquidos. Só a compra seguinte (0,1) fecha a meta.",
    [ex("ex-1", "10", "0.05", "10:00:00"), ex("ex-2", "0.1", "0", "11:00:00")],
    [ext("fill-1", "10", [("tokx", "0.05")], "10:00:00"), ext("fill-2", "0.1", [], "11:00:00")],
    [
        m("10:30:00", estado="ativa", quantidade_comprovada="9.95", elegibilidade="falso", motivos_elegibilidade=["quantidade_insuficiente"]),
        m("11:30:00", estado="atingida", eventos=["execucao_registrada", "atingida"], quantidade_comprovada="10.05", evidencia_em={"atingida": t("11:00:00")}),
    ],
)

# 03 --------------------------------------------------------------------------------------------------------------------------------------
C["03_taxa_em_terceiro_ativo_nao_reduz"] = cenario(
    "A taxa de 0,002 BNB é custo verificado em BNB: não tira nenhuma unidade de TOKX (10 comprados são 10 líquidos comprovados). Mas o orçamento cobre o CUSTO TOTAL e não há conversão confiável de BNB para USD: o orçamento fica indeterminado e a meta NÃO se declara cumprida.",
    [ex("ex-1", "10", "0", "10:00:00", taxas_outros_ativos=[{"ativo_id": "bnb", "valor": "0.002"}])],
    [ext("fill-1", "10", [("bnb", "0.002")], "10:00:00")],
    [m("10:30:00", estado="ativa", eventos=["ativada", "execucao_registrada"], quantidade_comprovada="10", elegibilidade="indeterminado", orcamento="indeterminado",
       motivos_elegibilidade=["orcamento_indeterminado"])],
)

# 04 --------------------------------------------------------------------------------------------------------------------------------------
C["04_pendencia_que_pode_reduzir_adia_a_conclusao"] = cenario(
    "A compra (10 líquidos) é comprovada, mas há um ESTORNO interno ainda sem registro externo. Ele pode reduzir o progresso: a conclusão é adiada (indeterminado). Quando o estorno é comprovado, o progresso cai para 5.",
    [ex("ex-1", "10.1", "0.1", "10:00:00"), ex("ex-2", "5", "0", "11:00:00", lado="estorno_compra", estorna="ex-1")],
    [ext("fill-1", "10.1", [("tokx", "0.1")], "10:00:00", recebido="11:20:00"),
     ext("fill-2", "5", [], "11:00:00", recebido="13:00:00", lado="estorno_compra", estorna="fill-1")],
    [
        m("10:30:00", estado="ativa", eventos=["ativada"], quantidade_comprovada="0", elegibilidade="falso"),
        m("11:30:00", estado="ativa", eventos=["execucao_registrada"], quantidade_comprovada="10", elegibilidade="indeterminado",
          motivos_elegibilidade=["pendencia_pode_reduzir_progresso"], completa=False),
        m("13:30:00", estado="ativa", eventos=[], eventos_conciliacao=["execucao_conciliada"], quantidade_comprovada="5", elegibilidade="falso",
          motivos_elegibilidade=["quantidade_insuficiente"]),
    ],
)

# 05 --------------------------------------------------------------------------------------------------------------------------------------
C["05_compra_pendente_nao_bloqueia_nem_apaga"] = cenario(
    "Uma compra extra ainda pendente NÃO pode reduzir o progresso: a meta fecha com o que já está comprovado. A completude fica falsa, mas a elegibilidade é verdadeira.",
    [ex("ex-1", "10", "0", "10:00:00"), ex("ex-2", "3", "0", "11:00:00")],
    [ext("fill-1", "10", [], "10:00:00"), ext("fill-2", "3", [], "11:00:00", recebido="12:00:00")],
    [
        m("11:30:00", estado="atingida", eventos=["ativada", "execucao_registrada", "atingida"], quantidade_comprovada="10", elegibilidade="verdadeiro",
          completa=False, evidencia_em={"atingida": t("10:00:00")}),
        m("13:00:00", estado="atingida", eventos=[], eventos_conciliacao=["execucao_conciliada"], quantidade_comprovada="13", completa=True),
    ],
)

# 06 --------------------------------------------------------------------------------------------------------------------------------------
C["06_orfaos_nao_relacionados_nao_bloqueiam"] = cenario(
    "Seis registros externos sem execução interna, nenhum capaz de afetar esta meta (outra conta, outro mercado, outro ativo, antes da ativação, dado de outra origem, estorno de outra compra). A meta fecha e a completude é verdadeira.",
    [ex("ex-1", "10", "0", "10:00:00")],
    [ext("fill-1", "10", [], "10:00:00"),
     ext("o-conta", "5", [], "10:10:00", conta="conta-b"), ext("o-mercado", "5", [], "10:10:00", mercado="bolsa-b"),
     ext("o-ativo", "5", [], "10:10:00", ativo="abc"), ext("o-antes", "5", [], "07:00:00"),
     ext("o-origem", "5", [], "10:10:00", origem="observado"),
     ext("o-estorno", "2", [], "10:20:00", lado="estorno_compra", estorna="fill-zzz")],
    [m("11:00:00", estado="atingida", eventos=["ativada", "execucao_registrada", "atingida"], quantidade_comprovada="10", elegibilidade="verdadeiro",
       completa=True, orfaos_relevantes=[],
       orfaos_ignorados={"o-conta": ["conta_diferente"], "o-mercado": ["mercado_diferente"], "o-ativo": ["ativo_diferente"],
                         "o-antes": ["fora_do_periodo"], "o-origem": ["origem_diferente"], "o-estorno": ["estorno_de_outra_compra"]})],
)

C["06b_orfao_estorno_depois_da_conclusao_nao_reabre"] = cenario(
    "A meta é atingida. Depois aparece um registro externo de ESTORNO da compra, que ninguém referencia. Isso é uma possibilidade, não uma prova: a conclusão é MANTIDA (indeterminado, completude falsa). Só quando o estorno é vinculado e comprovado (progresso 5) a meta é reaberta por reconciliação.",
    [ex("ex-1", "10", "0", "10:00:00"),
     ex("ex-2", "5", "0", "11:00:00", lado="estorno_compra", estorna="ex-1", refs=["o-est"], minutos_conf=90)],
    [ext("fill-1", "10", [], "10:00:00"),
     ext("o-est", "5", [], "11:00:00", lado="estorno_compra", estorna="fill-1", recebido="11:10:00")],
    [
        m("10:30:00", estado="atingida", eventos=["ativada", "execucao_registrada", "atingida"], quantidade_comprovada="10", elegibilidade="verdadeiro"),
        m("11:30:00", estado="atingida", eventos=[], quantidade_comprovada="10", elegibilidade="indeterminado", orfaos_relevantes=["o-est"], completa=False,
          motivos_elegibilidade=["pendencia_pode_reduzir_progresso"]),
        m("13:00:00", estado="ativa", eventos=["reconciliada"], eventos_conciliacao=["execucao_conciliada"], quantidade_comprovada="5", elegibilidade="falso",
          orfaos_relevantes=[], completa=True),
    ],
)

C["17_correcao_externa_apos_conclusao"] = cenario(
    "Meta atingida. A fonte corrige o registro (taxa maior): o líquido cai para 9,9 e a compra deixa de estar comprovada. Reconciliação reabre a meta e o razão devolve o que havia somado. Quando a fonte restaura o valor, a meta é atingida de novo (um novo evento `atingida`, com chave própria).",
    [ex("ex-1", "10.1", "0.1", "10:00:00")],
    [ext("fill-1", "10.1", [("tokx", "0.1")], "10:00:00"),
     ext("fill-1", "10.1", [("tokx", "0.2")], "10:00:00", versao=2, recebido="12:00:00"),
     ext("fill-1", "10.1", [("tokx", "0.1")], "10:00:00", versao=3, recebido="14:00:00")],
    [
        m("10:30:00", estado="atingida", eventos=["ativada", "execucao_registrada", "atingida"], quantidade_comprovada="10"),
        m("12:30:00", estado="ativa", eventos=["reconciliada"], eventos_conciliacao=["conciliacao_revertida"], quantidade_comprovada="0", elegibilidade="falso"),
        m("14:30:00", estado="atingida", eventos=["execucao_registrada", "atingida"], eventos_conciliacao=["execucao_conciliada"], quantidade_comprovada="10",
          evidencia_em={"atingida": t("10:00:00")}),
    ],
)

C["06c_orfao_estorno_sem_execucao_interna"] = cenario(
    "O estorno chega primeiro como registro externo órfão (ninguém o referencia ainda). Antes de a conclusão ser decidida ele já bloqueia, porque pode reduzir o progresso.",
    [ex("ex-1", "10", "0", "10:00:00", minutos_conf=1)],
    [ext("fill-1", "10", [], "10:00:00", recebido="11:30:00"),
     ext("o-est", "5", [], "11:00:00", lado="estorno_compra", estorna="fill-1", recebido="11:10:00")],
    [
        m("11:00:00", estado="ativa", eventos=["ativada"], quantidade_comprovada="0"),
        m("12:00:00", estado="ativa", eventos=["execucao_registrada"], quantidade_comprovada="10", elegibilidade="indeterminado",
          motivos_elegibilidade=["pendencia_pode_reduzir_progresso"], orfaos_relevantes=["o-est"], completa=False),
    ],
)

C["06d_orfao_compra_pode_estourar_orcamento"] = cenario(
    "Uma compra órfã da mesma conta, mercado e período pode ser desta meta. Ela não reduz progresso, mas somada ao gasto já comprovado (95,95) pode passar do orçamento de 100: limite indeterminado, conclusão adiada.",
    [ex("ex-1", "10.1", "0.1", "10:00:00")],
    [ext("fill-1", "10.1", [("tokx", "0.1")], "10:00:00"), ext("o-compra", "1", [], "10:30:00")],
    [m("11:00:00", estado="ativa", eventos=["ativada", "execucao_registrada"], quantidade_comprovada="10", elegibilidade="indeterminado",
       orcamento="indeterminado", motivos_elegibilidade=["orcamento_indeterminado"], orfaos_relevantes=["o-compra"])],
    orcamento="100",
)

# 07 / 08 -----------------------------------------------------------------------------------------------------------------------------------
C["07_evidencia_atrasada_dentro_da_carencia"] = cenario(
    "Executou às 13:00 (antes do prazo, 14:00) e a evidência só chega às 15:00, dentro da carência (até 16:00). A meta espera; ao chegar, é atingida com o instante EFETIVO da execução (13:00), não o da chegada.",
    [ex("ex-1", "10", "0", "13:00:00")],
    [ext("fill-1", "10", [], "13:00:00", recebido="15:00:00")],
    [
        m("13:30:00", estado="ativa", eventos=["ativada"], quantidade_comprovada="0", aguardando_evidencia=True, em_carencia=False),
        m("14:30:00", estado="ativa", eventos=[], quantidade_comprovada="0", aguardando_evidencia=True, em_carencia=True),
        m("15:30:00", estado="atingida", eventos=["execucao_registrada", "atingida"], quantidade_comprovada="10", evidencia_em={"atingida": t("13:00:00")}),
    ],
    prazo="14:00:00",
)

C["08_evidencia_depois_da_carencia"] = cenario(
    "A evidência chega às 17:00, depois da carência (16:00). A meta expira com 'prazo_sem_evidencia'. A evidência tardia gera um evento de reconciliação: o estado volta a 'atingida' e a expiração continua na história.",
    [ex("ex-1", "10", "0", "13:00:00")],
    [ext("fill-1", "10", [], "13:00:00", recebido="17:00:00")],
    [
        m("15:30:00", estado="ativa", eventos=["ativada"], em_carencia=True, aguardando_evidencia=True),
        m("16:30:00", estado="expirada", eventos=["expirada"], quantidade_comprovada="0", evidencia_em={"expirada": t("16:00:00")},
          motivo_evento={"expirada": "prazo_sem_evidencia"}),
        m("17:30:00", estado="atingida", eventos=["reconciliada"], quantidade_comprovada="10", motivo_evento={"reconciliada": "evidência tardia"}),
    ],
    prazo="14:00:00",
)

# 09 ---------------------------------------------------------------------------------------------------------------------------------------------
C["09_estorno_apos_conclusao_reabre_e_depois_expira"] = cenario(
    "A meta é atingida às 10:00. Às 13:00 há um estorno de 4: o progresso cai para 6. O evento `reconciliada` reabre a meta (a conclusão fica na história) e, passado o prazo sem novas compras, ela expira normalmente.",
    [ex("ex-1", "10", "0", "10:00:00"), ex("ex-2", "4", "0", "13:00:00", lado="estorno_compra", estorna="ex-1")],
    [ext("fill-1", "10", [], "10:00:00"), ext("fill-2", "4", [], "13:00:00", lado="estorno_compra", estorna="fill-1")],
    [
        m("10:30:00", estado="atingida", eventos=["ativada", "execucao_registrada", "atingida"], quantidade_comprovada="10"),
        m("13:30:00", estado="ativa", eventos=["reconciliada"], eventos_conciliacao=["execucao_conciliada"], quantidade_comprovada="6",
          elegibilidade="falso", motivo_evento={"reconciliada": "permanece na história"}),
        m("14:30:00", estado="ativa", eventos=[], quantidade_comprovada="6"),
        m("17:00:00", estado="expirada", eventos=["expirada"], quantidade_comprovada="6", motivo_evento={"expirada": "prazo_encerrado"}),
    ],
)

C["09b_estorno_apos_o_prazo"] = cenario(
    "A meta é atingida às 10:00; o prazo é 12:30. Um estorno às 13:00 (depois do prazo) desfaz a compra que a fez valer: o progresso cai para 6 e o estado é recalculado para 'expirada', por reconciliação.",
    [ex("ex-1", "10", "0", "10:00:00"), ex("ex-2", "4", "0", "13:00:00", lado="estorno_compra", estorna="ex-1")],
    [ext("fill-1", "10", [], "10:00:00"), ext("fill-2", "4", [], "13:00:00", lado="estorno_compra", estorna="fill-1")],
    [
        m("10:30:00", estado="atingida", eventos=["ativada", "execucao_registrada", "atingida"], quantidade_comprovada="10"),
        m("13:30:00", estado="expirada", eventos=["reconciliada"], quantidade_comprovada="6"),
    ],
    prazo="12:30:00",
)

# 10 ---------------------------------------------------------------------------------------------------------------------------------------------
C["10_reprocessamento_nao_duplica"] = cenario(
    "Dados duplicados (execução e registro externo entregues 3 vezes) e o MESMO momento processado de novo: nenhum evento novo, nenhum progresso em dobro.",
    [ex("ex-1", "10", "0", "10:00:00")] * 3,
    [ext("fill-1", "10", [], "10:00:00")] * 3,
    [
        m("11:00:00", estado="atingida", eventos=["ativada", "execucao_registrada", "atingida"], quantidade_comprovada="10"),
        m("11:00:00", estado="atingida", eventos=[], eventos_conciliacao=[], quantidade_comprovada="10"),
        m("15:00:00", estado="atingida", eventos=[], eventos_conciliacao=[], quantidade_comprovada="10"),
    ],
)

# 11 ---------------------------------------------------------------------------------------------------------------------------------------------
C["11_consulta_truncada_preserva_historia"] = cenario(
    "Às 12:30 a consulta à fonte NÃO traz o registro da primeira compra (feed truncado, sem garantia de cobertura). A ausência não prova nada: a prova anterior (6) é preservada e a meta fecha. A completude fica falsa; na consulta completa seguinte, tudo se normaliza sem eventos.",
    [ex("ex-1", "6", "0", "10:00:00"), ex("ex-2", "6", "0", "11:00:00")],
    [ext("fill-1", "6", [], "10:00:00"), ext("fill-2", "6", [], "11:00:00")],
    [
        m("10:30:00", estado="ativa", eventos=["ativada", "execucao_registrada"], quantidade_comprovada="6"),
        m("12:30:00", ocultar=["fill-1"], estado="atingida", eventos=["execucao_registrada", "atingida"], quantidade_comprovada="12", quantidade_preservada="6",
          completa=False, elegibilidade="verdadeiro", evidencia_em={"atingida": t("11:00:00")}),
        m("14:00:00", estado="atingida", eventos=[], eventos_conciliacao=[], quantidade_comprovada="12", quantidade_preservada="0", completa=True),
    ],
)

C["11b_ausencia_provada_por_consulta_completa_reverte"] = cenario(
    "Igual ao anterior, mas agora a fonte GARANTE que a consulta de 12:00 cobriu todo o período: a ausência é prova. A compra deixa de estar comprovada e o evento compensatório devolve exatamente o que havia somado.",
    [ex("ex-1", "6", "0", "10:00:00"), ex("ex-2", "6", "0", "11:00:00")],
    [ext("fill-1", "6", [], "10:00:00"), ext("fill-2", "6", [], "11:00:00")],
    [
        m("10:30:00", estado="ativa", eventos=["ativada", "execucao_registrada"], quantidade_comprovada="6"),
        m("12:30:00", ocultar=["fill-1"], estado="ativa", eventos=["execucao_registrada"], eventos_conciliacao=["conciliacao_revertida", "execucao_conciliada"],
          quantidade_comprovada="6", quantidade_preservada="0", elegibilidade="falso"),
    ],
    coberturas_execucoes=[{"fonte_id": FONTE, "inicio": t("08:00:00"), "fim": t("12:00:00"), "consultada_em": t("12:00:00")}],
)

# 12 ---------------------------------------------------------------------------------------------------------------------------------------------
C["12_custo_fixo_sem_evidencia_deixa_orcamento_indeterminado"] = cenario(
    "100 TOKX a 9,99 = 999 comprovados, orçamento 1000. Mas há um custo fixo de 5 SEM evidência externa: o pior caso (1004) estoura. O limite é indeterminado, a conclusão não ocorre e, esgotada a carência, a meta expira por falta de evidência.",
    [ex("ex-1", "100", "0", "10:00:00", preco="9.99", custo_fixo_real="5")],
    [ext("fill-1", "100", [], "10:00:00", preco="9.99")],
    [
        m("11:00:00", estado="ativa", eventos=["ativada", "execucao_registrada"], quantidade_comprovada="100", elegibilidade="indeterminado",
          orcamento="indeterminado", motivos_elegibilidade=["orcamento_indeterminado"]),
        m("17:00:00", estado="ativa", eventos=[], elegibilidade="indeterminado", aguardando_evidencia=True, em_carencia=True),
        m("18:30:00", estado="expirada", eventos=["expirada"], evidencia_em={"expirada": t("18:00:00")}, motivo_evento={"expirada": "prazo_sem_evidencia"}),
    ],
    alvo="100",
)

C["12b_sem_custo_fixo_o_orcamento_e_verdadeiro"] = cenario(
    "Mesma compra, sem custo fixo: o pior caso (999) cabe no orçamento de 1000. O limite é verdadeiro e a meta fecha.",
    [ex("ex-1", "100", "0", "10:00:00", preco="9.99")],
    [ext("fill-1", "100", [], "10:00:00", preco="9.99")],
    [m("11:00:00", estado="atingida", eventos=["ativada", "execucao_registrada", "atingida"], quantidade_comprovada="100", orcamento="verdadeiro")],
    alvo="100",
)

C["12c_orcamento_comprovadamente_excedido"] = cenario(
    "100 TOKX a 10,05 = 1005 COMPROVADOS: o orçamento (1000) foi estourado. O limite é falso e a meta não pode ser concluída.",
    [ex("ex-1", "100", "0", "10:00:00", preco="10.05")],
    [ext("fill-1", "100", [], "10:00:00", preco="10.05")],
    [m("11:00:00", estado="ativa", eventos=["ativada", "execucao_registrada"], quantidade_comprovada="100", elegibilidade="falso", orcamento="falso",
       motivos_elegibilidade=["orcamento_excedido"])],
    alvo="100",
)

# 13 ---------------------------------------------------------------------------------------------------------------------------------------------
_inv = lambda hora: [*OBS_BASE, obs("o-ret-inv", "retorno_7d", "-0.5", "razao", hora)]  # noqa: E731
C["13a_atingida_anterior_a_invalidacao_vence_com_evidencia_tardia"] = cenario(
    "A queda (invalidação) foi observada às 11:00 e a meta foi invalidada. Depois chega a evidência de que a execução que fecha o objetivo foi às 10:30, ANTES. Vale o menor instante de evidência: reconciliação para 'atingida'.",
    [ex("ex-1", "10", "0", "10:30:00")],
    [ext("fill-1", "10", [], "10:30:00", recebido="12:00:00")],
    [
        m("11:30:00", estado="invalidada", eventos=["ativada", "invalidada"], evidencia_em={"invalidada": t("11:00:00")}),
        m("12:30:00", estado="atingida", eventos=["reconciliada"], quantidade_comprovada="10"),
    ],
    observacoes=_inv("11:00:00"),
)

C["13b_invalidacao_anterior_prevalece"] = cenario(
    "A invalidação foi observada às 10:00, antes da execução (10:30). A evidência tardia da compra não desfaz a invalidação: continua 'invalidada', e o razão de conciliação ainda registra a execução.",
    [ex("ex-1", "10", "0", "10:30:00")],
    [ext("fill-1", "10", [], "10:30:00", recebido="12:00:00")],
    [
        m("11:30:00", estado="invalidada", eventos=["ativada", "invalidada"], evidencia_em={"invalidada": t("10:00:00")}),
        m("12:30:00", estado="invalidada", eventos=[], eventos_conciliacao=["execucao_conciliada"], quantidade_comprovada="10"),
    ],
    observacoes=_inv("10:00:00"),
)

C["13c_empate_exato_atingida_antes_de_invalidada"] = cenario(
    "Execução e observação da queda no MESMO instante (10:30). A política de empate congelada no contrato (atingida, invalidada, expirada, entrada) decide: 'atingida'.",
    [ex("ex-1", "10", "0", "10:30:00")],
    [ext("fill-1", "10", [], "10:30:00")],
    [m("11:30:00", estado="atingida", eventos=["ativada", "execucao_registrada", "atingida"], quantidade_comprovada="10")],
    observacoes=_inv("10:30:00"),
)

C["13d_empate_exato_com_outra_ordem_no_contrato"] = cenario(
    "Mesmo empate, mas o contrato congelou outra ordem (invalidada antes de atingida): a meta é 'invalidada'. A ordem vem do contrato, não do código.",
    [ex("ex-1", "10", "0", "10:30:00")],
    [ext("fill-1", "10", [], "10:30:00")],
    [m("11:30:00", estado="invalidada", eventos=["ativada", "execucao_registrada", "invalidada"], quantidade_comprovada="10")],
    observacoes=_inv("10:30:00"),
    ordem=["invalidada", "atingida", "expirada", "entrada"],
)

C["13e_invalidacao_observada_e_fato_historico"] = cenario(
    "A queda foi observada às 10:00 e a meta foi invalidada. Às 12:00 o retorno volta ao normal: a condição deixa de valer, mas a invalidação JÁ ocorreu e continua na história. A meta não volta a 'ativa'.",
    [], [],
    [m("11:00:00", estado="invalidada", eventos=["ativada", "invalidada"], evidencia_em={"invalidada": t("10:00:00")}),
     m("13:00:00", estado="invalidada", eventos=[])],
    observacoes=[*OBS_BASE, obs("o-ret-queda", "retorno_7d", "-0.5", "razao", "10:00:00"), obs("o-ret-volta", "retorno_7d", "0.02", "razao", "12:00:00")],
)

# 14 / 15 / 16 ---------------------------------------------------------------------------------------------------------------------------------
_precos = [*OBS_BASE, obs("o-preco-1", "preco_executavel", "9.4", "USD", "12:50:00"), obs("o-preco-2", "preco_executavel", "9.3", "USD", "13:40:00"),
           obs("o-preco-3", "preco_executavel", "9.2", "USD", "14:20:00")]
C["14_alerta_idempotente_e_sem_entrada_na_carencia"] = cenario(
    "O preço entra na regra de entrada às 12:50: um alerta. Reavaliar com os mesmos dados não repete. Novo dado, novo alerta. Depois do prazo (carência, aguardando evidência) NÃO há mais alertas, mesmo que chegue um dado novo que satisfaz a regra (às 14:20).",
    [ex("ex-1", "10", "0", "13:20:00")],
    [ext("fill-1", "10", [], "13:20:00", recebido="15:30:00")],
    [
        m("13:00:00", estado="ativa", eventos=["ativada", "alerta_emitido"]),
        m("13:30:00", estado="ativa", eventos=[]),
        m("13:45:00", estado="ativa", eventos=["alerta_emitido"]),
        m("14:30:00", estado="ativa", eventos=[], em_carencia=True, aguardando_evidencia=True),
    ],
    prazo="14:00:00", observacoes=_precos,
)

C["15_prazo_sem_pendencia_expira_sem_esperar"] = cenario(
    "Sem execução e sem nenhuma evidência que possa mudar o resultado, passado o prazo a meta expira de imediato ('prazo_encerrado'), sem esperar a carência.",
    [], [],
    [m("12:00:00", estado="ativa", eventos=["ativada"], quantidade_comprovada="0"),
     m("17:00:00", estado="expirada", eventos=["expirada"], aguardando_evidencia=False, evidencia_em={"expirada": t("16:00:00")},
       motivo_evento={"expirada": "prazo_encerrado"})],
)

C["16_bloqueio_por_dados_e_liberacao"] = cenario(
    "Sem dados de mercado, as regras ficam indeterminadas: a meta continua ativa, mas 'bloqueada por dados' (nenhuma entrada). Quando o dado chega, o bloqueio é encerrado.",
    [], [],
    [m("10:00:00", estado="ativa", eventos=["ativada", "bloqueio_iniciado"], bloqueada_por_dados=True),
     m("10:30:00", estado="ativa", eventos=[], bloqueada_por_dados=True),
     m("11:30:00", estado="ativa", eventos=["bloqueio_encerrado"], bloqueada_por_dados=False)],
    observacoes=[obs("o-preco-0", "preco_executavel", "12", "USD", "11:00:00"), obs("o-ret-0", "retorno_7d", "0.01", "razao", "11:00:00")],
)


def main() -> None:
    yaml = YAML(typ="safe", pure=True)
    yaml.default_flow_style = False
    yaml.allow_unicode = True
    yaml.width = 160
    DESTINO.mkdir(parents=True, exist_ok=True)
    for antigo in DESTINO.glob("*.yaml"):
        antigo.unlink()
    for nome, dados in C.items():
        saida = StringIO()
        yaml.dump(dados, saida)
        cabecalho = "# Cenário FICTÍCIO gerado por scripts/gerar_cenarios_meta.py (não edite à mão; mude o script).\n"
        (DESTINO / f"{nome}.yaml").write_text(cabecalho + saida.getvalue(), encoding="utf-8")
    print(f"{len(C)} cenários gravados em {DESTINO}")


if __name__ == "__main__":
    sys.exit(main())
