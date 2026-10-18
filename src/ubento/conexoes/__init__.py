"""Conexões com corretoras (credenciais somente leitura). Os dados virão depois; aqui só a credencial e sua verificação."""

from .binance import ClienteBinance, ErroDeConexao, Verificacao, transporte_http
from .cofre import Cofre, CofreMemoria, ErroDeCofre, cofre_padrao
from .provedores import PROVEDORES, Campo, Provedor
from .servico import CONECTADA, ERRO, REPROVADA, ChatEncontrado, Conexao, ErroDeConfiguracao, ServicoConexoes
from .telegram import ClienteTelegram

__all__ = [
    "CONECTADA", "Campo", "ChatEncontrado", "ClienteBinance", "ClienteTelegram", "Cofre", "CofreMemoria", "Conexao", "ERRO", "ErroDeCofre", "ErroDeConexao", "ErroDeConfiguracao", "PROVEDORES",
    "Provedor", "REPROVADA", "ServicoConexoes", "Verificacao", "cofre_padrao", "transporte_http",
]
