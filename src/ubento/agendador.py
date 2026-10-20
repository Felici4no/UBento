"""Agendador dos agentes (ADR-001, passo 6): cada agente roda sozinho na frequência dele, enquanto o UBento estiver aberto.

Regras (todas testadas com relógio injetado, o `agora` do `Mercado` do Workspace):
- vence o horário seguinte ao último `last_run`; sem execução anterior, o seguinte ao instante em que o agendador nasceu
  (o horário que passou antes de o app abrir não conta para quem nunca rodou);
- vários horários perdidos com o app fechado viram UMA execução ao abrir, não uma rajada;
- só conta como executado o que o `Workspace.run_agent` de fato rodou. Sem preço fresco (mercado real) ele recusa e o agendador tenta no próximo ciclo,
  sem fazer barulho. Por isso há um atraso inicial: dá tempo de a primeira leitura de preços chegar antes de qualquer operação;
- pausado, manual ou com o agendador desligado nas Configurações: não roda.
"""

from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal

from .agent_config import vencida
from .workspace import Workspace

log = logging.getLogger(__name__)

INTERVALO_PADRAO_MS = 30_000
ATRASO_INICIAL_PADRAO_MS = 10_000


class Agendador(QObject):
    executou = Signal(str, int, str)  # (agente, decisões geradas, mensagem para o usuário)
    falhou = Signal(str)

    def __init__(self, workspace: Workspace, intervalo_ms: int = INTERVALO_PADRAO_MS, atraso_inicial_ms: int = ATRASO_INICIAL_PADRAO_MS):
        super().__init__()
        self.ws = workspace
        self._nascimento = workspace.mercado.agora()
        self._falhas: dict[str, str] = {}  # agente -> último erro avisado (não se repete a cada ciclo)
        self._ocupado = False
        self._atraso = QTimer(self)
        self._atraso.setSingleShot(True)
        self._atraso.setInterval(atraso_inicial_ms)
        self._atraso.timeout.connect(self._comecar)
        self._ciclo = QTimer(self)
        self._ciclo.setInterval(intervalo_ms)
        self._ciclo.timeout.connect(self.verificar)

    def iniciar(self) -> None:
        self._atraso.start()

    def parar(self) -> None:
        self._atraso.stop()
        self._ciclo.stop()

    def _comecar(self) -> None:
        self._ciclo.start()
        self.verificar()

    def verificar(self) -> None:
        """Roda os agentes vencidos agora. Chamado a cada ciclo; os testes chamam direto."""
        if self._ocupado or not self.ws.pref("agendador"):
            return
        self._ocupado = True
        try:
            agora = self.ws.mercado.agora()
            for agente in list(self.ws.agents):
                self._verificar_agente(agente, agora)
        finally:
            self._ocupado = False

    def _verificar_agente(self, agente, agora: datetime) -> None:
        cfg = agente.config
        try:
            referencia = datetime.fromisoformat(cfg.last_run) if cfg.last_run else self._nascimento
        except ValueError:
            referencia = self._nascimento
        if not vencida(cfg, referencia, agora):
            return
        antes = cfg.last_run
        try:
            feitas, mensagem = self.ws.run_agent(agente.id)
        except Exception as erro:  # noqa: BLE001 - um agente com defeito não pode parar os outros
            log.exception("agendador: falha ao rodar %s", agente.id)
            if self._falhas.get(agente.id) != str(erro):
                self._falhas[agente.id] = str(erro)
                self.falhou.emit(f"O agente “{agente.name}” falhou ao rodar sozinho: {erro}")
            return
        if agente.config.last_run == antes:
            return  # adiado (por exemplo, sem preço fresco no mercado real): tenta no próximo ciclo
        self._falhas.pop(agente.id, None)
        self.executou.emit(agente.id, feitas, mensagem)
