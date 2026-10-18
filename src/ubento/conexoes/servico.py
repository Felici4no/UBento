"""Serviço de conexões: valida, verifica no provedor, guarda o segredo no cofre e os metadados no SQLite.

Regras:
  - o segredo (chave de API, token) vai SÓ para o cofre; o banco guarda um trecho mascarado e uma impressão (hash) para evitar duplicidade;
  - uma conexão só é criada depois de o provedor confirmar a credencial (e, numa corretora, que ela é SOMENTE LEITURA); senão nada é gravado;
  - segredos nunca entram em mensagens de erro nem em logs;
  - conectar não importa nem avalia nada: é só a credencial.
  - Telegram: o bot só atende o chat que a pessoa vincular, com um código de uso único (ver `iniciar_vinculo`).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ..persistencia import Repositorio
from . import binance, telegram
from .binance import ErroDeConexao
from .cofre import Cofre, ErroDeCofre
from .provedores import PROVEDORES

log = logging.getLogger("ubento.conexoes")

CONECTADA, REPROVADA, ERRO = "conectada", "reprovada", "erro"
VALIDADE_DO_CODIGO = timedelta(minutes=10)


class ErroDeConfiguracao(ValueError):
    """Dados da conexão recusados. A mensagem é para o usuário e nunca contém segredo."""


@dataclass(frozen=True)
class Conexao:
    id: str
    provedor: str
    apelido: str
    chave_mascarada: str
    status: str  # conectada | reprovada | erro
    status_em: datetime
    mensagem: str
    permissoes: dict[str, bool]
    criada_em: datetime
    detalhes: dict[str, Any]  # específicos do provedor (ex.: @usuário do bot, chat vinculado). Nunca segredos

    @property
    def nome_provedor(self) -> str:
        return PROVEDORES[self.provedor].nome

    @property
    def chat_vinculado(self) -> bool:
        return self.detalhes.get("chat_id") is not None


@dataclass(frozen=True)
class ChatEncontrado:
    chat_id: int
    nome: str
    proximo_offset: int


def mascarar(chave: str, provedor: str = "") -> str:
    if provedor == "telegram" and ":" in chave:  # o número do bot é público; do resto só os 4 últimos
        return f"{chave.split(':', 1)[0]}:••••{chave[-4:]}"
    return f"{chave[:4]}…{chave[-4:]}" if len(chave) >= 12 else "••••"


def _impressao(provedor: str, chave: str) -> str:
    return hashlib.sha256(f"{provedor}:{chave}".encode()).hexdigest()[:24]


def _nomes(provedor: str) -> list[str]:
    return [c.nome for c in PROVEDORES[provedor].campos]


class ServicoConexoes:
    def __init__(self, repo: Repositorio, cofre: Cofre, transporte: binance.Transporte = binance.transporte_http,
                 agora: Callable[[], datetime] = lambda: datetime.now(timezone.utc), transporte_telegram: telegram.Transporte = telegram.transporte_http):
        self.repo, self.cofre, self.agora = repo, cofre, agora
        self.transportes: dict[str, Any] = {"binance": transporte, "telegram": transporte_telegram}
        self._codigos: dict[str, tuple[str, datetime]] = {}  # códigos de vínculo: só em memória e de uso único

    # -- consulta ----------------------------------------------------------------------------------------------------

    def listar(self) -> list[Conexao]:
        return [self._de_linha(r) for r in self.repo.conexoes()]

    @staticmethod
    def _de_linha(r) -> Conexao:
        return Conexao(
            id=r["id"], provedor=r["provedor"], apelido=r["apelido"], chave_mascarada=r["chave_mascarada"], status=r["status"],
            status_em=datetime.fromisoformat(r["status_em"]), mensagem=r["mensagem"], permissoes=json.loads(r["permissoes"]),
            criada_em=datetime.fromisoformat(r["criada_em"]), detalhes=json.loads(r["detalhes"]),
        )

    def obter(self, ident: str) -> Conexao:
        c = next((c for c in self.listar() if c.id == ident), None)
        if c is None:
            raise ErroDeConfiguracao("Conexão não encontrada.")
        return c

    # -- criação ---------------------------------------------------------------------------------------------------

    def _validar(self, provedor_id: str, credenciais: dict[str, str]) -> dict[str, str]:
        provedor = PROVEDORES.get(provedor_id)
        if provedor is None:
            raise ErroDeConfiguracao(f"provedor desconhecido: {provedor_id}")
        if not provedor.disponivel or provedor.criar_cliente is None:
            raise ErroDeConfiguracao(f"{provedor.nome} ainda não está disponível para conexão (em breve).")
        limpas: dict[str, str] = {}
        for campo in provedor.campos:
            valor = (credenciais.get(campo.nome) or "").strip()
            if not valor:
                raise ErroDeConfiguracao(f"Informe {campo.rotulo}.")
            if not re.fullmatch(campo.padrao, valor):
                raise ErroDeConfiguracao(f"{campo.rotulo} parece incompleto ou tem caracteres inválidos: {campo.erro_de_formato}.")
            limpas[campo.nome] = valor
        return limpas

    def _cliente(self, provedor_id: str, credenciais: dict[str, str]):
        return PROVEDORES[provedor_id].criar_cliente(credenciais, self.transportes[provedor_id])

    def _verificar(self, provedor_id: str, credenciais: dict[str, str]):
        try:
            return self._cliente(provedor_id, credenciais).verificar()
        except ErroDeConexao as erro:
            log.warning("verificação de %s falhou: %s", provedor_id, erro.tecnico or erro)
            raise ErroDeConfiguracao(str(erro)) from erro

    # A criação é feita em TRÊS passos para a interface poder esperar a rede sem travar e sem usar o SQLite fora da sua thread:
    # `preparar` (valida e confere duplicidade; só banco), `verificar` (só rede) e `gravar` (cofre + banco). `adicionar` junta os três.

    def preparar(self, provedor_id: str, credenciais: dict[str, str]) -> dict[str, str]:
        limpas = self._validar(provedor_id, credenciais)
        principal = limpas[_nomes(provedor_id)[0]]
        if any(r["impressao"] == _impressao(provedor_id, principal) for r in self.repo.conexoes()):
            raise ErroDeConfiguracao("Esta credencial já está conectada.")
        return limpas

    def verificar(self, provedor_id: str, limpas: dict[str, str]):
        """SÓ rede (sem banco): seguro para rodar em outra thread. Numa corretora, reprova chave com qualquer poder além da leitura."""
        verificacao = self._verificar(provedor_id, limpas)
        if not verificacao.somente_leitura:
            raise ErroDeConfiguracao(verificacao.mensagem)
        return verificacao

    def gravar(self, provedor_id: str, apelido: str, limpas: dict[str, str], verificacao) -> Conexao:
        principal = limpas[_nomes(provedor_id)[0]]
        ident = uuid.uuid4().hex[:12]
        agora = self.agora()
        try:
            for nome, valor in limpas.items():
                self.cofre.guardar(f"conexao:{ident}:{nome}", valor)
        except ErroDeCofre as erro:
            self._apagar_segredos(ident, provedor_id)
            raise ErroDeConfiguracao(f"Não foi possível guardar a credencial com segurança: {erro}") from erro
        try:
            self.repo.salvar_conexao({
                "id": ident, "provedor": provedor_id, "apelido": (apelido or "").strip() or PROVEDORES[provedor_id].nome,
                "chave_mascarada": mascarar(principal, provedor_id), "impressao": _impressao(provedor_id, principal), "criada_em": agora.isoformat(),
                "status": CONECTADA, "status_em": agora.isoformat(), "permissoes": json.dumps(verificacao.permissoes), "mensagem": verificacao.mensagem,
                "detalhes": json.dumps(verificacao.extras),
            })
        except Exception:
            self._apagar_segredos(ident, provedor_id)  # sem linha no banco, o segredo não pode ficar órfão no cofre
            raise
        return self.obter(ident)

    def adicionar(self, provedor_id: str, apelido: str, credenciais: dict[str, str]) -> Conexao:
        """Valida, verifica no provedor e só então grava (segredos no cofre, metadados no banco)."""
        limpas = self.preparar(provedor_id, credenciais)
        return self.gravar(provedor_id, apelido, limpas, self.verificar(provedor_id, limpas))

    # -- manutenção ------------------------------------------------------------------------------------------------

    def credenciais_de(self, ident: str) -> tuple[Conexao, dict[str, str] | None]:
        """Lê a conexão e o segredo do cofre (None se o segredo sumiu). Só banco e cofre: roda na thread principal."""
        atual = self.obter(ident)
        credenciais = {n: self.cofre.ler(f"conexao:{ident}:{n}") for n in _nomes(atual.provedor)}
        return atual, (credenciais if all(credenciais.values()) else None)  # type: ignore[return-value]

    def conferir(self, atual: Conexao, credenciais: dict[str, str] | None):
        """SÓ rede: devolve (status, mensagem, permissões). Uma chave que ganhou poderes demais vira 'reprovada'."""
        if credenciais is None:
            return ERRO, "A credencial não está mais no cofre deste computador. Remova a conexão e conecte de novo.", atual.permissoes
        try:
            v = self._verificar(atual.provedor, credenciais)
            return (CONECTADA if v.somente_leitura else REPROVADA), v.mensagem, v.permissoes
        except ErroDeConfiguracao as erro:
            return ERRO, str(erro), atual.permissoes

    def registrar_teste(self, ident: str, resultado) -> Conexao:
        status, mensagem, permissoes = resultado
        self.repo.atualizar_status_conexao(ident, status, self.agora().isoformat(), mensagem, json.dumps(permissoes))
        return self.obter(ident)

    def testar(self, ident: str) -> Conexao:
        """Reverifica no provedor e atualiza o status (os três passos juntos)."""
        atual, credenciais = self.credenciais_de(ident)
        return self.registrar_teste(ident, self.conferir(atual, credenciais))

    def remover(self, ident: str) -> None:
        """Apaga o segredo do cofre e a conexão do banco. Só mexe na credencial local; nada no provedor (revogue a chave/token lá também)."""
        atual = self.obter(ident)
        self._apagar_segredos(ident, atual.provedor)
        self._codigos.pop(ident, None)
        self.repo.remover_conexao(ident)

    def _apagar_segredos(self, ident: str, provedor_id: str) -> None:
        for nome in _nomes(provedor_id):
            self.cofre.apagar(f"conexao:{ident}:{nome}")

    # -- Telegram: vincular o chat que será atendido -----------------------------------------------------------------------------------------

    def _telegram(self, ident: str) -> tuple[Conexao, telegram.ClienteTelegram]:
        atual, credenciais = self.credenciais_de(ident)
        if atual.provedor != "telegram":
            raise ErroDeConfiguracao("Esta conexão não é um bot do Telegram.")
        if credenciais is None:
            raise ErroDeConfiguracao("O token não está mais no cofre deste computador. Remova a conexão e conecte de novo.")
        return atual, self._cliente("telegram", credenciais)

    # Cada operação de rede tem a sua versão "em passos" (preparar na thread principal, só rede em outra thread, concluir na principal),
    # porque o SQLite e o cofre só podem ser usados na thread da interface. As versões compostas (`iniciar_vinculo`, `procurar_vinculo`,
    # `enviar_teste`) juntam os passos e servem a testes e a quem não tem interface.

    def preparar_vinculo(self, ident: str) -> telegram.ClienteTelegram:
        return self._telegram(ident)[1]

    def descartar_pendentes(self, cliente: telegram.ClienteTelegram) -> int | None:
        """SÓ rede: pula o que já estava na fila do bot e devolve o offset a partir do qual procurar."""
        try:
            return cliente.descartar_pendentes()
        except ErroDeConexao as erro:
            log.warning("não foi possível preparar o vínculo: %s", erro.tecnico or erro)
            raise ErroDeConfiguracao(str(erro)) from erro

    def novo_codigo(self, ident: str) -> str:
        """Código de uso único (8 hex, válido por 10 min, só em memória)."""
        codigo = secrets.token_hex(4).upper()
        self._codigos[ident] = (codigo, self.agora() + VALIDADE_DO_CODIGO)
        return codigo

    def iniciar_vinculo(self, ident: str) -> tuple[str, int | None]:
        cliente = self.preparar_vinculo(ident)
        return self.novo_codigo(ident), self.descartar_pendentes(cliente)

    def preparar_busca(self, ident: str) -> telegram.ClienteTelegram:
        codigo = self._codigos.get(ident)
        if codigo is None:
            raise ErroDeConfiguracao("Gere um código de vínculo primeiro.")
        if self.agora() > codigo[1]:
            self._codigos.pop(ident, None)
            raise ErroDeConfiguracao("O código expirou. Gere outro.")
        return self._telegram(ident)[1]

    def buscar_atualizacoes(self, cliente: telegram.ClienteTelegram, offset: int | None) -> list[dict]:
        """SÓ rede: UMA rodada de espera (2 s) por mensagens novas do bot."""
        try:
            return cliente.atualizacoes(offset=offset, espera=2)
        except ErroDeConexao as erro:
            log.warning("falha ao procurar o vínculo: %s", erro.tecnico or erro)
            raise ErroDeConfiguracao(str(erro)) from erro

    def interpretar(self, ident: str, atualizacoes: list[dict], offset: int | None) -> tuple[ChatEncontrado | None, int | None]:
        """Procura, nas mensagens, `/vincular CODIGO` (ou `/start CODIGO`) vindo de um chat PRIVADO. Mensagens de grupos, de outros
        chats ou com código errado são ignoradas em silêncio. Devolve (chat ou None, próximo offset)."""
        codigo = self._codigos.get(ident)
        if codigo is None:
            raise ErroDeConfiguracao("Gere um código de vínculo primeiro.")
        proximo = offset
        for u in atualizacoes:
            proximo = u["update_id"] + 1
            m = u.get("message") or {}
            chat, texto = m.get("chat") or {}, (m.get("text") or "").strip()
            partes = texto.split()
            if chat.get("type") != "private" or len(partes) != 2 or partes[0].split("@")[0] not in ("/vincular", "/start"):
                continue
            if hmac.compare_digest(partes[1].upper(), codigo[0]):
                quem = m.get("from") or {}
                nome = " ".join(x for x in (quem.get("first_name"), quem.get("last_name")) if x) or str(chat.get("id"))
                return ChatEncontrado(int(chat["id"]), nome, proximo), proximo
        return None, proximo

    def procurar_vinculo(self, ident: str, offset: int | None) -> tuple[ChatEncontrado | None, int | None]:
        cliente = self.preparar_busca(ident)
        return self.interpretar(ident, self.buscar_atualizacoes(cliente, offset), offset)

    def concluir_vinculo(self, ident: str, chat: ChatEncontrado) -> Conexao:
        """Grava o chat vinculado (só id e nome, nada secreto) e inutiliza o código."""
        atual = self.obter(ident)
        detalhes = {**atual.detalhes, "chat_id": chat.chat_id, "chat_nome": chat.nome, "vinculado_em": self.agora().isoformat()}
        self.repo.atualizar_detalhes_conexao(ident, json.dumps(detalhes))
        self._codigos.pop(ident, None)
        return self.obter(ident)

    def desvincular(self, ident: str) -> Conexao:
        atual = self.obter(ident)
        detalhes = {k: v for k, v in atual.detalhes.items() if k not in ("chat_id", "chat_nome", "vinculado_em")}
        self.repo.atualizar_detalhes_conexao(ident, json.dumps(detalhes))
        return self.obter(ident)

    def preparar_teste(self, ident: str) -> tuple[int, telegram.ClienteTelegram]:
        atual, cliente = self._telegram(ident)
        if not atual.chat_vinculado:
            raise ErroDeConfiguracao("Vincule um chat antes de enviar um teste.")
        return int(atual.detalhes["chat_id"]), cliente

    @staticmethod
    def enviar_teste_rede(cliente: telegram.ClienteTelegram, chat_id: int) -> None:
        """SÓ rede: manda a mensagem de teste ao chat vinculado."""
        try:
            cliente.enviar(chat_id, "UBento conectado. Envie /ajuda para ver o que eu respondo. "
                           "Respondo só a você, e só enquanto o UBento estiver aberto no computador.")
        except ErroDeConexao as erro:
            log.warning("falha ao enviar o teste: %s", erro.tecnico or erro)
            raise ErroDeConfiguracao(str(erro)) from erro

    def enviar_teste(self, ident: str) -> None:
        chat_id, cliente = self.preparar_teste(ident)
        self.enviar_teste_rede(cliente, chat_id)

    def cliente_telegram(self, ident: str) -> tuple[Conexao, telegram.ClienteTelegram]:
        """Para o ouvinte: a conexão e um cliente já com o token do cofre (banco e cofre: thread principal)."""
        return self._telegram(ident)
