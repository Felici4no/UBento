"""Guarda e devolve as carteiras do mercado real (ADR-001, passo 4).

- Só o mercado real persiste; a demonstração continua efêmera e nunca toca no banco.
- Ao ligar o mercado real (ou abrir o app já nele), cada agente recebe de volta a carteira guardada ANTES de qualquer gravação: a carteira nova do
  início nunca vai para o banco por cima da guardada. O último preço lido também volta, mas vencido, então não libera nenhuma operação.
- Grava pouco: só quando o estado da carteira mudou (o preço sozinho não regrava), com um pequeno atraso para juntar várias mudanças.
- Estado ilegível não derruba o app e não é sobrescrito: a carteira daquele agente fica sem gravar na sessão e o app avisa.
- Agente removido tem a carteira ARQUIVADA, nunca apagada (as metas dele continuam no banco).
"""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import QObject, QTimer, Signal

from .carteira_serial import ErroDeEstado, aplicar_estado, de_utc, estado_da_carteira, numero, para_utc, pontos_da_carteira, texto
from .persistencia import Repositorio
from .persistencia.carteiras import RepositorioCarteiras
from .workspace import Workspace

log = logging.getLogger(__name__)

ATRASO_PADRAO_MS = 1000


class PersistenciaCarteiras(QObject):
    falhou = Signal(str)
    restaurada = Signal(str)  # id do agente cuja carteira voltou do banco

    def __init__(self, workspace: Workspace, repo: Repositorio | RepositorioCarteiras, atraso_ms: int = ATRASO_PADRAO_MS):
        super().__init__()
        self.ws = workspace
        self.repo = repo if isinstance(repo, RepositorioCarteiras) else RepositorioCarteiras(repo)
        self._ultimo: dict[str, str] = {}  # agente -> estado (JSON) já gravado
        self._ultimo_ponto: dict[str, tuple[str, str]] = {}  # agente -> último ponto (instante, valor) já gravado
        self._bloqueadas: set[str] = set()  # carteiras cujo estado guardado não deu para ler: não se sobrescreve
        self._conectadas: set[int] = set()
        self._ativa = False  # a carteira guardada já foi restaurada nesta ativação do mercado real
        self._avisou = False
        self._ultimo_mercado: dict | None = None
        self._pronto = False  # avisos da restauração inicial esperam alguém conectar em `falhou`
        self._pendentes: list[str] = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(atraso_ms)
        self._timer.timeout.connect(self.salvar_tudo)
        workspace.mercado_vai_mudar.connect(self._antes_de_trocar)
        workspace.mercado_changed.connect(self._ao_mudar_mercado)
        workspace.changed.connect(self._conectar_stores)
        workspace.agente_removido.connect(self._arquivar)
        self._conectar_stores()
        if workspace.mercado_real:
            self._ativar()
        QTimer.singleShot(0, self._liberar_avisos)

    def _avisar(self, mensagem: str) -> None:
        if self._pronto:
            self.falhou.emit(mensagem)
        else:
            self._pendentes.append(mensagem)

    def _liberar_avisos(self) -> None:
        self._pronto = True
        for mensagem in self._pendentes:
            self.falhou.emit(mensagem)
        self._pendentes.clear()

    def _antes_de_trocar(self) -> None:
        """O mercado real vai ser ligado ou desligado: as carteiras reais em memória saem de cena, então guarda-se o que há agora.
        (O modo em `prefs` já mudou neste ponto, por isso a trava é a ativação, não a preferência.)"""
        if self._ativa:
            self._gravar_todas()

    # -- ativação e restauração ---------------------------------------------------------------------------------------------------------------

    def _ao_mudar_mercado(self) -> None:
        if not self.ws.mercado_real:
            self._ativa = False
        elif not self._ativa:
            self._ativar()
        else:
            self._guardar_mercado()

    def _ativar(self) -> None:
        self._ativa = True
        self._restaurar_mercado()
        for agente in self.ws.agents:
            self._restaurar(agente)

    def _restaurar_mercado(self) -> None:
        try:
            guardado = self.repo.carregar_mercado()
            if guardado is None or self.ws.mercado.atualizado_em is not None:
                return
            dados, lido_em = guardado
            precos = {s: numero(v, f"preço {s}", minimo=0) for s, v in dados["precos"].items()}
            variacao = {s: numero(v, f"variação {s}") for s, v in dados["variacao_7d"].items()}
            self.ws.mercado.aplicar(precos, variacao, de_utc(lido_em, "lido_em"))
        except Exception as erro:  # noqa: BLE001 - sem o último preço o app só espera a primeira leitura
            log.warning("carteiras: não foi possível restaurar o último preço (%s)", erro)

    def _restaurar(self, agente) -> None:
        try:
            dados = self.repo.carregar(agente.id)
            if dados is None:
                return
            aplicar_estado(agente.store, dados, self.repo.pontos(agente.id))
        except (ErroDeEstado, ValueError, KeyError, TypeError) as erro:
            self._bloqueadas.add(agente.id)
            log.warning("carteiras: estado ilegível de %s: %s", agente.id, erro)
            self._avisar(f"A carteira guardada de “{agente.name}” está ilegível ({erro}). Ela foi mantida no banco e não será sobrescrita nesta sessão.")
            return
        self._ultimo[agente.id] = json.dumps(estado_da_carteira(agente.store), sort_keys=True)
        pontos = pontos_da_carteira(agente.store)
        if pontos:
            self._ultimo_ponto[agente.id] = pontos[-1]
        agente.store.changed.emit()
        self.restaurada.emit(agente.id)

    # -- gravação ----------------------------------------------------------------------------------------------------------------------------------

    def _conectar_stores(self) -> None:
        for agente in self.ws.agents:
            if id(agente.store) not in self._conectadas:
                self._conectadas.add(id(agente.store))
                agente.store.changed.connect(self._agendar)

    def _agendar(self) -> None:
        if self.ws.mercado_real and self._ativa:
            self._timer.start()

    def salvar_tudo(self) -> None:
        if not (self.ws.mercado_real and self._ativa):
            return  # a demonstração nunca grava
        self._gravar_todas()

    def _gravar_todas(self) -> None:
        em = para_utc(self.ws.mercado.agora())
        for agente in self.ws.agents:
            if agente.id in self._bloqueadas or not agente.store.real:
                continue
            try:
                self._salvar_agente(agente, em)
                self._avisou = False
            except Exception as erro:  # noqa: BLE001 - a carteira nunca pode quebrar por causa do disco
                log.exception("carteiras: não foi possível gravar %s", agente.id)
                self._ultimo.pop(agente.id, None)  # tenta de novo na próxima
                if not self._avisou:
                    self._avisou = True
                    self._avisar(f"Não foi possível guardar a carteira de “{agente.name}”: {erro}")
        self._guardar_mercado()

    def _salvar_agente(self, agente, em: str) -> None:
        estado = estado_da_carteira(agente.store)
        corpo = json.dumps(estado, sort_keys=True)
        if corpo != self._ultimo.get(agente.id):
            self.repo.salvar(agente.id, estado, em)
            self._ultimo[agente.id] = corpo
        ultimo = self._ultimo_ponto.get(agente.id)
        novos = [p for p in pontos_da_carteira(agente.store) if ultimo is None or p[0] >= ultimo[0]]  # inclusive o último: o ponto do minuto corrente é regravado
        if novos and novos[-1] != ultimo:
            self.repo.gravar_pontos(agente.id, novos)
            self._ultimo_ponto[agente.id] = novos[-1]

    def _guardar_mercado(self) -> None:
        m = self.ws.mercado
        if not self.ws.mercado_real or m.atualizado_em is None:
            return
        dados = {"precos": {s: texto(p) for s, p in sorted(m.precos.items())}, "variacao_7d": {s: texto(v) for s, v in sorted(m.variacao_7d.items())}}
        marca = {"dados": dados, "em": para_utc(m.atualizado_em)}
        if marca == self._ultimo_mercado:
            return
        try:
            self.repo.salvar_mercado(dados, marca["em"])
            self._ultimo_mercado = marca
        except Exception:  # noqa: BLE001
            log.exception("carteiras: não foi possível gravar o último preço")

    # -- remoção ---------------------------------------------------------------------------------------------------------------------------------------

    def _arquivar(self, agente_id: str) -> None:
        self._ultimo.pop(agente_id, None)
        self._ultimo_ponto.pop(agente_id, None)
        self._bloqueadas.discard(agente_id)
        try:
            self.repo.arquivar(agente_id, para_utc(self.ws.mercado.agora()))
        except Exception as erro:  # noqa: BLE001
            log.exception("carteiras: não foi possível arquivar %s", agente_id)
            self._avisar(f"Não foi possível arquivar a carteira do agente removido: {erro}")
