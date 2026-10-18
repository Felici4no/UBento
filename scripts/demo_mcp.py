"""Demonstração do MCP local com um banco PERSISTIDO de teste, falando com o servidor por um cliente MCP real (SDK oficial, via stdio).

    python scripts/demo_mcp.py [--db caminho.db]      (sem --db: cria um banco novo numa pasta temporária)

Monta duas metas com dados SIMULADOS (uma atingida; uma com execuções ainda por comprovar), grava o banco em disco, FECHA o banco
(o app "não está aberto") e então faz perguntas ao servidor: quais metas estão pendentes, explique uma pendência, mostre o histórico.
A "narração" abaixo de cada resposta é gerada por este script a partir do que a ferramenta devolveu: é o que um agente de IA faria.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from mcp import StdioServerParameters  # noqa: E402
from mcp.client import Client  # noqa: E402

from ubento.metas import EvidenciaExterna, ServicoMetas  # noqa: E402
from ubento.nucleo.avaliacao.reproducao import carregar_reproducao_meta  # noqa: E402
from ubento.persistencia import Repositorio  # noqa: E402

CENARIO = RAIZ / "exemplos" / "avaliacao" / "01_parcial_ate_atingir.yaml"
PALAVRAS = {"nao": "não", "conciliada": "conciliada", "possivel": "possível", "vinculada": "vinculada", "execucao": "execução", "compra": "compra",
            "pendencia": "pendência", "comprovacao": "comprovação", "prova": "prova", "anterior": "anterior", "contradita": "contradita"}


def humano(identificador: str) -> str:
    return " ".join(PALAVRAS.get(p, p) for p in identificador.split("_"))


def instante(iso: str | None) -> str:
    return "—" if not iso else f"{iso[8:10]}/{iso[5:7]}/{iso[:4]} {iso[11:16]} UTC"


def montar_banco(db: Path) -> tuple[str, str]:
    """Meta A: três compras comprovadas por vínculo manual (meta atingida). Meta B: as três compras registradas SEM referência externa, avaliada
    momento a momento do cenário; DEPOIS chega mais um registro externo que ninguém reavaliou (por isso a evidência aparece como mais nova)."""
    o = carregar_reproducao_meta(CENARIO)
    sv = ServicoMetas(Repositorio(db))
    justificativa = "Conferi o extrato da corretora: é a mesma compra."
    ids = []
    for meta_id in ("meta-pessoal-tokx", "meta-empresa-tokx"):
        meta = o.meta.model_copy(update={"id": meta_id})
        vazio = o.model_copy(update={"meta": meta, "execucoes": (), "registros_externos": (), "coberturas_execucoes": ()})
        sv.importar(vazio, agente_id="demo")
        for e in o.execucoes:
            sv.registrar_execucao(meta_id, e.model_copy(update={"meta_id": meta_id, "referencias_externas": ()}))
        sv.importar_evidencia(meta_id, EvidenciaExterna(registros_externos=o.registros_externos))
        ids.append(meta_id)
    a, b = ids
    for n in (1, 2, 3):
        sv.vincular_manualmente(a, f"ex-{n}", "corretora-sim", f"fill-{n}", "Lucas", justificativa)
    sv.repo.fechar()
    # B: avaliada em todos os momentos do cenário; as execuções seguem sem referência externa. DEPOIS chega evidência nova.
    sv = ServicoMetas(Repositorio(db))
    while sv.avancar(b) is not None:
        pass
    tardio = o.registros_externos[0].model_copy(update={"id_externo": "fill-novo", "recebido_em": o.momentos[-1].agora.replace(hour=23), "executado_em": o.momentos[-1].agora.replace(hour=22)})
    sv.importar_evidencia(b, EvidenciaExterna(registros_externos=(tardio,)))
    sv.repo.fechar()
    return a, b


async def demonstrar(db: Path) -> None:
    params = StdioServerParameters(command=sys.executable, args=["-m", "ubento.mcp_local", "--db", str(db)],
                                   env={**os.environ, "PYTHONPATH": str(RAIZ / "src"), "PYTHONIOENCODING": "utf-8"}, cwd=str(RAIZ))
    async with Client(params) as c:
        print(f"Cliente MCP: SDK oficial `mcp` | protocolo negociado: {c.protocol_version} | servidor: {c.server_info.name} {c.server_info.version}")
        print("Dados SIMULADOS. A narração é gerada por este script a partir das respostas das ferramentas.\n")

        print("PERGUNTA 1: quais metas estão pendentes?  →  listar_metas(somente_com_pendencias=true)")
        r = (await c.call_tool("listar_metas", {"somente_com_pendencias": True})).structured_content
        for m in r["metas"]:
            print(f"  • {m['meta_id']}: estado gravado '{m['estado_persistido']}', última avaliação em {instante(m['ultima_avaliacao_em'])}; "
                  f"{m['execucoes_pendentes_de_comprovacao']} execução(ões) por comprovar, {m['pendencias_abertas']} pendência(s) aberta(s).")
            if m["evidencia_desatualizada"]:
                print("    Atenção: há evidência importada DEPOIS dessa avaliação; ela ainda não foi considerada.")
        print(f"  Observação: {r['leitura']['aviso']}\n")
        alvo = r["metas"][0]["meta_id"]

        print(f"PERGUNTA 2: explique a pendência de {alvo}.  →  consultar_pendencias")
        r = await c.call_tool("consultar_pendencias", {"meta_id": alvo})
        e = r.structured_content
        print(f"  Estado gravado: '{e['estado_persistido']}' (avaliado em {instante(e['ultima_avaliacao']['avaliada_em'])}).")
        for p in e["dados"]["pendencias"]:
            risco = " Se for resolvida contra a meta, pode REDUZIR o progresso." if p["pode_reduzir_progresso"] else ""
            print(f"  • {p['referencia']}: {humano(p['motivo_avaliacao'])}.{risco}")
        for x in e["dados"]["execucoes"]:
            extra = " (sem referência externa: não pode ser comprovada até ser vinculada a um registro)" if x["sem_referencia_externa"] else ""
            print(f"    - execução {x['id']}: {x['quantidade_liquida']} tokx em {instante(x['executada_em'])}, situação '{humano(x['situacao'])}'{extra}")
        cob = e["cobertura_da_evidencia"]
        print(f"  Evidência: {cob['registros_externos_importados']} registro(s) externo(s) importado(s), "
              f"{cob['posterior_a_ultima_avaliacao']['registros_externos']} chegou(aram) depois da última avaliação; "
              f"{'há' if cob['ausencia_comprovavel'] else 'NÃO há'} cobertura de consulta (sem ela, a ausência de um registro não prova nada).")
        print(f"  Observação: {e['leitura']['aviso']}\n")

        print(f"PERGUNTA 3: mostre o histórico de {alvo}.  →  consultar_historico(limite=10)")
        h = (await c.call_tool("consultar_historico", {"meta_id": alvo, "limite": 10})).structured_content
        for ev in h["dados"]["eventos"]:
            print(f"  #{ev['sequencia']:>2} {instante(ev['horario_evidencia'])}  {humano(ev['tipo'])}" + (f" — {ev['motivo']}" if ev["motivo"] else ""))
        ult = h["dados"]["avaliacoes"]["ultimas"][-1]
        print(f"  {h['dados']['eventos_total']} evento(s) no total; {h['dados']['avaliacoes']['total']} avaliação(ões); a última foi em {instante(ult['avaliada_em'])}.")
        print(f"  Observação: {h['leitura']['aviso']}")


def main() -> None:
    destino = sys.argv[sys.argv.index("--db") + 1] if "--db" in sys.argv else None
    db = Path(destino) if destino else Path(tempfile.mkdtemp(prefix="ubento-demo-")) / "ubento-demo.db"
    if not db.exists():
        montar_banco(db)
    print(f"Banco persistido de teste: {db}\n")
    asyncio.run(demonstrar(db))


if __name__ == "__main__":
    main()
