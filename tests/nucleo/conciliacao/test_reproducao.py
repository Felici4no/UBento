"""Cada arquivo em exemplos/conciliacao é um cenário de regressão: o resultado esperado de cada momento é verificado."""

from pathlib import Path

import pytest

from ubento.nucleo.conciliacao import carregar_reproducao, executar, verificar

PASTA = Path(__file__).resolve().parents[3] / "exemplos" / "conciliacao"
ARQUIVOS = sorted(PASTA.glob("*.yaml"))


def test_ha_cenarios():
    assert len(ARQUIVOS) >= 15


@pytest.mark.parametrize("arquivo", ARQUIVOS, ids=lambda p: p.stem)
def test_cenario(arquivo):
    cenario = carregar_reproducao(arquivo)
    assert cenario.origem == "simulado"
    for momento, relatorio, eventos in executar(cenario):
        assert verificar(momento, relatorio, eventos) == [], f"{arquivo.name} em {momento.agora}"


@pytest.mark.parametrize("arquivo", ARQUIVOS, ids=lambda p: p.stem)
def test_cenario_e_reproduzivel(arquivo):
    """Reprocessar os mesmos dados dá exatamente o mesmo relatório (hashes iguais) e os mesmos eventos."""
    cenario = carregar_reproducao(arquivo)
    a, b = executar(cenario), executar(cenario)
    assert [r.hash_saida for _, r, _ in a] == [r.hash_saida for _, r, _ in b]
    assert [[e.id for e in ev] for _, _, ev in a] == [[e.id for e in ev] for _, _, ev in b]
