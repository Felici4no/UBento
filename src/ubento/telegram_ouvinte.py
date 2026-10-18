"""Ouvinte do bot: enquanto o UBento está aberto, lê as mensagens do bot (long polling) e responde SÓ ao chat vinculado.

- Mensagens de qualquer outro chat, grupo ou usuário são ignoradas em silêncio (nem uma resposta de "não autorizado": quem acha o bot não aprende nada).
- O que foi enviado ao bot com o app fechado é descartado ao iniciar (o app não responde a pedidos velhos).
- Erros de rede: tenta de novo com espera crescente. Conflito (outro programa ou webhook usando o bot): para e avisa.
- O texto das mensagens nunca vai para o log.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from .conexoes import ClienteTelegram, ErroDeConexao, ServicoConexoes

log = logging.getLogger("ubento.telegram")
ERRO_GENERICO = "Não consegui responder agora. Tente de novo em instantes."


class OuvinteTelegram:
    def __init__(self, cliente: ClienteTelegram, chat_id: int, responder: Callable[[str], str], espera: int = 20):
        self.cliente, self.chat_id, self.responder, self.espera = cliente, chat_id, responder, espera
        self.estado = "parado"  # parado | ouvindo | erro | conflito
        self.ignoradas = 0
        self._offset: int | None = None
        self._preparado = False
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None

    # -- uma rodada (testável sem thread) ------------------------------------------------------------------------------------

    def preparar(self) -> None:
        self._offset = self.cliente.descartar_pendentes()
        self._preparado = True

    def uma_rodada(self) -> int:
        """Busca mensagens novas e responde as do chat vinculado. Devolve quantas respondeu."""
        if not self._preparado:
            self.preparar()
        respondidas = 0
        for u in self.cliente.atualizacoes(offset=self._offset, espera=self.espera):
            self._offset = u["update_id"] + 1
            m = u.get("message")
            if not m:
                continue
            chat, remetente = m.get("chat") or {}, m.get("from") or {}
            if chat.get("type") != "private" or chat.get("id") != self.chat_id or remetente.get("id") != self.chat_id:
                self.ignoradas += 1
                log.info("mensagem ignorada: chat não vinculado")  # sem identificar o remetente nem o conteúdo
                continue
            texto = m.get("text") or ""
            try:
                resposta = self.responder(texto) if texto.startswith("/") else "Envie /ajuda para ver os comandos."
            except Exception:  # noqa: BLE001 - o detalhe técnico vai para o log, a pessoa recebe uma frase simples
                log.exception("falha ao montar a resposta")
                resposta = ERRO_GENERICO
            self.cliente.enviar(self.chat_id, resposta)
            respondidas += 1
        return respondidas

    # -- thread -----------------------------------------------------------------------------------------------------------------

    def iniciar(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._parar.clear()
        self._thread = threading.Thread(target=self._laco, name="ubento-telegram", daemon=True)
        self._thread.start()

    def parar(self, esperar: float = 0) -> None:
        self._parar.set()
        if esperar and self._thread:
            self._thread.join(esperar)

    def _laco(self) -> None:
        espera = 1.0
        while not self._parar.is_set():
            try:
                self.uma_rodada()
                self.estado, espera = "ouvindo", 1.0
            except ErroDeConexao as erro:
                if (erro.tecnico or "").startswith("HTTP 409"):
                    self.estado = "conflito"
                    log.error("o bot está em uso por outro programa (ou tem webhook): ouvinte parado (%s)", erro.tecnico)
                    break
                self.estado = "erro"
                log.warning("falha de rede no ouvinte (tenta de novo em %.0fs): %s", espera, erro.tecnico or erro)
                self._parar.wait(espera)
                espera = min(60.0, espera * 2)
            except Exception:  # noqa: BLE001
                self.estado = "erro"
                log.exception("falha inesperada no ouvinte")
                self._parar.wait(espera)
                espera = min(60.0, espera * 2)
        if self.estado != "conflito":
            self.estado = "parado"


class GerenteOuvintes:
    """Mantém um ouvinte por bot vinculado. Use na thread principal (lê banco e cofre)."""

    def __init__(self, servico: ServicoConexoes, responder: Callable[[], Callable[[str], str]], criar: Callable[..., OuvinteTelegram] = OuvinteTelegram, espera: int = 20):
        self.servico, self._responder, self._criar, self._espera = servico, responder, criar, espera
        self.ouvintes: dict[str, OuvinteTelegram] = {}

    def iniciar(self, ident: str) -> OuvinteTelegram | None:
        self.parar(ident)
        conexao, cliente = self.servico.cliente_telegram(ident)
        if not conexao.chat_vinculado or conexao.status != "conectada":
            return None  # sem chat vinculado o bot não atende ninguém
        ouvinte = self._criar(cliente, int(conexao.detalhes["chat_id"]), self._responder(), self._espera)
        self.ouvintes[ident] = ouvinte
        ouvinte.iniciar()
        return ouvinte

    def iniciar_todos(self) -> None:
        for c in self.servico.listar():
            if c.provedor == "telegram":
                try:
                    self.iniciar(c.id)
                except Exception:  # noqa: BLE001 - uma conexão quebrada não impede as outras nem o app
                    log.exception("não foi possível iniciar o ouvinte")

    def parar(self, ident: str) -> None:
        ouvinte = self.ouvintes.pop(ident, None)
        if ouvinte:
            ouvinte.parar()

    def parar_todos(self) -> None:
        for ident in list(self.ouvintes):
            self.parar(ident)

    def estado(self, ident: str) -> str:
        return self.ouvintes[ident].estado if ident in self.ouvintes else "parado"
