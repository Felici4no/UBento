"""Tipos básicos do núcleo: lógica de três valores, decimais estritos, instantes em UTC e arredondamento.

Nada aqui conhece Qt, rede ou o relógio do sistema.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, Field, StringConstraints


class Tri(StrEnum):
    """Resultado de uma condição: nunca se confunde "não sei" com "falso"."""

    VERDADEIRO = "verdadeiro"
    FALSO = "falso"
    INDETERMINADO = "indeterminado"


class Direcao(StrEnum):
    """Para onde arredondar. Cada fórmula escolhe, não existe valor padrão."""

    BAIXO = "baixo"
    CIMA = "cima"


# -- decimais ------------------------------------------------------------------------

MAX_DIGITOS = 40  # evita entradas patológicas (ex.: "1e999999999")


class ErroDeTipo(ValueError):
    """Valor que não pode virar um tipo do núcleo."""


def para_decimal(valor: object) -> Decimal:
    """Converte texto, inteiro ou Decimal em Decimal finito. `float` e `bool` são rejeitados.

    Nunca há conversão a partir de `float`: ela já chega com erro de representação.
    """
    if isinstance(valor, bool) or isinstance(valor, float):
        raise ErroDeTipo(f"use texto decimal entre aspas, não {type(valor).__name__}: {valor!r}")
    if isinstance(valor, Decimal):
        numero = valor
    elif isinstance(valor, (int, str)):
        texto = str(valor).strip()
        if not texto or len(texto) > MAX_DIGITOS + 8:
            raise ErroDeTipo(f"decimal inválido: {texto[:20]!r}")
        try:
            numero = Decimal(texto)
        except InvalidOperation as erro:
            raise ErroDeTipo(f"decimal inválido: {texto!r}") from erro
    else:
        raise ErroDeTipo(f"esperava texto decimal, recebeu {type(valor).__name__}")
    if not numero.is_finite():
        raise ErroDeTipo(f"decimal não finito: {valor!r}")
    if abs(numero.adjusted()) > MAX_DIGITOS or len(numero.as_tuple().digits) > MAX_DIGITOS:
        raise ErroDeTipo(f"decimal fora do limite de {MAX_DIGITOS} dígitos: {valor!r}")
    return numero


def normalizar_decimal(valor: Decimal) -> str:
    """Forma textual canônica: sem expoente, sem zeros inúteis, `-0` vira `0`.

    `"1.0"`, `"1.00"` e `"1"` produzem `"1"`.
    """
    if valor == 0:
        return "0"
    texto = format(valor.normalize(), "f")
    return texto


def _nao_negativo(valor: Decimal) -> Decimal:
    if valor < 0:
        raise ValueError("não pode ser negativo")
    return valor


def _positivo(valor: Decimal) -> Decimal:
    if valor <= 0:
        raise ValueError("deve ser maior que zero")
    return valor


def _razao_0_1(valor: Decimal) -> Decimal:
    if not (0 <= valor <= 1):
        raise ValueError("deve estar entre 0 e 1 (ex.: '0.05' para 5%)")
    return valor


Numero = Annotated[Decimal, BeforeValidator(para_decimal)]
"""Decimal com qualquer sinal (ex.: retorno, variação)."""
Quantidade = Annotated[Decimal, BeforeValidator(para_decimal), AfterValidator(_nao_negativo)]
Positivo = Annotated[Decimal, BeforeValidator(para_decimal), AfterValidator(_positivo)]
Razao = Annotated[Decimal, BeforeValidator(para_decimal)]
"""Percentual como razão decimal: `"0.05"` é 5%. Sem limites; use `Fracao` quando for entre 0 e 1."""
Fracao = Annotated[Decimal, BeforeValidator(para_decimal), AfterValidator(_razao_0_1)]


# -- instantes -------------------------------------------------------------------------


def para_instante(valor: object) -> datetime:
    """Texto ISO 8601 **com fuso** (ou datetime com fuso) → datetime em UTC. Sem fuso é erro."""
    if isinstance(valor, str):
        texto = valor.strip()
        try:
            momento = datetime.fromisoformat(texto.replace("Z", "+00:00") if texto.endswith("Z") else texto)
        except ValueError as erro:
            raise ErroDeTipo(f"data/hora ISO 8601 inválida: {valor!r}") from erro
    elif isinstance(valor, datetime):
        momento = valor
    else:
        raise ErroDeTipo(f"esperava data/hora ISO 8601 entre aspas, recebeu {type(valor).__name__}")
    if momento.tzinfo is None or momento.utcoffset() is None:
        raise ErroDeTipo(f"data/hora sem fuso horário: {valor!r} (use ex.: 2026-10-18T12:00:00-03:00 ou ...Z)")
    return momento.astimezone(UTC)


Instante = Annotated[datetime, BeforeValidator(para_instante)]


def formatar_instante(momento: datetime) -> str:
    """UTC canônico: `YYYY-MM-DDTHH:MM:SSZ`, com microssegundos só se existirem."""
    momento = momento.astimezone(UTC)
    base = momento.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{momento.microsecond:06d}Z" if momento.microsecond else f"{base}Z"


# -- textos --------------------------------------------------------------------------------

IDENTIFICADOR_RE = r"^[a-z0-9][a-z0-9_.:@-]{0,63}$"
Identificador = Annotated[str, StringConstraints(pattern=IDENTIFICADOR_RE, strict=True)]
"""Identificador estável: minúsculas, dígitos e `_ . : @ -`; até 64 caracteres."""
Texto = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000, strict=True)]
Unidade = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_./%-]{1,24}$", strict=True)]
HashHex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$", strict=True)]
Inteiro = Annotated[int, Field(strict=True)]



# -- arredondamento ----------------------------------------------------------------------------


def arredondar_para_baixo(valor: Decimal, passo: Decimal) -> Decimal:
    """Maior múltiplo exato de `passo` que não excede `valor`."""
    return _arredondar(valor, passo, ROUND_FLOOR)


def arredondar_para_cima(valor: Decimal, passo: Decimal) -> Decimal:
    """Menor múltiplo exato de `passo` que não é menor que `valor`."""
    return _arredondar(valor, passo, ROUND_CEILING)


def arredondar(valor: Decimal, passo: Decimal, direcao: Direcao) -> Decimal:
    return arredondar_para_baixo(valor, passo) if direcao is Direcao.BAIXO else arredondar_para_cima(valor, passo)


def _arredondar(valor: Decimal, passo: Decimal, modo: str) -> Decimal:
    if passo <= 0:
        raise ValueError("o passo de arredondamento deve ser positivo")
    passos = (valor / passo).to_integral_value(rounding=modo)
    return passos * passo
