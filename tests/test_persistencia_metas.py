"""Persistência e serviço de metas: os cenários do núcleo, agora passando pelo SQLite (inclusive "reiniciando" o app)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ubento.metas import ServicoMetas
from ubento.nucleo.avaliacao.reproducao import carregar_reproducao_meta, executar_meta
from ubento.nucleo.esquema import Execucao
from ubento.persistencia import ErroDeContrato, ErroDePersistencia, ErroDeSequencia, Repositorio

CENARIOS = sorted((Path(__file__).resolve().parent.parent / "exemplos" / "avaliacao").glob("*.yaml"))


def _por_cenario(caminho: Path) -> str:
    return caminho.stem


@pytest.mark.parametrize("caminho", CENARIOS, ids=_por_cenario)
def test_cenario_pelo_banco_e_igual_ao_nucleo_puro(caminho):
    puro = executar_meta(carregar_reproducao_meta(caminho))
    servico = ServicoMetas()
    meta_id = servico.importar(caminho)
    for passo in puro:
        momento, resultado = servico.avancar(meta_id)
        assert resultado.avaliacao == passo.resultado.avaliacao
        assert resultado.eventos == passo.resultado.eventos
        assert resultado.eventos_conciliacao == passo.resultado.eventos_conciliacao
        assert resultado.progresso == passo.resultado.progresso
    assert servico.avancar(meta_id) is None
    # o que foi gravado é a história inteira, na ordem
    assert servico.repo.eventos(meta_id) == [e for p in puro for e in p.resultado.eventos]
    assert servico.repo.razao(meta_id) == [e for p in puro for e in p.resultado.eventos_conciliacao]
    assert servico.painel(meta_id).estado is puro[-1].resultado.estado


@pytest.mark.parametrize("caminho", CENARIOS[::4], ids=_por_cenario)
def test_reiniciar_o_app_no_meio_nao_muda_nada(caminho, tmp_path):
    puro = executar_meta(carregar_reproducao_meta(caminho))
    db = tmp_path / "ubento.db"
    servico = ServicoMetas(Repositorio(db))
    meta_id = servico.importar(caminho)
    metade = max(1, len(puro) // 2)
    for _ in range(metade):
        servico.avancar(meta_id)
    servico.repo.fechar()  # "fecha o app"

    servico = ServicoMetas(Repositorio(db))  # "abre de novo"
    assert servico.painel(meta_id).proximo_momento == metade
    for _ in puro[metade:]:
        servico.avancar(meta_id)
    assert servico.repo.eventos(meta_id) == [e for p in puro for e in p.resultado.eventos]
    assert servico.repo.razao(meta_id) == [e for p in puro for e in p.resultado.eventos_conciliacao]
    assert servico.painel(meta_id).estado is puro[-1].resultado.estado


def test_reavaliar_e_importar_de_novo_nao_duplica():
    caminho = CENARIOS[0]
    servico = ServicoMetas()
    meta_id = servico.importar(caminho)
    momento, _ = servico.avancar(meta_id)
    antes = (servico.repo.eventos(meta_id), servico.repo.razao(meta_id))
    novo = servico.avaliar(meta_id, momento.agora, momento.ocultar)  # mesmo momento, mesmas entradas
    assert not novo.eventos and not novo.eventos_conciliacao  # nenhum evento novo
    assert servico.importar(caminho) == meta_id  # reimportar é idempotente
    assert (servico.repo.eventos(meta_id), servico.repo.razao(meta_id)) == antes
    n_execucoes = len(servico.repo.entradas(meta_id, "execucoes", Execucao))
    servico.importar(caminho)
    assert len(servico.repo.entradas(meta_id, "execucoes", Execucao)) == n_execucoes  # entradas também não duplicam
    assert servico.painel(meta_id).proximo_momento == 1  # reimportar não zera o cursor


def test_historico_e_append_only_no_banco():
    servico = ServicoMetas()
    meta_id = servico.importar(CENARIOS[0])
    servico.avancar(meta_id)
    con = servico.repo.con
    for tabela in ("metas", "eventos", "razao", "avaliacoes", "entradas"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            con.execute(f"DELETE FROM {tabela}")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        con.execute("UPDATE eventos SET tipo = 'cancelada'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        con.execute("UPDATE metas SET contrato_hash = 'x'")


def test_contrato_ativo_e_imutavel():
    arquivo = carregar_reproducao_meta(CENARIOS[0])
    servico = ServicoMetas()
    servico.importar(arquivo)
    outro = arquivo.model_copy(update={"meta": arquivo.meta.model_copy(update={"objetivo": arquivo.meta.objetivo.model_copy(update={"quantidade_alvo": 999})})})
    with pytest.raises(ErroDeContrato):
        servico.importar(outro)


def test_gravar_recusa_sequencia_que_nao_continua_a_historia():
    servico = ServicoMetas()
    meta_id = servico.importar(CENARIOS[0])
    _, resultado = servico.avancar(meta_id)
    with pytest.raises(ErroDeSequencia):  # regravar eventos já gravados (sequência repetida)
        servico.repo.gravar(meta_id, resultado)
    assert servico.repo.eventos(meta_id) == list(resultado.eventos)  # a transação não deixou lixo


def test_gravacao_e_atomica(monkeypatch):
    puro = executar_meta(carregar_reproducao_meta(CENARIOS[0]))[0].resultado
    servico = ServicoMetas()
    meta_id = servico.importar(CENARIOS[0])

    def falha(*_a, **_k):
        raise RuntimeError("disco cheio")

    # a falha acontece DEPOIS de os eventos já terem sido inseridos: tudo precisa ser desfeito
    monkeypatch.setattr(type(puro.progresso), "model_dump_json", falha)
    with pytest.raises(RuntimeError):
        servico.repo.gravar(meta_id, puro)
    monkeypatch.undo()
    assert servico.repo.eventos(meta_id) == [] and servico.repo.razao(meta_id) == [] and servico.repo.avaliacoes(meta_id) == []
    with pytest.raises(ErroDePersistencia):
        servico.repo.gravar("outra", puro)


def test_banco_adulterado_e_detectado_na_leitura(tmp_path):
    db = tmp_path / "x.db"
    servico = ServicoMetas(Repositorio(db))
    meta_id = servico.importar(CENARIOS[0])
    con = servico.repo.con
    con.execute("DROP TRIGGER metas_sem_update")
    con.execute("UPDATE metas SET contrato = replace(contrato, '\"quantidade_alvo\":\"', '\"quantidade_alvo\":\"9')")
    con.commit()
    with pytest.raises(Exception):  # hash não confere (ou contrato deixa de validar)
        servico.repo.carregar_meta(meta_id)


def test_painel_traz_as_quatro_grandezas_separadas():
    servico = ServicoMetas()
    meta_id = servico.importar(CENARIOS[0], agente_id="ag1")
    assert servico.painel(meta_id).estado is None and servico.painel(meta_id).pode_avancar
    servico.avancar(meta_id)
    painel = servico.painel(meta_id)
    p = painel.progresso
    assert painel.agente_id == "ag1" and servico.metas("ag1") == [meta_id] and servico.metas("outro") == []
    assert p.quantidade_comprovada >= 0 and p.completude is not None and p.orcamento is not None and p.elegibilidade is not None


def test_reprocessar_apos_reiniciar_nao_duplica_nada(tmp_path):
    caminho = next(c for c in CENARIOS if c.stem.startswith("09_"))  # tem estorno: história rica
    db = tmp_path / "ubento.db"
    servico = ServicoMetas(Repositorio(db))
    meta_id = servico.importar(caminho)
    while (passo := servico.avancar(meta_id)) is not None:
        ultimo = passo[0]
    antes = (servico.repo.eventos(meta_id), servico.repo.razao(meta_id), servico.painel(meta_id).estado, servico.painel(meta_id).progresso)
    servico.repo.fechar()

    servico = ServicoMetas(Repositorio(db))
    assert (servico.repo.eventos(meta_id), servico.repo.razao(meta_id), servico.painel(meta_id).estado, servico.painel(meta_id).progresso) == antes
    for _ in range(2):  # reprocessa os MESMOS dados, e reimporta o mesmo arquivo, depois de reiniciar
        resultado = servico.avaliar(meta_id, ultimo.agora, ultimo.ocultar)
        assert not resultado.eventos and not resultado.eventos_conciliacao
        servico.importar(caminho)
    assert (servico.repo.eventos(meta_id), servico.repo.razao(meta_id)) == antes[:2]
    assert servico.painel(meta_id).estado is antes[2]


def test_execucao_registrada_manualmente_nao_vira_prova_externa():
    """Registrar uma execução (confirmação interna) NÃO a transforma em evidência conciliada: sem registro externo, não há progresso comprovado."""
    original = carregar_reproducao_meta(next(c for c in CENARIOS if c.stem.startswith("01_")))
    execucao = original.execucoes[0]
    vazio = original.model_copy(update={"execucoes": (), "registros_externos": (), "coberturas_execucoes": ()})
    servico = ServicoMetas()
    meta_id = servico.importar(vazio)
    ultimo = vazio.momentos[-1]
    assert servico.avaliar(meta_id, ultimo.agora).progresso.quantidade_comprovada == 0

    servico.registrar_execucao(meta_id, execucao)
    servico.registrar_execucao(meta_id, execucao)  # clique repetido: mesma execução, nenhuma entrada nova
    assert len(servico.repo.entradas(meta_id, "execucoes", Execucao)) == 1
    resultado = servico.avaliar(meta_id, ultimo.agora)
    p = resultado.progresso
    assert p.quantidade_comprovada == 0  # confirmação manual != comprovação
    assert p.quantidade_pendente > 0  # aparece como declarada e ainda não comprovada
    assert not any(e.tipo.value == "execucao_conciliada" for e in resultado.eventos_conciliacao)
    assert resultado.estado.value != "atingida"
