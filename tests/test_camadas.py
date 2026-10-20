"""Fronteiras entre as camadas (ADR-001): quem pode importar quem.

    ui ──► serviços (metas, conexoes, workspace) ──► domínio (store, engine, agent_config, cotacoes) ──► núcleo
    persistencia, conexoes e nucleo nunca importam a ui; o domínio da carteira nunca importa adaptadores de rede nem o banco.

O teste lê os `import` de cada arquivo (sem executá-lo), então pega a dependência errada mesmo em import tardio, dentro de função.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "ubento"


def importados(arquivo: Path) -> set[str]:
    """Módulos `ubento.*` que o arquivo importa, com os imports relativos já resolvidos."""
    pacote = ["ubento", *arquivo.relative_to(SRC).parent.parts]
    achados: set[str] = set()
    for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
        if isinstance(no, ast.ImportFrom):
            if no.level:
                base = pacote[: len(pacote) - (no.level - 1)]
                modulo = ".".join([*base, *([no.module] if no.module else [])])
                achados.add(modulo)
                achados.update(f"{modulo}.{a.name}" for a in no.names)
            elif no.module and no.module.split(".")[0] == "ubento":
                achados.add(no.module)
                achados.update(f"{no.module}.{a.name}" for a in no.names)
        elif isinstance(no, ast.Import):
            achados.update(a.name for a in no.names if a.name.split(".")[0] == "ubento")
    return achados


def arquivos(*alvos: str) -> list[Path]:
    saida: list[Path] = []
    for alvo in alvos:
        caminho = SRC / alvo
        saida += sorted(caminho.rglob("*.py")) if caminho.is_dir() else [caminho.with_suffix(".py")]
    return saida


def quebras(origens: list[Path], proibidos: tuple[str, ...]) -> list[str]:
    erros = []
    for arquivo in origens:
        for modulo in sorted(importados(arquivo)):
            if any(modulo == p or modulo.startswith(p + ".") for p in proibidos):
                erros.append(f"{arquivo.relative_to(SRC)} importa {modulo}")
    return erros


def test_o_detector_enxerga_imports_relativos_absolutos_e_tardios():
    assert "ubento.cotacoes" in importados(SRC / "workspace.py")  # relativo de um nível `from .cotacoes import ...`
    assert "ubento.ui.settings" in importados(SRC / "ui" / "agent_page.py")  # relativo `from .settings import ...`
    assert "ubento.conexoes" in importados(SRC / "ui" / "settings.py")  # relativo de dois níveis `from ..conexoes import ...`
    assert "ubento.conexoes" in importados(SRC / "__main__.py")  # absoluto `from ubento.conexoes import ...`
    assert "ubento.ui.conexoes" in importados(SRC / "ui" / "settings.py")  # tardio: o import está dentro de uma função


def test_nucleo_persistencia_e_conexoes_nao_importam_a_interface():
    assert quebras(arquivos("nucleo", "persistencia", "conexoes"), ("ubento.ui",)) == []


def test_o_dominio_da_carteira_nao_conhece_adaptadores_de_rede_nem_o_banco():
    dominio = arquivos("store", "engine", "agent_config", "formatting", "workspace", "cotacoes", "mercado")
    assert quebras(dominio, ("ubento.conexoes", "ubento.persistencia", "ubento.ui")) == []


def test_o_sql_das_carteiras_nao_conhece_o_dominio_nem_a_interface():
    assert quebras(arquivos("persistencia"), ("ubento.ui", "ubento.store", "ubento.workspace", "ubento.engine", "ubento.carteira_serial")) == []


def test_o_nucleo_nao_conhece_o_resto_do_app():
    resto = ("ubento.ui", "ubento.conexoes", "ubento.persistencia", "ubento.store", "ubento.engine", "ubento.workspace", "ubento.metas")
    assert quebras(arquivos("nucleo"), resto) == []


def test_adaptadores_dependem_do_dominio_e_nao_o_contrario():
    assert "ubento.cotacoes" in importados(SRC / "conexoes" / "mercado.py")
