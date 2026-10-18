"""Renderiza a janela inteira (header + conteúdo completo) e salva um PNG.

    python scripts/screenshot.py saida.png [--tab N] [--hover] [--menu CHAVE|vazio]

--tab N      seleciona a aba N (0 = Geral), "settings", "cfg" (configuração do 1º agente) ou "metas" (metas do 1º agente)
--cenario X  com --tab metas: arquivo de exemplos/avaliacao a importar (padrão 04_*) e --momentos N a avançar (padrão todos)
--run        roda os algoritmos dos agentes antes (gera propostas)
--hide       liga o modo ocultar valores
--expand K   salva <saida>-K.png com o card K expandido (crypto, total, summary, activity, decisions, agents, coin)
--hover      simula o mouse sobre o gráfico de barras
--menu K     salva também <saida>-menu.png com o menu de botão direito
             (K = índice da aba, ou "vazio" para o menu do espaço vazio do header)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QPoint, QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QRegion  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from ubento.ui import theme  # noqa: E402
from ubento.ui.main_window import MainWindow  # noqa: E402
from ubento.workspace import Workspace  # noqa: E402


def arg(name: str) -> str | None:
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None


def main() -> None:
    out = next((a for a in sys.argv[1:] if a.endswith(".png")), "screenshot.png")
    app = QApplication(sys.argv)
    app.setFont(theme.font(13))
    app.setStyleSheet(theme.APP_QSS)
    ws = Workspace()
    win = MainWindow(ws, animations=False)
    win.show()
    app.processEvents()

    first = ws.agents[0].id
    keys = ["overview"] + [a.id for a in ws.agents] + ["settings", "cfg:" + first]
    which = arg("--tab") or "0"
    if "--run" in sys.argv:  # gera propostas/decisões dos agentes antes de capturar
        for agent in ws.agents:
            ws.run_agent(agent.id)
    if which == "cfg":
        win.open_config(first)
    if which == "metas":
        raiz = Path(__file__).resolve().parents[1] / "exemplos" / "avaliacao"
        cenario = arg("--cenario") or next(raiz.glob("04_*.yaml")).name
        meta_id = win.metas.importar(raiz / cenario, first)
        for _ in range(int(arg("--momentos") or 99)):
            if win.metas.avancar(meta_id) is None:
                break
        win.open_metas(first)
        keys.append("metas:" + first)
    tab = {"settings": len(keys) - 2, "cfg": len(keys) - 1, "metas": len(keys) - 1}.get(which) or int(which)
    if "--hide" in sys.argv:
        ws.set_pref("hide_values", True)
    win.select(keys[tab])
    app.processEvents()

    if "--hover" in sys.argv and keys[tab] != "settings":
        chart = win.dashboard(keys[tab]).total.chart
        chart._hover = int(len(chart._points) * 0.62)
        chart._anim.stop()
        chart._shown = list(chart._to)
        chart.update()
    QTest.qWait(700)  # deixa as animações de entrada terminarem
    app.processEvents()

    header, content = win.header, win.pages[keys[tab]].widget()
    dpr = win.devicePixelRatio()
    w, h = content.width(), header.height() + content.height()
    img = QImage(int(w * dpr), int(h * dpr), QImage.Format.Format_ARGB32)
    p = QPainter(img)
    p.scale(dpr, dpr)
    g = QLinearGradient(0, 0, 0, h)
    g.setColorAt(0, QColor(theme.BG_TOP))
    g.setColorAt(1, QColor(theme.BG_BOTTOM))
    p.fillRect(QRectF(0, 0, w, h), g)
    header.render(p, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
    content.render(p, QPoint(0, header.height()), QRegion(), QWidget.RenderFlag.DrawChildren)
    p.end()
    img.save(out)
    print(f"salvo em {out} ({img.width()}x{img.height()})")

    kind = arg("--expand")
    if kind:
        dash = win.dashboard(keys[tab])
        win.expand(dash, kind, getattr(dash, kind))
        app.processEvents()
        win.grab().save(out.replace(".png", f"-{kind}.png"))
        print(f"expandido: {kind}")

    menu_arg = arg("--menu")
    if menu_arg:
        menu = win.build_menu(None if menu_arg == "vazio" else keys[int(menu_arg)])
        menu.ensurePolished()
        menu.adjustSize()
        menu.grab().save(out.replace(".png", "-menu.png"))
        print("menu salvo")


if __name__ == "__main__":
    main()
