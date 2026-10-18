"""Renderiza a janela e salva um PNG (uso em desenvolvimento).

    python scripts/screenshot.py saida.png [largura altura] [--hover]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from ubento.store import Store  # noqa: E402
from ubento.ui import theme  # noqa: E402
from ubento.ui.main_window import MainWindow  # noqa: E402


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = args[0] if args else "screenshot.png"
    app = QApplication(sys.argv)
    app.setFont(theme.font(13))
    app.setStyleSheet(theme.APP_QSS)
    win = MainWindow(Store())
    if len(args) >= 3:
        win.resize(int(args[1]), int(args[2]))
    win.show()
    app.processEvents()
    if "--hover" in sys.argv:  # simula o mouse sobre o gráfico de barras
        chart = win.total.chart
        chart._hover = int(len(chart._points) * 0.62)
        chart._anim.stop()
        chart._shown = list(chart._to)
        chart.update()
    import time
    time.sleep(0.5)
    app.processEvents()
    win.centralWidget().widget().grab().save(out)  # conteúdo inteiro, mesmo que a janela role
    print(f"salvo em {out} ({win.width()}x{win.height()})")


if __name__ == "__main__":
    main()
