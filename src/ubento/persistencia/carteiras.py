"""Persistência SQLite das carteiras do mercado real (ADR-001, passo 4). Mora no mesmo banco das metas, em tabelas próprias.

Diferente das metas, isto NÃO é evidência: é o estado de trabalho de cada carteira, então as tabelas são mutáveis (sem os gatilhos de
append-only). Este módulo só guarda e devolve dados já prontos (`dict`, texto); quem converte carteira ↔ dados é `ubento.carteira_serial`.
Uma carteira de agente removido é ARQUIVADA, nunca apagada.
"""

from __future__ import annotations

import json
import sqlite3

from .repositorio import Repositorio

ESQUEMA = """
CREATE TABLE IF NOT EXISTS carteiras (
    agente_id TEXT PRIMARY KEY, estado TEXT NOT NULL, atualizada_em TEXT NOT NULL, arquivada_em TEXT
);
CREATE TABLE IF NOT EXISTS carteira_pontos (
    agente_id TEXT NOT NULL, instante TEXT NOT NULL, valor TEXT NOT NULL, PRIMARY KEY (agente_id, instante)
);
CREATE TABLE IF NOT EXISTS mercado_ultimo (
    id INTEGER PRIMARY KEY CHECK (id = 1), dados TEXT NOT NULL, lido_em TEXT NOT NULL
);
"""


class RepositorioCarteiras:
    def __init__(self, repo: Repositorio):
        self.repo = repo
        if not repo.somente_leitura:
            repo.con.executescript(ESQUEMA)

    def _ler(self, sql: str, parametros: tuple = ()) -> list[sqlite3.Row]:
        try:
            return list(self.repo.con.execute(sql, parametros))
        except sqlite3.OperationalError as erro:
            if "no such table" in str(erro):
                return []  # banco aberto só para leitura, criado antes das carteiras existirem
            raise

    # -- estado -------------------------------------------------------------------------------------------------------------------------

    def salvar(self, agente_id: str, estado: dict, em: str) -> None:
        with self.repo.escrita():
            self.repo.con.execute(
                "INSERT INTO carteiras (agente_id, estado, atualizada_em, arquivada_em) VALUES (?, ?, ?, NULL) "
                "ON CONFLICT(agente_id) DO UPDATE SET estado = excluded.estado, atualizada_em = excluded.atualizada_em, arquivada_em = NULL",
                (agente_id, json.dumps(estado, sort_keys=True, ensure_ascii=False), em),
            )

    def carregar(self, agente_id: str) -> dict | None:
        """O estado guardado da carteira, ou None se não existe ou foi arquivada. JSON corrompido levanta `ValueError`."""
        linhas = self._ler("SELECT estado FROM carteiras WHERE agente_id = ? AND arquivada_em IS NULL", (agente_id,))
        return json.loads(linhas[0]["estado"]) if linhas else None

    def arquivar(self, agente_id: str, em: str) -> None:
        with self.repo.escrita():
            self.repo.con.execute("UPDATE carteiras SET arquivada_em = ? WHERE agente_id = ? AND arquivada_em IS NULL", (em, agente_id))

    def arquivadas(self) -> list[tuple[str, str]]:
        return [(r["agente_id"], r["arquivada_em"]) for r in self._ler("SELECT agente_id, arquivada_em FROM carteiras WHERE arquivada_em IS NOT NULL ORDER BY arquivada_em, agente_id")]

    # -- patrimônio observado -------------------------------------------------------------------------------------------------------

    def gravar_pontos(self, agente_id: str, pontos: list[tuple[str, str]]) -> None:
        """Acrescenta pontos novos e corrige os que já existiam no mesmo instante (o último ponto de cada minuto é regravado)."""
        with self.repo.escrita():
            self.repo.con.executemany("INSERT OR REPLACE INTO carteira_pontos (agente_id, instante, valor) VALUES (?, ?, ?)", [(agente_id, q, v) for q, v in pontos])

    def pontos(self, agente_id: str) -> list[tuple[str, str]]:
        return [(r["instante"], r["valor"]) for r in self._ler("SELECT instante, valor FROM carteira_pontos WHERE agente_id = ? ORDER BY instante", (agente_id,))]

    # -- último preço lido ------------------------------------------------------------------------------------------------------------

    def salvar_mercado(self, dados: dict, lido_em: str) -> None:
        with self.repo.escrita():
            self.repo.con.execute(
                "INSERT INTO mercado_ultimo (id, dados, lido_em) VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET dados = excluded.dados, lido_em = excluded.lido_em",
                (json.dumps(dados, sort_keys=True), lido_em),
            )

    def carregar_mercado(self) -> tuple[dict, str] | None:
        linhas = self._ler("SELECT dados, lido_em FROM mercado_ultimo WHERE id = 1")
        return (json.loads(linhas[0]["dados"]), linhas[0]["lido_em"]) if linhas else None
