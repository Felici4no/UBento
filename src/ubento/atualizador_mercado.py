"""Lê as cotações da Binance em segundo plano, a cada `intervalo` segundos, sem travar a interface.

A leitura de rede roda numa thread própria que NÃO toca em nenhum objeto Qt: ela só põe o resultado numa fila. Um temporizador da thread da interface
esvazia a fila e emite os sinais, e quem aplica é o `Workspace`. (Emitir sinais direto de uma thread Python derrubava o processo de vez em quando.)
Só funciona enquanto estiver ativo: no modo simulado nada sai do computador.
"""

from __future__ import annotations

import queue
import threading

from PySide6.QtCore import QObject, QTimer, Signal

from .conexoes.binance import ErroDeConexao
from .conexoes.mercado import ClienteMercado

INTERVALO_PADRAO = 15.0
ENTREGA_MS = 100  # de quanto em quanto tempo a interface olha a fila


class AtualizadorDeMercado(QObject):
    cotacoes = Signal(object)  # Cotacoes
    falhou = Signal(str)

    def __init__(self, cliente: ClienteMercado | None = None, intervalo: float = INTERVALO_PADRAO):
        super().__init__()
        self._cliente = cliente or ClienteMercado()
        self._intervalo = intervalo
        self._parar: threading.Event | None = None
        self._thread: threading.Thread | None = None
        self._fila: queue.Queue = queue.Queue()
        self._entrega = QTimer(self)
        self._entrega.setInterval(ENTREGA_MS)
        self._entrega.timeout.connect(self._entregar)

    @property
    def ativo(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not (self._parar and self._parar.is_set())

    def definir_ativo(self, ligado: bool) -> None:
        self.iniciar() if ligado else self.parar()

    def iniciar(self) -> None:
        if self.ativo:
            return
        parar = self._parar = threading.Event()
        self._thread = threading.Thread(target=_ler_em_loop, args=(self._cliente, self._intervalo, self._fila, parar), name="ubento-mercado", daemon=True)
        self._thread.start()
        self._entrega.start()

    def parar(self) -> None:
        if self._parar is not None:
            self._parar.set()
        self._entrega.stop()
        self._esvaziar()  # o que a leitura em andamento ainda trouxer é descartado

    def _esvaziar(self) -> list:
        itens = []
        while True:
            try:
                itens.append(self._fila.get_nowait())
            except queue.Empty:
                return itens

    def _entregar(self) -> None:
        for leitura, tipo, valor in self._esvaziar():
            if leitura is self._parar and not leitura.is_set():  # só vale o que veio da leitura atual; a que foi desligada no meio não entra
                (self.cotacoes if tipo == "cotacoes" else self.falhou).emit(valor)


def _ler_em_loop(cliente, intervalo: float, fila: queue.Queue, parar: threading.Event) -> None:
    """Corpo da thread de rede. Função solta de propósito: se ela guardasse o QObject, o último a soltá-lo seria a thread, e um objeto Qt destruído fora
    da thread da interface derruba o processo."""
    while not parar.is_set():
        try:
            resultado = cliente.cotacoes()
        except ErroDeConexao as erro:
            fila.put((parar, "falhou", str(erro)))
        except Exception:  # noqa: BLE001 - uma falha inesperada não pode matar a leitura para sempre
            fila.put((parar, "falhou", "Erro inesperado ao ler os preços da Binance."))
        else:
            fila.put((parar, "cotacoes", resultado))
        parar.wait(intervalo)
