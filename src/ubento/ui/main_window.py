"""Janela principal: header de abas (Geral + agentes) sobre páginas rolláveis."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPropertyAnimation, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QKeySequence, QLinearGradient, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QFrame, QGraphicsOpacityEffect, QInputDialog, QMainWindow, QMenu, QMessageBox, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ..conexoes import CofreMemoria, ServicoConexoes
from ..metas import ServicoMetas
from ..store import Store
from ..workspace import COLORS, OVERVIEW, Workspace
from . import theme
from .agent_page import AgentConfigPage
from .components import Toast
from .dashboard import Dashboard
from .expanded import build as build_expanded
from .header import Tab, TabHeader
from .metas_page import MetasPage
from .overlay import ExpandOverlay
from .settings import SettingsPage

SETTINGS = "settings"
CFG = "cfg:"  # prefixo da página de configuração de um agente
METAS = "metas:"  # prefixo da página de metas de um agente


class _Canvas(QWidget):
    resized = Signal()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor(theme.BG_TOP))
        g.setColorAt(1, QColor(theme.BG_BOTTOM))
        p.fillRect(QRectF(self.rect()), g)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.resized.emit()  # o layout já ajustou os filhos neste ponto


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
    def __init__(self, workspace: Workspace, animations: bool = True, metas: ServicoMetas | None = None, conexoes: ServicoConexoes | None = None, ouvintes=None):
        super().__init__()
        self.setWindowTitle("UBento")
        self.setMinimumSize(760, 520)
        available = self.screen().availableGeometry() if self.screen() else None
        self.resize(980, min(1100, (available.height() - 40) if available else 1100))

        self.workspace = workspace
        self.metas = metas or ServicoMetas()  # sem banco informado: em memória (testes, capturas)
        # sem serviço informado: conexões só em memória e com cofre temporário (testes e capturas nunca tocam o cofre real)
        self.conexoes = conexoes or ServicoConexoes(self.metas.repo, CofreMemoria())
        self.ouvintes = ouvintes  # ouvintes do bot do Telegram (None em testes e capturas)
        self.animations = animations
        self.pages: dict[str, QScrollArea] = {}
        self.current = OVERVIEW

        canvas = _Canvas()
        self.setCentralWidget(canvas)
        self.header = TabHeader()
        self.header.animate = animations
        self.stack = QStackedWidget()
        layout = QVBoxLayout(canvas)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self.stack, 1)
        self.overlay = ExpandOverlay(canvas)
        self.toast = Toast(canvas)
        canvas.resized.connect(self._layout_floating)
        QShortcut(QKeySequence("Esc"), self, activated=lambda: self.overlay.collapse())

        self.header.selected.connect(self.select)
        self.header.add_requested.connect(self.add_agent)
        self.header.rename_requested.connect(self.rename)
        self.header.context_requested.connect(self.show_menu)
        self.header.reordered.connect(workspace.move_to)
        self.header.settings_requested.connect(lambda: self.select(SETTINGS))
        self.header.privacy_toggled.connect(lambda: workspace.set_pref("hide_values", not workspace.pref("hide_values")))
        workspace.changed.connect(self.sync)
        workspace.agent_changed.connect(lambda _id: self._refresh_tabs())
        workspace.prefs_changed.connect(self._apply_prefs)
        self._settings_page()
        self.sync()
        self._apply_prefs()

    # -- páginas -----------------------------------------------------------

    def _scroll(self, widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setAutoFillBackground(False)
        scroll.setWidget(widget)
        widget.setAutoFillBackground(False)  # QScrollArea liga o preenchimento; o fundo vem do canvas
        self.stack.addWidget(scroll)
        return scroll

    def _page(self, key: str, store: Store) -> QScrollArea:
        dash = Dashboard(store, self.workspace, self.workspace.agent(key) if key != OVERVIEW else None)
        dash.configure_requested.connect(self.open_config)
        dash.metas_requested.connect(self.open_metas)
        dash.notify.connect(self.toast.show_message)
        dash.open_agent.connect(self.select)
        dash.expand_requested.connect(lambda kind, card, d=dash: self.expand(d, kind, card))
        self.pages[key] = self._scroll(dash)
        return self.pages[key]

    def _settings_page(self) -> None:
        page = SettingsPage(self.workspace, self.conexoes, self.ouvintes)
        page.notify.connect(self.toast.show_message)
        page.add_agent_requested.connect(self.add_agent)
        self.pages[SETTINGS] = self._scroll(page)

    def _apply_prefs(self) -> None:
        ws = self.workspace
        self.header.set_greeting(ws.pref("user_name"))
        self.header.set_hidden(ws.pref("hide_values"))
        for key in self.pages:
            if key != SETTINGS and not key.startswith((CFG, METAS)) and ws.pref("default_range") != self.dashboard(key).total.range_key:
                self.dashboard(key).total.set_range(ws.pref("default_range"))

    def dashboard(self, key: str) -> Dashboard:
        return self.pages[key].widget()  # type: ignore[return-value]

    def sync(self) -> None:
        ws = self.workspace
        wanted = {OVERVIEW, SETTINGS} | {a.id for a in ws.agents} | {CFG + a.id for a in ws.agents} | {METAS + a.id for a in ws.agents}
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
                self.dashboard(agent.id).total.set_range(ws.pref("default_range"))
        if self.current not in self.pages:
            self.current = OVERVIEW
        self._refresh_tabs()
        self.stack.setCurrentWidget(self.pages[self.current])

    def _refresh_tabs(self) -> None:
        ws = self.workspace
        tabs = [Tab(OVERVIEW, ws.overview_name, None, ws.pending_count())]
        tabs += [Tab(a.id, a.name, a.color, ws.pending_count(a.id)) for a in ws.agents]
        self.header.set_tabs(tabs, self._tab_key())

    def _tab_key(self) -> str:
        """As páginas de configuração e de metas mantêm a aba do agente destacada."""
        for prefixo in (CFG, METAS):
            if self.current.startswith(prefixo):
                return self.current[len(prefixo):]
        return self.current

    def select(self, key: str) -> None:
        if key not in self.pages:
            return
        self.overlay.collapse(animate=False)
        changed = key != self.current
        self.current = key
        self.header.set_current(self._tab_key())
        self.stack.setCurrentWidget(self.pages[key])
        if changed:
            self._fade_in(self.pages[key])

    def _fade_in(self, page: QWidget) -> None:
        if not self.animations:
            return
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", page)
        anim.setDuration(260)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.finished.connect(lambda: page.setGraphicsEffect(None))  # solta o efeito: rende mais sem ele
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def open_config(self, agent_id: str) -> None:
        key = CFG + agent_id
        if key not in self.pages and self.workspace.agent(agent_id):
            page = AgentConfigPage(self.workspace, agent_id)
            page.notify.connect(self.toast.show_message)
            page.back_requested.connect(lambda: self.select(agent_id))
            self.pages[key] = self._scroll(page)
        self.select(key)

    def open_metas(self, agent_id: str) -> None:
        key = METAS + agent_id
        if key not in self.pages and self.workspace.agent(agent_id):
            page = MetasPage(self.workspace, self.metas, agent_id)
            page.notify.connect(self.toast.show_message)
            page.back_requested.connect(lambda: self.select(agent_id))
            self.pages[key] = self._scroll(page)
        self.select(key)

    # -- expansão de cards ---------------------------------------------------

    def expand(self, dash: Dashboard, kind: str, card: QWidget) -> None:
        title, subtitle, content = build_expanded(kind, dash, self.workspace)

        def card_rect() -> QRect:
            try:
                return QRect(self.overlay.mapFromGlobal(card.mapToGlobal(QPoint(0, 0))), card.size())
            except RuntimeError:  # o card foi destruído (aba removida)
                return self.overlay.rect().adjusted(200, 200, -200, -200)

        self.overlay.open(title, subtitle, content, card_rect(), card.grab(), card_rect, self.animations)

    def _layout_floating(self) -> None:
        self.overlay.setGeometry(self.stack.geometry())
        self.toast.reposition()

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
        agent = ws.agent(key)
        if agent is not None:
            menu.addAction("Configurar agente…", lambda: self.open_config(key))
            menu.addAction("Metas…", lambda: self.open_metas(key))
        menu.addAction("Renomear…", lambda: self.rename(key))
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
