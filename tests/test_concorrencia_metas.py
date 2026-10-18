"""Concorrência: duas conexões (como dois processos) disputando a mesma quantidade de um registro externo."""

from __future__ import annotations

import threading
import time
from decimal import Decimal
from pathlib import Path

import pytest

from test_correcao_vinculo import CENARIO, JUST, base
from ubento.metas import ErroDeRegistro, ServicoMetas
from ubento.nucleo.avaliacao.reproducao import carregar_reproducao_meta
from ubento.persistencia import Repositorio


@pytest.fixture
def lento(monkeypatch):
    """Alarga a janela entre "verificar" e "gravar": quem não for atômico perde a corrida de forma determinística."""
    original = ServicoMetas._reivindicacoes

    def devagar(self):
        resultado = original(self)
        time.sleep(0.25)
        return resultado

    monkeypatch.setattr(ServicoMetas, "_reivindicacoes", devagar)


def duas_metas(db: Path):
    sv = ServicoMetas(Repositorio(db))
    _, a, *_ = base(sv)
    _, b, *_ = base(sv, meta_id="meta-b")
    sv.repo.fechar()
    return a, b


def disputar(db: Path, tarefas) -> list[object]:
    """Roda cada tarefa(servico) numa thread com SUA PRÓPRIA conexão, largando juntas. Devolve o resultado ou a exceção de cada uma."""
    saidas: list[object] = [None] * len(tarefas)
    largada = threading.Barrier(len(tarefas))

    def correr(i, tarefa):
        sv = ServicoMetas(Repositorio(db))
        try:
            largada.wait()
            saidas[i] = tarefa(sv)
        except Exception as erro:  # noqa: BLE001 - o teste inspeciona o tipo
            saidas[i] = erro
        finally:
            sv.repo.fechar()

    threads = [threading.Thread(target=correr, args=(i, t)) for i, t in enumerate(tarefas)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return saidas


def test_dois_vinculos_simultaneos_do_mesmo_registro_so_um_vence(tmp_path, lento):
    db = tmp_path / "x.db"
    a, b = duas_metas(db)
    saidas = disputar(db, [
        lambda sv: sv.vincular_manualmente(a, "ex-1", "corretora-sim", "fill-1", "Lucas", JUST),
        lambda sv: sv.vincular_manualmente(b, "ex-1", "corretora-sim", "fill-1", "Marina", JUST),
    ])
    vencedores = [s for s in saidas if s is True]
    perdedores = [s for s in saidas if isinstance(s, ErroDeRegistro)]
    assert len(vencedores) == 1 and len(perdedores) == 1, saidas
    sv = ServicoMetas(Repositorio(db))
    donos = [(m, v.execucao_id) for m in (a, b) for v in sv.repo.entradas(m, "vinculos_manuais", __import__("ubento.nucleo.conciliacao", fromlist=["VinculoManual"]).VinculoManual)]
    assert len(donos) == 1  # a compra foi contada uma vez só
    sv.repo.fechar()


def test_duas_alocacoes_parciais_simultaneas_nao_passam_da_quantidade_do_registro(tmp_path, lento):
    db = tmp_path / "x.db"
    a, b = duas_metas(db)
    o = carregar_reproducao_meta(CENARIO)
    ref = o.execucoes[0].referencias_externas[0].model_copy(update={"quantidade_bruta_alocada": Decimal(3)})  # o registro tem 4: 3 + 3 não cabe
    modelo = o.execucoes[0]
    saidas = disputar(db, [
        lambda sv: sv.registrar_execucao(a, modelo.model_copy(update={"id": "p-a", "meta_id": a, "referencias_externas": (ref,)})),
        lambda sv: sv.registrar_execucao(b, modelo.model_copy(update={"id": "p-b", "meta_id": b, "referencias_externas": (ref,)})),
    ])
    assert sorted(type(s).__name__ for s in saidas) == ["ErroDeRegistro", "bool"], saidas
    sv = ServicoMetas(Repositorio(db))
    alocado = sum(
        (r.quantidade_bruta_alocada for m in (a, b) for e in sv.repo.entradas(m, "execucoes", type(modelo)) if e.id.startswith("p-") for r in e.referencias_externas),
        Decimal(0),
    )
    assert alocado == Decimal(3) <= o.registros_externos[0].quantidade
    sv.repo.fechar()


def test_alocacoes_que_cabem_podem_ser_simultaneas(tmp_path, lento):
    db = tmp_path / "x.db"
    a, b = duas_metas(db)
    o = carregar_reproducao_meta(CENARIO)
    modelo = o.execucoes[0]

    def ref(n):
        return (modelo.referencias_externas[0].model_copy(update={"quantidade_bruta_alocada": Decimal(n)}),)

    saidas = disputar(db, [
        lambda sv: sv.registrar_execucao(a, modelo.model_copy(update={"id": "p-a", "meta_id": a, "referencias_externas": ref(2)})),
        lambda sv: sv.registrar_execucao(b, modelo.model_copy(update={"id": "p-b", "meta_id": b, "referencias_externas": ref(2)})),
    ])
    assert saidas == [True, True]  # 2 + 2 <= 4: a exclusividade não impede o que cabe
