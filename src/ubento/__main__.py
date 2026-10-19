from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ubento.atualizador_mercado import AtualizadorDeMercado
from ubento.caminhos import caminho_do_banco
from ubento.conexoes import ServicoConexoes, cofre_padrao
from ubento.consulta import abrir
from ubento.metas import ServicoMetas
from ubento.telegram_comandos import responder
from ubento.telegram_ouvinte import GerenteOuvintes
from ubento.persistencia import Repositorio
from ubento.workspace import Workspace
from ubento.ui import theme
from ubento.ui.main_window import MainWindow

APP_NAME = "UBento"


def asset(name: str) -> Path:
    """Localiza arquivos em assets/ tanto no código-fonte quanto no app empacotado."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "assets" / name


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

    banco = caminho_do_banco()
    metas = ServicoMetas(Repositorio(banco))
    conexoes = ServicoConexoes(metas.repo, cofre_padrao(banco.parent))  # segredos no cofre do sistema, ao lado do banco
    # o bot do Telegram atende o chat vinculado enquanto o app estiver aberto; cada mensagem abre o banco SOMENTE para leitura
    ouvintes = GerenteOuvintes(conexoes, lambda: (lambda texto: responder(texto, lambda: abrir(banco))))
    workspace = Workspace(QSettings(APP_NAME, APP_NAME))
    window = MainWindow(workspace, metas=metas, conexoes=conexoes, ouvintes=ouvintes)
    ouvintes.iniciar_todos()
    app.aboutToQuit.connect(ouvintes.parar_todos)
    # preços públicos da Binance: só lidos enquanto o modo mercado real estiver ligado (no simulado nada sai do computador)
    mercado = AtualizadorDeMercado()
    mercado.cotacoes.connect(workspace.receber_cotacoes)
    mercado.falhou.connect(workspace.receber_falha)
    workspace.mercado_changed.connect(lambda: mercado.definir_ativo(workspace.mercado_real))
    mercado.definir_ativo(workspace.mercado_real)
    app.aboutToQuit.connect(mercado.parar)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
