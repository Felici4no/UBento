"""Vínculo manual posterior: execução registrada sem referência externa ligada depois a um registro externo importado."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from decimal import Decimal  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ubento.metas import COMPROVADA, PENDENTE_DE_COMPROVACAO, ErroDeRegistro, EvidenciaExterna, ServicoMetas  # noqa: E402
from ubento.nucleo.avaliacao.reproducao import carregar_reproducao_meta  # noqa: E402
from ubento.nucleo.conciliacao.modelos import VinculoManual  # noqa: E402
from ubento.nucleo.esquema import Execucao  # noqa: E402
from ubento.persistencia import Repositorio  # noqa: E402
from ubento.ui import theme  # noqa: E402
from ubento.ui.components import ActionButton  # noqa: E402
from ubento.ui.main_window import MainWindow  # noqa: E402
from ubento.workspace import Workspace  # noqa: E402

CENARIO = Path(__file__).resolve().parent.parent / "exemplos" / "avaliacao" / "01_parcial_ate_atingir.yaml"
JUSTIFICATIVA = "Conferi o extrato da corretora: é a mesma compra."


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(theme.APP_QSS)
    return a


def montar(servico: ServicoMetas | None = None, registros: int = 2):
    """Meta sem execuções; devolve (serviço, meta_id, execução SEM referência externa, evidência com `registros` registros)."""
    original = carregar_reproducao_meta(CENARIO)
    vazio = original.model_copy(update={"execucoes": (), "registros_externos": (), "coberturas_execucoes": ()})
    servico = servico or ServicoMetas()
    meta_id = servico.importar(vazio)
    sem_ref = original.execucoes[0].model_copy(update={"referencias_externas": ()})
    evidencia = EvidenciaExterna(registros_externos=original.registros_externos[:registros])
    return servico, meta_id, sem_ref, evidencia, original


def vincular(servico, meta_id, execucao_id="ex-1", id_externo="fill-1"):
    return servico.vincular_manualmente(meta_id, execucao_id, "corretora-sim", id_externo, "Lucas", JUSTIFICATIVA)


def test_vincular_depois_comprova_e_preserva_o_historico():
    servico, meta_id, sem_ref, evidencia, _ = montar()
    servico.registrar_execucao(meta_id, sem_ref)
    servico.importar_evidencia(meta_id, evidencia)
    servico.reavaliar(meta_id, evidencia.registros_externos[0].recebido_em)
    antes = servico.painel(meta_id)
    assert [(r.execucao.id, r.situacao, r.sem_referencia_externa) for r in antes.execucoes] == [("ex-1", PENDENTE_DE_COMPROVACAO, True)]
    assert antes.progresso.quantidade_comprovada == 0
    assert antes.quantidade_registrada_pendente == sem_ref.quantidade_liquida  # registrada e pendente, mesmo sem referência
    eventos_antes, razao_antes = servico.repo.eventos(meta_id), servico.repo.razao(meta_id)
    execucoes_antes = servico.repo.entradas(meta_id, "execucoes", Execucao)

    assert vincular(servico, meta_id) is True

    depois = servico.painel(meta_id)
    assert [(r.execucao.id, r.situacao) for r in depois.execucoes] == [("ex-1", COMPROVADA)]
    assert depois.progresso.quantidade_comprovada == sem_ref.quantidade_liquida
    assert depois.quantidade_registrada_pendente == 0
    # histórico preservado: o que existia continua igual e na mesma ordem; a execução NÃO foi editada
    assert servico.repo.eventos(meta_id)[: len(eventos_antes)] == eventos_antes
    assert servico.repo.razao(meta_id)[: len(razao_antes)] == razao_antes
    assert servico.repo.entradas(meta_id, "execucoes", Execucao) == execucoes_antes
    assert not servico.repo.entradas(meta_id, "execucoes", Execucao)[0].referencias_externas
    # a decisão humana ficou registrada com autor, justificativa e instante
    (vinculo,) = servico.repo.entradas(meta_id, "vinculos_manuais", VinculoManual)
    assert (vinculo.execucao_id, vinculo.id_externo, vinculo.autor, vinculo.justificativa) == ("ex-1", "fill-1", "Lucas", JUSTIFICATIVA)
    assert depois.execucoes[0].vinculo == vinculo


def test_repetir_o_vinculo_nao_duplica_nada():
    servico, meta_id, sem_ref, evidencia, _ = montar()
    servico.registrar_execucao(meta_id, sem_ref)
    servico.importar_evidencia(meta_id, evidencia)
    assert vincular(servico, meta_id) is True
    foto = (servico.repo.eventos(meta_id), servico.repo.razao(meta_id), servico.repo.entradas(meta_id, "vinculos_manuais", VinculoManual))
    for _ in range(3):
        assert vincular(servico, meta_id) is False  # clique repetido
    assert (servico.repo.eventos(meta_id), servico.repo.razao(meta_id), servico.repo.entradas(meta_id, "vinculos_manuais", VinculoManual)) == foto


def test_registro_externo_nao_pode_pertencer_a_duas_execucoes():
    servico, meta_id, sem_ref, evidencia, _ = montar()
    outra = sem_ref.model_copy(update={"id": "ex-outra"})
    servico.registrar_execucao(meta_id, sem_ref)
    servico.registrar_execucao(meta_id, outra)
    servico.importar_evidencia(meta_id, evidencia)
    assert vincular(servico, meta_id, "ex-1") is True
    with pytest.raises(ErroDeRegistro, match="já está vinculado a outra execução"):
        vincular(servico, meta_id, "ex-outra")  # mesmo registro, outra execução
    com_ref = sem_ref.model_copy(update={"id": "ex-3", "referencias_externas": evidencia_ref()})
    with pytest.raises(ErroDeRegistro, match="já está vinculado"):
        servico.registrar_execucao(meta_id, com_ref)  # nem declarando a referência na hora de registrar
    assert servico.painel(meta_id).progresso.quantidade_comprovada == sem_ref.quantidade_liquida  # a prova não foi contestada


def evidencia_ref():
    from ubento.nucleo.esquema import ReferenciaExterna

    return (ReferenciaExterna(fonte_id="corretora-sim", id_externo="fill-1"),)


def test_recusas_de_registro_inexistente_e_de_execucao_inexistente():
    servico, meta_id, sem_ref, evidencia, _ = montar()
    servico.registrar_execucao(meta_id, sem_ref)
    with pytest.raises(ErroDeRegistro, match="ainda não foi importado"):
        vincular(servico, meta_id)  # a evidência ainda não chegou
    servico.importar_evidencia(meta_id, evidencia)
    with pytest.raises(ErroDeRegistro, match="não está registrada"):
        vincular(servico, meta_id, "ex-fantasma")
    assert servico.repo.entradas(meta_id, "vinculos_manuais", VinculoManual) == []


def test_vinculo_nao_forca_comprovacao_conciliacao_ainda_confere_os_dados():
    """O vínculo diz QUAL registro corresponde. Se a quantidade não bate, a execução continua sem provar nada."""
    servico, meta_id, sem_ref, evidencia, _ = montar()
    divergente = evidencia.registros_externos[0].model_copy(update={"quantidade": Decimal("7")})
    servico.registrar_execucao(meta_id, sem_ref)
    servico.importar_evidencia(meta_id, EvidenciaExterna(registros_externos=(divergente,)))
    assert vincular(servico, meta_id) is True
    painel = servico.painel(meta_id)
    assert painel.progresso.quantidade_comprovada == 0
    assert painel.execucoes[0].situacao != COMPROVADA


def test_justificativa_curta_e_recusada_pelo_nucleo():
    servico, meta_id, sem_ref, evidencia, _ = montar()
    servico.registrar_execucao(meta_id, sem_ref)
    servico.importar_evidencia(meta_id, evidencia)
    with pytest.raises(Exception, match="at least 10|10"):
        servico.vincular_manualmente(meta_id, "ex-1", "corretora-sim", "fill-1", "Lucas", "curta")
    assert servico.repo.entradas(meta_id, "vinculos_manuais", VinculoManual) == []


# -- pela interface ------------------------------------------------------------------------------------------------------


def _abrir(app, db: Path):
    janela = MainWindow(Workspace(QSettings(str(db.with_suffix(".ini")), QSettings.Format.IniFormat)), animations=False,
                        metas=ServicoMetas(Repositorio(db)))
    janela.show()
    app.processEvents()
    return janela, janela.workspace.agents[0].id


def test_fluxo_pela_interface_vincular_comprovar_e_reiniciar(app, tmp_path):
    original = carregar_reproducao_meta(CENARIO)
    arquivo = tmp_path / "meta.json"
    arquivo.write_text(original.model_copy(update={"execucoes": (), "registros_externos": (), "coberturas_execucoes": ()}).model_dump_json(), encoding="utf-8")
    evidencia = EvidenciaExterna(registros_externos=original.registros_externos[:1])
    liquida = original.execucoes[0].quantidade_liquida
    db = tmp_path / "ubento.db"
    janela, agente = _abrir(app, db)
    janela.open_metas(agente)
    page = janela.pages["metas:" + agente].widget()
    page.importar_arquivo(str(arquivo))
    meta_id = page.meta_id

    # registra SEM referência externa pelo formulário
    form = page.criar_formulario()
    form.definir(id="ex-1", quantidade_bruta="4", taxa_no_ativo="0.02", preco_executado="9.5", executada_em="2026-10-20 10:00",
                 confirmada_em="2026-10-20 10:01")
    form.origem.setCurrentIndex(1)
    assert form.salvar() is True
    evid = tmp_path / "evidencia.json"
    evid.write_text(evidencia.model_dump_json(), encoding="utf-8")
    page.importar_evidencia_arquivo(str(evid))
    assert janela.metas.painel(meta_id).progresso.quantidade_comprovada == 0
    botoes = [b.text() for b in page.findChildren(ActionButton)]
    assert "Vincular…" in botoes  # o botão aparece para a execução pendente e sem referência

    # diálogo: erros mantêm o preenchido; depois vincula
    dialogo = page.criar_vinculo("ex-1")
    assert dialogo.registro.count() == 1 and "fill-1" in dialogo.registro.itemText(0)
    dialogo.definir(autor="", justificativa="curta")
    assert dialogo.salvar() is False and not dialogo.erros.isHidden() and dialogo.justificativa.toPlainText() == "curta"
    dialogo.definir(autor="Lucas", justificativa="curta")
    assert dialogo.salvar() is False and "10 caracteres" in dialogo.erros.text()
    dialogo.definir(autor="Lucas", justificativa=JUSTIFICATIVA)
    assert dialogo.salvar() is True
    painel = janela.metas.painel(meta_id)
    assert painel.progresso.quantidade_comprovada == liquida
    assert [r.situacao for r in painel.execucoes] == [COMPROVADA]
    assert "Vincular…" not in [b.text() for b in page.findChildren(ActionButton)]
    assert page.criar_vinculo("ex-1").registro.count() == 0  # nenhum candidato sobrando
    antes = (janela.metas.repo.eventos(meta_id), janela.metas.repo.razao(meta_id), painel.progresso)

    # reiniciar: tudo igual e reprocessar não duplica
    janela.close()
    janela.metas.repo.fechar()
    janela, agente = _abrir(app, db)
    painel = janela.metas.painel(meta_id)
    assert (janela.metas.repo.eventos(meta_id), janela.metas.repo.razao(meta_id), painel.progresso) == antes
    assert painel.execucoes[0].vinculo is not None and painel.execucoes[0].vinculo.autor == "Lucas"
    resultado = janela.metas.reavaliar(meta_id)
    assert not resultado.eventos and not resultado.eventos_conciliacao
    janela.close()
    janela.metas.repo.fechar()
