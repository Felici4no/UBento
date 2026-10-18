"""Serviço de conexões: valida, verifica na corretora, guarda o segredo no cofre e os metadados no SQLite.

Regras:
  - o segredo e a chave de API vão SÓ para o cofre; o banco guarda um trecho mascarado e uma impressão (hash) para evitar duplicidade;
  - uma conexão só é criada depois de a corretora confirmar a chave e que ela é SOMENTE LEITURA (sem isso, nada é gravado);
  - segredos nunca entram em mensagens de erro nem em logs;
  - conectar não importa nem avalia nada: é só a credencial. A ingestão de dados virá depois, em outro passo.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from ..persistencia import Repositorio
from .binance import ErroDeConexao, Transporte, transporte_http
from .cofre import Cofre, ErroDeCofre
from .provedores import PROVEDORES

log = logging.getLogger("ubento.conexoes")

CONECTADA, REPROVADA, ERRO = "conectada", "reprovada", "erro"


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

    @property
    def nome_provedor(self) -> str:
        return PROVEDORES[self.provedor].nome


def mascarar(chave: str) -> str:
    return f"{chave[:4]}…{chave[-4:]}" if len(chave) >= 12 else "••••"


def _impressao(provedor: str, chave: str) -> str:
    return hashlib.sha256(f"{provedor}:{chave}".encode()).hexdigest()[:24]


class ServicoConexoes:
    def __init__(self, repo: Repositorio, cofre: Cofre, transporte: Transporte = transporte_http,
                 agora: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.repo, self.cofre, self.transporte, self.agora = repo, cofre, transporte, agora

    # -- consulta ----------------------------------------------------------------------------------------------------

    def listar(self) -> list[Conexao]:
        return [self._de_linha(r) for r in self.repo.conexoes()]

    @staticmethod
    def _de_linha(r) -> Conexao:
        return Conexao(
            id=r["id"], provedor=r["provedor"], apelido=r["apelido"], chave_mascarada=r["chave_mascarada"], status=r["status"],
            status_em=datetime.fromisoformat(r["status_em"]), mensagem=r["mensagem"], permissoes=json.loads(r["permissoes"]),
            criada_em=datetime.fromisoformat(r["criada_em"]),
        )

    # -- criação ---------------------------------------------------------------------------------------------------

    def _validar(self, provedor_id: str, credenciais: dict[str, str]) -> dict[str, str]:
        provedor = PROVEDORES.get(provedor_id)
        if provedor is None:
            raise ErroDeConfiguracao(f"provedor desconhecido: {provedor_id}")
        limpas: dict[str, str] = {}
        for campo in provedor.campos:
            valor = (credenciais.get(campo.nome) or "").strip()
            if not valor:
                raise ErroDeConfiguracao(f"Informe {campo.rotulo}.")
            if not re.fullmatch(r"[A-Za-z0-9]{16,128}", valor):
                raise ErroDeConfiguracao(f"{campo.rotulo} parece incompleto ou tem caracteres inválidos: use só letras e números, sem espaços.")
            limpas[campo.nome] = valor
        return limpas

    def _verificar(self, provedor_id: str, credenciais: dict[str, str]):
        cliente = PROVEDORES[provedor_id].criar_cliente(credenciais, self.transporte)
        try:
            return cliente.verificar()
        except ErroDeConexao as erro:
            log.warning("verificação de %s falhou: %s", provedor_id, erro.tecnico or erro)
            raise ErroDeConfiguracao(str(erro)) from erro

    # A criação é feita em TRÊS passos para a interface poder esperar a rede sem travar e sem usar o SQLite fora da sua thread:
    # `preparar` (valida e confere duplicidade; só banco), `verificar` (só rede) e `gravar` (cofre + banco). `adicionar` junta os três.

    def preparar(self, provedor_id: str, credenciais: dict[str, str]) -> dict[str, str]:
        limpas = self._validar(provedor_id, credenciais)
        if any(r["impressao"] == _impressao(provedor_id, limpas["api_key"]) for r in self.repo.conexoes()):
            raise ErroDeConfiguracao("Esta chave de API já está conectada.")
        return limpas

    def verificar(self, provedor_id: str, limpas: dict[str, str]):
        """SÓ rede (sem banco): seguro para rodar em outra thread. Reprova (ErroDeConfiguracao) chave com qualquer poder além da leitura."""
        verificacao = self._verificar(provedor_id, limpas)
        if not verificacao.somente_leitura:
            raise ErroDeConfiguracao(verificacao.mensagem)
        return verificacao

    def gravar(self, provedor_id: str, apelido: str, limpas: dict[str, str], verificacao) -> Conexao:
        chave = limpas["api_key"]
        ident = uuid.uuid4().hex[:12]
        agora = self.agora()
        try:
            for nome, valor in limpas.items():
                self.cofre.guardar(f"conexao:{ident}:{nome}", valor)
        except ErroDeCofre as erro:
            self._apagar_segredos(ident, limpas)
            raise ErroDeConfiguracao(f"Não foi possível guardar a chave com segurança: {erro}") from erro
        try:
            self.repo.salvar_conexao({
                "id": ident, "provedor": provedor_id, "apelido": (apelido or "").strip() or PROVEDORES[provedor_id].nome,
                "chave_mascarada": mascarar(chave), "impressao": _impressao(provedor_id, chave), "criada_em": agora.isoformat(), "status": CONECTADA,
                "status_em": agora.isoformat(), "permissoes": json.dumps(verificacao.permissoes), "mensagem": verificacao.mensagem,
            })
        except Exception:
            self._apagar_segredos(ident, limpas)  # sem linha no banco, o segredo não pode ficar órfão no cofre
            raise
        return next(c for c in self.listar() if c.id == ident)

    def adicionar(self, provedor_id: str, apelido: str, credenciais: dict[str, str]) -> Conexao:
        """Valida, verifica na corretora e, só se a chave for somente leitura, grava (segredos no cofre, metadados no banco)."""
        limpas = self.preparar(provedor_id, credenciais)
        return self.gravar(provedor_id, apelido, limpas, self.verificar(provedor_id, limpas))

    # -- manutenção ------------------------------------------------------------------------------------------------

    def credenciais_de(self, ident: str) -> tuple[Conexao, dict[str, str] | None]:
        """Lê a conexão e o segredo do cofre (None se o segredo sumiu). Só banco e cofre: roda na thread principal."""
        atual = next((c for c in self.listar() if c.id == ident), None)
        if atual is None:
            raise ErroDeConfiguracao("Conexão não encontrada.")
        credenciais = {n: self.cofre.ler(f"conexao:{ident}:{n}") for n in ("api_key", "api_secret")}
        return atual, (credenciais if all(credenciais.values()) else None)  # type: ignore[return-value]

    def conferir(self, atual: Conexao, credenciais: dict[str, str] | None):
        """SÓ rede: devolve (status, mensagem, permissões). Uma chave que ganhou poderes demais vira 'reprovada'."""
        if credenciais is None:
            return ERRO, "A chave não está mais no cofre deste computador. Remova a conexão e conecte de novo.", atual.permissoes
        try:
            v = self._verificar(atual.provedor, credenciais)
            return (CONECTADA if v.somente_leitura else REPROVADA), v.mensagem, v.permissoes
        except ErroDeConfiguracao as erro:
            return ERRO, str(erro), atual.permissoes

    def registrar_teste(self, ident: str, resultado) -> Conexao:
        status, mensagem, permissoes = resultado
        self.repo.atualizar_status_conexao(ident, status, self.agora().isoformat(), mensagem, json.dumps(permissoes))
        return next(c for c in self.listar() if c.id == ident)

    def testar(self, ident: str) -> Conexao:
        """Reverifica na corretora e atualiza o status (os três passos juntos)."""
        atual, credenciais = self.credenciais_de(ident)
        return self.registrar_teste(ident, self.conferir(atual, credenciais))

    def remover(self, ident: str) -> None:
        """Apaga o segredo do cofre e a conexão do banco. Só mexe na credencial local; nada na corretora (revogue a chave lá também)."""
        self._apagar_segredos(ident, {"api_key": "", "api_secret": ""})
        self.repo.remover_conexao(ident)

    def _apagar_segredos(self, ident: str, campos: dict[str, str]) -> None:
        for nome in campos:
            self.cofre.apagar(f"conexao:{ident}:{nome}")
