"""Persistência SQLite das metas. Fica FORA de `ubento.nucleo` (o núcleo é puro: sem sqlite, Qt, rede ou relógio).

Princípios:
  - tudo o que é registro histórico é append-only: gatilhos do banco recusam UPDATE e DELETE;
  - o contrato e a ativação não mudam (hash conferido na leitura e na gravação);
  - eventos têm sequência contínua por meta (`UNIQUE(meta_id, sequencia)` + verificação na gravação);
  - `gravar` é uma transação: ou entram eventos, razão e avaliação juntos, ou nada;
  - gravar duas vezes o mesmo resultado não duplica nada (ids determinísticos).
Só o cursor de reprodução (`cursor`) é mutável: não é fato do domínio, só a posição de quem está navegando.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar

from ..nucleo.avaliacao.modelos import ProgressoAvaliado, ResultadoAvaliacao
from ..nucleo.avaliacao.reproducao import MomentoMeta, ReproducaoMeta
from ..nucleo.canonico import hash_contrato
from ..nucleo.conciliacao.eventos import EventoConciliacao
from ..nucleo.esquema import Ativacao, Avaliacao, Evento, Meta, Modelo

M = TypeVar("M", bound=Modelo)

APPEND_ONLY = ("metas", "eventos", "razao", "avaliacoes", "entradas")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS metas (
    meta_id TEXT PRIMARY KEY, contrato_hash TEXT NOT NULL, contrato TEXT NOT NULL,
    ativada_em TEXT NOT NULL, responsavel TEXT NOT NULL, agente_id TEXT, descricao TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eventos (
    meta_id TEXT NOT NULL REFERENCES metas(meta_id), sequencia INTEGER NOT NULL, id TEXT NOT NULL, tipo TEXT NOT NULL, dados TEXT NOT NULL,
    PRIMARY KEY (meta_id, sequencia), UNIQUE (meta_id, id)
);
CREATE TABLE IF NOT EXISTS razao (
    ordem INTEGER PRIMARY KEY AUTOINCREMENT, meta_id TEXT NOT NULL REFERENCES metas(meta_id), id TEXT NOT NULL, tipo TEXT NOT NULL,
    dados TEXT NOT NULL, UNIQUE (meta_id, id)
);
CREATE TABLE IF NOT EXISTS avaliacoes (
    ordem INTEGER PRIMARY KEY AUTOINCREMENT, meta_id TEXT NOT NULL REFERENCES metas(meta_id), id TEXT NOT NULL, avaliada_em TEXT NOT NULL,
    estado TEXT NOT NULL, avaliacao TEXT NOT NULL, progresso TEXT NOT NULL, UNIQUE (meta_id, id)
);
CREATE TABLE IF NOT EXISTS entradas (
    ordem INTEGER PRIMARY KEY AUTOINCREMENT, meta_id TEXT NOT NULL REFERENCES metas(meta_id), tipo TEXT NOT NULL, hash TEXT NOT NULL,
    dados TEXT NOT NULL, UNIQUE (meta_id, tipo, hash)
);
CREATE TABLE IF NOT EXISTS cursor (meta_id TEXT PRIMARY KEY REFERENCES metas(meta_id), proximo INTEGER NOT NULL);
"""

# Campos de ReproducaoMeta que viram "entradas" (os dados que alimentam a conciliação). `momentos` entra à parte, em ordem.
CAMPOS_ENTRADA = (
    "execucoes", "registros_externos", "coberturas_execucoes", "movimentacoes", "saldos", "coberturas", "vinculos_manuais", "observacoes",
)


# o que pode ser acrescentado depois da importação: as entradas do cenário + as revogações de vínculos manuais
TIPOS_REGISTRAVEIS = (*CAMPOS_ENTRADA, "revogacoes_vinculos")


class ErroDePersistencia(RuntimeError):
    pass


class ErroDeSequencia(ErroDePersistencia):
    """Os eventos a gravar não continuam a história já registrada (outro processo gravou antes?)."""


class ErroDeContrato(ErroDePersistencia):
    pass


def _gatilhos() -> str:
    partes = []
    for t in APPEND_ONLY:
        for op in ("UPDATE", "DELETE"):
            partes.append(f"CREATE TRIGGER IF NOT EXISTS {t}_sem_{op.lower()} BEFORE {op} ON {t} BEGIN SELECT RAISE(ABORT, '{t} é append-only'); END;")
    return "\n".join(partes)


class Repositorio:
    """`somente_leitura=True` abre o banco existente em modo `ro` com `query_only`: nenhuma escrita é possível (nem criar tabelas)."""

    def __init__(self, caminho: str | Path = ":memory:", somente_leitura: bool = False):
        self.caminho = str(caminho)
        self.somente_leitura = somente_leitura
        if somente_leitura:
            if self.caminho == ":memory:" or not Path(self.caminho).exists():
                raise ErroDePersistencia(f"banco inexistente (somente leitura não cria nada): {self.caminho}")
            self.con = sqlite3.connect(Path(self.caminho).resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
            self.con.row_factory = sqlite3.Row
            self.con.execute("PRAGMA query_only = ON")
            return
        if self.caminho != ":memory:":
            Path(self.caminho).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.caminho, timeout=10)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys = ON")
        if self.caminho != ":memory:":
            self.con.execute("PRAGMA journal_mode = WAL")
        self.con.executescript(ESQUEMA + _gatilhos())

    def fechar(self) -> None:
        self.con.close()

    @contextmanager
    def _tx(self, imediata: bool = False):
        """Transação com commit/rollback. Aninhada, ela se junta à transação já aberta (quem abriu é quem fecha)."""
        if self.con.in_transaction:
            yield
            return
        self.con.execute("BEGIN IMMEDIATE" if imediata else "BEGIN")
        try:
            yield
        except BaseException:
            self.con.rollback()
            raise
        else:
            self.con.commit()

    def escrita(self):
        """Seção de escrita EXCLUSIVA: `BEGIN IMMEDIATE` toma o direito de escrever já no início, então "verificar e gravar" é atômico
        mesmo com outro processo ou thread (conexão) escrevendo no mesmo banco: o segundo espera e enxerga o resultado do primeiro."""
        return self._tx(imediata=True)

    # -- metas ------------------------------------------------------------------------------------------------------

    def importar(self, arquivo: ReproducaoMeta, ativacao: Ativacao, agente_id: str | None = None) -> bool:
        """Registra o contrato, a ativação e as entradas. Idempotente: importar de novo não muda nada. Devolve se criou."""
        meta = arquivo.meta
        h = hash_contrato(meta)
        with self._tx():
            atual = self.con.execute("SELECT contrato_hash FROM metas WHERE meta_id = ?", (meta.id,)).fetchone()
            if atual and atual["contrato_hash"] != h:
                raise ErroDeContrato(f"a meta {meta.id} já está ativa com outro contrato: metas ativas são imutáveis")
            criou = atual is None
            if criou:
                self.con.execute(
                    "INSERT INTO metas VALUES (?,?,?,?,?,?,?)",
                    (meta.id, h, meta.model_dump_json(), ativacao.ativada_em.isoformat(), ativacao.responsavel, agente_id, arquivo.descricao),
                )
                self.con.execute("INSERT INTO cursor VALUES (?, 0)", (meta.id,))
            for campo in CAMPOS_ENTRADA:
                self._entradas(meta.id, campo, getattr(arquivo, campo))
            self._entradas(meta.id, "politica_conciliacao", [arquivo.politica_conciliacao])
            for i, momento in enumerate(sorted(arquivo.momentos, key=lambda m: m.agora)):
                self._entradas(meta.id, "momento", [momento], chave=f"{i:06d}")
        return criou

    def _entradas(self, meta_id: str, tipo: str, itens: Iterable[Modelo], chave: str = "") -> None:
        """Grava as entradas na ordem recebida. A chave inclui a POSIÇÃO: dois itens idênticos no mesmo arquivo são duas entradas
        (um feed duplicado é um fato que a conciliação precisa ver), e reimportar o mesmo arquivo cai nas mesmas chaves."""
        from ..nucleo.canonico import hash_canonico

        for i, item in enumerate(itens):
            h = f"{chave}{i:06d}:{hash_canonico(item, 'ubento.entrada.v1')}"
            self.con.execute("INSERT OR IGNORE INTO entradas (meta_id, tipo, hash, dados) VALUES (?,?,?,?)", (meta_id, tipo, h, item.model_dump_json()))

    def registrar_entrada(self, meta_id: str, tipo: str, item: Modelo) -> bool:
        """Acrescenta UMA entrada nova (ex.: uma execução confirmada manualmente). Nunca altera as existentes.
        Registrar o mesmo conteúdo de novo não faz nada. Devolve se gravou."""
        return self.registrar_entradas(meta_id, [(tipo, item)])[0]

    def registrar_entradas(self, meta_id: str, itens: list[tuple[str, Modelo]]) -> list[bool]:
        """Acrescenta várias entradas NUMA transação (ou todas, ou nenhuma). Conteúdo já registrado é ignorado (False)."""
        from ..nucleo.canonico import hash_canonico

        for tipo, _ in itens:
            if tipo not in TIPOS_REGISTRAVEIS:
                raise ErroDePersistencia(f"tipo de entrada desconhecido: {tipo}")
        gravou = []
        with self._tx():
            for tipo, item in itens:
                conteudo = hash_canonico(item, "ubento.entrada.v1")
                if self.con.execute("SELECT 1 FROM entradas WHERE meta_id = ? AND tipo = ? AND hash LIKE ?", (meta_id, tipo, f"%:{conteudo}")).fetchone():
                    gravou.append(False)
                    continue
                n = self.con.execute("SELECT COUNT(*) FROM entradas WHERE meta_id = ? AND tipo = ?", (meta_id, tipo)).fetchone()[0]
                self.con.execute(
                    "INSERT INTO entradas (meta_id, tipo, hash, dados) VALUES (?,?,?,?)",
                    (meta_id, tipo, f"manual{n:06d}:{conteudo}", item.model_dump_json()),
                )
                gravou.append(True)
        return gravou

    def metas_ids(self) -> list[str]:
        return [r["meta_id"] for r in self.con.execute("SELECT meta_id FROM metas ORDER BY rowid")]

    def agente_da_meta(self, meta_id: str) -> str | None:
        r = self.con.execute("SELECT agente_id FROM metas WHERE meta_id = ?", (meta_id,)).fetchone()
        return r["agente_id"] if r else None

    def descricao(self, meta_id: str) -> str:
        return self.con.execute("SELECT descricao FROM metas WHERE meta_id = ?", (meta_id,)).fetchone()["descricao"]

    def carregar_meta(self, meta_id: str) -> tuple[Meta, Ativacao]:
        r = self.con.execute("SELECT * FROM metas WHERE meta_id = ?", (meta_id,)).fetchone()
        if r is None:
            raise ErroDePersistencia(f"meta desconhecida: {meta_id}")
        meta = Meta.model_validate_json(r["contrato"])
        if hash_contrato(meta) != r["contrato_hash"]:
            raise ErroDeContrato(f"contrato da meta {meta_id} não confere com o hash registrado (banco adulterado?)")
        ativacao = Ativacao(meta_id=meta_id, contrato_hash=r["contrato_hash"], ativada_em=r["ativada_em"], responsavel=r["responsavel"])
        return meta, ativacao

    def entradas(self, meta_id: str, tipo: str, modelo: type[M]) -> list[M]:
        linhas = self.con.execute("SELECT dados FROM entradas WHERE meta_id = ? AND tipo = ? ORDER BY ordem", (meta_id, tipo))
        return [modelo.model_validate_json(r["dados"]) for r in linhas]

    def momentos(self, meta_id: str) -> list[MomentoMeta]:
        linhas = self.con.execute("SELECT dados FROM entradas WHERE meta_id = ? AND tipo = 'momento' ORDER BY hash", (meta_id,))
        return [MomentoMeta.model_validate_json(r["dados"]) for r in linhas]

    # -- história ---------------------------------------------------------------------------------------------------

    def eventos(self, meta_id: str) -> list[Evento]:
        linhas = self.con.execute("SELECT dados FROM eventos WHERE meta_id = ? ORDER BY sequencia", (meta_id,))
        return [Evento.model_validate_json(r["dados"]) for r in linhas]

    def razao(self, meta_id: str) -> list[EventoConciliacao]:
        linhas = self.con.execute("SELECT dados FROM razao WHERE meta_id = ? ORDER BY ordem", (meta_id,))
        return [EventoConciliacao.model_validate_json(r["dados"]) for r in linhas]

    def avaliacoes(self, meta_id: str) -> list[tuple[Avaliacao, ProgressoAvaliado]]:
        linhas = self.con.execute("SELECT avaliacao, progresso FROM avaliacoes WHERE meta_id = ? ORDER BY ordem", (meta_id,))
        return [(Avaliacao.model_validate_json(r["avaliacao"]), ProgressoAvaliado.model_validate_json(r["progresso"])) for r in linhas]

    def ultima_avaliacao(self, meta_id: str) -> tuple[Avaliacao, ProgressoAvaliado] | None:
        r = self.con.execute("SELECT avaliacao, progresso FROM avaliacoes WHERE meta_id = ? ORDER BY ordem DESC LIMIT 1", (meta_id,)).fetchone()
        return None if r is None else (Avaliacao.model_validate_json(r["avaliacao"]), ProgressoAvaliado.model_validate_json(r["progresso"]))

    def gravar(self, meta_id: str, resultado: ResultadoAvaliacao) -> int:
        """Grava eventos, razão e avaliação numa transação. Devolve quantos registros NOVOS entraram (0 = reprocessamento limpo)."""
        if resultado.avaliacao.meta_id != meta_id:
            raise ErroDePersistencia("a avaliação pertence a outra meta")
        novos = 0
        with self._tx():  # rollback automático em qualquer exceção
            ultima = self.con.execute("SELECT COALESCE(MAX(sequencia), 0) FROM eventos WHERE meta_id = ?", (meta_id,)).fetchone()[0]
            for esperada, e in enumerate(resultado.eventos, start=ultima + 1):
                if e.meta_id != meta_id or e.sequencia != esperada:
                    raise ErroDeSequencia(f"evento {e.id}: sequência {e.sequencia} não continua a história (esperava {esperada})")
                self.con.execute("INSERT INTO eventos VALUES (?,?,?,?,?)", (meta_id, e.sequencia, e.id, e.tipo.value, e.model_dump_json()))
                novos += 1
            for c in resultado.eventos_conciliacao:
                cur = self.con.execute(
                    "INSERT OR IGNORE INTO razao (meta_id, id, tipo, dados) VALUES (?,?,?,?)", (meta_id, c.id, c.tipo.value, c.model_dump_json()),
                )
                novos += cur.rowcount
            a = resultado.avaliacao
            cur = self.con.execute(
                "INSERT OR IGNORE INTO avaliacoes (meta_id, id, avaliada_em, estado, avaliacao, progresso) VALUES (?,?,?,?,?,?)",
                (meta_id, a.id, a.avaliada_em.isoformat(), a.estado.value, a.model_dump_json(), resultado.progresso.model_dump_json()),
            )
            novos += cur.rowcount
        return novos

    # -- cursor da reprodução ------------------------------------------------------------------------------------------

    def cursor(self, meta_id: str) -> int:
        return self.con.execute("SELECT proximo FROM cursor WHERE meta_id = ?", (meta_id,)).fetchone()["proximo"]

    def mover_cursor(self, meta_id: str, proximo: int) -> None:
        with self._tx():
            self.con.execute("UPDATE cursor SET proximo = ? WHERE meta_id = ?", (proximo, meta_id))
