"""MCP local (somente consulta): protocolo, respostas, e a garantia de que consultar nunca importa, reavalia nem grava."""

from __future__ import annotations

import hashlib
import io
import json
import re
import sqlite3
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from test_correcao_vinculo import CENARIO, JUST, base
from ubento import consulta, mcp_local
from ubento.mcp_local import FERRAMENTAS, ServidorMcp, servir
from ubento.metas import EvidenciaExterna, ServicoMetas
from ubento.nucleo.avaliacao.reproducao import carregar_reproducao_meta
from ubento.persistencia import ErroDePersistencia, Repositorio

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def banco(tmp_path):
    """Banco com: A atingida (3 vínculos, 1 revogado e refeito), B com evidência MAIS NOVA que a última avaliação."""
    db = tmp_path / "ubento.db"
    sv = ServicoMetas(Repositorio(db))
    _, a, *_ = base(sv)
    for n in (1, 2, 3):
        sv.vincular_manualmente(a, f"ex-{n}", "corretora-sim", f"fill-{n}", "Lucas", JUST)
    sv.revogar_vinculo(a, "ex-3", "corretora-sim", "fill-3", "Marina", "Engano meu: o registro certo é outro, vide extrato.")
    sv.vincular_manualmente(a, "ex-3", "corretora-sim", "fill-3", "Marina", "Revisei de novo: o registro estava certo mesmo.")
    _, b, *_ = base(sv, meta_id="meta-b")
    o = carregar_reproducao_meta(CENARIO)
    sv.avaliar(b, o.momentos[-1].agora)
    depois = o.momentos[-1].agora + timedelta(hours=1)
    tardio = o.registros_externos[0].model_copy(update={"id_externo": "fill-novo", "recebido_em": depois, "executado_em": depois})
    sv.importar_evidencia(b, EvidenciaExterna(registros_externos=(tardio,)))  # chegou DEPOIS da última avaliação de b; ninguém reavaliou
    sv.repo.fechar()
    return db, a, b


def chamar(servidor, nome, argumentos=None, ident=1):
    r = servidor.tratar({"jsonrpc": "2.0", "id": ident, "method": "tools/call", "params": {"name": nome, "arguments": argumentos or {}}})
    return r["result"]


def sha(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def contagens(db: Path) -> dict[str, int]:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("metas", "eventos", "razao", "avaliacoes", "entradas")}
    finally:
        con.close()


# -- protocolo ---------------------------------------------------------------------------------------------------------------


def test_protocolo_initialize_listagem_e_erros(banco):
    db, *_ = banco
    s = ServidorMcp(db)
    r = s.tratar({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}}})
    assert r["result"]["serverInfo"]["name"] == "ubento-metas" and "tools" in r["result"]["capabilities"] and "somente leitura" in r["result"]["instructions"].lower()
    assert s.tratar({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None  # notificação: sem resposta
    assert s.tratar({"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"] == {}
    tools = s.tratar({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})["result"]["tools"]
    assert sorted(t["name"] for t in tools) == ["consultar_historico", "consultar_meta", "consultar_pendencias", "consultar_progresso", "listar_metas"]
    assert all(t["annotations"]["readOnlyHint"] is True and t["annotations"]["destructiveHint"] is False for t in tools)
    assert s.tratar({"jsonrpc": "2.0", "id": 4, "method": "resources/list"})["error"]["code"] == -32601
    assert s.tratar({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "importar_cenario"}})["error"]["code"] == -32602
    assert s.tratar({"id": 6, "method": "ping"})["error"]["code"] == -32600  # sem "jsonrpc"


def test_nenhuma_ferramenta_de_escrita_e_exposta():
    assert not [n for n in FERRAMENTAS if re.search(r"importar|avaliar|avancar|registrar|vincular|revogar|substituir|gravar", n)]
    for modulo in (consulta, mcp_local):
        fonte = Path(modulo.__file__).read_text(encoding="utf-8")
        chamadas = re.findall(r"\.(importar|importar_evidencia|avaliar|reavaliar|avancar|registrar_\w+|vincular_manualmente|revogar_vinculo|substituir_vinculo|gravar|mover_cursor)\(", fonte)
        assert chamadas == [], f"{modulo.__name__} chama escrita: {chamadas}"


# -- respostas ------------------------------------------------------------------------------------------------------------------


def test_respostas_distinguem_estado_persistido_ultima_avaliacao_e_cobertura(banco):
    db, a, b = banco
    s = ServidorMcp(db)
    lista = chamar(s, "listar_metas")["structuredContent"]
    por_id = {m["meta_id"]: m for m in lista["metas"]}
    assert lista["consulta"] == {"somente_leitura": True, "recalculou": False, "gravou": False, "base": "estado persistido no banco"}
    assert por_id[a]["estado_persistido"] == "atingida" and por_id[a]["evidencia_desatualizada"] is False
    assert por_id[b]["evidencia_desatualizada"] is True  # há evidência mais nova que a última avaliação...
    assert por_id[b]["estado_persistido"] == "ativa"  # ...e mesmo assim o estado devolvido é o PERSISTIDO: ninguém recalculou

    prog = chamar(s, "consultar_progresso", {"meta_id": a})["structuredContent"]
    assert prog["estado_persistido"] == "atingida"
    assert re.match(r"\d{4}-\d\d-\d\dT.*Z$", prog["ultima_avaliacao"]["avaliada_em"])
    cob = prog["cobertura_da_evidencia"]
    assert cob["registros_externos_importados"] == 3 and cob["desatualizada"] is False and cob["ausencia_comprovavel"] is False
    assert cob["posterior_a_ultima_avaliacao"] == {"registros_externos": 0, "execucoes": 0, "vinculos": 0, "revogacoes": 0}
    d = prog["dados"]
    assert Decimal(d["quantidade_comprovada"]) >= Decimal(d["quantidade_alvo"]) and d["quantidade_registrada_pendente_de_comprovacao"] == "0"
    assert isinstance(d["quantidade_comprovada"], str)  # decimal como texto, nunca float

    cob_b = chamar(s, "consultar_progresso", {"meta_id": b})["structuredContent"]["cobertura_da_evidencia"]
    assert cob_b["posterior_a_ultima_avaliacao"]["registros_externos"] == 1 and cob_b["desatualizada"] is True


from decimal import Decimal  # noqa: E402


def test_detalhes_pendencias_e_historico(banco):
    db, a, b = banco
    s = ServidorMcp(db)
    meta = chamar(s, "consultar_meta", {"meta_id": a})["structuredContent"]["dados"]
    assert meta["objetivo"]["ativo_id"] == "tokx" and meta["ativacao"]["responsavel"] and len(meta["ativacao"]["contrato_hash"]) == 64

    pend = chamar(s, "consultar_pendencias", {"meta_id": b})["structuredContent"]["dados"]
    assert pend["avaliada"] is True and pend["conciliacao_completa"] is False
    assert {e["id"] for e in pend["execucoes"]} == {"ex-1", "ex-2", "ex-3"} and pend["execucoes_sem_referencia_externa"] == ["ex-1", "ex-2", "ex-3"]
    # fill-1..3 pertencem a meta A (exclusividade global): não são órfãos de B. "fill-novo" chegou depois da última avaliação e ainda não aparece.
    assert pend["orfaos_relevantes"] == [] and {x["referencia"] for x in pend["pendencias"]} == {"ex-1", "ex-2", "ex-3"}

    h = chamar(s, "consultar_historico", {"meta_id": a, "limite": 2})["structuredContent"]["dados"]
    assert len(h["eventos"]) == 2 and h["eventos_total"] > 2 and h["proxima_sequencia"] == h["eventos"][-1]["sequencia"]
    proxima = chamar(s, "consultar_historico", {"meta_id": a, "limite": 500, "apos_sequencia": h["proxima_sequencia"]})["structuredContent"]["dados"]
    assert proxima["eventos"][0]["sequencia"] == h["proxima_sequencia"] + 1 and proxima["proxima_sequencia"] is None
    vinculos = h["vinculos_manuais"]
    assert len(vinculos) == 4 and sum(1 for v in vinculos if v["revogacao"]) == 1  # o revogado continua na trilha, ao lado do vigente
    assert h["avaliacoes"]["total"] >= 1 and h["razao_de_conciliacao"]["total"] >= 1


def test_erros_de_uso_sao_resultados_com_isError(banco, tmp_path):
    db, a, _ = banco
    s = ServidorMcp(db)
    assert chamar(s, "consultar_meta", {"meta_id": "nao-existe"})["isError"] is True
    assert chamar(s, "consultar_meta", {})["isError"] is True
    assert chamar(s, "consultar_meta", {"meta_id": a, "extra": 1})["isError"] is True
    assert chamar(s, "consultar_historico", {"meta_id": a, "limite": 0})["isError"] is True
    assert chamar(s, "consultar_historico", {"meta_id": a, "limite": "10"})["isError"] is True
    assert chamar(s, "consultar_historico", {"meta_id": a, "apos_sequencia": -1})["isError"] is True
    inexistente = tmp_path / "nada.db"
    r = chamar(ServidorMcp(inexistente), "listar_metas")
    assert r["isError"] is True and not inexistente.exists()  # consultar nunca cria o banco


# -- somente leitura: consultar não importa, não reavalia, não grava -----------------------------------------------------------------


def test_consultar_nao_altera_o_banco_nem_reavalia(banco):
    db, a, b = banco
    antes_hash, antes_contagens = sha(db), contagens(db)
    s = ServidorMcp(db)
    for _ in range(2):
        chamar(s, "listar_metas")
        for meta in (a, b):
            for nome in ("consultar_meta", "consultar_progresso", "consultar_pendencias", "consultar_historico"):
                assert chamar(s, nome, {"meta_id": meta})["isError"] is False
    assert sha(db) == antes_hash and contagens(db) == antes_contagens  # nenhum byte, nenhuma linha mudou
    sv = ServicoMetas(Repositorio(db))
    assert sv.painel(b).progresso is not None
    n = len(sv.repo.avaliacoes(b))
    sv.repo.fechar()
    chamar(s, "consultar_progresso", {"meta_id": b})  # b tem evidência mais nova, mas consultar NÃO reavalia
    sv = ServicoMetas(Repositorio(db))
    assert len(sv.repo.avaliacoes(b)) == n
    sv.repo.fechar()


def test_conexao_somente_leitura_recusa_escrita_e_nao_cria_tabelas(banco, tmp_path):
    db, a, _ = banco
    repo = Repositorio(db, somente_leitura=True)
    with pytest.raises(sqlite3.OperationalError):
        repo.con.execute("INSERT INTO cursor VALUES ('x', 1)")
    with pytest.raises(sqlite3.OperationalError):
        repo.con.execute("CREATE TABLE intruso (a)")
    with pytest.raises(sqlite3.DatabaseError):
        repo.con.execute("UPDATE cursor SET proximo = 9")
    repo.fechar()
    with pytest.raises(ErroDePersistencia):
        Repositorio(tmp_path / "nao-existe.db", somente_leitura=True)
    with pytest.raises(ValueError):
        consulta.ConsultaMetas(Repositorio(":memory:"))  # a camada de consulta recusa um repositório gravável


# -- transporte -----------------------------------------------------------------------------------------------------------------------


def test_laco_stdio_em_memoria(banco):
    db, a, _ = banco
    linhas = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "consultar_meta", "arguments": {"meta_id": a}}},
    ]
    entrada = io.StringIO("\n".join(json.dumps(m) for m in linhas) + "\n\nnão é json\n")
    saida = io.StringIO()
    servir(ServidorMcp(db), entrada, saida)
    respostas = [json.loads(x) for x in saida.getvalue().splitlines()]
    assert [r.get("id") for r in respostas] == [1, 2, None]  # a notificação não gera resposta; o lixo gera erro -32700
    assert respostas[2]["error"]["code"] == -32700


def test_processo_real_por_stdio(banco):
    db, a, _ = banco
    pedidos = "\n".join(json.dumps(m) for m in (
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "consultar_progresso", "arguments": {"meta_id": a}}},
    )) + "\n"
    antes = sha(db)
    proc = subprocess.run([sys.executable, "-m", "ubento.mcp_local", "--db", str(db)], input=pedidos, capture_output=True, text=True, encoding="utf-8",
                          cwd=RAIZ, env={**__import__("os").environ, "PYTHONPATH": str(RAIZ / "src"), "PYTHONIOENCODING": "utf-8"}, timeout=60)
    assert proc.returncode == 0, proc.stderr
    respostas = [json.loads(x) for x in proc.stdout.splitlines()]
    assert [r["id"] for r in respostas] == [1, 2]
    assert respostas[1]["result"]["structuredContent"]["estado_persistido"] == "atingida"
    assert "somente leitura" in proc.stderr  # o aviso vai para stderr; stdout é só do protocolo
    assert sha(db) == antes
