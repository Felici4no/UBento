"""MCP local (somente consulta) validado com o cliente do SDK oficial: inicialização, ferramentas, erros, encerramento e não-escrita."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason='o MCP local usa o SDK oficial: pip install "ubento[mcp]"')

from mcp import StdioServerParameters  # noqa: E402
from mcp.client import Client  # noqa: E402

from test_correcao_vinculo import CENARIO, JUST, base  # noqa: E402
from ubento import consulta, mcp_local  # noqa: E402
from ubento.mcp_local import criar_servidor  # noqa: E402
from ubento.metas import EvidenciaExterna, ServicoMetas  # noqa: E402
from ubento.nucleo.avaliacao.reproducao import carregar_reproducao_meta  # noqa: E402
from ubento.persistencia import ErroDePersistencia, Repositorio  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
FERRAMENTAS = {"listar_metas", "consultar_meta", "consultar_progresso", "consultar_pendencias", "consultar_historico"}


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


def sha(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def contagens(db: Path) -> dict[str, int]:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("metas", "eventos", "razao", "avaliacoes", "entradas")}
    finally:
        con.close()


def sessao(db, corpo):
    """Roda `corpo(cliente)` com um cliente do SDK ligado ao servidor em memória."""
    async def rodar():
        async with Client(criar_servidor(db)) as cliente:
            return await corpo(cliente)

    return asyncio.run(rodar())


def estrutura(resultado) -> dict:
    assert resultado.is_error is False, [c.text for c in resultado.content]
    return resultado.structured_content


# -- inicialização, descoberta e argumentos --------------------------------------------------------------------------------------


def test_inicializacao_e_descoberta_das_cinco_ferramentas(banco):
    db, *_ = banco

    async def corpo(c):
        tools = (await c.list_tools()).tools
        return c.protocol_version, c.server_info, c.instructions, tools

    versao, info, instrucoes, tools = sessao(db, corpo)
    assert versao and info.name == "ubento-metas" and info.version
    assert "tempo real" in instrucoes and "somente leitura" in instrucoes.lower()
    assert {t.name for t in tools} == FERRAMENTAS
    assert all(t.annotations.read_only_hint is True and t.annotations.destructive_hint is False for t in tools)
    esquemas = {t.name: t.input_schema for t in tools}
    assert esquemas["consultar_meta"]["required"] == ["meta_id"]
    assert esquemas["consultar_historico"]["properties"]["limite"]["maximum"] == 500
    assert "somente_com_pendencias" in esquemas["listar_metas"]["properties"]


def test_chamadas_com_argumentos_invalidos_voltam_como_erro_legivel(banco):
    db, a, _ = banco

    async def corpo(c):
        casos = {
            "meta_inexistente": await c.call_tool("consultar_meta", {"meta_id": "nao-existe"}),
            "sem_meta_id": await c.call_tool("consultar_meta", {}),
            "tipo_errado": await c.call_tool("consultar_meta", {"meta_id": 7}),
            "limite_zero": await c.call_tool("consultar_historico", {"meta_id": a, "limite": 0}),
            "limite_alto": await c.call_tool("consultar_historico", {"meta_id": a, "limite": 501}),
            "apos_negativo": await c.call_tool("consultar_historico", {"meta_id": a, "apos_sequencia": -1}),
            "ferramenta_inexistente": await c.call_tool("importar_cenario", {}),
        }
        return {k: (r.is_error, r.content[0].text) for k, r in casos.items()}

    r = sessao(db, corpo)
    assert all(erro is True for erro, _ in r.values())
    assert "meta desconhecida" in r["meta_inexistente"][1] and "listar_metas" in r["meta_inexistente"][1]
    assert "Unknown tool" in r["ferramenta_inexistente"][1]


# -- respostas ------------------------------------------------------------------------------------------------------------------------


def test_respostas_distinguem_estado_persistido_ultima_avaliacao_e_cobertura(banco):
    db, a, b = banco

    async def corpo(c):
        return (
            estrutura(await c.call_tool("listar_metas", {})),
            estrutura(await c.call_tool("consultar_progresso", {"meta_id": a})),
            estrutura(await c.call_tool("consultar_progresso", {"meta_id": b})),
        )

    lista, prog_a, prog_b = sessao(db, corpo)
    por_id = {m["meta_id"]: m for m in lista["metas"]}
    assert lista["consulta"] == {"somente_leitura": True, "recalculou": False, "gravou": False, "base": "estado persistido no banco"}
    assert lista["leitura"]["tempo_real"] is False
    assert por_id[a]["estado_persistido"] == "atingida" and por_id[a]["evidencia_desatualizada"] is False
    assert por_id[b]["evidencia_desatualizada"] is True  # há evidência mais nova que a última avaliação...
    assert por_id[b]["estado_persistido"] == "ativa"  # ...e mesmo assim o estado devolvido é o PERSISTIDO: ninguém recalculou
    assert "tempo real" in por_id[b]["aviso"] and "entradas mais novas" in por_id[b]["aviso"]

    assert prog_a["estado_persistido"] == "atingida" and re.match(r"\d{4}-\d\d-\d\dT.*Z$", prog_a["ultima_avaliacao"]["avaliada_em"])
    assert prog_a["leitura"]["tempo_real"] is False and "última avaliação gravada, feita em" in prog_a["leitura"]["aviso"]
    cob = prog_a["cobertura_da_evidencia"]
    assert cob["registros_externos_importados"] == 3 and cob["desatualizada"] is False and cob["ausencia_comprovavel"] is False
    assert cob["posterior_a_ultima_avaliacao"] == {"registros_externos": 0, "execucoes": 0, "vinculos": 0, "revogacoes": 0}
    d = prog_a["dados"]
    assert Decimal(d["quantidade_comprovada"]) >= Decimal(d["quantidade_alvo"]) and d["quantidade_registrada_pendente_de_comprovacao"] == "0"
    assert isinstance(d["quantidade_comprovada"], str)  # decimal como texto, nunca float
    assert prog_b["cobertura_da_evidencia"]["posterior_a_ultima_avaliacao"]["registros_externos"] == 1


def test_filtro_de_pendencias_detalhes_e_historico(banco):
    db, a, b = banco

    async def corpo(c):
        return (
            estrutura(await c.call_tool("listar_metas", {"somente_com_pendencias": True})),
            estrutura(await c.call_tool("consultar_meta", {"meta_id": a})),
            estrutura(await c.call_tool("consultar_pendencias", {"meta_id": b})),
            estrutura(await c.call_tool("consultar_historico", {"meta_id": a, "limite": 2})),
        )

    so_pendentes, meta, pend, h = sessao(db, corpo)
    assert [m["meta_id"] for m in so_pendentes["metas"]] == [b]  # a está atingida e completa; b tem execuções por comprovar
    assert so_pendentes["filtro"]["somente_com_pendencias"] is True and so_pendentes["metas"][0]["tem_pendencia"] is True
    d = meta["dados"]
    assert d["objetivo"]["ativo_id"] == "tokx" and d["ativacao"]["responsavel"] and len(d["ativacao"]["contrato_hash"]) == 64

    p = pend["dados"]
    assert p["avaliada"] is True and p["conciliacao_completa"] is False
    assert {e["id"] for e in p["execucoes"]} == {"ex-1", "ex-2", "ex-3"} and p["execucoes_sem_referencia_externa"] == ["ex-1", "ex-2", "ex-3"]
    # fill-1..3 pertencem à meta A (exclusividade global): não são órfãos de B; "fill-novo" chegou depois da última avaliação e ainda não aparece
    assert p["orfaos_relevantes"] == [] and {x["referencia"] for x in p["pendencias"]} == {"ex-1", "ex-2", "ex-3"}

    hd = h["dados"]
    assert len(hd["eventos"]) == 2 and hd["eventos_total"] > 2 and hd["proxima_sequencia"] == hd["eventos"][-1]["sequencia"]
    vinculos = hd["vinculos_manuais"]
    assert len(vinculos) == 4 and sum(1 for v in vinculos if v["revogacao"]) == 1  # o revogado continua na trilha, ao lado do vigente

    async def pagina(c):
        return estrutura(await c.call_tool("consultar_historico", {"meta_id": a, "limite": 500, "apos_sequencia": hd["proxima_sequencia"]}))["dados"]

    proxima = sessao(db, pagina)
    assert proxima["eventos"][0]["sequencia"] == hd["proxima_sequencia"] + 1 and proxima["proxima_sequencia"] is None


def test_banco_inexistente_e_erro_e_nao_e_criado(tmp_path):
    ausente = tmp_path / "nada.db"

    async def corpo(c):
        return await c.call_tool("listar_metas", {})

    r = sessao(ausente, corpo)
    assert r.is_error is True and "banco inexistente" in r.content[0].text and not ausente.exists()


# -- somente leitura -------------------------------------------------------------------------------------------------------------------


def test_nenhuma_ferramenta_de_escrita_e_o_codigo_nao_chama_escrita():
    assert not [n for n in FERRAMENTAS if re.search(r"importar|avaliar|avancar|registrar|vincular|revogar|substituir|gravar", n)]
    for modulo in (consulta, mcp_local):
        fonte = Path(modulo.__file__).read_text(encoding="utf-8")
        chamadas = re.findall(r"\.(importar|importar_evidencia|avaliar|reavaliar|avancar|registrar_\w+|vincular_manualmente|revogar_vinculo|substituir_vinculo|gravar|mover_cursor)\(", fonte)
        assert chamadas == [], f"{modulo.__name__} chama escrita: {chamadas}"


def test_consultar_nao_altera_o_banco_nem_reavalia(banco):
    db, a, b = banco
    antes_hash, antes_contagens = sha(db), contagens(db)

    async def corpo(c):
        for _ in range(2):
            await c.call_tool("listar_metas", {})
            for meta in (a, b):
                for nome in ("consultar_meta", "consultar_progresso", "consultar_pendencias", "consultar_historico"):
                    assert (await c.call_tool(nome, {"meta_id": meta})).is_error is False

    sessao(db, corpo)
    assert sha(db) == antes_hash and contagens(db) == antes_contagens  # nenhum byte, nenhuma linha mudou
    assert contagens(db)["avaliacoes"] == antes_contagens["avaliacoes"]  # b tem evidência mais nova e continua sem reavaliação


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


# -- transporte real (processo + stdio) ------------------------------------------------------------------------------------------


def _ambiente():
    return {**os.environ, "PYTHONPATH": str(RAIZ / "src"), "PYTHONIOENCODING": "utf-8"}


def test_cliente_real_por_stdio_inicializa_consulta_e_encerra(banco):
    db, a, _ = banco
    antes = sha(db)

    async def rodar():
        params = StdioServerParameters(command=sys.executable, args=["-m", "ubento.mcp_local", "--db", str(db)], env=_ambiente(), cwd=str(RAIZ))
        async with Client(params) as c:
            tools = {t.name for t in (await c.list_tools()).tools}
            ok = await c.call_tool("consultar_progresso", {"meta_id": a})
            erro = await c.call_tool("consultar_meta", {"meta_id": "x"})
            return c.protocol_version, c.server_info.name, tools, ok.structured_content, erro.is_error

    versao, nome, tools, ok, erro = asyncio.run(rodar())  # sair do `async with` fecha o stdin: o servidor encerra sozinho
    assert nome == "ubento-metas" and tools == FERRAMENTAS and erro is True and ok["estado_persistido"] == "atingida" and versao
    assert sha(db) == antes


def test_stdout_so_tem_protocolo_logs_vao_para_stderr_e_a_versao_e_negociada(banco):
    """Fala JSON-RPC cru com o processo: cada linha do stdout precisa ser uma mensagem JSON-RPC; o log fica no stderr.
    Como um cliente de verdade, só fecha o stdin depois de receber as respostas (o servidor encerra no fim da entrada)."""
    db, a, _ = banco

    def conversar(versao_pedida: str):
        pedidos = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": versao_pedida, "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "consultar_meta", "arguments": {"meta_id": "x"}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "listar_metas", "arguments": {}}},
        ]
        proc = subprocess.Popen([sys.executable, "-m", "ubento.mcp_local", "--db", str(db)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", cwd=RAIZ, env=_ambiente())
        vigia = threading.Timer(60, proc.kill)  # se algo travar, o teste falha em vez de pendurar
        vigia.start()
        try:
            for m in pedidos:
                proc.stdin.write(json.dumps(m) + "\n")
            proc.stdin.flush()
            mensagens = []
            while len({m["id"] for m in mensagens if "id" in m}) < 3:
                linha = proc.stdout.readline()
                assert linha, "o servidor encerrou antes de responder"
                mensagens.append(json.loads(linha))  # qualquer linha que não seja JSON (ex.: um print) quebra aqui
            proc.stdin.close()  # fim da entrada = encerramento limpo
            resto = proc.stdout.read()
            codigo = proc.wait(timeout=30)
            stderr = proc.stderr.read()
        finally:
            vigia.cancel()
            proc.kill()
        mensagens += [json.loads(x) for x in resto.splitlines() if x.strip()]
        assert codigo == 0, stderr
        assert all(m.get("jsonrpc") == "2.0" for m in mensagens)
        return mensagens, stderr

    mensagens, stderr = conversar("2025-06-18")
    resposta = {m["id"]: m for m in mensagens}
    assert resposta[1]["result"]["protocolVersion"] == "2025-06-18"  # versão que o servidor suporta: devolve a pedida
    assert resposta[2]["result"]["isError"] is True and resposta[3]["result"]["isError"] is False
    assert "ubento-mcp" in stderr and "somente leitura" in stderr  # o aviso do app vai para o stderr
    desconhecida, _ = conversar("1999-01-01")
    assert {m["id"]: m for m in desconhecida}[1]["result"]["protocolVersion"] != "1999-01-01"  # versão desconhecida: o servidor propõe a sua (não repete cegamente)
