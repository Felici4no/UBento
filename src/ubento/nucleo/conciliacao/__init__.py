"""Conciliação de execuções (e, separadamente, de saldos). Contrato em `docs/CONCILIACAO.md`."""

from .conciliador import conciliar, id_do_vinculo, vinculos_vigentes
from .eventos import EventoConciliacao, TipoEventoConciliacao, diferenciar
from .modelos import (
    Cobertura, CoberturaExecucoes, Confirmacao, Motivo, Movimentacao, PoliticaConciliacao, ProgressoMeta, RegistroExterno, RelatorioConciliacao,
    ResultadoExecucao, RevogacaoVinculo, SaldoObservado, StatusConciliacao, StatusRegistroExterno, StatusSaldo, TaxaExterna, TipoMovimentacao,
    VinculoManual,
)
from .reproducao import ArquivoReproducao, carregar_reproducao, executar, executar_momento, verificar

__all__ = [
    "ArquivoReproducao", "Cobertura", "CoberturaExecucoes", "Confirmacao", "EventoConciliacao", "Motivo", "Movimentacao", "PoliticaConciliacao",
    "ProgressoMeta", "RegistroExterno", "RelatorioConciliacao", "ResultadoExecucao", "RevogacaoVinculo", "SaldoObservado", "StatusConciliacao",
    "StatusRegistroExterno", "StatusSaldo", "TaxaExterna", "TipoEventoConciliacao", "TipoMovimentacao", "VinculoManual",
    "carregar_reproducao", "conciliar", "id_do_vinculo", "vinculos_vigentes", "diferenciar", "executar", "executar_momento", "verificar",
]
