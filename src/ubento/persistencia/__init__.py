"""Persistência (SQLite) das metas. Fora do núcleo puro."""

from .repositorio import ErroDeContrato, ErroDePersistencia, ErroDeSequencia, Repositorio

__all__ = ["ErroDeContrato", "ErroDePersistencia", "ErroDeSequencia", "Repositorio"]
