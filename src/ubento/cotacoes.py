"""Tipo de dado de mercado do domínio: o que a carteira precisa saber de uma leitura de preços, venha ela de onde vier.

Os adaptadores (hoje `conexoes.mercado`, a API pública da Binance) dependem deste módulo, nunca o contrário.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Cotacoes:
    precos: dict[str, float]  # USD por unidade de cada ativo
    variacao_7d: dict[str, float]  # % em 7 dias (janela móvel); USD e USDT não variam
