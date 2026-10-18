"""Textos para pessoas: os identificadores do domínio não têm acento; na tela (e no Telegram) eles voltam a ser português."""

from __future__ import annotations

ACENTOS = {
    "nao": "não", "execucao": "execução", "execucoes": "execuções", "pendencia": "pendência", "conciliacao": "conciliação",
    "conciliada": "conciliada", "avaliacao": "avaliação", "invalidacao": "invalidação", "evidencia": "evidência", "orcamento": "orçamento",
    "possivel": "possível", "verificavel": "verificável", "indeterminado": "indeterminado", "ate": "até", "registro": "registro",
    "reducao": "redução", "excecao": "exceção", "divergencia": "divergência", "revisao": "revisão", "movimentacao": "movimentação",
    "reconciliada": "reconciliada", "bloqueio": "bloqueio", "cotacao": "cotação", "periodo": "período", "ja": "já", "comprovacao": "comprovação",
}


def legivel(identificador: str) -> str:
    return " ".join(ACENTOS.get(parte, parte) for parte in identificador.split("_"))
