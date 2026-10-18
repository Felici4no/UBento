from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ubento.metas import ServicoMetas
from ubento.persistencia import Repositorio
from ubento.workspace import Workspace
from ubento.ui import theme
from ubento.ui.main_window import MainWindow

APP_NAME = "UBento"


def asset(name: str) -> Path:
    """Localiza arquivos em assets/ tanto no código-fonte quanto no app empacotado."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "assets" / name


def caminho_do_banco() -> Path:
    """Banco das metas: `UBENTO_DB` se definido, senão a pasta de dados do usuário (ex.: %LOCALAPPDATA%/UBento)."""
    if os.environ.get("UBENTO_DB"):
        return Path(os.environ["UBENTO_DB"])
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation) or str(Path.home() / ".ubento")
    return Path(base) / "ubento.db"


def main() -> int:
    if sys.platform == "win32":  # agrupa o ícone na barra de tarefas sob o UBento, não sob o python.exe
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ubento.app")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setFont(theme.font(13))
    app.setStyleSheet(theme.APP_QSS)
    icon = asset("ubento.svg")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    window = MainWindow(Workspace(QSettings(APP_NAME, APP_NAME)), metas=ServicoMetas(Repositorio(caminho_do_banco())))
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
