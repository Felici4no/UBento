"""Cada arquivo em exemplos/avaliacao acompanha uma meta de ponta a ponta e afirma o resultado de cada momento."""

from pathlib import Path

import pytest

from ubento.nucleo.avaliacao.reproducao import carregar_reproducao_meta, executar_meta, verificar_passo

PASTA = Path(__file__).resolve().parents[3] / "exemplos" / "avaliacao"
ARQUIVOS = sorted(PASTA.glob("*.yaml"))


def test_ha_cenarios():
    assert len(ARQUIVOS) >= 20


@pytest.mark.parametrize("arquivo", ARQUIVOS, ids=lambda p: p.stem)
def test_cenario(arquivo):
    cenario = carregar_reproducao_meta(arquivo)
    assert cenario.origem == "simulado"
    for passo in executar_meta(cenario):
        assert verificar_passo(passo) == [], f"{arquivo.name} em {passo.momento.agora}"
