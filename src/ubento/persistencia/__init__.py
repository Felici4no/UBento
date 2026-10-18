"""Persistência (SQLite) das metas. Fora do núcleo puro."""

from .repositorio import ErroBancoOcupado, ErroDeContrato, ErroDePersistencia, ErroDeSequencia, Repositorio

__all__ = ["ErroBancoOcupado", "ErroDeContrato", "ErroDePersistencia", "ErroDeSequencia", "Repositorio"]
