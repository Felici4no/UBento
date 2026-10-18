"""Onde ficam os dados do UBento. Sem Qt: serve ao app e ao MCP local, que precisam apontar para o MESMO banco."""

from __future__ import annotations

import os
import sys
from pathlib import Path

NOME = "UBento"


def pasta_de_dados() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / NOME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / NOME
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / NOME


def caminho_do_banco() -> Path:
    """`UBENTO_DB` se definido; senão a pasta de dados do usuário (ex.: %LOCALAPPDATA%/UBento/ubento.db)."""
    return Path(os.environ["UBENTO_DB"]) if os.environ.get("UBENTO_DB") else pasta_de_dados() / "ubento.db"
