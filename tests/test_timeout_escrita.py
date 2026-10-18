"""Timeout de escrita: mensagem compreensível, erro técnico no log e nenhuma gravação parcial."""

from __future__ import annotations

import logging
import sqlite3

import pytest

from test_correcao_vinculo import JUST, base
from ubento.metas import ErroDeRegistro, ServicoMetas
from ubento.nucleo.conciliacao import VinculoManual
from ubento.persistencia import ErroBancoOcupado, Repositorio


def estado(db):
    """Tudo o que o teste precisa para provar que nada mudou."""
    sv = ServicoMetas(Repositorio(db))
    try:
        return {m: (sv.repo.eventos(m), sv.repo.razao(m), len(sv.repo.avaliacoes(m)), sv.repo.entradas(m, "vinculos_manuais", VinculoManual)) for m in sv.repo.metas_ids()}
    finally:
        sv.repo.fechar()


def preparar(tmp_path):
    db = tmp_path / "x.db"
    sv = ServicoMetas(Repositorio(db))
    _, mid, *_ = base(sv)
    sv.repo.fechar()
    return db, mid


def test_timeout_de_escrita_da_mensagem_clara_loga_o_erro_tecnico_e_nao_grava_nada(tmp_path, caplog):
    db, mid = preparar(tmp_path)
    antes = estado(db)
    segurando = Repositorio(db)  # outra conexão (outro processo) segura o direito de escrever
    impaciente = ServicoMetas(Repositorio(db, timeout=0.3))
    with segurando.escrita():
        with caplog.at_level(logging.ERROR, logger="ubento.persistencia"), pytest.raises(ErroDeRegistro) as exc:
            impaciente.vincular_manualmente(mid, "ex-1", "corretora-sim", "fill-1", "Lucas", JUST)
    texto = str(exc.value)
    assert "ocupado" in texto and "Nada foi gravado" in texto and "tente novamente" in texto.lower()  # para o usuário
    assert "database is locked" not in texto and "sqlite" not in texto.lower()  # o jargão técnico não vaza para a mensagem
    causa = exc.value.__cause__
    assert isinstance(causa, ErroBancoOcupado) and isinstance(causa.__cause__, sqlite3.OperationalError)  # a cadeia preserva o erro original
    registros = [r for r in caplog.records if r.name == "ubento.persistencia" and r.levelno == logging.ERROR]
    assert registros and "database is locked" in registros[0].getMessage() and registros[0].exc_info  # o detalhe técnico fica no log
    assert estado(db) == antes  # nenhuma gravação parcial

    # quando o outro escritor termina, a mesma operação funciona: a conexão não ficou com transação pendurada
    segurando.fechar()
    assert impaciente.vincular_manualmente(mid, "ex-1", "corretora-sim", "fill-1", "Lucas", JUST) is True
    impaciente.repo.fechar()


def test_falha_de_lock_no_meio_da_operacao_desfaz_tudo(tmp_path, monkeypatch, caplog):
    """Mesmo se o 'locked' aparecer depois de o vínculo já ter sido inserido (na reavaliação), a transação inteira volta atrás."""
    db, mid = preparar(tmp_path)
    antes = estado(db)

    def trava(self, *a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ServicoMetas, "reavaliar", trava)
    sv = ServicoMetas(Repositorio(db))
    with caplog.at_level(logging.ERROR, logger="ubento.persistencia"), pytest.raises(ErroDeRegistro, match="Nada foi gravado"):
        sv.vincular_manualmente(mid, "ex-1", "corretora-sim", "fill-1", "Lucas", JUST)
    assert "database is locked" in caplog.text
    sv.repo.fechar()
    assert estado(db) == antes  # o vínculo inserido antes da falha NÃO ficou


def test_erros_que_nao_sao_de_lock_nao_viram_mensagem_de_banco_ocupado(tmp_path, monkeypatch):
    db, mid = preparar(tmp_path)

    def quebra(self, *a, **k):
        raise sqlite3.OperationalError("no such table: fantasma")

    monkeypatch.setattr(ServicoMetas, "reavaliar", quebra)
    sv = ServicoMetas(Repositorio(db))
    with pytest.raises(sqlite3.OperationalError, match="fantasma"):
        sv.vincular_manualmente(mid, "ex-1", "corretora-sim", "fill-1", "Lucas", JUST)
    sv.repo.fechar()
