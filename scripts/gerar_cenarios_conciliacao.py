"""Gera exemplos/conciliacao/06_*.yaml em diante. Os cenários 01 a 05 são escritos à mão e não são tocados.

    python scripts/gerar_cenarios_conciliacao.py

Todos os dados são FICTÍCIOS. Os valores são strings decimais, como o contrato exige.
"""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "exemplos" / "conciliacao"
META = "meta-tokx-001"
FONTE = "corretora-sim"
POLITICA = {"janela_atraso_segundos": 3600, "tolerancia_horario_segundos": 60, "janela_candidatos_segundos": 300}


def t(hora: str, dia: str = "2026-10-20") -> str:
    return f"{dia}T{hora}Z"


def ex(id_, bruta="10", taxa="0.05", preco="9.5", refs=(), meta=META, lado="compra", executada="10:00:00", confirmada="10:01:00", **extra):
    liquida = f"{float(bruta) - float(taxa):g}" if "liquida" not in extra else extra.pop("liquida")
    registro = {
        "id": id_, "meta_id": meta, "ativo_id": "tokx", "lado": lado, "quantidade_bruta": bruta, "taxa_no_ativo": taxa,
        "quantidade_liquida": liquida, "preco_executado": preco, "executada_em": t(executada), "confirmada_em": t(confirmada),
        "fonte_id": "registro-manual", "origem": "simulado",
    }
    if refs:
        registro["referencias_externas"] = [r if isinstance(r, dict) else {"fonte_id": FONTE, "id_externo": r} for r in refs]
    registro.update(extra)
    return registro


def ext(id_, qtd="10", preco="9.5", taxa="0.05", versao=1, status="confirmado", lado="compra", executado="10:00:00", recebido="10:00:30", estorna=None, **extra):
    registro = {
        "fonte_id": FONTE, "id_externo": id_, "versao": versao, "mercado_id": "bolsa-a", "ativo_id": "tokx", "moeda_cotacao_id": "usd",
        "lado": lado, "quantidade": qtd, "preco": preco, "taxas": [{"ativo_id": "tokx", "valor": taxa}] if taxa not in (None, "0") else [],
        "status": status, "executado_em": t(executado), "recebido_em": t(recebido), "origem": "simulado",
    }
    if estorna:
        registro["estorna_id_externo"] = estorna
    registro.update(extra)
    return registro


def momento(hora: str, **esperado):
    return {"agora": t(hora), "esperado": esperado}


def cenario(descricao, execucoes, externos, momentos, **extra):
    return {"schema_versao": 1, "origem": "simulado", "descricao": descricao, "politica": dict(POLITICA), "execucoes": execucoes,
            "registros_externos": externos, "momentos": momentos, **extra}


CENARIOS: dict[str, dict] = {}

CENARIOS["06_duplicata_interna_conflitante"] = cenario(
    "O mesmo id interno chega duas vezes com quantidades diferentes: nenhuma das duas versões conta; vai para revisão.",
    [ex("ex-1", refs=["fill-001"]), ex("ex-1", bruta="11", taxa="0.05", refs=["fill-001"])],
    [ext("fill-001")],
    [momento("12:00:00", execucoes={"ex-1": "revisao"}, motivos={"ex-1": ["id_interno_duplicado_conteudo_diferente"]},
             comprovado={META: "0"}, declarado={META: "0"}, confirmacao="incompleta", orfaos=[])],
)

CENARIOS["07_versao_externa_conflitante"] = cenario(
    "A fonte entregou duas linhas da MESMA versão com conteúdos diferentes: não há como saber qual vale. Revisão.",
    [ex("ex-1", refs=["fill-001"])],
    [ext("fill-001"), ext("fill-001", taxa="0.06")],
    [momento("12:00:00", execucoes={"ex-1": "revisao"}, motivos={"ex-1": ["versao_externa_conflitante"]}, comprovado={META: "0"}, confirmacao="incompleta")],
)

CENARIOS["08_sem_identificador_vinculo_manual"] = cenario(
    "A execução não tem identificador externo. Há UM candidato plausível, mas preço/horário NÃO criam elo. Só o vínculo manual (humano) resolve.",
    [ex("ex-1")],
    [ext("fill-77", executado="10:00:20", recebido="10:00:30")],
    [
        momento("12:00:00", execucoes={"ex-1": "revisao"}, motivos={"ex-1": ["sem_identificador_externo"]}, comprovado={META: "0"},
                declarado={META: "9.95"}, confirmacao="incompleta", orfaos=["fill-77"], eventos=["revisao_aberta", "orfao_detectado"]),
        momento("14:00:00", execucoes={"ex-1": "conciliada"}, comprovado={META: "9.95"}, confirmacao="confirmada", orfaos=[],
                eventos=["execucao_conciliada", "revisao_encerrada"]),
    ],
    vinculos_manuais=[{"execucao_id": "ex-1", "fonte_id": FONTE, "id_externo": "fill-77", "autor": "Pessoa de exemplo",
                       "justificativa": "Conferi o extrato: é a mesma compra de 10 TOKX.", "em": t("13:00:00")}],
)

CENARIOS["09_candidatos_ambiguos"] = cenario(
    "Dois registros externos servem como candidatos igualmente bons. Nenhum é escolhido sozinho: revisão e dois órfãos.",
    [ex("ex-1")],
    [ext("fill-81", executado="10:00:10"), ext("fill-82", executado="10:00:15")],
    [momento("12:00:00", execucoes={"ex-1": "revisao"}, motivos={"ex-1": ["sem_identificador_externo"]}, comprovado={META: "0"},
             confirmacao="incompleta", orfaos=["fill-81", "fill-82"])],
)

CENARIOS["10_dados_atrasados"] = cenario(
    "O registro externo só chega às 13:00. Antes disso a execução fica pendente e, passada a janela de atraso, sem registro externo.",
    [ex("ex-1", refs=["fill-001"])],
    [ext("fill-001", recebido="13:00:00")],
    [
        momento("10:10:00", execucoes={"ex-1": "pendente"}, motivos={"ex-1": ["aguardando_registro_externo"]}, comprovado={META: "0"},
                declarado={META: "9.95"}, confirmacao="incompleta", eventos=[]),
        momento("12:00:00", execucoes={"ex-1": "sem_registro_externo"}, motivos={"ex-1": ["registro_externo_nao_encontrado"]}, comprovado={META: "0"}, eventos=[]),
        momento("14:00:00", execucoes={"ex-1": "conciliada"}, comprovado={META: "9.95"}, confirmacao="confirmada", eventos=["execucao_conciliada"]),
    ],
)

CENARIOS["11_correcao_externa"] = cenario(
    "A fonte corrige o registro (versão 2, taxa 0,06) e depois o restaura (versão 3). O progresso é revertido e depois recomposto, sem reescrever nada.",
    [ex("ex-1", refs=["fill-001"])],
    [ext("fill-001"), ext("fill-001", versao=2, taxa="0.06", recebido="11:00:00"), ext("fill-001", versao=3, recebido="12:00:00")],
    [
        momento("10:30:00", execucoes={"ex-1": "conciliada"}, comprovado={META: "9.95"}, eventos=["execucao_conciliada"]),
        momento("11:30:00", execucoes={"ex-1": "divergente"}, motivos={"ex-1": ["taxa_no_ativo_diferente", "corrigido_externamente"]},
                comprovado={META: "0"}, declarado={META: "9.95"}, confirmacao="incompleta", eventos=["conciliacao_revertida", "divergencia_aberta"]),
        momento("12:30:00", execucoes={"ex-1": "conciliada"}, motivos={"ex-1": ["corrigido_externamente"]}, comprovado={META: "9.95"},
                confirmacao="confirmada", eventos=["execucao_conciliada", "divergencia_encerrada"]),
    ],
)

CENARIOS["12_cancelamento_externo"] = cenario(
    "A fonte cancela a execução depois de confirmá-la. Ela deixa de contar e o evento compensatório devolve o que havia sido somado.",
    [ex("ex-1", refs=["fill-001"])],
    [ext("fill-001"), ext("fill-001", versao=2, status="cancelado", recebido="11:00:00")],
    [
        momento("10:30:00", execucoes={"ex-1": "conciliada"}, comprovado={META: "9.95"}, eventos=["execucao_conciliada"]),
        momento("11:30:00", execucoes={"ex-1": "divergente"}, motivos={"ex-1": ["cancelado_externamente"]}, comprovado={META: "0"},
                confirmacao="incompleta", orfaos=[], eventos=["conciliacao_revertida", "divergencia_aberta"]),
    ],
)

_estorno_ex = ex("ex-2", bruta="9.95", taxa="0", preco="9.5", lado="estorno_compra", estorna_execucao_id="ex-1", refs=["fill-002"],
                 executada="13:00:00", confirmada="13:01:00")
_estorno_ext = ext("fill-002", qtd="9.95", taxa=None, lado="estorno_compra", estorna="fill-001", executado="13:00:00", recebido="13:00:30")
CENARIOS["13_estorno"] = cenario(
    "Compra e depois estorno integral da quantidade líquida. O estorno é uma execução própria, conciliada; o progresso volta a zero por compensação.",
    [ex("ex-1", refs=["fill-001"]), _estorno_ex], [ext("fill-001"), _estorno_ext],
    [
        momento("12:00:00", execucoes={"ex-1": "conciliada"}, comprovado={META: "9.95"}, eventos=["execucao_conciliada"]),
        momento("14:00:00", execucoes={"ex-1": "conciliada", "ex-2": "conciliada"}, comprovado={META: "0"}, declarado={META: "0"},
                confirmacao="confirmada", eventos=["execucao_conciliada"]),
    ],
)

CENARIOS["14_estorno_excedente"] = cenario(
    "Dois estornos somam mais que a compra original: o primeiro vale; o que excede vai para revisão.",
    [ex("ex-1", refs=["fill-001"]),
     ex("ex-2", bruta="9.95", taxa="0", lado="estorno_compra", estorna_execucao_id="ex-1", refs=["fill-002"], executada="11:00:00", confirmada="11:01:00"),
     ex("ex-3", bruta="1", taxa="0", lado="estorno_compra", estorna_execucao_id="ex-1", refs=["fill-003"], executada="11:30:00", confirmada="11:31:00")],
    [ext("fill-001"), ext("fill-002", qtd="9.95", taxa=None, lado="estorno_compra", estorna="fill-001", executado="11:00:00", recebido="11:00:30"),
     ext("fill-003", qtd="1", taxa=None, lado="estorno_compra", estorna="fill-001", executado="11:30:00", recebido="11:30:30")],
    [momento("12:00:00", execucoes={"ex-1": "conciliada", "ex-2": "conciliada", "ex-3": "revisao"}, motivos={"ex-3": ["estorno_excede_original"]},
             comprovado={META: "0"}, confirmacao="incompleta", eventos=["execucao_conciliada", "execucao_conciliada", "revisao_aberta"])],
)

CENARIOS["15_estorno_de_original_divergente"] = cenario(
    "O estorno bate com a fonte, mas a compra original está divergente (preço errado). Não se subtrai de algo que não foi comprovado: revisão.",
    [ex("ex-1", preco="9.6", refs=["fill-001"]),
     ex("ex-2", bruta="9.95", taxa="0", lado="estorno_compra", estorna_execucao_id="ex-1", refs=["fill-002"], executada="11:00:00", confirmada="11:01:00")],
    [ext("fill-001"), ext("fill-002", qtd="9.95", taxa=None, lado="estorno_compra", estorna="fill-001", executado="11:00:00", recebido="11:00:30")],
    [momento("12:00:00", execucoes={"ex-1": "divergente", "ex-2": "revisao"}, motivos={"ex-2": ["estorno_de_original_nao_conciliada"]},
             comprovado={META: "0"}, declarado={META: "0"}, confirmacao="incompleta")],
)

CENARIOS["16_mesma_execucao_em_duas_metas"] = cenario(
    "Duas metas reivindicam o registro externo INTEIRO. Nenhuma recebe o crédito: revisão em ambas.",
    [ex("ex-a", meta="meta-a", refs=["fill-001"]), ex("ex-b", meta="meta-b", refs=["fill-001"])],
    [ext("fill-001")],
    [momento("12:00:00", execucoes={"ex-a": "revisao", "ex-b": "revisao"}, motivos={"ex-a": ["registro_externo_em_metas_diferentes"]},
             comprovado={"meta-a": "0", "meta-b": "0"}, confirmacao="incompleta", orfaos=[])],
)

CENARIOS["17_alocacao_parcial_entre_metas"] = cenario(
    "Um registro de 10 TOKX dividido explicitamente: 6 para meta-a e 4 para meta-b, com a taxa rateada proporcionalmente. Ninguém é contado duas vezes.",
    [ex("ex-a", meta="meta-a", bruta="6", taxa="0.06", refs=[{"fonte_id": FONTE, "id_externo": "fill-001", "quantidade_bruta_alocada": "6"}]),
     ex("ex-b", meta="meta-b", bruta="4", taxa="0.04", refs=[{"fonte_id": FONTE, "id_externo": "fill-001", "quantidade_bruta_alocada": "4"}])],
    [ext("fill-001", taxa="0.1")],
    [momento("12:00:00", execucoes={"ex-a": "conciliada", "ex-b": "conciliada"}, comprovado={"meta-a": "5.94", "meta-b": "3.96"},
             confirmacao="confirmada", orfaos=[])],
)

CENARIOS["18_alocacao_excede_o_registro"] = cenario(
    "As alocações (7 + 4) ultrapassam os 10 do registro externo: revisão nas duas execuções.",
    [ex("ex-a", bruta="7", taxa="0.07", refs=[{"fonte_id": FONTE, "id_externo": "fill-001", "quantidade_bruta_alocada": "7"}]),
     ex("ex-b", bruta="4", taxa="0.04", refs=[{"fonte_id": FONTE, "id_externo": "fill-001", "quantidade_bruta_alocada": "4"}])],
    [ext("fill-001", taxa="0.1")],
    [momento("12:00:00", execucoes={"ex-a": "revisao", "ex-b": "revisao"}, motivos={"ex-a": ["alocacao_excede_registro_externo"]},
             comprovado={META: "0"}, confirmacao="incompleta")],
)

CENARIOS["19_divergencias_de_campo"] = cenario(
    "Uma divergência por execução: quantidade, taxa no ativo, preço e horário. Todas ficam fora do progresso, com o motivo certo.",
    [ex("ex-q", bruta="9", taxa="0.05", refs=["fill-q"]), ex("ex-t", taxa="0.06", refs=["fill-t"]),
     ex("ex-p", preco="9.6", refs=["fill-p"]), ex("ex-h", executada="10:10:00", confirmada="10:11:00", refs=["fill-h"])],
    [ext("fill-q"), ext("fill-t"), ext("fill-p"), ext("fill-h")],
    [momento("12:00:00", execucoes={"ex-q": "divergente", "ex-t": "divergente", "ex-p": "divergente", "ex-h": "divergente"},
             motivos={"ex-q": ["quantidade_bruta_diferente"], "ex-t": ["taxa_no_ativo_diferente"], "ex-p": ["preco_diferente"],
                      "ex-h": ["horario_fora_da_tolerancia"]},
             comprovado={META: "0"}, confirmacao="incompleta")],
)

CENARIOS["20_orfao_impede_confirmacao"] = cenario(
    "Há um registro externo de compra de TOKX que nenhuma execução interna referencia (pode ser uma compra não registrada). Não conta, e a conciliação é INCOMPLETA.",
    [ex("ex-1", refs=["fill-001"])],
    [ext("fill-001"), ext("fill-999", qtd="5", taxa="0.025", executado="11:00:00", recebido="11:00:30")],
    [momento("12:00:00", execucoes={"ex-1": "conciliada"}, comprovado={META: "9.95"}, confirmacao="incompleta", orfaos=["fill-999"])],
)


def _saldo(qtd, hora):
    return {"fonte_id": FONTE, "ativo_id": "tokx", "quantidade": qtd, "observado_em": t(hora), "recebido_em": t(hora), "origem": "simulado"}


def _mov(id_, tipo, qtd, hora, ref=None):
    registro = {"fonte_id": FONTE, "id_externo": id_, "ativo_id": "tokx", "tipo": tipo, "quantidade": qtd, "em": t(hora),
                "recebido_em": t(hora), "origem": "simulado"}
    if ref:
        registro["referencia_execucao_externa"] = ref
    return registro


_mov_execucao = [_mov("mov-2", "execucao", "10", "10:00:00", "fill-001"), _mov("mov-3", "taxa", "-0.05", "10:00:00", "fill-001")]
_cobertura = [{"fonte_id": FONTE, "ativo_id": "tokx", "inicio": t("08:00:00"), "fim": t("12:00:00")}]

CENARIOS["21_saldo_explicado_com_deposito"] = cenario(
    "O saldo subiu 59,95: 50 de um DEPÓSITO externo + 9,95 da compra. O depósito explica o saldo, mas NUNCA conta como progresso.",
    [ex("ex-1", refs=["fill-001"])], [ext("fill-001")],
    [momento("12:00:00", execucoes={"ex-1": "conciliada"}, comprovado={META: "9.95"}, confirmacao="confirmada", saldos={"tokx": "explicada"})],
    saldos=[_saldo("100", "09:00:00"), _saldo("159.95", "11:00:00")],
    movimentacoes=[_mov("mov-1", "deposito", "50", "09:30:00")] + _mov_execucao,
    coberturas=_cobertura,
)

CENARIOS["22_saldo_nao_explicado_nao_afeta_execucao"] = cenario(
    "Sobram 50 unidades sem explicação (nenhuma movimentação informada). O saldo fica 'não explicado', mas a execução continua conciliada: diferença de saldo não prova erro de execução.",
    [ex("ex-1", refs=["fill-001"])], [ext("fill-001")],
    [momento("12:00:00", execucoes={"ex-1": "conciliada"}, comprovado={META: "9.95"}, confirmacao="confirmada", saldos={"tokx": "nao_explicada"})],
    saldos=[_saldo("100", "09:00:00"), _saldo("159.95", "11:00:00")],
    movimentacoes=_mov_execucao,
    coberturas=_cobertura,
)

CENARIOS["23_saldo_sem_cobertura"] = cenario(
    "A fonte só garante as movimentações até 10:00. O intervalo termina às 11:00: não se afirma nem que há, nem que não há diferença.",
    [ex("ex-1", refs=["fill-001"])], [ext("fill-001")],
    [momento("12:00:00", execucoes={"ex-1": "conciliada"}, comprovado={META: "9.95"}, confirmacao="confirmada", saldos={"tokx": "dados_insuficientes"})],
    saldos=[_saldo("100", "09:00:00"), _saldo("159.95", "11:00:00")],
    movimentacoes=_mov_execucao,
    coberturas=[{"fonte_id": FONTE, "ativo_id": "tokx", "inicio": t("08:00:00"), "fim": t("10:00:00")}],
)


def main() -> None:
    yaml = YAML(typ="safe", pure=True)
    yaml.default_flow_style = False
    yaml.allow_unicode = True
    yaml.width = 140
    DESTINO.mkdir(parents=True, exist_ok=True)
    for nome, dados in CENARIOS.items():
        saida = StringIO()
        yaml.dump(dados, saida)
        cabecalho = "# Cenário FICTÍCIO gerado por scripts/gerar_cenarios_conciliacao.py (não edite à mão; mude o script).\n"
        (DESTINO / f"{nome}.yaml").write_text(cabecalho + saida.getvalue(), encoding="utf-8")
    print(f"{len(CENARIOS)} cenários gravados em {DESTINO}")


if __name__ == "__main__":
    sys.exit(main())
