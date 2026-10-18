"""Conexões com corretoras: verificação somente leitura, cofre de segredos e garantia de que segredo nenhum vaza."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import sys
import urllib.parse
from pathlib import Path

import pytest

from ubento.conexoes import (
    CONECTADA, ERRO, REPROVADA, CofreMemoria, ErroDeConexao, ErroDeConfiguracao, ServicoConexoes, cofre_padrao,
)
from ubento.conexoes.cofre import CofreDpapi, CofreIndisponivel
from ubento.persistencia import Repositorio

CHAVE = "AbCdEfGh1234567890IjKlMnOpQrStUv"
SEGREDO = "ZyXwVuTs0987654321QpOnMlKjIhGfEd"
LEITURA = {"enableReading": True, "ipRestrict": True, "createTime": 1700000000000}


class Rede:
    """Transporte falso: devolve o que o teste mandar e guarda o que foi pedido (nunca toca a rede)."""

    def __init__(self, resposta=(200, LEITURA)):
        self.resposta, self.pedidos = resposta, []

    def __call__(self, url, cabecalhos, tempo_limite):
        self.pedidos.append((url, cabecalhos))
        if isinstance(self.resposta, Exception):
            raise self.resposta
        status, corpo = self.resposta
        return status, json.dumps(corpo).encode()


def servico(rede=None, cofre=None, repo=None):
    return ServicoConexoes(repo or Repositorio(), cofre or CofreMemoria(), rede or Rede())


def conectar(sv, **extra):
    return sv.adicionar("binance", "Minha Binance", {"api_key": CHAVE, "api_secret": SEGREDO, **extra})


# -- conexão válida: assinatura, cofre e banco ---------------------------------------------------------------------------------------


def test_chave_somente_leitura_conecta_assina_o_pedido_e_guarda_o_segredo_so_no_cofre(tmp_path):
    rede, cofre = Rede(), CofreMemoria()
    db = tmp_path / "x.db"
    sv = servico(rede, cofre, Repositorio(db))
    c = conectar(sv)
    assert (c.provedor, c.apelido, c.status, c.chave_mascarada, c.nome_provedor) == ("binance", "Minha Binance", CONECTADA, "AbCd…StUv", "Binance")
    assert c.permissoes["enableReading"] is True and c.permissoes["enableWithdrawals"] is False
    # o pedido é assinado com HMAC-SHA256 do segredo, leva a chave no cabeçalho e NÃO leva o segredo
    (url, cabecalhos), = rede.pedidos
    partes = urllib.parse.urlsplit(url)
    consulta = dict(urllib.parse.parse_qsl(partes.query))
    base = urllib.parse.urlencode({k: v for k, v in consulta.items() if k != "signature"})
    assert partes.path == "/sapi/v1/account/apiRestrictions" and cabecalhos == {"X-MBX-APIKEY": CHAVE}
    assert consulta["signature"] == hmac.new(SEGREDO.encode(), base.encode(), hashlib.sha256).hexdigest() and SEGREDO not in url
    # segredo e chave estão no cofre; o banco só tem o trecho mascarado e uma impressão
    assert cofre.ler(f"conexao:{c.id}:api_key") == CHAVE and cofre.ler(f"conexao:{c.id}:api_secret") == SEGREDO
    sv.repo.fechar()
    bruto = db.read_bytes() + b"".join(p.read_bytes() for p in tmp_path.glob("x.db-*"))
    assert CHAVE.encode() not in bruto and SEGREDO.encode() not in bruto  # nem no arquivo do banco, nem no WAL


@pytest.mark.parametrize("poder,nome", [
    ("enableWithdrawals", "saques"), ("enableSpotAndMarginTrading", "negociação"), ("enableFutures", "futuros"),
    ("enableInternalTransfer", "transferências internas"), ("permitsUniversalTransfer", "transferência universal"),
])
def test_chave_com_qualquer_poder_alem_da_leitura_e_recusada_e_nada_e_gravado(poder, nome):
    cofre = CofreMemoria()
    sv = servico(Rede((200, {**LEITURA, poder: True})), cofre)
    with pytest.raises(ErroDeConfiguracao, match=nome):
        conectar(sv)
    assert sv.listar() == [] and cofre._dados == {}  # nem linha no banco, nem segredo no cofre


def test_chave_sem_permissao_de_leitura_e_recusada():
    sv = servico(Rede((200, {"enableReading": False})))
    with pytest.raises(ErroDeConfiguracao, match="leitura"):
        conectar(sv)
    assert sv.listar() == []


# -- erros da corretora, de rede e de formato ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("resposta,trecho", [
    ((401, {"code": -2015, "msg": "Invalid API-key, IP, or permissions for action."}), "recusou a chave"),
    ((400, {"code": -1022, "msg": "Signature for this request is not valid."}), "assinatura"),
    ((400, {"code": -1021, "msg": "Timestamp for this request is outside of the recvWindow."}), "relógio"),
    ((400, {"code": -2014, "msg": "API-key format invalid."}), "formato"),
    ((429, {"code": -1003, "msg": "Too many requests"}), "limitou"),
    ((503, {}), "indisponível"),
    ((400, {"code": -9999, "msg": "algo novo"}), "recusou o pedido"),
])
def test_erros_da_binance_viram_mensagens_claras_sem_segredo(resposta, trecho, caplog):
    cofre = CofreMemoria()
    sv = servico(Rede(resposta), cofre)
    with caplog.at_level(logging.DEBUG), pytest.raises(ErroDeConfiguracao, match=trecho) as exc:
        conectar(sv)
    assert CHAVE not in str(exc.value) and SEGREDO not in str(exc.value)
    assert CHAVE not in caplog.text and SEGREDO not in caplog.text
    assert sv.listar() == [] and cofre._dados == {}


def test_falha_de_rede_e_mensagem_clara_e_se_a_binance_ecoar_a_chave_ela_e_mascarada_no_log(caplog):
    sv = servico(Rede(ErroDeConexao("Não foi possível falar com a Binance. Confira a conexão com a internet e tente de novo.", "URLError")))
    with pytest.raises(ErroDeConfiguracao, match="internet"):
        conectar(sv)
    eco = servico(Rede((400, {"code": -1000, "msg": f"falha com a chave {CHAVE} e segredo {SEGREDO}"})))
    with caplog.at_level(logging.DEBUG), pytest.raises(ErroDeConfiguracao):
        conectar(eco)
    assert CHAVE not in caplog.text and SEGREDO not in caplog.text and "***" in caplog.text


@pytest.mark.parametrize("credenciais,trecho", [
    ({"api_key": "", "api_secret": SEGREDO}, "API Key"),
    ({"api_key": CHAVE, "api_secret": ""}, "API Secret"),
    ({"api_key": "curta", "api_secret": SEGREDO}, "incompleto"),
    ({"api_key": CHAVE + " espaço", "api_secret": SEGREDO}, "inválidos"),
    ({"api_key": CHAVE, "api_secret": "x" * 16 + "\n--"}, "inválidos"),
])
def test_formato_invalido_e_recusado_antes_de_qualquer_chamada_de_rede(credenciais, trecho):
    rede = Rede()
    with pytest.raises(ErroDeConfiguracao, match=trecho):
        servico(rede).adicionar("binance", "", credenciais)
    assert rede.pedidos == []
    with pytest.raises(ErroDeConfiguracao, match="desconhecido"):
        servico(rede).adicionar("corretora-x", "", credenciais)


def test_a_mesma_chave_nao_conecta_duas_vezes():
    sv = servico()
    conectar(sv)
    with pytest.raises(ErroDeConfiguracao, match="já está conectada"):
        conectar(sv)
    assert len(sv.listar()) == 1


def test_apelido_vazio_usa_o_nome_do_provedor():
    sv = servico()
    assert sv.adicionar("binance", "  ", {"api_key": CHAVE, "api_secret": SEGREDO}).apelido == "Binance"


# -- testar de novo, remover, cofre indisponível --------------------------------------------------------------------------------------


def test_retestar_atualiza_o_status_e_chave_que_ganhou_poderes_vira_reprovada():
    rede = Rede()
    sv = servico(rede)
    c = conectar(sv)
    assert sv.testar(c.id).status == CONECTADA
    rede.resposta = (200, {**LEITURA, "enableWithdrawals": True})
    reprovada = sv.testar(c.id)
    assert reprovada.status == REPROVADA and "saques" in reprovada.mensagem
    rede.resposta = ErroDeConexao("Sem internet.", "URLError")
    assert sv.testar(c.id).status == ERRO
    with pytest.raises(ErroDeConfiguracao, match="não encontrada"):
        sv.testar("inexistente")


def test_retestar_com_o_segredo_ausente_do_cofre_explica_e_nao_chama_a_rede():
    rede, cofre = Rede(), CofreMemoria()
    sv = servico(rede, cofre)
    c = conectar(sv)
    cofre.apagar(f"conexao:{c.id}:api_secret")
    n = len(rede.pedidos)
    r = sv.testar(c.id)
    assert r.status == ERRO and "cofre" in r.mensagem and len(rede.pedidos) == n


def test_remover_apaga_o_segredo_do_cofre_e_a_conexao():
    cofre = CofreMemoria()
    sv = servico(cofre=cofre)
    c = conectar(sv)
    sv.remover(c.id)
    assert sv.listar() == [] and cofre._dados == {}
    conectar(sv)  # e a mesma chave pode ser conectada de novo


def test_cofre_indisponivel_recusa_conectar_sem_gravar_nada_em_texto_puro():
    sv = servico(cofre=CofreIndisponivel("Neste sistema não há cofre seguro."))
    with pytest.raises(ErroDeConfiguracao, match="com segurança"):
        conectar(sv)
    assert sv.listar() == []


# -- persistência e cofre do Windows ---------------------------------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI é do Windows")
def test_dpapi_guarda_cifrado_e_sobrevive_a_reiniciar(tmp_path):
    arquivo = tmp_path / "cofre.json"
    CofreDpapi(arquivo).guardar("a", SEGREDO)
    assert SEGREDO not in arquivo.read_text(encoding="utf-8")  # em disco só há o blob cifrado
    assert CofreDpapi(arquivo).ler("a") == SEGREDO  # "reiniciar": outra instância lê
    assert CofreDpapi(arquivo).ler("nao-existe") is None
    cofre = CofreDpapi(arquivo)
    cofre.apagar("a")
    assert cofre.ler("a") is None


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI é do Windows")
def test_conexao_e_segredo_sobrevivem_a_reiniciar_o_app(tmp_path):
    db = tmp_path / "x.db"
    sv = ServicoConexoes(Repositorio(db), cofre_padrao(tmp_path), Rede())
    c = conectar(sv)
    sv.repo.fechar()
    sv2 = ServicoConexoes(Repositorio(db), cofre_padrao(tmp_path), Rede())
    assert [x.id for x in sv2.listar()] == [c.id] and sv2.testar(c.id).status == CONECTADA  # leu o segredo do cofre e verificou de novo
    assert SEGREDO not in (tmp_path / "cofre.json").read_text(encoding="utf-8")
    sv2.repo.fechar()


def test_tabela_de_conexoes_nao_tem_coluna_para_segredo(tmp_path):
    repo = Repositorio(tmp_path / "x.db")
    colunas = {r[1] for r in repo.con.execute("PRAGMA table_info(conexoes)")}
    assert colunas == {"id", "provedor", "apelido", "chave_mascarada", "impressao", "criada_em", "status", "status_em", "permissoes", "mensagem"}
    repo.fechar()


def test_o_mcp_de_consulta_nao_enxerga_conexoes_nem_cofre():
    """As ferramentas do MCP só leem metas: nada de conexões, chaves ou cofre no código que elas executam."""
    raiz = Path(__file__).resolve().parent.parent / "src" / "ubento"
    for arquivo in ("consulta.py", "mcp_local.py"):
        fonte = (raiz / arquivo).read_text(encoding="utf-8").lower()
        assert "conexoes" not in fonte.replace("ubento.conexoes", "") and "cofre" not in fonte and "api_secret" not in fonte, arquivo


def test_provedor_reservado_nao_conecta_e_nao_toca_rede_nem_cofre():
    rede, cofre = Rede(), CofreMemoria()
    sv = servico(rede, cofre)
    with pytest.raises(ErroDeConfiguracao, match="ainda não está disponível"):
        sv.adicionar("telegram", "meu bot", {"token": "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ"})
    assert rede.pedidos == [] and cofre._dados == {} and sv.listar() == []
