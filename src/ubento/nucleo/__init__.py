"""Núcleo de análises e metas: tipos, esquema, carregamento seguro e hash canônico.

Sem Qt, sem rede e sem relógio do sistema. Contrato em `docs/ESPECIFICACAO_NUCLEO.md`.
"""

from .canonico import hash_canonico, hash_contrato, hash_documento, json_canonico
from .carregador import (
    ErroDeCarga, ErroDeValidacao, carregar_arquivo, carregar_texto, ler_json, ler_yaml, para_json, para_yaml, validar,
)
from .esquema import Analise, Ativacao, Avaliacao, Evento, Execucao, Meta
from .tipos import Direcao, Tri, arredondar, arredondar_para_baixo, arredondar_para_cima

__all__ = [
    "Analise", "Ativacao", "Avaliacao", "Direcao", "ErroDeCarga", "ErroDeValidacao", "Evento", "Execucao", "Meta", "Tri",
    "arredondar", "arredondar_para_baixo", "arredondar_para_cima", "carregar_arquivo", "carregar_texto", "hash_canonico",
    "hash_contrato", "hash_documento", "json_canonico", "ler_json", "ler_yaml", "para_json", "para_yaml", "validar",
]
