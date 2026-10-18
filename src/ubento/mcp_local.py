"""Servidor MCP local do UBento, SOMENTE CONSULTA, sobre o SDK oficial (`pip install "ubento[mcp]"`).

    python -m ubento.mcp_local [--db CAMINHO]        (padrão: UBENTO_DB ou a pasta de dados do usuário)

Ferramentas: listar_metas, consultar_meta, consultar_progresso, consultar_pendencias, consultar_historico.
Nenhuma importa dados, reavalia ou grava: o banco é aberto em modo somente leitura a cada chamada e cada resposta diz que base usou
(estado persistido), quando foi a última avaliação e o que a evidência cobre. O SDK cuida do protocolo (negociação de versão,
validação dos argumentos, transporte stdio); a lógica de consulta continua em `ubento.consulta`. Logs vão para stderr: o stdout é só do protocolo.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from . import __version__
from .caminhos import caminho_do_banco
from .consulta import LIMITE_MAXIMO, LIMITE_PADRAO, ConsultaMetas, ErroDeConsulta, abrir

try:
    from mcp.server import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp.types import ToolAnnotations
except ImportError as erro:  # o SDK é uma dependência opcional (extra "mcp"): o app não precisa dele
    raise SystemExit('O MCP local precisa do SDK oficial: pip install "ubento[mcp]" (ou pip install mcp)') from erro

log = logging.getLogger("ubento.mcp")

INSTRUCOES = (
    "Consulta SOMENTE LEITURA às metas do UBento. Toda resposta separa três coisas: o estado persistido (o da última avaliação gravada), "
    "o instante dessa avaliação e a cobertura da evidência. Os dados NÃO são atualizados em tempo real: ao responder, diga sempre quando foi "
    "a última avaliação. Consultar não importa, não reavalia e não grava."
)
ANOTACOES = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
MetaId = Annotated[str, Field(description="Identificador da meta (veja listar_metas).")]


def criar_servidor(caminho: str | Path | None = None, abrir_consulta: Callable[[Any], ConsultaMetas] = abrir) -> MCPServer:
    """Monta o servidor. O banco é aberto (somente leitura) a cada chamada: a resposta é sempre o que está gravado naquele instante."""
    banco = Path(caminho) if caminho else caminho_do_banco()
    servidor = MCPServer("ubento-metas", title="UBento · metas (somente consulta)", instructions=INSTRUCOES, version=__version__)

    def consultar(nome: str, consulta_fn: Callable[[ConsultaMetas], dict]) -> dict:
        try:
            consulta = abrir_consulta(banco)
            try:
                return consulta_fn(consulta)
            finally:
                consulta.repo.fechar()
        except ErroDeConsulta as erro:  # erro de uso: mensagem clara para quem perguntou
            raise ToolError(str(erro)) from erro
        except Exception:
            log.exception("falha inesperada em %s", nome)  # o detalhe técnico fica no log (stderr), não na resposta
            raise

    @servidor.tool(annotations=ANOTACOES)
    def listar_metas(
        agente_id: Annotated[str | None, Field(description="Opcional: só as metas deste agente.")] = None,
        somente_com_pendencias: Annotated[bool, Field(description="Só as metas com pendência na última avaliação gravada.")] = False,
    ) -> dict[str, Any]:
        """Lista as metas com o estado PERSISTIDO, o instante da última avaliação e se há evidência mais nova que ela (sem recalcular)."""
        return consultar("listar_metas", lambda c: c.listar_metas(agente_id, somente_com_pendencias))

    @servidor.tool(annotations=ANOTACOES)
    def consultar_meta(meta_id: MetaId) -> dict[str, Any]:
        """Detalhes de uma meta: objetivo, mercado/conta, ativação e cenário. Não recalcula nada."""
        return consultar("consultar_meta", lambda c: c.consultar_meta(meta_id))

    @servidor.tool(annotations=ANOTACOES)
    def consultar_progresso(meta_id: MetaId) -> dict[str, Any]:
        """Progresso comprovado (separado do registrado pendente), elegibilidade, orçamento e custos, como gravados na última avaliação."""
        return consultar("consultar_progresso", lambda c: c.consultar_progresso(meta_id))

    @servidor.tool(annotations=ANOTACOES)
    def consultar_pendencias(meta_id: MetaId) -> dict[str, Any]:
        """Pendências da conciliação, registros externos sem execução (relevantes e ignorados) e cada execução com sua situação."""
        return consultar("consultar_pendencias", lambda c: c.consultar_pendencias(meta_id))

    @servidor.tool(annotations=ANOTACOES)
    def consultar_historico(
        meta_id: MetaId,
        limite: Annotated[int, Field(ge=1, le=LIMITE_MAXIMO, description="Itens por lista.")] = LIMITE_PADRAO,
        apos_sequencia: Annotated[int, Field(ge=0, description="Só eventos com sequência maior que esta (paginação).")] = 0,
    ) -> dict[str, Any]:
        """Eventos da meta (paginados por sequência), razão de conciliação, avaliações e a trilha de vínculos manuais com suas revogações."""
        return consultar("consultar_historico", lambda c: c.consultar_historico(meta_id, limite, apos_sequencia))

    return servidor


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ubento-mcp", description="MCP local do UBento (somente consulta).")
    ap.add_argument("--db", help="caminho do banco (padrão: UBENTO_DB ou a pasta de dados do usuário)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(name)s %(levelname)s %(message)s")  # stdout é só do protocolo
    banco = Path(args.db) if args.db else caminho_do_banco()
    log.info("ubento-mcp %s: somente leitura, banco %s", __version__, banco)
    criar_servidor(banco).run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
