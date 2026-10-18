"""Serialização canônica e hash dos contratos (`ubento.contrato.v1`).

Regras completas em `docs/ESPECIFICACAO_NUCLEO.md`, seção 3.1.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel

from .tipos import formatar_instante, normalizar_decimal

DOMINIO_CONTRATO = "ubento.contrato.v1"
DOMINIO_DOCUMENTO = "ubento.documento.v1"


class ErroCanonico(TypeError):
    """Valor que não tem representação canônica (ex.: float)."""


def canonicalizar(valor: Any, _caminho: str = "$") -> Any:
    """Converte estruturas Python em valores JSON canônicos (somente str, int, bool, None, list, dict)."""
    if isinstance(valor, BaseModel):
        return canonicalizar({nome: getattr(valor, nome) for nome in type(valor).model_fields}, _caminho)
    if valor is None or isinstance(valor, bool):
        return valor
    if isinstance(valor, float):
        raise ErroCanonico(f"{_caminho}: float não tem representação canônica; use Decimal")
    if isinstance(valor, int):
        return valor
    if isinstance(valor, Decimal):
        return normalizar_decimal(valor)
    if isinstance(valor, datetime):
        if valor.tzinfo is None:
            raise ErroCanonico(f"{_caminho}: data/hora sem fuso")
        return formatar_instante(valor)
    if isinstance(valor, Enum):
        return canonicalizar(valor.value, _caminho)
    if isinstance(valor, str):
        return unicodedata.normalize("NFC", valor)
    if isinstance(valor, dict):
        saida: dict[str, Any] = {}
        for chave, item in valor.items():
            if not isinstance(chave, str):
                raise ErroCanonico(f"{_caminho}: chave não textual {chave!r}")
            chave_nfc = unicodedata.normalize("NFC", chave)
            if chave_nfc in saida:
                raise ErroCanonico(f"{_caminho}: chave duplicada após normalização: {chave_nfc!r}")
            saida[chave_nfc] = canonicalizar(item, f"{_caminho}.{chave_nfc}")
        return saida
    if isinstance(valor, (list, tuple)):
        return [canonicalizar(item, f"{_caminho}[{i}]") for i, item in enumerate(valor)]
    if isinstance(valor, (set, frozenset)):
        raise ErroCanonico(f"{_caminho}: conjuntos não são canônicos; ordene na validação e use lista")
    raise ErroCanonico(f"{_caminho}: tipo sem representação canônica: {type(valor).__name__}")


def json_canonico(valor: Any) -> str:
    """JSON determinístico: chaves ordenadas, sem espaços, UTF-8 sem escape."""
    return json.dumps(canonicalizar(valor), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def hash_canonico(valor: Any, dominio: str) -> str:
    """SHA-256 hexadecimal de `dominio + "\\n" + json_canonico(valor)`."""
    return hashlib.sha256(f"{dominio}\n{json_canonico(valor)}".encode("utf-8")).hexdigest()


def hash_contrato(contrato: BaseModel) -> str:
    """Hash dos termos congelados de uma meta (nunca de estado, progresso ou ativação)."""
    return hash_canonico(contrato, DOMINIO_CONTRATO)


def hash_documento(documento: BaseModel) -> str:
    """Hash de um documento versionado (ex.: uma análise publicada)."""
    return hash_canonico(documento, DOMINIO_DOCUMENTO)
