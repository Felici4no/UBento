"""Comandos do bot do Telegram: SOMENTE CONSULTA, em cima de `ubento.consulta` (a mesma camada do MCP).

Cada resposta diz quando foi a última avaliação gravada e que NÃO é tempo real. Nenhum comando importa, reavalia ou grava; o banco é
aberto em modo somente leitura a cada mensagem.
"""

from __future__ import annotations

from collections.abc import Callable

from .consulta import ConsultaMetas, ErroDeConsulta
from .textos import legivel

AJUDA = (
    "Comandos (só consulta, nada é alterado):\n"
    "/metas — suas metas e o estado gravado de cada uma\n"
    "/progresso [meta] — quanto está comprovado\n"
    "/pendencias [meta] — o que falta comprovar\n"
    "/historico [meta] [n] — últimos eventos (padrão 5)\n"
    "/ajuda — esta lista\n"
    "Os dados são os da última avaliação gravada no UBento, não de tempo real. "
    "Sem [meta], uso a única meta existente."
)
NAO_ENTENDI = "Não entendi. Envie /ajuda para ver os comandos."


def instante(iso: str | None) -> str:
    return "—" if not iso else f"{iso[8:10]}/{iso[5:7]}/{iso[:4]} {iso[11:16]} UTC"


def rodape(envelope: dict) -> str:
    ultima = (envelope.get("ultima_avaliacao") or {}).get("avaliada_em")
    if ultima is None:
        return "Esta meta ainda não tem avaliação gravada."
    texto = f"Última avaliação gravada: {instante(ultima)}. Não é tempo real."
    if (envelope.get("cobertura_da_evidencia") or {}).get("desatualizada"):
        texto += " Há entradas mais novas que ela, ainda não consideradas."
    return texto


def _meta(consulta: ConsultaMetas, argumentos: list[str]) -> str:
    ids = [m["meta_id"] for m in consulta.listar_metas()["metas"]]
    if argumentos:
        return argumentos[0]
    if len(ids) == 1:
        return ids[0]
    if not ids:
        raise ErroDeConsulta("Nenhuma meta cadastrada.")
    raise ErroDeConsulta("Informe a meta. Existentes: " + ", ".join(ids))


def responder(texto: str, abrir: Callable[[], ConsultaMetas]) -> str:
    """Interpreta um comando e devolve o texto da resposta. `abrir()` entrega uma consulta somente leitura (fechada aqui no fim)."""
    partes = texto.strip().split()
    if not partes or not partes[0].startswith("/"):
        return NAO_ENTENDI
    comando, argumentos = partes[0].split("@")[0].lower(), partes[1:]
    if comando in ("/start", "/ajuda", "/help"):
        return AJUDA
    if comando not in ("/metas", "/progresso", "/pendencias", "/historico"):
        return NAO_ENTENDI
    try:
        consulta = abrir()
    except ErroDeConsulta as erro:
        return f"Não consegui ler os dados: {erro}"
    try:
        if comando == "/metas":
            return _metas(consulta)
        meta = _meta(consulta, argumentos)
        if comando == "/progresso":
            return _progresso(consulta, meta)
        if comando == "/pendencias":
            return _pendencias(consulta, meta)
        return _historico(consulta, meta, argumentos[1:])
    except ErroDeConsulta as erro:
        return str(erro)
    finally:
        consulta.repo.fechar()


def _metas(consulta: ConsultaMetas) -> str:
    metas = consulta.listar_metas()["metas"]
    if not metas:
        return "Nenhuma meta cadastrada."
    linhas = []
    for m in metas:
        comprovado = f"{m['quantidade_comprovada']} de {m['quantidade_alvo']} {m['ativo_id']}" if m["quantidade_comprovada"] is not None else "sem avaliação"
        pend = "" if not m["tem_pendencia"] else f" · {m['execucoes_pendentes_de_comprovacao']} execução(ões) por comprovar"
        linhas.append(f"• {m['meta_id']}: {m['estado_persistido'] or 'não avaliada'} · {comprovado}{pend}\n  avaliada em {instante(m['ultima_avaliacao_em'])}"
                      + (" · há evidência mais nova" if m["evidencia_desatualizada"] else ""))
    return "\n".join(linhas) + "\n\nCada meta mostra a sua última avaliação gravada; não é tempo real."


def _progresso(consulta: ConsultaMetas, meta: str) -> str:
    r = consulta.consultar_progresso(meta)
    d = r["dados"]
    if not d.get("avaliada"):
        return f"{meta}: ainda não avaliada."
    elegivel = d["elegibilidade_para_concluir"]["resultado"]
    orcamento = d["orcamento"]["resultado"]
    linhas = [
        f"{meta} · estado gravado: {r['estado_persistido']}",
        f"Comprovado: {d['quantidade_comprovada']} de {d['quantidade_alvo']}",
        f"Registrado e pendente de comprovação (não conta): {d['quantidade_registrada_pendente_de_comprovacao']}",
        f"Pode concluir? {elegivel} · orçamento: {orcamento}",
    ]
    if d["instante_atingimento"]:
        linhas.append(f"Atingida na execução de {instante(d['instante_atingimento'])}")
    return "\n".join(linhas) + "\n\n" + rodape(r)


def _pendencias(consulta: ConsultaMetas, meta: str) -> str:
    r = consulta.consultar_pendencias(meta)
    d = r["dados"]
    if not d.get("avaliada"):
        return f"{meta}: ainda não avaliada."
    linhas = [f"{meta} · conciliação {'completa' if d['conciliacao_completa'] else 'INCOMPLETA'}"]
    for p in d["pendencias"]:
        risco = " (pode reduzir o progresso)" if p["pode_reduzir_progresso"] else ""
        linhas.append(f"• {p['referencia']}: {legivel(p['motivo_avaliacao'])}{risco}")
    for o in d["orfaos_relevantes"]:
        linhas.append(f"• registro externo sem execução: {o['id_externo']}")
    if d["execucoes_sem_referencia_externa"]:
        linhas.append("Sem referência externa (não podem ser comprovadas até serem vinculadas): " + ", ".join(d["execucoes_sem_referencia_externa"]))
    if len(linhas) == 1:
        linhas.append("Nenhuma pendência na última avaliação.")
    return "\n".join(linhas) + "\n\n" + rodape(r)


def _historico(consulta: ConsultaMetas, meta: str, extra: list[str]) -> str:
    try:
        n = max(1, min(20, int(extra[0]))) if extra else 5
    except ValueError:
        return "O número de eventos deve ser inteiro (ex.: /historico " + meta + " 10)."
    total = consulta.consultar_historico(meta, limite=1)["dados"]["eventos_total"]
    r = consulta.consultar_historico(meta, limite=n, apos_sequencia=max(0, total - n))
    eventos = r["dados"]["eventos"]
    linhas = [f"{meta} · {total} evento(s); últimos {len(eventos)}:"]
    for e in eventos:
        linhas.append(f"#{e['sequencia']} {instante(e['horario_evidencia'])} {legivel(e['tipo'])}" + (f" — {e['motivo']}" if e["motivo"] else ""))
    return "\n".join(linhas) + "\n\n" + rodape(r)
