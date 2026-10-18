"""Janela principal: header de abas (Geral + agentes) sobre páginas rolláveis."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame, QInputDialog, QMainWindow, QMenu, QMessageBox, QScrollArea, QStackedWidget,
    QVBoxLayout, QWidget,
)

from ..store import Store
from ..workspace import COLORS, OVERVIEW, Workspace
from . import theme
from .components import Toast
from .dashboard import Dashboard
from .header import Tab, TabHeader


class _Canvas(QWidget):
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor(theme.BG_TOP))
        g.setColorAt(1, QColor(theme.BG_BOTTOM))
        p.fillRect(QRectF(self.rect()), g)


def _swatch(color: str) -> QIcon:
    pm = QPixmap(14, 14)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(1, 1, 12, 12)
    p.end()
    return QIcon(pm)


class MainWindow(QMainWindow):
    def __init__(self, workspace: Workspace):
        super().__init__()
        self.setWindowTitle("UBento")
        self.setMinimumSize(760, 520)
        available = self.screen().availableGeometry() if self.screen() else None
        self.resize(980, min(1100, (available.height() - 40) if available else 1100))

        self.workspace = workspace
        self.pages: dict[str, QScrollArea] = {}
        self.current = OVERVIEW

        canvas = _Canvas()
        self.setCentralWidget(canvas)
        self.header = TabHeader()
        self.stack = QStackedWidget()
        layout = QVBoxLayout(canvas)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self.stack, 1)
        self.toast = Toast(canvas)

        self.header.selected.connect(self.select)
        self.header.add_requested.connect(self.add_agent)
        self.header.rename_requested.connect(self.rename)
        self.header.context_requested.connect(self.show_menu)
        self.header.reordered.connect(workspace.move_to)
        workspace.changed.connect(self.sync)
        self.sync()

    # -- páginas -----------------------------------------------------------

    def _page(self, key: str, store: Store) -> QScrollArea:
        dash = Dashboard(store)
        dash.notify.connect(self.toast.show_message)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setAutoFillBackground(False)
        scroll.setWidget(dash)
        dash.setAutoFillBackground(False)  # QScrollArea liga o preenchimento; o fundo vem do canvas
        self.stack.addWidget(scroll)
        self.pages[key] = scroll
        return scroll

    def dashboard(self, key: str) -> Dashboard:
        return self.pages[key].widget()  # type: ignore[return-value]

    def sync(self) -> None:
        ws = self.workspace
        wanted = {OVERVIEW} | {a.id for a in ws.agents}
        for key in list(self.pages):
            if key not in wanted:
                page = self.pages.pop(key)
                self.stack.removeWidget(page)
                page.deleteLater()
        if OVERVIEW not in self.pages:
            self._page(OVERVIEW, ws.overview)
        for agent in ws.agents:
            if agent.id not in self.pages:
                self._page(agent.id, agent.store)
        if self.current not in self.pages:
            self.current = OVERVIEW
        tabs = [Tab(OVERVIEW, ws.overview_name, None)] + [Tab(a.id, a.name, a.color) for a in ws.agents]
        self.header.set_tabs(tabs, self.current)
        self.stack.setCurrentWidget(self.pages[self.current])

    def select(self, key: str) -> None:
        if key in self.pages:
            self.current = key
            self.header.set_current(key)
            self.stack.setCurrentWidget(self.pages[key])

    # -- ações de configuração (botão direito) -------------------------------

    def add_agent(self) -> None:
        agent = self.workspace.add()
        self.select(agent.id)
        self.rename(agent.id)

    def rename(self, key: str) -> None:
        ws = self.workspace
        current = ws.overview_name if key == OVERVIEW else (ws.agent(key).name if ws.agent(key) else "")
        name, ok = QInputDialog.getText(self, "Renomear", "Nome da aba:", text=current)
        if ok and name.strip():
            ws.rename(key, name)

    def remove(self, key: str) -> None:
        agent = self.workspace.agent(key)
        if agent is None or len(self.workspace.agents) <= 1:
            return
        box = QMessageBox(QMessageBox.Icon.Question, "Remover agente", f"Remover “{agent.name}”?", parent=self)
        box.setInformativeText("A aba e os dados de demonstração dela serão descartados.")
        yes = box.addButton("Remover", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is yes:
            self.workspace.remove(key)
            self.toast.show_message(f"Agente “{agent.name}” removido", True)

    def build_menu(self, key: str | None) -> QMenu:
        ws = self.workspace
        menu = QMenu(self)
        if key is None:
            menu.addAction("Novo agente", self.add_agent)
            return menu
        menu.addAction("Renomear…", lambda: self.rename(key))
        agent = ws.agent(key)
        if agent is None:  # aba "Geral": só renomeia
            return menu

        colors = menu.addMenu("Cor")
        group = QActionGroup(colors)
        for c in COLORS:
            act = QAction(_swatch(c), c.upper(), colors, checkable=True)
            act.setChecked(c.lower() == agent.color.lower())
            act.triggered.connect(lambda _=False, c=c: ws.recolor(key, c))
            group.addAction(act)
            colors.addAction(act)

        menu.addAction("Duplicar", lambda: ws.duplicate(key))
        idx = ws.index(key)
        menu.addSeparator()
        left = menu.addAction("Mover para a esquerda", lambda: ws.move_to(key, idx - 1))
        left.setEnabled(idx > 0)
        right = menu.addAction("Mover para a direita", lambda: ws.move_to(key, idx + 1))
        right.setEnabled(idx < len(ws.agents) - 1)
        menu.addSeparator()
        rm = menu.addAction("Remover", lambda: self.remove(key))
        rm.setEnabled(len(ws.agents) > 1)
        return menu

    def show_menu(self, key: str | None, pos: QPoint) -> None:
        self.build_menu(key).exec(pos)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.toast.reposition()
