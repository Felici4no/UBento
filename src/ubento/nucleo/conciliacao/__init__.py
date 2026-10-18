"""Conciliação de execuções (e, separadamente, de saldos). Contrato em `docs/CONCILIACAO.md`."""

from .conciliador import conciliar
from .eventos import EventoConciliacao, TipoEventoConciliacao, diferenciar
from .modelos import (
    Cobertura, Confirmacao, Motivo, Movimentacao, PoliticaConciliacao, ProgressoMeta, RegistroExterno, RelatorioConciliacao,
    ResultadoExecucao, SaldoObservado, StatusConciliacao, StatusRegistroExterno, StatusSaldo, TaxaExterna, TipoMovimentacao,
    VinculoManual,
)
from .reproducao import ArquivoReproducao, carregar_reproducao, executar, executar_momento, verificar

__all__ = [
    "ArquivoReproducao", "Cobertura", "Confirmacao", "EventoConciliacao", "Motivo", "Movimentacao", "PoliticaConciliacao",
    "ProgressoMeta", "RegistroExterno", "RelatorioConciliacao", "ResultadoExecucao", "SaldoObservado", "StatusConciliacao",
    "StatusRegistroExterno", "StatusSaldo", "TaxaExterna", "TipoEventoConciliacao", "TipoMovimentacao", "VinculoManual",
    "carregar_reproducao", "conciliar", "diferenciar", "executar", "executar_momento", "verificar",
]
