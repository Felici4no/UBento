"""Consultas SOMENTE LEITURA sobre as metas persistidas. É a camada que o MCP local expõe.

Princípios (cada resposta os explicita no envelope):
  - **estado persistido**: o que está no banco, da última avaliação gravada. Nada é recalculado aqui;
  - **instante da última avaliação**: dito à parte, porque o mundo pode ter andado depois dela;
  - **cobertura da evidência**: o que a evidência importada garante (e o que chegou DEPOIS da última avaliação).
Consultar nunca importa, nunca reavalia e nunca grava: o repositório é aberto em modo somente leitura (o próprio banco recusa escrita)
e este módulo só chama métodos de leitura.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from . import __version__
from .metas import ServicoMetas
from .nucleo.conciliacao.conciliador import id_do_vinculo
from .nucleo.conciliacao.modelos import CoberturaExecucoes, RegistroExterno, RevogacaoVinculo, VinculoManual
from .nucleo.esquema import Execucao
from .persistencia import ErroDePersistencia, Repositorio

LIMITE_PADRAO, LIMITE_MAXIMO = 50, 500


class ErroDeConsulta(ValueError):
    """Pedido inválido (meta inexistente, parâmetro fora do limite…). A mensagem é para quem fez a pergunta."""


def jsonavel(valor: Any) -> Any:
    """Decimais viram texto, instantes viram ISO em UTC, enums viram o valor: nada de float."""
    if isinstance(valor, BaseModel):
        return valor.model_dump(mode="json")
    if isinstance(valor, datetime):
        return valor.isoformat().replace("+00:00", "Z")
    if isinstance(valor, dict):
        return {str(k): jsonavel(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple, set)):
        return [jsonavel(v) for v in valor]
    return str(valor) if hasattr(valor, "as_tuple") else getattr(valor, "value", valor)


class ConsultaMetas:
    def __init__(self, repositorio: Repositorio):
        if not repositorio.somente_leitura:
            raise ValueError("a consulta exige um repositório aberto em modo somente leitura")
        self.repo = repositorio
        self._servico = ServicoMetas(repositorio)  # só `painel` e `metas` (leituras) são usados

    # -- apoio ----------------------------------------------------------------------------------------------------------

    def _exigir(self, meta_id: str) -> None:
        if meta_id not in self.repo.metas_ids():
            raise ErroDeConsulta(f"meta desconhecida: {meta_id!r}. Use listar_metas para ver as existentes.")

    def _ultima(self, meta_id: str):
        return self.repo.ultima_avaliacao(meta_id)

    def _ultima_avaliacao(self, meta_id: str) -> dict | None:
        ultima = self._ultima(meta_id)
        if ultima is None:
            return None
        a = ultima[0]
        return {"id": a.id, "avaliada_em": jsonavel(a.avaliada_em), "versao_motor": a.versao_motor, "bloqueada_por_dados": a.bloqueada_por_dados,
                "instante_vem_de": "cenario" if self.repo.meta_e_cenario(meta_id) else "relogio_real"}

    def _cobertura(self, meta_id: str) -> dict:
        """O que a evidência cobre e o que chegou depois da última avaliação. É um INDICADOR por instantes: nada é reconciliado aqui."""
        r = self.repo
        registros = r.entradas(meta_id, "registros_externos", RegistroExterno)
        coberturas = r.entradas(meta_id, "coberturas_execucoes", CoberturaExecucoes)
        ultima = self._ultima(meta_id)
        posterior: dict[str, int] | None = None
        if ultima is not None:
            t = ultima[0].avaliada_em
            posterior = {
                "registros_externos": sum(1 for x in registros if x.recebido_em > t),
                "execucoes": sum(1 for x in r.entradas(meta_id, "execucoes", Execucao) if x.confirmada_em > t),
                "vinculos": sum(1 for x in r.entradas(meta_id, "vinculos_manuais", VinculoManual) if x.em > t),
                "revogacoes": sum(1 for x in r.entradas(meta_id, "revogacoes_vinculos", RevogacaoVinculo) if x.em > t),
            }
        return {
            "registros_externos_importados": len({x.chave for x in registros}),
            "ultimo_recebimento": jsonavel(max((x.recebido_em for x in registros), default=None)),
            "coberturas_de_consulta": [jsonavel(c) for c in coberturas],
            "ausencia_comprovavel": bool(coberturas),
            "posterior_a_ultima_avaliacao": posterior,
            "desatualizada": None if posterior is None else any(posterior.values()),
            "observacao": (
                "Cobertura da consulta é declarada pela fonte: sem ela, a ausência de um registro externo NÃO prova que ele não existe. "
                "'desatualizada' é um indicador por instantes (há entradas mais novas que a última avaliação); consultar não reavalia."
            ),
        }

    @staticmethod
    def _aviso_de_atualidade(avaliada_em: datetime | None, desatualizada: bool | None) -> str:
        if avaliada_em is None:
            return "A meta ainda não tem avaliação gravada: não há estado persistido para informar."
        quando = f"{avaliada_em:%d/%m/%Y %H:%M} UTC"
        texto = (f"Estes dados refletem a última avaliação gravada, feita em {quando}. Não são atualizados em tempo real: "
                 "o que mudou depois dela só aparece quando o app reavaliar a meta.")
        if desatualizada:
            texto += " Há entradas mais novas que essa avaliação (veja cobertura_da_evidencia.posterior_a_ultima_avaliacao)."
        return texto

    def _envelope(self, meta_id: str, dados: dict) -> dict:
        ultima = self._ultima(meta_id)
        cobertura = self._cobertura(meta_id)
        return {
            "meta_id": meta_id,
            "consulta": {"somente_leitura": True, "recalculou": False, "gravou": False, "versao_do_app": __version__,
                         "base": "estado persistido no banco; nada é recalculado ao consultar"},
            "estado_persistido": ultima[0].estado.value if ultima else None,
            "ultima_avaliacao": self._ultima_avaliacao(meta_id),
            "leitura": {"tempo_real": False, "aviso": self._aviso_de_atualidade(ultima[0].avaliada_em if ultima else None, cobertura["desatualizada"])},
            "cobertura_da_evidencia": cobertura,
            "dados": dados,
        }

    # -- consultas ------------------------------------------------------------------------------------------------------

    def listar_metas(self, agente_id: str | None = None, somente_com_pendencias: bool = False) -> dict:
        itens = []
        for meta_id in self._servico.metas(agente_id):
            painel = self._servico.painel(meta_id)
            p = painel.progresso
            cobertura = self._cobertura(meta_id)
            relevantes = [o for o in p.orfaos if o.relevante] if p else []
            pendentes = sum(1 for r in painel.execucoes if r.situacao == "pendente_de_comprovacao")
            abertas = (len(p.completude.pendencias) + len(relevantes)) if p else None
            item = {
                "meta_id": meta_id, "descricao": painel.descricao, "agente_id": painel.agente_id, "ativo_id": painel.ativo_id,
                "estado_persistido": painel.estado.value if painel.estado else None,
                "ultima_avaliacao_em": jsonavel(painel.avaliacao.avaliada_em) if painel.avaliacao else None,
                "quantidade_alvo": jsonavel(p.quantidade_alvo) if p else None,
                "quantidade_comprovada": jsonavel(p.quantidade_comprovada) if p else None,
                "execucoes_registradas": len(painel.execucoes),
                "execucoes_pendentes_de_comprovacao": pendentes,
                "pendencias_abertas": abertas,
                "tem_pendencia": None if p is None else (not p.completude.completa) or pendentes > 0 or bool(relevantes),
                "evidencia_desatualizada": cobertura["desatualizada"],
                "aviso": self._aviso_de_atualidade(painel.avaliacao.avaliada_em if painel.avaliacao else None, cobertura["desatualizada"]),
            }
            if not somente_com_pendencias or item["tem_pendencia"]:
                itens.append(item)
        return {
            "consulta": {"somente_leitura": True, "recalculou": False, "gravou": False, "base": "estado persistido no banco"},
            "leitura": {"tempo_real": False, "aviso": "Cada meta mostra o estado da sua última avaliação gravada (ultima_avaliacao_em); nada aqui é atualizado em tempo real."},
            "filtro": {"agente_id": agente_id, "somente_com_pendencias": somente_com_pendencias},
            "total": len(itens), "metas": itens,
        }

    def consultar_meta(self, meta_id: str) -> dict:
        self._exigir(meta_id)
        meta, ativacao = self.repo.carregar_meta(meta_id)
        painel = self._servico.painel(meta_id)
        return self._envelope(meta_id, {
            "descricao": painel.descricao, "agente_id": painel.agente_id,
            "objetivo": {"ativo_id": meta.objetivo.ativo_id, "moeda_cotacao_id": meta.objetivo.moeda_cotacao_id,
                         "quantidade_alvo": jsonavel(meta.objetivo.quantidade_alvo), "prazo": jsonavel(meta.objetivo.prazo)},
            "mercado": {"mercado_id": meta.mercado.mercado_id, "conta_id": meta.mercado.conta_id},
            "ativacao": {"ativada_em": jsonavel(ativacao.ativada_em), "responsavel": ativacao.responsavel, "contrato_hash": ativacao.contrato_hash},
            "execucoes_registradas": len(painel.execucoes),
            "cenario": {"momentos_total": painel.momentos_total, "proximo_momento": painel.proximo_momento},
        })

    def consultar_progresso(self, meta_id: str) -> dict:
        self._exigir(meta_id)
        painel = self._servico.painel(meta_id)
        p = painel.progresso
        if p is None:
            return self._envelope(meta_id, {"avaliada": False, "mensagem": "A meta ainda não tem avaliação gravada."})
        return self._envelope(meta_id, {
            "avaliada": True,
            "quantidade_alvo": jsonavel(p.quantidade_alvo),
            "quantidade_comprovada": jsonavel(p.quantidade_comprovada),
            "quantidade_preservada_por_prova_anterior": jsonavel(p.quantidade_preservada),
            "quantidade_pendente_na_avaliacao": jsonavel(p.quantidade_pendente),
            "quantidade_registrada_pendente_de_comprovacao": jsonavel(painel.quantidade_registrada_pendente),
            "quantidade_fora_da_janela": jsonavel(p.quantidade_fora_da_janela),
            "instante_atingimento": jsonavel(p.instante_atingimento),
            "em_carencia": p.em_carencia, "aguardando_evidencia": p.aguardando_evidencia,
            "elegibilidade_para_concluir": jsonavel(p.elegibilidade),
            "orcamento": jsonavel(p.orcamento),
            "custos": jsonavel(list(p.custos)),
            "aviso": "'comprovada' é só o que a conciliação confirmou; 'registrada pendente' foi confirmada internamente e NÃO conta como progresso.",
        })

    def consultar_pendencias(self, meta_id: str) -> dict:
        self._exigir(meta_id)
        painel = self._servico.painel(meta_id)
        p = painel.progresso
        execucoes = [{
            "id": r.execucao.id, "lado": r.execucao.lado.value, "quantidade_liquida": jsonavel(r.execucao.quantidade_liquida),
            "executada_em": jsonavel(r.execucao.executada_em), "situacao": r.situacao,
            "sem_referencia_externa": r.sem_referencia_externa,
            "vinculo_vigente": jsonavel(r.vinculo) if r.vinculo else None,
        } for r in painel.execucoes]
        if p is None:
            return self._envelope(meta_id, {"avaliada": False, "execucoes": execucoes, "mensagem": "A meta ainda não tem avaliação gravada."})
        return self._envelope(meta_id, {
            "avaliada": True,
            "conciliacao_completa": p.completude.completa,
            "pendencias": jsonavel(list(p.completude.pendencias)),
            "orfaos_relevantes": jsonavel([o for o in p.orfaos if o.relevante]),
            "orfaos_ignorados": jsonavel([o for o in p.orfaos if not o.relevante]),
            "execucoes": execucoes,
            "execucoes_sem_referencia_externa": [e["id"] for e in execucoes if e["sem_referencia_externa"]],
        })

    def consultar_historico(self, meta_id: str, limite: int = LIMITE_PADRAO, apos_sequencia: int = 0) -> dict:
        self._exigir(meta_id)
        if not isinstance(limite, int) or isinstance(limite, bool) or not 1 <= limite <= LIMITE_MAXIMO:
            raise ErroDeConsulta(f"limite deve ser um inteiro entre 1 e {LIMITE_MAXIMO}")
        if not isinstance(apos_sequencia, int) or isinstance(apos_sequencia, bool) or apos_sequencia < 0:
            raise ErroDeConsulta("apos_sequencia deve ser um inteiro >= 0")
        r = self.repo
        eventos = [e for e in r.eventos(meta_id) if e.sequencia > apos_sequencia]
        pagina = eventos[:limite]
        razao = r.razao(meta_id)
        avaliacoes = r.avaliacoes(meta_id)
        vinculos = r.entradas(meta_id, "vinculos_manuais", VinculoManual)
        revogacoes = {x.vinculo_id: x for x in r.entradas(meta_id, "revogacoes_vinculos", RevogacaoVinculo)}
        return self._envelope(meta_id, {
            "eventos": [{"sequencia": e.sequencia, "tipo": e.tipo.value, "horario_evidencia": jsonavel(e.horario_evidencia),
                         "registrado_em": jsonavel(e.registrado_em), "autor": e.autor, "motivo": e.motivo} for e in pagina],
            "eventos_total": len(r.eventos(meta_id)),
            "proxima_sequencia": pagina[-1].sequencia if len(eventos) > limite else None,
            "razao_de_conciliacao": {"total": len(razao), "ultimos": [
                {"tipo": x.tipo.value, "alvo": x.alvo, "delta_progresso": jsonavel(x.delta_progresso), "horario_evidencia": jsonavel(x.horario_evidencia)}
                for x in razao[-limite:]]},
            "avaliacoes": {"total": len(avaliacoes), "ultimas": [
                {"id": a.id, "avaliada_em": jsonavel(a.avaliada_em), "estado": a.estado.value, "versao_motor": a.versao_motor}
                for a, _ in avaliacoes[-limite:]]},
            "vinculos_manuais": [
                {"vinculo": jsonavel(v), "revogacao": jsonavel(revogacoes[id_do_vinculo(v)]) if id_do_vinculo(v) in revogacoes else None}
                for v in vinculos],
        })


def abrir(caminho) -> ConsultaMetas:
    """Abre o banco em modo somente leitura. Banco inexistente é erro (nunca é criado por uma consulta)."""
    try:
        return ConsultaMetas(Repositorio(caminho, somente_leitura=True))
    except ErroDePersistencia as erro:
        raise ErroDeConsulta(str(erro)) from erro
