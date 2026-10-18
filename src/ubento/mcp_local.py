"""Servidor MCP local do UBento, SOMENTE CONSULTA (v1). Fala JSON-RPC 2.0 por stdio (uma mensagem JSON por linha).

    python -m ubento.mcp_local [--db CAMINHO]        (padrão: UBENTO_DB ou a pasta de dados do usuário)

Ferramentas: listar_metas, consultar_meta, consultar_progresso, consultar_pendencias, consultar_historico.
Nenhuma importa dados, reavalia ou grava: o banco é aberto em modo somente leitura e cada resposta diz que base usou
(estado persistido), quando foi a última avaliação e o que a evidência cobre. Sem dependências além da biblioteca padrão
e do próprio UBento (a camada de ferramentas é independente do transporte, então trocar por um SDK de MCP é trivial).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import __version__
from .caminhos import caminho_do_banco
from .consulta import LIMITE_MAXIMO, LIMITE_PADRAO, ConsultaMetas, ErroDeConsulta, abrir

VERSAO_DO_PROTOCOLO = "2025-06-18"
INSTRUCOES = (
    "Consulta somente leitura às metas do UBento. Toda resposta separa: estado persistido (último gravado), instante da última avaliação "
    "e cobertura da evidência. Consultar não importa, não reavalia e não grava."
)
ANOTACOES = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
_META = {"type": "string", "description": "Identificador da meta (veja listar_metas)."}


def _schema(propriedades: dict | None = None, obrigatorias: list[str] | None = None) -> dict:
    return {"type": "object", "properties": propriedades or {}, "required": obrigatorias or [], "additionalProperties": False}


FERRAMENTAS: dict[str, dict[str, Any]] = {
    "listar_metas": {
        "descricao": "Lista as metas com o estado PERSISTIDO, o instante da última avaliação e se há evidência mais nova que ela.",
        "schema": _schema({"agente_id": {"type": "string", "description": "Opcional: só as metas deste agente."}}),
        "chamar": lambda c, a: c.listar_metas(a.get("agente_id")),
    },
    "consultar_meta": {
        "descricao": "Detalhes de uma meta: objetivo, mercado/conta, ativação e cenário. Não recalcula nada.",
        "schema": _schema({"meta_id": _META}, ["meta_id"]),
        "chamar": lambda c, a: c.consultar_meta(a["meta_id"]),
    },
    "consultar_progresso": {
        "descricao": "Progresso comprovado (separado do registrado pendente), elegibilidade, orçamento e custos, como gravados na última avaliação.",
        "schema": _schema({"meta_id": _META}, ["meta_id"]),
        "chamar": lambda c, a: c.consultar_progresso(a["meta_id"]),
    },
    "consultar_pendencias": {
        "descricao": "Pendências da conciliação, registros externos sem execução (relevantes e ignorados) e execuções com sua situação.",
        "schema": _schema({"meta_id": _META}, ["meta_id"]),
        "chamar": lambda c, a: c.consultar_pendencias(a["meta_id"]),
    },
    "consultar_historico": {
        "descricao": "Eventos da meta (paginados por sequência), razão de conciliação, avaliações e a trilha de vínculos manuais com suas revogações.",
        "schema": _schema({
            "meta_id": _META,
            "limite": {"type": "integer", "minimum": 1, "maximum": LIMITE_MAXIMO, "default": LIMITE_PADRAO, "description": "Itens por lista."},
            "apos_sequencia": {"type": "integer", "minimum": 0, "default": 0, "description": "Só eventos com sequência maior que esta (paginação)."},
        }, ["meta_id"]),
        "chamar": lambda c, a: c.consultar_historico(a["meta_id"], a.get("limite", LIMITE_PADRAO), a.get("apos_sequencia", 0)),
    },
}


def _tipo_ok(valor: Any, tipo: str) -> bool:
    return {"string": isinstance(valor, str), "integer": isinstance(valor, int) and not isinstance(valor, bool)}.get(tipo, True)


def validar_argumentos(nome: str, argumentos: Any) -> dict:
    esquema = FERRAMENTAS[nome]["schema"]
    if not isinstance(argumentos, dict):
        raise ErroDeConsulta("os argumentos devem ser um objeto")
    for k in esquema["required"]:
        if k not in argumentos:
            raise ErroDeConsulta(f"argumento obrigatório ausente: {k}")
    for k, v in argumentos.items():
        if k not in esquema["properties"]:
            raise ErroDeConsulta(f"argumento desconhecido: {k}")
        if not _tipo_ok(v, esquema["properties"][k]["type"]):
            raise ErroDeConsulta(f"argumento {k} deve ser {esquema['properties'][k]['type']}")
    return argumentos


class ServidorMcp:
    """`tratar(mensagem)` devolve a resposta (ou None para notificações). Abre o banco somente leitura A CADA chamada: sempre o que está gravado agora."""

    def __init__(self, caminho: str | Path | None = None, abrir_consulta: Callable[[Any], ConsultaMetas] = abrir):
        self.caminho = Path(caminho) if caminho else caminho_do_banco()
        self._abrir = abrir_consulta

    def tratar(self, mensagem: Any) -> dict | None:
        if not isinstance(mensagem, dict) or mensagem.get("jsonrpc") != "2.0" or not isinstance(mensagem.get("method"), str):
            return _erro(mensagem.get("id") if isinstance(mensagem, dict) else None, -32600, "requisição inválida")
        ident, metodo, params = mensagem.get("id"), mensagem["method"], mensagem.get("params") or {}
        if "id" not in mensagem:  # notificação: nunca se responde
            return None
        if metodo == "initialize":
            pedido = params.get("protocolVersion") if isinstance(params, dict) else None
            return _ok(ident, {
                "protocolVersion": pedido if isinstance(pedido, str) else VERSAO_DO_PROTOCOLO,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "ubento-metas", "version": __version__},
                "instructions": INSTRUCOES,
            })
        if metodo == "ping":
            return _ok(ident, {})
        if metodo == "tools/list":
            return _ok(ident, {"tools": [
                {"name": n, "description": f["descricao"], "inputSchema": f["schema"], "annotations": ANOTACOES} for n, f in FERRAMENTAS.items()]})
        if metodo == "tools/call":
            return self._chamar(ident, params)
        return _erro(ident, -32601, f"método não suportado: {metodo}")

    def _chamar(self, ident: Any, params: Any) -> dict:
        nome = params.get("name") if isinstance(params, dict) else None
        if nome not in FERRAMENTAS:
            return _erro(ident, -32602, f"ferramenta desconhecida: {nome!r}")
        try:
            argumentos = validar_argumentos(nome, params.get("arguments") or {})
            consulta = self._abrir(self.caminho)
            try:
                dados = FERRAMENTAS[nome]["chamar"](consulta, argumentos)
            finally:
                consulta.repo.fechar()
        except ErroDeConsulta as erro:
            return _ok(ident, {"content": [{"type": "text", "text": str(erro)}], "isError": True})
        texto = json.dumps(dados, ensure_ascii=False, indent=2)
        return _ok(ident, {"content": [{"type": "text", "text": texto}], "structuredContent": dados, "isError": False})


def _ok(ident: Any, resultado: dict) -> dict:
    return {"jsonrpc": "2.0", "id": ident, "result": resultado}


def _erro(ident: Any, codigo: int, mensagem: str) -> dict:
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": codigo, "message": mensagem}}


def servir(servidor: ServidorMcp, entrada=None, saida=None) -> None:
    entrada = entrada or sys.stdin
    saida = saida or sys.stdout
    for linha in entrada:
        if not linha.strip():
            continue
        try:
            mensagem = json.loads(linha)
        except json.JSONDecodeError:
            resposta = _erro(None, -32700, "JSON inválido")
        else:
            resposta = servidor.tratar(mensagem)
        if resposta is not None:
            saida.write(json.dumps(resposta, ensure_ascii=False) + "\n")
            saida.flush()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ubento-mcp", description="MCP local do UBento (somente consulta).")
    ap.add_argument("--db", help="caminho do banco (padrão: UBENTO_DB ou a pasta de dados do usuário)")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    servidor = ServidorMcp(args.db)
    print(f"ubento-mcp {__version__}: somente leitura, banco {servidor.caminho}", file=sys.stderr)  # stderr: stdout é só do protocolo
    servir(servidor)
    return 0


if __name__ == "__main__":
    sys.exit(main())
