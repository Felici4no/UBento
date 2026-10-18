"""Construtores de teste para o avaliador: reaproveitam os mesmos construtores que geram os cenários de exemplo."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

from ubento.nucleo.avaliacao.reproducao import MomentoMeta, ReproducaoMeta, executar_meta

RAIZ = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("gerar_cenarios_meta", RAIZ / "scripts" / "gerar_cenarios_meta.py")
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)  # só define construtores e o dicionário de cenários; nada é gravado


def instante(hora: str) -> datetime:
    h, m, s = (int(x) for x in hora.split(":"))
    return datetime(2026, 10, 20, h, m, s, tzinfo=UTC)


def montar(execucoes, externos, horas, **kw) -> ReproducaoMeta:
    momentos = [{"agora": G.t(h), "esperado": {}} for h in horas]
    return ReproducaoMeta.model_validate(G.cenario("cenário de teste", execucoes, externos, momentos, **kw))


def rodar(execucoes, externos, horas, **kw):
    return executar_meta(montar(execucoes, externos, horas, **kw))


def ultimo(passos):
    return passos[-1].resultado


def tipos(resultado):
    return [e.tipo.value for e in resultado.eventos]


__all__ = ["G", "MomentoMeta", "instante", "montar", "rodar", "tipos", "ultimo"]
