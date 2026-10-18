"""Formatação de números e datas para a interface (pt-BR)."""

from __future__ import annotations

from datetime import date, datetime

MONTHS_ABBR = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
MONTHS = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]


MASK = "••••"
_hidden = False


def set_hidden(hidden: bool) -> None:
    """Liga/desliga o modo privacidade: saldos e valores passam a ser mascarados."""
    global _hidden
    _hidden = hidden


def is_hidden() -> bool:
    return _hidden


def number(value: float, decimals: int = 2) -> str:
    """`1234.5` -> `1.234,50`."""
    text = f"{abs(value):,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-{text}" if value < 0 else text


def money(value: float) -> str:
    """`1234.5` -> `$1.234,50` (ou `$••••` no modo privacidade)."""
    if _hidden:
        return f"${MASK}"
    return f"${number(value, 2)}" if value >= 0 else f"-${number(abs(value), 2)}"


def split_money(value: float) -> tuple[str, str]:
    """Separa a parte inteira dos centavos, para destacar visualmente: ('$1.234', ',50')."""
    if _hidden:
        return f"${MASK}", ""
    text = money(value)
    head, _, cents = text.rpartition(",")
    return head, "," + cents


def compact(value: float) -> str:
    """`1240` -> `$1,2K`; `525` -> `$525`."""
    if _hidden:
        return f"${MASK}"
    if abs(value) >= 1000:
        return f"${number(value / 1000, 1)}K"
    return f"${number(value, 0)}"


def amount(value: float, decimals: int = 2) -> str:
    """Quantidade de um ativo (saldo); mascarada no modo privacidade."""
    return MASK if _hidden else number(value, decimals)


def pct(value: float) -> str:
    """`14.31` -> `14,3%` (sem sinal; a seta/cor indica a direção)."""
    return f"{number(abs(value), 2 if abs(value) < 1 else 1)}%"


def short_date(d: date | datetime, with_year: bool = False) -> str:
    base = f"{d.day} {MONTHS_ABBR[d.month - 1]}"
    return f"{base} {d.year}" if with_year else base


def ago(moment: datetime, now: datetime) -> str:
    seconds = (now - moment).total_seconds()
    if seconds < 60:
        return "Agora"
    if seconds < 3600:
        return f"há {int(seconds // 60)} min"
    if moment.date() == now.date():
        return f"há {int(seconds // 3600)} h"
    if (now.date() - moment.date()).days == 1:
        return "Ontem"
    return short_date(moment)
