"""Cliente do Bot API do Telegram: verificar o token, ler mensagens (getUpdates) e responder (sendMessage). Sem dependências (`urllib`).

O token vai no CAMINHO da URL (`/bot<token>/método`), então nenhuma URL pode ir para log ou mensagem de erro: tudo passa por `_limpar`.
O transporte é injetável, então os testes nunca falam com a rede.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

from .binance import ErroDeConexao, Verificacao

BASE = "https://api.telegram.org"
TEMPO_LIMITE = 15.0
LIMITE_TEXTO = 4000  # o Telegram aceita 4096 caracteres por mensagem

# (método HTTP, url, dados do formulário ou None, tempo limite) -> (status HTTP, corpo)
Transporte = Callable[[str, str, "dict[str, str] | None", float], tuple[int, bytes]]


def transporte_http(metodo: str, url: str, dados: dict[str, str] | None, tempo_limite: float) -> tuple[int, bytes]:
    corpo = urllib.parse.urlencode(dados).encode() if dados is not None else None
    requisicao = urllib.request.Request(url, data=corpo, method=metodo)
    try:
        with urllib.request.urlopen(requisicao, timeout=tempo_limite) as resposta:  # noqa: S310 - URL fixa https
            return resposta.status, resposta.read()
    except urllib.error.HTTPError as erro:  # o Telegram explica o erro no corpo
        return erro.code, erro.read()
    except (urllib.error.URLError, TimeoutError, OSError) as erro:
        raise ErroDeConexao("Não foi possível falar com o Telegram. Confira a conexão com a internet e tente de novo.", type(erro).__name__) from erro


class ClienteTelegram:
    def __init__(self, token: str, transporte: Transporte = transporte_http, base: str = BASE):
        self._token, self._transporte, self._base = token, transporte, base

    def _limpar(self, texto: str) -> str:
        segredo = self._token.split(":", 1)[-1]
        return texto.replace(self._token, "***").replace(segredo, "***")

    def _chamar(self, metodo_api: str, dados: dict[str, str] | None = None, tempo_limite: float = TEMPO_LIMITE):
        status, corpo = self._transporte("POST" if dados is not None else "GET", f"{self._base}/bot{self._token}/{metodo_api}", dados, tempo_limite)
        try:
            resposta = json.loads(corpo.decode("utf-8")) if corpo else {}
        except ValueError:
            resposta = {}
        if status == 200 and isinstance(resposta, dict) and resposta.get("ok"):
            return resposta.get("result")
        descricao = resposta.get("description", "") if isinstance(resposta, dict) else ""
        tecnico = self._limpar(f"HTTP {status} {metodo_api}: {descricao}")
        if status in (401, 404):
            raise ErroDeConexao("O Telegram recusou o token. Copie o token inteiro que o @BotFather mostrou, sem espaços.", tecnico)
        if status == 409:
            raise ErroDeConexao("Outro programa está usando este bot (ou ele tem um webhook ativo). Só um programa por vez pode receber as mensagens do bot.", tecnico)
        if status == 429:
            raise ErroDeConexao("O Telegram limitou as requisições deste bot. Aguarde um pouco e tente de novo.", tecnico)
        if status >= 500:
            raise ErroDeConexao("O Telegram está indisponível no momento. Tente de novo em instantes.", tecnico)
        raise ErroDeConexao("O Telegram recusou o pedido.", tecnico)

    def verificar(self) -> Verificacao:
        """`getMe`: confirma que o token é de um bot e devolve o @usuário dele."""
        bot = self._chamar("getMe")
        if not isinstance(bot, dict) or not bot.get("is_bot"):
            raise ErroDeConexao("Este token não é de um bot do Telegram.", "getMe sem is_bot")
        usuario = bot.get("username") or str(bot.get("id"))
        return Verificacao(True, {}, (), f"Bot @{usuario} verificado.", extras={"bot_id": bot.get("id"), "bot_username": usuario})

    def atualizacoes(self, offset: int | None = None, espera: int = 0) -> list[dict]:
        """`getUpdates`. `espera` > 0 faz o Telegram segurar a resposta até chegar mensagem (long polling)."""
        dados = {"timeout": str(espera), "allowed_updates": json.dumps(["message"])}
        if offset is not None:
            dados["offset"] = str(offset)
        return self._chamar("getUpdates", dados, tempo_limite=TEMPO_LIMITE + espera) or []

    def descartar_pendentes(self) -> int | None:
        """Pula tudo o que foi enviado ao bot antes de agora (offset -1 confirma o passado). Devolve o próximo `offset`."""
        ultimas = self.atualizacoes(offset=-1)
        return ultimas[-1]["update_id"] + 1 if ultimas else None

    def enviar(self, chat_id: int, texto: str) -> None:
        """`sendMessage` em texto puro (sem Markdown: nada que o usuário digite vira formatação)."""
        for inicio in range(0, max(len(texto), 1), LIMITE_TEXTO):
            self._chamar("sendMessage", {"chat_id": str(chat_id), "text": texto[inicio:inicio + LIMITE_TEXTO] or "(vazio)", "disable_web_page_preview": "true"})
