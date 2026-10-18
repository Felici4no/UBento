"""Correção auditável de vínculos manuais: revogação, substituição, exclusividade entre metas e núcleo."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from ubento.metas import COMPROVADA, REVERTIDA, ErroDeRegistro, EvidenciaExterna, ServicoMetas
from ubento.nucleo.avaliacao.reproducao import carregar_reproducao_meta
from ubento.nucleo.conciliacao import RevogacaoVinculo, VinculoManual, conciliar, id_do_vinculo, vinculos_vigentes
from ubento.nucleo.esquema import Execucao
from ubento.persistencia import Repositorio

CENARIO = Path(__file__).resolve().parent.parent / "exemplos" / "avaliacao" / "01_parcial_ate_atingir.yaml"
JUST = "Conferi o extrato da corretora: é a mesma compra."
JUST2 = "Engano meu: o registro certo é outro, vide extrato."


def base(servico=None, meta_id=None, conta=None):
    """Meta SEM execuções, com as 3 compras do cenário registradas SEM referência externa e a evidência (3 registros) já importada."""
    o = carregar_reproducao_meta(CENARIO)
    meta = o.meta
    if meta_id:
        meta = meta.model_copy(update={"id": meta_id})
    if conta:
        meta = meta.model_copy(update={"mercado": meta.mercado.model_copy(update={"conta_id": conta})})
    vazio = o.model_copy(update={"meta": meta, "execucoes": (), "registros_externos": (), "coberturas_execucoes": ()})
    servico = servico or ServicoMetas()
    mid = servico.importar(vazio)
    execs = [e.model_copy(update={"referencias_externas": (), "meta_id": mid}) for e in o.execucoes]
    for e in execs:
        servico.registrar_execucao(mid, e)
    servico.importar_evidencia(mid, EvidenciaExterna(registros_externos=o.registros_externos))
    return servico, mid, execs, o


def vincular(sv, mid, n, registro=None, autor="Lucas", just=JUST):
    return sv.vincular_manualmente(mid, f"ex-{n}", "corretora-sim", registro or f"fill-{n}", autor, just)


def situacoes(sv, mid):
    return {r.execucao.id: r.situacao for r in sv.painel(mid).execucoes}


def atingir(sv, mid):
    for n in (1, 2, 3):
        vincular(sv, mid, n)
    painel = sv.painel(mid)
    assert painel.estado.value == "atingida", painel.estado
    return painel


# -- revogação de vínculo incorreto, com a meta já atingida ----------------------------------------------------------------------


def test_revogar_vinculo_de_meta_atingida_preserva_historico_e_reabre_pelo_mecanismo_existente():
    sv, mid, execs, _ = base()
    atingida = atingir(sv, mid)
    eventos_antes, razao_antes = sv.repo.eventos(mid), sv.repo.razao(mid)
    avaliacoes_antes = sv.repo.avaliacoes(mid)
    execucoes_antes = sv.repo.entradas(mid, "execucoes", Execucao)
    vinculos_antes = sv.repo.entradas(mid, "vinculos_manuais", VinculoManual)
    assert atingida.progresso.quantidade_comprovada >= Decimal("10")

    assert sv.revogar_vinculo(mid, "ex-3", "corretora-sim", "fill-3", "Marina", JUST2) is True

    painel = sv.painel(mid)
    assert painel.estado.value != "atingida"  # a conclusão deixou de valer
    assert painel.progresso.quantidade_comprovada < Decimal("10")
    assert situacoes(sv, mid)["ex-3"] == REVERTIDA and situacoes(sv, mid)["ex-1"] == COMPROVADA
    # a história anterior continua intacta e na mesma ordem; a correção só acrescenta
    assert sv.repo.eventos(mid)[: len(eventos_antes)] == eventos_antes
    assert sv.repo.razao(mid)[: len(razao_antes)] == razao_antes
    assert sv.repo.avaliacoes(mid)[: len(avaliacoes_antes)] == avaliacoes_antes  # avaliações anteriores preservadas
    assert len(sv.repo.avaliacoes(mid)) > len(avaliacoes_antes)
    tipos_novos = [e.tipo.value for e in sv.repo.eventos(mid)[len(eventos_antes):]]
    assert "reconciliada" in tipos_novos and "atingida" in [e.tipo.value for e in eventos_antes]  # a conclusão antiga segue na história
    # não nasceu execução nem estorno; o vínculo original continua guardado
    assert sv.repo.entradas(mid, "execucoes", Execucao) == execucoes_antes
    assert sv.repo.entradas(mid, "vinculos_manuais", VinculoManual) == vinculos_antes
    (revogacao,) = sv.repo.entradas(mid, "revogacoes_vinculos", RevogacaoVinculo)
    original = next(v for v in vinculos_antes if v.execucao_id == "ex-3")
    assert (revogacao.vinculo_id, revogacao.autor, revogacao.justificativa) == (id_do_vinculo(original), "Marina", JUST2)
    assert revogacao.em > original.em and revogacao.substituido_por_id is None
    historico = next(r for r in painel.execucoes if r.execucao.id == "ex-3").historico_vinculos
    assert historico == ((original, revogacao),) and next(r for r in painel.execucoes if r.execucao.id == "ex-3").vinculo is None
    assert any(r.sem_referencia_externa for r in painel.execucoes if r.execucao.id == "ex-3")  # volta a poder receber vínculo


def test_repetir_a_revogacao_nao_duplica_nada():
    sv, mid, *_ = base()
    atingir(sv, mid)
    assert sv.revogar_vinculo(mid, "ex-3", "corretora-sim", "fill-3", "Marina", JUST2) is True
    foto = (sv.repo.eventos(mid), sv.repo.razao(mid), sv.repo.entradas(mid, "revogacoes_vinculos", RevogacaoVinculo), len(sv.repo.avaliacoes(mid)))
    for _ in range(3):
        assert sv.revogar_vinculo(mid, "ex-3", "corretora-sim", "fill-3", "Marina", JUST2) is False
    assert (sv.repo.eventos(mid), sv.repo.razao(mid), sv.repo.entradas(mid, "revogacoes_vinculos", RevogacaoVinculo), len(sv.repo.avaliacoes(mid))) == foto


def test_revogar_o_que_nao_existe_ou_nao_e_manual_e_recusado():
    sv, mid, execs, o = base()
    with pytest.raises(ErroDeRegistro, match="não há vínculo manual"):
        sv.revogar_vinculo(mid, "ex-1", "corretora-sim", "fill-1", "Marina", JUST2)
    with pytest.raises(ErroDeRegistro, match="não está registrada"):
        sv.revogar_vinculo(mid, "ex-9", "corretora-sim", "fill-1", "Marina", JUST2)
    declarada = o.execucoes[0].model_copy(update={"id": "ex-decl"})  # referência declarada no próprio registro: não é vínculo manual
    sv.registrar_execucao(mid, declarada.model_copy(update={"referencias_externas": (), "id": "ex-0"}))
    with pytest.raises(ErroDeRegistro):
        sv.revogar_vinculo(mid, "ex-0", "corretora-sim", "fill-1", "Marina", JUST2)
    vincular(sv, mid, 1)
    with pytest.raises(Exception):  # justificativa curta: o núcleo recusa
        sv.revogar_vinculo(mid, "ex-1", "corretora-sim", "fill-1", "Marina", "curta")
    assert sv.repo.entradas(mid, "revogacoes_vinculos", RevogacaoVinculo) == []


def test_relinkar_depois_de_revogar_vale_de_novo_e_o_historico_mostra_os_dois():
    sv, mid, *_ = base()
    vincular(sv, mid, 1)
    assert situacoes(sv, mid)["ex-1"] == COMPROVADA
    sv.revogar_vinculo(mid, "ex-1", "corretora-sim", "fill-1", "Marina", JUST2)
    assert situacoes(sv, mid)["ex-1"] == REVERTIDA
    assert vincular(sv, mid, 1, autor="Marina", just="Revisei de novo e o registro estava certo, afinal.") is True
    painel = sv.painel(mid)
    execucao = next(r for r in painel.execucoes if r.execucao.id == "ex-1")
    assert execucao.situacao == COMPROVADA and execucao.vinculo.autor == "Marina"
    assert [rv is not None for _, rv in execucao.historico_vinculos] == [True, False]  # o primeiro revogado, o segundo vigente


# -- substituição -------------------------------------------------------------------------------------------------------------


def test_vinculo_incorreto_nao_comprova_e_a_substituicao_corrige_com_trilha():
    sv, mid, *_ = base()
    # ex-1 (4 tokx) ligada por engano ao registro de OUTRA compra: a conciliação confere os dados e não comprova
    vincular(sv, mid, 1, registro="fill-3")
    assert situacoes(sv, mid)["ex-1"] != COMPROVADA and sv.painel(mid).progresso.quantidade_comprovada == 0
    errado = next(r for r in sv.painel(mid).execucoes if r.execucao.id == "ex-1").vinculo
    eventos_antes = sv.repo.eventos(mid)

    assert sv.substituir_vinculo(mid, "ex-1", "corretora-sim", "fill-3", "corretora-sim", "fill-1", "Marina", JUST2) is True

    painel = sv.painel(mid)
    ex1 = next(r for r in painel.execucoes if r.execucao.id == "ex-1")
    assert ex1.situacao == COMPROVADA and painel.progresso.quantidade_comprovada == Decimal("3.98")
    (revogacao,) = sv.repo.entradas(mid, "revogacoes_vinculos", RevogacaoVinculo)
    assert revogacao.vinculo_id == id_do_vinculo(errado) and revogacao.substituido_por_id == id_do_vinculo(ex1.vinculo)
    assert revogacao.em == ex1.vinculo.em and revogacao.autor == "Marina"
    assert [(v.id_externo, rv is not None) for v, rv in ex1.historico_vinculos] == [("fill-3", True), ("fill-1", False)]
    assert sv.repo.eventos(mid)[: len(eventos_antes)] == eventos_antes
    # repetir a mesma troca não faz nada
    foto = (sv.repo.eventos(mid), len(sv.repo.avaliacoes(mid)), sv.repo.entradas(mid, "vinculos_manuais", VinculoManual))
    assert sv.substituir_vinculo(mid, "ex-1", "corretora-sim", "fill-3", "corretora-sim", "fill-1", "Marina", JUST2) is False
    assert (sv.repo.eventos(mid), len(sv.repo.avaliacoes(mid)), sv.repo.entradas(mid, "vinculos_manuais", VinculoManual)) == foto


def test_substituicao_e_atomica_e_respeita_a_exclusividade():
    sv, mid, *_ = base()
    vincular(sv, mid, 1)
    vincular(sv, mid, 2)
    with pytest.raises(ErroDeRegistro, match="já está vinculado a outra execução"):
        sv.substituir_vinculo(mid, "ex-1", "corretora-sim", "fill-1", "corretora-sim", "fill-2", "Marina", JUST2)  # fill-2 é de ex-2
    with pytest.raises(ErroDeRegistro, match="mesmo"):
        sv.substituir_vinculo(mid, "ex-1", "corretora-sim", "fill-1", "corretora-sim", "fill-1", "Marina", JUST2)
    with pytest.raises(ErroDeRegistro, match="não foi importado"):
        sv.substituir_vinculo(mid, "ex-1", "corretora-sim", "fill-1", "corretora-sim", "fill-99", "Marina", JUST2)
    assert sv.repo.entradas(mid, "revogacoes_vinculos", RevogacaoVinculo) == []  # nada foi gravado pela metade
    assert situacoes(sv, mid)["ex-1"] == COMPROVADA


def test_reiniciar_o_app_preserva_correcoes_e_reprocessar_nao_duplica(tmp_path):
    db = tmp_path / "x.db"
    sv, mid, *_ = base(ServicoMetas(Repositorio(db)))
    atingir(sv, mid)
    sv.revogar_vinculo(mid, "ex-3", "corretora-sim", "fill-3", "Marina", JUST2)
    antes = (sv.repo.eventos(mid), sv.repo.razao(mid), sv.painel(mid).progresso, sv.painel(mid).estado, sv.repo.avaliacoes(mid))
    sv.repo.fechar()

    sv = ServicoMetas(Repositorio(db))
    painel = sv.painel(mid)
    assert (sv.repo.eventos(mid), sv.repo.razao(mid), painel.progresso, painel.estado, sv.repo.avaliacoes(mid)) == antes
    ex3 = next(r for r in painel.execucoes if r.execucao.id == "ex-3")
    assert ex3.vinculo is None and ex3.historico_vinculos[0][1].autor == "Marina"
    resultado = sv.reavaliar(mid)  # reprocessar os mesmos dados depois de reiniciar
    assert not resultado.eventos and not resultado.eventos_conciliacao
    assert sv.revogar_vinculo(mid, "ex-3", "corretora-sim", "fill-3", "Marina", JUST2) is False
    assert (sv.repo.eventos(mid), sv.repo.razao(mid)) == antes[:2]
    sv.repo.fechar()


# -- exclusividade entre metas ---------------------------------------------------------------------------------------------------


def test_o_registro_externo_nao_pode_ser_contado_em_duas_metas_nem_de_contas_diferentes():
    sv, a, *_ = base()
    _, b, *_ = base(sv, meta_id="meta-b", conta="conta-outra")  # outra meta, OUTRA conta, mesmos ids de execução e mesmos registros
    vincular(sv, a, 1)
    with pytest.raises(ErroDeRegistro, match="da meta meta-tokx-001"):
        sv.vincular_manualmente(b, "ex-1", "corretora-sim", "fill-1", "Lucas", JUST)  # mesma compra, outra meta
    assert all(r.id_externo != "fill-1" for r in sv.registros_disponiveis(b))  # nem aparece como candidato
    outro = carregar_reproducao_meta(CENARIO).execucoes[0].model_copy(update={"id": "ex-decl", "meta_id": b})
    with pytest.raises(ErroDeRegistro, match="não pode ser contada duas vezes"):
        sv.registrar_execucao(b, outro)  # nem declarando a referência na hora de registrar
    sv.revogar_vinculo(a, "ex-1", "corretora-sim", "fill-1", "Marina", JUST2)  # revogado, o registro volta a ficar livre
    assert sv.vincular_manualmente(b, "ex-1", "corretora-sim", "fill-1", "Lucas", JUST) is True


def test_alocacoes_parciais_de_metas_diferentes_convivem_ate_o_limite_do_registro():
    sv, a, *_ = base()
    _, b, *_ = base(sv, meta_id="meta-b")
    o = carregar_reproducao_meta(CENARIO)
    fill1 = o.registros_externos[0]  # 4 tokx
    ref = lambda n: (o.execucoes[0].model_copy().referencias_externas[0].model_copy(update={"quantidade_bruta_alocada": Decimal(n)}),)  # noqa: E731
    base_exec = o.execucoes[0]
    sv.registrar_execucao(a, base_exec.model_copy(update={"id": "p-a", "meta_id": a, "referencias_externas": ref(2)}))
    sv.registrar_execucao(b, base_exec.model_copy(update={"id": "p-b", "meta_id": b, "referencias_externas": ref(1)}))  # 2 + 1 <= 4
    with pytest.raises(ErroDeRegistro, match="não pode ser contada duas vezes"):
        sv.registrar_execucao(b, base_exec.model_copy(update={"id": "p-c", "meta_id": b, "referencias_externas": ref(2)}))  # 2 + 1 + 2 > 4
    assert fill1.quantidade == Decimal("4")


def test_rede_de_seguranca_a_mesma_compra_em_duas_metas_importadas_vira_revisao_nas_duas():
    """Cenários importados com a MESMA referência (sem passar pelo formulário): o núcleo enxerga as duas metas juntas e não comprova nenhuma."""
    o = carregar_reproducao_meta(CENARIO)
    outro = o.model_copy(update={
        "meta": o.meta.model_copy(update={"id": "meta-b"}),
        "execucoes": tuple(e.model_copy(update={"meta_id": "meta-b"}) for e in o.execucoes),
    })
    sozinha = ServicoMetas()
    sozinha.importar(o)
    sozinha.avaliar(o.meta.id, o.momentos[-1].agora)
    assert sozinha.painel(o.meta.id).progresso.quantidade_comprovada > 0  # sozinha, a meta comprova normalmente

    sv = ServicoMetas()
    sv.importar(o)
    sv.importar(outro)
    for mid in (o.meta.id, "meta-b"):
        resultado = sv.avaliar(mid, o.momentos[-1].agora)
        assert resultado.progresso.quantidade_comprovada == 0  # nada foi contado em dobro, em nenhuma das duas
        assert not resultado.progresso.completude.completa


# -- núcleo --------------------------------------------------------------------------------------------------------------------


def test_nucleo_revogacao_vale_a_partir_do_seu_instante_e_nao_retroage():
    o = carregar_reproducao_meta(CENARIO)
    execucao = o.execucoes[0].model_copy(update={"referencias_externas": ()})
    v = VinculoManual(execucao_id="ex-1", fonte_id="corretora-sim", id_externo="fill-1", autor="Lucas", justificativa=JUST, em=execucao.confirmada_em)
    rev = RevogacaoVinculo(vinculo_id=id_do_vinculo(v), autor="Marina", justificativa=JUST2, em=v.em + timedelta(hours=1))
    antes, depois = v.em + timedelta(minutes=30), v.em + timedelta(hours=2)
    assert vinculos_vigentes([v], [rev], antes) == [v]  # reproduzir um instante anterior à correção devolve o mundo como era
    assert vinculos_vigentes([v], [rev], depois) == []
    assert vinculos_vigentes([v], [rev.model_copy(update={"em": v.em})], depois) == [v]  # revogação que não é posterior ao vínculo é ignorada
    outro = v.model_copy(update={"justificativa": JUST2})
    assert vinculos_vigentes([v, outro], [rev], depois) == [outro]  # a revogação só atinge o vínculo a que se refere (identidade por conteúdo)

    kw = dict(politica=o.politica_conciliacao, externos=o.registros_externos[:1], coberturas_execucoes=o.coberturas_execucoes)
    comprovada = conciliar([execucao], agora=depois, vinculos=[v], **kw)
    revogada = conciliar([execucao], agora=depois, vinculos=[v], revogacoes=[rev], **kw)
    assert comprovada.execucoes[0].status.value == "conciliada" and revogada.execucoes[0].status.value != "conciliada"
    assert comprovada.hash_saida == conciliar([execucao], agora=depois, vinculos=[v], revogacoes=[], **kw).hash_saida  # sem revogação, o hash é o de sempre


# -- pela interface ------------------------------------------------------------------------------------------------------------


def test_correcao_pela_interface_com_meta_atingida_e_reinicio(tmp_path):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from ubento.ui import theme
    from ubento.ui.components import ActionButton, Label
    from ubento.ui.controls import Chip
    from ubento.ui.main_window import MainWindow
    from ubento.workspace import Workspace

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme.APP_QSS)
    o = carregar_reproducao_meta(CENARIO)
    arquivo = tmp_path / "meta.json"
    arquivo.write_text(o.model_copy(update={"execucoes": (), "registros_externos": (), "coberturas_execucoes": ()}).model_dump_json(), encoding="utf-8")
    db = tmp_path / "ubento.db"

    def abrir():
        janela = MainWindow(Workspace(QSettings(str(db.with_suffix(".ini")), QSettings.Format.IniFormat)), animations=False, metas=ServicoMetas(Repositorio(db)))
        janela.show()
        app.processEvents()
        agente = janela.workspace.agents[0].id
        janela.open_metas(agente)
        return janela, janela.pages["metas:" + agente].widget()

    def textos(page):
        return "\n".join([r.text() for r in page.findChildren(Label)] + [c._text for c in page.findChildren(Chip)])

    janela, page = abrir()
    page.importar_arquivo(str(arquivo))
    mid = page.meta_id
    sv = janela.metas
    for e in o.execucoes:
        sv.registrar_execucao(mid, e.model_copy(update={"referencias_externas": ()}))
    sv.importar_evidencia(mid, EvidenciaExterna(registros_externos=o.registros_externos))
    for n in (1, 2, 3):
        vincular(sv, mid, n)
    page.refresh()
    assert sv.painel(mid).estado.value == "atingida"
    botoes = [b.text() for b in page.findChildren(ActionButton)]
    assert botoes.count("Corrigir…") == 3 and "Vincular…" not in botoes

    dialogo = page.criar_correcao("ex-3")
    assert page.criar_correcao("ex-inexistente") is None
    dialogo.definir(acao="revogar", autor="", justificativa="curta")
    assert dialogo.salvar() is False and dialogo.justificativa.toPlainText() == "curta" and not dialogo.erros.isHidden()
    dialogo.definir(acao="revogar", autor="Marina", justificativa="curta")
    assert dialogo.salvar() is False and "10 caracteres" in dialogo.erros.text()
    dialogo.definir(acao="revogar", autor="Marina", justificativa=JUST2)
    assert dialogo.salvar() is True
    assert sv.painel(mid).estado.value != "atingida"
    page.refresh()
    texto = textos(page)
    assert "revogado por Marina" in texto and "Comprovação revertida" in texto
    botoes = [b.text() for b in page.findChildren(ActionButton)]
    assert botoes.count("Corrigir…") == 2 and botoes.count("Vincular…") == 1  # ex-3 pode receber vínculo de novo
    antes = (sv.repo.eventos(mid), sv.repo.razao(mid), sv.painel(mid).progresso, sv.repo.avaliacoes(mid))

    # substituir pela interface (ex-1: troca fill-1 por fill-3, agora livre)
    sub = page.criar_correcao("ex-1")
    assert sub.registro.count() == 1 and "fill-3" in sub.registro.itemText(0)  # só o registro livre é candidato
    sub.definir(acao="substituir", autor="Marina", justificativa=JUST2)
    assert sub.salvar() is True
    assert next(r for r in sv.painel(mid).execucoes if r.execucao.id == "ex-1").vinculo.id_externo == "fill-3"
    janela.close()
    janela.metas.repo.fechar()

    # reiniciar: a trilha completa volta, e reprocessar não duplica
    janela, page = abrir()
    sv = janela.metas
    ex1 = next(r for r in sv.painel(mid).execucoes if r.execucao.id == "ex-1")
    assert [(v.id_externo, rv is not None) for v, rv in ex1.historico_vinculos] == [("fill-1", True), ("fill-3", False)]
    assert sv.repo.eventos(mid)[: len(antes[0])] == antes[0] and sv.repo.avaliacoes(mid)[: len(antes[3])] == antes[3]
    resultado = sv.reavaliar(mid)
    assert not resultado.eventos and not resultado.eventos_conciliacao
    assert "substituído por Marina" in textos(page)
    janela.close()
    janela.metas.repo.fechar()
