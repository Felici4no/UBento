"""Fluxo completo pela interface: registrar → pendente → importar evidência → comprovado → reiniciar → persistência."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from decimal import Decimal  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from ubento.metas import COMPROVADA, PENDENTE_DE_COMPROVACAO, EvidenciaExterna, ServicoMetas  # noqa: E402
from ubento.nucleo.avaliacao.reproducao import carregar_reproducao_meta  # noqa: E402
from ubento.persistencia import Repositorio  # noqa: E402
from ubento.ui import theme  # noqa: E402
from ubento.ui.components import Label  # noqa: E402
from ubento.ui.controls import Chip  # noqa: E402
from ubento.ui.main_window import MainWindow  # noqa: E402
from ubento.workspace import Workspace  # noqa: E402

CENARIO = Path(__file__).resolve().parent.parent / "exemplos" / "avaliacao" / "01_parcial_ate_atingir.yaml"


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(theme.APP_QSS)
    return a


def _valores(execucao) -> dict[str, str]:
    """Os campos do formulário que correspondem a uma execução (como o usuário digitaria)."""
    return {
        "id": execucao.id, "quantidade_bruta": format(execucao.quantidade_bruta, "f"), "taxa_no_ativo": format(execucao.taxa_no_ativo, "f"),
        "preco_executado": format(execucao.preco_executado, "f"), "executada_em": f"{execucao.executada_em:%Y-%m-%d %H:%M}",
        "confirmada_em": f"{execucao.confirmada_em:%Y-%m-%d %H:%M}", "fonte_id": execucao.fonte_id,
        "ref_fonte": execucao.referencias_externas[0].fonte_id, "ref_id": execucao.referencias_externas[0].id_externo,
    }


def _abrir(app, db: Path) -> tuple[MainWindow, str]:
    servico = ServicoMetas(Repositorio(db))
    # configurações em arquivo, como no app real: os agentes mantêm o mesmo id entre execuções
    janela = MainWindow(Workspace(QSettings(str(db.with_suffix(".ini")), QSettings.Format.IniFormat)), animations=False, metas=servico)
    janela.show()
    app.processEvents()
    return janela, janela.workspace.agents[0].id


def _textos(page) -> str:
    """Todo o texto visível: rótulos e chips (os chips são desenhados, não são QLabel)."""
    return "\n".join([r.text() for r in page.findChildren(Label)] + [c._text for c in page.findChildren(Chip)])


def test_registrar_pendente_importar_evidencia_comprovar_e_reiniciar(app, tmp_path):
    original = carregar_reproducao_meta(CENARIO)
    ex1, ex2 = original.execucoes[0], original.execucoes[1]
    # a meta nasce SEM execuções nem evidências: tudo entra pelo formulário e pela importação
    vazio = original.model_copy(update={"execucoes": (), "registros_externos": (), "coberturas_execucoes": ()})
    arquivo = tmp_path / "meta.json"
    arquivo.write_text(vazio.model_dump_json(), encoding="utf-8")
    evidencia = tmp_path / "evidencia.json"
    evidencia.write_text(EvidenciaExterna(registros_externos=original.registros_externos[:1], coberturas_execucoes=()).model_dump_json(), encoding="utf-8")
    db = tmp_path / "ubento.db"

    janela, agente = _abrir(app, db)
    janela.open_metas(agente)
    page = janela.pages["metas:" + agente].widget()
    page.importar_arquivo(str(arquivo))
    meta_id = page.meta_id
    assert janela.metas.painel(meta_id).execucoes == ()

    # 1) erros não apagam o que foi digitado
    dialogo = page.criar_formulario()
    dialogo.definir(**{**_valores(ex1), "quantidade_bruta": "abc", "executada_em": "20/10/2026"})
    assert dialogo.salvar() is False and not dialogo.erros.isHidden()
    assert dialogo.campos["quantidade_bruta"].text() == "abc" and dialogo.campos["id"].text() == ex1.id  # nada se perdeu
    dialogo.definir(quantidade_bruta="4", executada_em="2026-10-20 10:00")
    dialogo.definir(taxa_no_ativo="5")  # taxa maior que a quantidade: o núcleo recusa (líquida não positiva)
    assert dialogo.salvar() is False and not dialogo.erros.isHidden()
    assert janela.metas.painel(meta_id).execucoes == ()  # nada foi gravado
    dialogo.definir(taxa_no_ativo=format(ex1.taxa_no_ativo, "f"))
    dialogo.origem.setCurrentIndex(1)  # simulado, como nos cenários
    assert dialogo.salvar() is True

    # 2) registrada e PENDENTE; progresso comprovado continua separado e zerado
    painel = janela.metas.painel(meta_id)
    assert [(r.execucao.id, r.situacao) for r in painel.execucoes] == [(ex1.id, PENDENTE_DE_COMPROVACAO)]
    assert painel.progresso.quantidade_comprovada == 0
    assert painel.progresso.quantidade_pendente == ex1.quantidade_liquida
    texto = _textos(page)
    assert "Pendente de comprovação" in texto and "NÃO conta como progresso" in texto

    # 3) proteção contra duplicidade: reenviar o mesmo formulário e reutilizar o id com outros dados
    repetido = page.criar_formulario()
    repetido.definir(**_valores(ex1))
    repetido.origem.setCurrentIndex(1)
    assert repetido.salvar() is True and repetido.nova is False
    assert len(janela.metas.painel(meta_id).execucoes) == 1
    conflito = page.criar_formulario()
    conflito.definir(**{**_valores(ex1), "quantidade_bruta": "9"})
    conflito.origem.setCurrentIndex(1)
    assert conflito.salvar() is False and "já existe" in conflito.erros.text()
    assert conflito.campos["quantidade_bruta"].text() == "9"
    mesmo_externo = page.criar_formulario()
    mesmo_externo.definir(**{**_valores(ex2), "ref_id": ex1.referencias_externas[0].id_externo})
    mesmo_externo.origem.setCurrentIndex(1)
    assert mesmo_externo.salvar() is False and "já está vinculado" in mesmo_externo.erros.text()

    # 4) evidência correspondente → comprovada
    page.importar_evidencia_arquivo(str(evidencia))
    page.importar_evidencia_arquivo(str(evidencia))  # importar de novo não duplica
    painel = janela.metas.painel(meta_id)
    assert [(r.execucao.id, r.situacao) for r in painel.execucoes] == [(ex1.id, COMPROVADA)]
    assert painel.progresso.quantidade_comprovada == ex1.quantidade_liquida == Decimal("3.98")
    assert painel.progresso.quantidade_pendente == 0
    assert len(janela.metas.repo.entradas(meta_id, "registros_externos", type(original.registros_externos[0]))) == 1
    antes = (janela.metas.repo.eventos(meta_id), janela.metas.repo.razao(meta_id), painel.progresso, painel.estado)
    assert "Comprovada" in _textos(page)

    # 5) reiniciar: tudo volta igual e reprocessar não duplica
    janela.close()
    janela.metas.repo.fechar()
    janela2, agente2 = _abrir(app, db)
    janela2.open_metas(agente2)
    page2 = janela2.pages["metas:" + agente2].widget()
    assert page2.meta_id == meta_id
    painel2 = janela2.metas.painel(meta_id)
    assert (janela2.metas.repo.eventos(meta_id), janela2.metas.repo.razao(meta_id), painel2.progresso, painel2.estado) == antes
    assert [(r.execucao.id, r.situacao) for r in painel2.execucoes] == [(ex1.id, COMPROVADA)]
    resultado = janela2.metas.reavaliar(meta_id)
    assert not resultado.eventos and not resultado.eventos_conciliacao
    assert (janela2.metas.repo.eventos(meta_id), janela2.metas.repo.razao(meta_id)) == antes[:2]
    janela2.close()
    janela2.metas.repo.fechar()


def test_formulario_mostra_unidades_moeda_e_horario(app, tmp_path):
    janela, agente = _abrir(app, tmp_path / "x.db")
    janela.open_metas(agente)
    page = janela.pages["metas:" + agente].widget()
    page.importar_arquivo(str(CENARIO))
    dialogo = page.criar_formulario()
    rotulos = " | ".join(item.text() for item in dialogo.findChildren(QLabel))
    for esperado in ("tokx", "usd", "UTC", "Quantidade líquida", "Preço executado (usd/tokx)"):
        assert esperado in rotulos
    dialogo.definir(quantidade_bruta="4", taxa_no_ativo="0.02")
    assert "3.98" in dialogo.liquida.text()  # líquida calculada pelo sistema, nunca digitada
    janela.close()
    janela.metas.repo.fechar()
