from datetime import timedelta
from decimal import Decimal

import pytest

from ubento.nucleo.conciliacao import Confirmacao, Motivo, PoliticaConciliacao, StatusConciliacao, VinculoManual
from ubento.nucleo.esquema import Execucao

from .fabrica import AGORA, BASE, FONTE, META, POLITICA, comprovado, d, execucao, externo, rodar, status

C = StatusConciliacao


# -- identificador estável: preço, horário e quantidade nunca criam elo ------------------------------------------------------


def test_correspondencia_perfeita_sem_identificador_nao_concilia():
    """Mesmo ativo, lado, quantidade, preço e horário idênticos: ainda assim exige identificador."""
    r = rodar([execucao(refs=())], [externo()])
    e = status(r, "ex-1")
    assert e.status is C.REVISAO and Motivo.SEM_IDENTIFICADOR_EXTERNO in e.motivos
    assert [c.id_externo for c in e.candidatos] == ["fill-001"]  # sugerido, mas não vinculado
    assert comprovado(r) == 0 and e.efeito_no_progresso == 0
    assert [o.id_externo for o in r.orfaos] == ["fill-001"]  # o registro continua sem dono


def test_identificador_prevalece_sobre_um_candidato_melhor():
    """A referência aponta para fill-002 (que diverge); fill-001 seria perfeito por preço/horário, mas não é usado."""
    r = rodar([execucao(refs=("fill-002",))], [externo("fill-001"), externo("fill-002", preco="9.9", minutos=30)])
    assert status(r, "ex-1").status is C.DIVERGENTE


def test_vinculo_manual_resolve_e_so_depois_de_existir():
    vinculo = VinculoManual(execucao_id="ex-1", fonte_id=FONTE, id_externo="fill-001", autor="Pessoa", justificativa="Conferido no extrato da corretora.",
                            em=BASE + timedelta(hours=1))
    antes = rodar([execucao(refs=())], [externo()], vinculos=[vinculo], agora=BASE + timedelta(minutes=30))
    depois = rodar([execucao(refs=())], [externo()], vinculos=[vinculo], agora=BASE + timedelta(hours=2))
    assert status(antes, "ex-1").status is C.REVISAO
    assert status(depois, "ex-1").status is C.CONCILIADA and comprovado(depois) == d("9.95")


def test_candidatos_respeitam_ativo_lado_e_janela():
    longe = externo("fill-longe", minutos=30)
    outro_ativo = externo("fill-outro", ativo_id="abc")
    r = rodar([execucao(refs=())], [longe, outro_ativo])
    assert status(r, "ex-1").candidatos == ()


# -- taxas ---------------------------------------------------------------------------------------------------------------------------


def test_taxa_no_ativo_recebido_reduz_a_quantidade_acumulada():
    r = rodar([execucao(bruta="100", taxa="0.1")], [externo(qtd="100", taxas=(("tokx", "0.1"),))])
    assert comprovado(r) == d("99.9")


def test_taxa_em_outro_ativo_nao_subtrai_unidades_e_vira_custo():
    e = execucao(bruta="100", taxa="0.1", taxa_na_cotacao="5", moeda_cotacao_id="usd", taxas_outros_ativos=[{"ativo_id": "bnb", "valor": "0.002"}])
    x = externo(qtd="100", taxas=(("tokx", "0.1"), ("usd", "5"), ("bnb", "0.002")))
    r = rodar([e], [x])
    assert status(r, "ex-1").status is C.CONCILIADA
    assert comprovado(r) == d("99.9")  # 0,002 BNB não tirou unidade nenhuma de TOKX
    custos = {c.ativo_id: c.valor for c in r.progresso[0].custos}
    assert custos == {"usd": d("5"), "bnb": d("0.002")}  # cada ativo na sua moeda, sem conversão


def test_taxa_em_outro_ativo_nao_registrada_internamente_diverge():
    r = rodar([execucao()], [externo(taxas=(("tokx", "0.05"), ("bnb", "0.002")))])
    e = status(r, "ex-1")
    assert e.status is C.DIVERGENTE and Motivo.TAXA_OUTRO_ATIVO_NAO_REGISTRADA in e.motivos
    assert comprovado(r) == 0


def test_taxa_em_outro_ativo_com_valor_diferente_diverge():
    e = execucao(taxas_outros_ativos=[{"ativo_id": "bnb", "valor": "0.003"}])
    r = rodar([e], [externo(taxas=(("tokx", "0.05"), ("bnb", "0.002")))])
    assert Motivo.TAXA_OUTRO_ATIVO_DIFERENTE in status(r, "ex-1").motivos


def test_taxa_na_cotacao_diferente_diverge():
    e = execucao(taxa_na_cotacao="5", moeda_cotacao_id="usd")
    r = rodar([e], [externo(taxas=(("tokx", "0.05"), ("usd", "5.01")))])
    assert Motivo.TAXA_NA_COTACAO_DIFERENTE in status(r, "ex-1").motivos


def test_taxa_no_ativo_nao_pode_ser_confundida_com_taxa_em_outro_ativo():
    """Fonte cobra 0,05 em BNB; o interno registrou 0,05 TOKX. Unidades de ativos diferentes não se compensam."""
    r = rodar([execucao(taxa="0.05")], [externo(taxas=(("bnb", "0.05"),))])
    e = status(r, "ex-1")
    assert e.status is C.DIVERGENTE
    assert Motivo.TAXA_NO_ATIVO_DIFERENTE in e.motivos and Motivo.TAXA_OUTRO_ATIVO_NAO_REGISTRADA in e.motivos


def test_quantidade_liquida_e_o_que_a_fonte_realmente_entregou():
    """Interno achou que a taxa era 0,05, a fonte cobrou 0,10: o líquido recebido é 9,90, não 9,95."""
    r = rodar([execucao(taxa="0.05")], [externo(taxas=(("tokx", "0.10"),))])
    e = status(r, "ex-1")
    assert e.status is C.DIVERGENTE and ("quantidade_liquida", "9.95", "9.9") in [(x.campo, x.interno, x.externo) for x in e.diferencas]


# -- execuções parciais -----------------------------------------------------------------------------------------------------------


def test_parciais_individuais_somam():
    execs = [execucao(f"ex-{i}", bruta=q, taxa=t, preco=p, refs=(f"fill-{i}",), minutos=i)
             for i, (q, t, p) in enumerate([("4", "0.02", "10"), ("3", "0.015", "9.9"), ("3", "0.015", "9.8")], 1)]
    exts = [externo(f"fill-{i}", qtd=q, taxas=(("tokx", t),), preco=p, minutos=i)
            for i, (q, t, p) in enumerate([("4", "0.02", "10"), ("3", "0.015", "9.9"), ("3", "0.015", "9.8")], 1)]
    assert comprovado(rodar(execs, exts)) == d("9.95")


def test_agregada_usa_preco_medio_ponderado_exato():
    e = execucao(bruta="10", taxa="0.05", preco="9.7", refs=("fill-a", "fill-b"))
    exts = [externo("fill-a", qtd="4", preco="10", taxas=(("tokx", "0.02"),)), externo("fill-b", qtd="6", preco="9.5", taxas=(("tokx", "0.03"),))]
    assert status(rodar([e], exts), "ex-1").status is C.CONCILIADA
    errado = execucao(bruta="10", taxa="0.05", preco="9.75", refs=("fill-a", "fill-b"))
    assert Motivo.PRECO_DIFERENTE in status(rodar([errado], exts), "ex-1").motivos


def test_agregada_com_um_preenchimento_faltando_nao_concilia():
    e = execucao(bruta="10", taxa="0.05", preco="9.7", refs=("fill-a", "fill-b"))
    r = rodar([e], [externo("fill-a", qtd="4", preco="10", taxas=(("tokx", "0.02"),))], agora=BASE + timedelta(minutes=30))
    assert status(r, "ex-1").status is C.PENDENTE  # dentro da janela de atraso
    r2 = rodar([e], [externo("fill-a", qtd="4", preco="10", taxas=(("tokx", "0.02"),))], agora=BASE + timedelta(hours=5))
    assert status(r2, "ex-1").status is C.SEM_REGISTRO_EXTERNO


def test_registro_com_preenchimento_nao_contabilizado_aparece_como_orfao():
    r = rodar([execucao(bruta="4", taxa="0.02", refs=("fill-1",))], [externo("fill-1", qtd="4", taxas=(("tokx", "0.02"),)), externo("fill-2", qtd="6", taxas=(("tokx", "0.03"),))])
    assert [o.id_externo for o in r.orfaos] == ["fill-2"] and r.confirmacao is Confirmacao.INCOMPLETA


def test_quantidade_bruta_diferente_da_soma_das_alocacoes():
    r = rodar([execucao(bruta="9")], [externo()])
    assert Motivo.QUANTIDADE_BRUTA_DIFERENTE in status(r, "ex-1").motivos


# -- duplicidade --------------------------------------------------------------------------------------------------------------------------


def test_duplicata_interna_identica_nao_duplica_progresso():
    r = rodar([execucao(), execucao(), execucao()], [externo()])
    assert comprovado(r) == d("9.95") and len(r.execucoes) == 1
    assert Motivo.DUPLICATA_IDENTICA in status(r, "ex-1").motivos


def test_duplicata_externa_identica_nao_duplica():
    r = rodar([execucao()], [externo(), externo(), externo()])
    assert comprovado(r) == d("9.95") and r.orfaos == ()


def test_duplicata_interna_conflitante_sai_do_calculo():
    r = rodar([execucao(), execucao(bruta="11")], [externo()])
    e = status(r, "ex-1")
    assert e.status is C.REVISAO and Motivo.ID_INTERNO_DUPLICADO_CONTEUDO_DIFERENTE in e.motivos
    assert comprovado(r) == 0 and r.orfaos == ()  # o registro externo tem "dono" (em revisão)


def test_versao_externa_conflitante_vai_para_revisao():
    r = rodar([execucao()], [externo(), externo(taxas=(("tokx", "0.06"),))])
    assert status(r, "ex-1").status is C.REVISAO and Motivo.VERSAO_EXTERNA_CONFLITANTE in status(r, "ex-1").motivos


def test_vale_a_maior_versao_independente_da_ordem_de_chegada():
    nova = externo(versao=2, taxas=(("tokx", "0.05"),), recebido_min=1)
    velha = externo(versao=1, taxas=(("tokx", "0.99"),), recebido_min=10)  # chegou DEPOIS, mas é a versão antiga
    r = rodar([execucao()], [nova, velha])
    assert status(r, "ex-1").status is C.CONCILIADA and Motivo.CORRIGIDO_EXTERNAMENTE in status(r, "ex-1").motivos


# -- visibilidade temporal e atraso ----------------------------------------------------------------------------------------------------


def test_registro_externo_futuro_nao_existe_ainda():
    cedo = BASE + timedelta(minutes=30)
    r = rodar([execucao()], [externo(recebido_min=600)], agora=cedo)
    assert status(r, "ex-1").status is C.PENDENTE and r.orfaos == ()  # ainda dentro da janela de atraso
    depois = rodar([execucao()], [externo(recebido_min=600)], agora=BASE + timedelta(hours=3))
    assert status(depois, "ex-1").status is C.SEM_REGISTRO_EXTERNO  # passou da janela e o registro continua "no futuro"


def test_execucao_confirmada_depois_de_agora_nao_entra():
    r = rodar([execucao(minutos=600)], [externo()])
    assert r.execucoes == ()


def test_registro_externo_pendente_nao_comprova():
    r = rodar([execucao()], [externo(status="pendente")])
    assert status(r, "ex-1").status is C.PENDENTE and Motivo.REGISTRO_EXTERNO_PENDENTE in status(r, "ex-1").motivos and comprovado(r) == 0


def test_cancelamento_externo_remove_o_credito():
    r = rodar([execucao()], [externo(), externo(versao=2, status="cancelado", recebido_min=5)])
    assert status(r, "ex-1").status is C.DIVERGENTE and Motivo.CANCELADO_EXTERNAMENTE in status(r, "ex-1").motivos and comprovado(r) == 0


def test_orfao_cancelado_e_ignorado():
    r = rodar([execucao()], [externo(), externo("fill-x", status="cancelado")])
    assert r.orfaos == ()


# -- tolerâncias explícitas -------------------------------------------------------------------------------------------------------------------


def test_tolerancia_de_preco_e_explicita():
    e, x = execucao(preco="9.50"), externo(preco="9.51")
    assert status(rodar([e], [x]), "ex-1").status is C.DIVERGENTE
    frouxa = POLITICA.model_copy(update={"tolerancia_preco_relativa": Decimal("0.002")})
    assert status(rodar([e], [x], politica=frouxa), "ex-1").status is C.CONCILIADA


def test_tolerancia_de_quantidade_e_por_ativo():
    e, x = execucao(bruta="10.00000001", taxa="0.05"), externo()
    assert status(rodar([e], [x]), "ex-1").status is C.DIVERGENTE
    politica = PoliticaConciliacao(janela_atraso_segundos=3600, tolerancia_horario_segundos=60, tolerancias_quantidade={"tokx": Decimal("0.00000002")})
    assert status(rodar([e], [x], politica=politica), "ex-1").status is C.CONCILIADA


def test_horario_fora_da_tolerancia():
    r = rodar([execucao(minutos=5)], [externo()])
    assert Motivo.HORARIO_FORA_DA_TOLERANCIA in status(r, "ex-1").motivos


@pytest.mark.parametrize("campo, valor, motivo", [
    ("ativo_id", "abc", Motivo.ATIVO_DIFERENTE),
    ("moeda_cotacao_id", "eur", Motivo.MOEDA_COTACAO_DIFERENTE),
])
def test_campos_de_identidade_divergentes(campo, valor, motivo):
    e = execucao(moeda_cotacao_id="usd")
    r = rodar([e], [externo(**{campo: valor})])
    assert motivo in status(r, "ex-1").motivos


# -- alocação e metas ----------------------------------------------------------------------------------------------------------------------------


def test_registro_inteiro_em_duas_metas_nao_credita_nenhuma():
    r = rodar([execucao("ex-a", meta="meta-a"), execucao("ex-b", meta="meta-b")], [externo()])
    assert {status(r, i).status for i in ("ex-a", "ex-b")} == {C.REVISAO}
    assert Motivo.REGISTRO_EXTERNO_EM_METAS_DIFERENTES in status(r, "ex-a").motivos
    assert comprovado(r, "meta-a") == 0 and comprovado(r, "meta-b") == 0


def test_registro_inteiro_em_duas_execucoes_da_mesma_meta():
    r = rodar([execucao("ex-a"), execucao("ex-b")], [externo()])
    assert Motivo.REGISTRO_EXTERNO_EM_VARIAS_EXECUCOES in status(r, "ex-a").motivos and comprovado(r) == 0


def test_alocacao_parcial_entre_metas_rateia_a_taxa():
    ref = lambda q: [{"fonte_id": FONTE, "id_externo": "fill-001", "quantidade_bruta_alocada": q}]  # noqa: E731
    a = execucao("ex-a", meta="meta-a", bruta="6", taxa="0.06", refs=ref("6"))
    b = execucao("ex-b", meta="meta-b", bruta="4", taxa="0.04", refs=ref("4"))
    r = rodar([a, b], [externo(taxas=(("tokx", "0.1"),))])
    assert comprovado(r, "meta-a") == d("5.94") and comprovado(r, "meta-b") == d("3.96") and r.confirmacao is Confirmacao.CONFIRMADA


def test_rateio_nao_divisivel_e_comparado_sem_arredondar():
    """Taxa 0,1 dividida em 1/3 e 2/3 não é decimal exato: a comparação é feita em racionais."""
    ref = lambda q: [{"fonte_id": FONTE, "id_externo": "fill-001", "quantidade_bruta_alocada": q}]  # noqa: E731
    a = execucao("ex-a", meta="meta-a", bruta="1", taxa="0.0333333333", refs=ref("1"))
    r = rodar([a], [externo(qtd="3", taxas=(("tokx", "0.1"),))])
    assert Motivo.TAXA_NO_ATIVO_DIFERENTE in status(r, "ex-a").motivos  # 0,0333333333 ≠ 0,1/3 exato
    politica = POLITICA.model_copy(update={"tolerancias_quantidade": {"tokx": Decimal("0.0000001")}})
    assert status(rodar([a], [externo(qtd="3", taxas=(("tokx", "0.1"),))], politica=politica), "ex-a").status is C.CONCILIADA


def test_alocacao_que_excede_o_registro():
    ref = lambda q: [{"fonte_id": FONTE, "id_externo": "fill-001", "quantidade_bruta_alocada": q}]  # noqa: E731
    r = rodar([execucao("ex-a", bruta="7", taxa="0.07", refs=ref("7")), execucao("ex-b", bruta="4", taxa="0.04", refs=ref("4"))], [externo(taxas=(("tokx", "0.1"),))])
    assert Motivo.ALOCACAO_EXCEDE_REGISTRO_EXTERNO in status(r, "ex-a").motivos and comprovado(r) == 0


# -- estornos -----------------------------------------------------------------------------------------------------------------------------------------


def _estorno(id_="ex-2", bruta="9.95", fill="fill-002", minutos=60, original="ex-1"):
    return execucao(id_, bruta=bruta, taxa="0", lado="estorno_compra", estorna_execucao_id=original, refs=(fill,), minutos=minutos)


def _ext_estorno(fill="fill-002", qtd="9.95", minutos=60, alvo="fill-001"):
    return externo(fill, qtd=qtd, taxas=(), lado="estorno_compra", estorna=alvo, minutos=minutos)


def test_estorno_compensa_sem_editar_a_original():
    r = rodar([execucao(), _estorno()], [externo(), _ext_estorno()])
    assert status(r, "ex-1").efeito_no_progresso == d("9.95") and status(r, "ex-2").efeito_no_progresso == d("-9.95")
    assert comprovado(r) == 0


def test_estorno_sem_original_e_recusado():
    r = rodar([_estorno(original="ex-nao-existe")], [_ext_estorno()])
    assert Motivo.ESTORNO_SEM_ORIGINAL in status(r, "ex-2").motivos and comprovado(r) == 0


def test_estorno_de_outra_meta():
    r = rodar([execucao(), _estorno().model_copy(update={"meta_id": "meta-outra"})], [externo(), _ext_estorno()])
    assert Motivo.ESTORNO_DE_OUTRA_META in status(r, "ex-2").motivos


def test_estorno_acima_do_original():
    r = rodar([execucao(), _estorno(bruta="10")], [externo(), _ext_estorno(qtd="10")])
    assert Motivo.ESTORNO_EXCEDE_ORIGINAL in status(r, "ex-2").motivos and comprovado(r) == d("9.95")


def test_estorno_externo_que_aponta_para_outra_compra():
    r = rodar([execucao(), _estorno()], [externo(), _ext_estorno(alvo="fill-999")])
    assert Motivo.ESTORNO_EXTERNO_APONTA_PARA_OUTRA_EXECUCAO in status(r, "ex-2").motivos


def test_estorno_nao_subtrai_de_original_nao_comprovada():
    r = rodar([execucao(preco="9.9"), _estorno()], [externo(), _ext_estorno()])
    assert status(r, "ex-1").status is C.DIVERGENTE
    assert Motivo.ESTORNO_DE_ORIGINAL_NAO_CONCILIADA in status(r, "ex-2").motivos and comprovado(r) == 0


# -- progresso e confirmação ------------------------------------------------------------------------------------------------------------------------------


def test_declarado_e_comprovado_sao_separados():
    r = rodar([execucao("ex-1"), execucao("ex-2", refs=("fill-002",), preco="9.9", minutos=10)], [externo(), externo("fill-002", minutos=10)])
    p = r.progresso[0]
    assert (p.declarado, p.comprovado, p.nao_comprovado) == (d("19.9"), d("9.95"), d("9.95"))
    assert p.confirmacao is Confirmacao.INCOMPLETA and r.confirmacao is Confirmacao.INCOMPLETA and p.por_status == {"conciliada": 1, "divergente": 1}


def test_orfao_pode_ou_nao_bloquear_conforme_a_politica():
    execs, exts = [execucao()], [externo(), externo("fill-999", qtd="5", taxas=(("tokx", "0.025"),), minutos=30)]
    assert rodar(execs, exts).confirmacao is Confirmacao.INCOMPLETA
    permissiva = POLITICA.model_copy(update={"orfaos_bloqueiam_confirmacao": False})
    assert rodar(execs, exts, politica=permissiva).confirmacao is Confirmacao.CONFIRMADA


def test_meta_sem_execucoes_nao_tem_progresso_nem_confirmacao_falsa():
    r = rodar([], [])
    assert r.progresso == () and r.execucoes == ()


def test_sem_execucao_deposito_nao_vira_progresso():
    """Um depósito externo (movimentação) não cria progresso: só execuções vinculadas contam."""
    from ubento.nucleo.conciliacao import Movimentacao

    deposito = Movimentacao(fonte_id=FONTE, id_externo="dep-1", ativo_id="tokx", tipo="deposito", quantidade="500", em=BASE, recebido_em=BASE, origem="simulado")
    r = rodar([], [], movimentacoes=[deposito])
    assert r.progresso == ()


# -- idempotência e reprodução ---------------------------------------------------------------------------------------------------------------------------------


def test_mesmas_entradas_mesmo_relatorio():
    entradas = ([execucao(), execucao("ex-2", refs=("fill-002",), minutos=10)], [externo(), externo("fill-002", minutos=10)])
    a, b = rodar(*entradas), rodar(*entradas)
    assert a == b and a.hash_saida == b.hash_saida and a.hash_entradas == b.hash_entradas


def test_ordem_das_entradas_nao_importa():
    execs = [execucao("ex-1"), execucao("ex-2", refs=("fill-002",), minutos=10), execucao("ex-3", refs=("fill-003",), minutos=20)]
    exts = [externo(), externo("fill-002", minutos=10), externo("fill-003", minutos=20)]
    assert rodar(execs, exts).hash_saida == rodar(list(reversed(execs)), list(reversed(exts))).hash_saida


def test_reprocessar_nao_acumula():
    """Rodar de novo (com os dados repetidos) nunca soma o progresso duas vezes: ele é recalculado do conjunto."""
    uma = rodar([execucao()], [externo()])
    varias = rodar([execucao()] * 5, [externo()] * 5)
    assert comprovado(uma) == comprovado(varias) == d("9.95")


def test_execucoes_do_proprio_arquivo_de_entrada_sao_imutaveis():
    e = execucao()
    antes = e.model_dump()
    rodar([e], [externo()])
    assert e.model_dump() == antes


def test_execucao_valida_os_novos_campos():
    with pytest.raises(Exception):
        execucao(taxa_na_cotacao="1")  # sem moeda_cotacao_id
    with pytest.raises(Exception):
        execucao(refs=("fill-001", "fill-001"))
    with pytest.raises(Exception):
        execucao(moeda_cotacao_id="usd", taxas_outros_ativos=[{"ativo_id": "usd", "valor": "1"}])
    assert isinstance(execucao(), Execucao)
    assert META and AGORA
