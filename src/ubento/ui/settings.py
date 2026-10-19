"""Tela de configurações gerais."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPainter
from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QLineEdit, QMessageBox, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import __version__
from ..conexoes import ServicoConexoes
from ..store import CAPITAL_INICIAL_REAL, RANGES
from ..workspace import Workspace
from . import theme
from .components import ActionButton, Card, Label, LinkButton, PillButton, Switch

W = theme.W
REPO = "github.com/Felici4no/UBento"
REPO_URL = f"https://{REPO}"


class SettingRow(QWidget):
    """Título + descrição à esquerda, controle à direita, separador embaixo."""

    def __init__(self, title: str, description: str, control: QWidget | None, *, last=False, parent=None):
        super().__init__(parent)
        self._last = last
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(Label(title, 16, W.Medium))
        desc = self.desc = Label(description, 13, W.Normal, theme.MUTED)
        desc.setWordWrap(True)
        text.addWidget(desc)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 16, 0, 16)
        h.setSpacing(24)
        h.addLayout(text, 1)
        if control is not None:
            h.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)

    def paintEvent(self, _e) -> None:
        if not self._last:
            p = QPainter(self)
            p.setPen(QColor(theme.LINE))
            p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)


class SettingSection(Card):
    def __init__(self, title: str, rows: list[SettingRow], parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 4)
        v.setSpacing(0)
        v.addWidget(Label(title, 13, W.DemiBold, theme.MUTED))
        for i, row in enumerate(rows):
            row._last = i == len(rows) - 1
            v.addWidget(row)


class SettingsPage(QWidget):
    notify = Signal(str, bool)
    add_agent_requested = Signal()

    def __init__(self, workspace: Workspace, conexoes: ServicoConexoes | None = None, ouvintes=None, parent=None):
        super().__init__(parent)
        self.ws = workspace
        self.setMinimumWidth(640)

        # -- perfil
        self.name = QLineEdit(workspace.pref("user_name"))
        self.name.setFixedWidth(220)
        self.name.setMaxLength(30)
        self.name.setStyleSheet(
            f"QLineEdit {{ background: {theme.PANEL}; color: {theme.TEXT}; border: 1px solid {theme.PANEL_EDGE};"
            f" border-radius: 12px; padding: 9px 14px; font-size: 15px; selection-background-color: {theme.BLUE}; }}"
            f"QLineEdit:focus {{ border-color: {theme.BLUE}; }}"
        )
        self.name.editingFinished.connect(self._save_name)

        # -- exibição
        self.hide_values = Switch()
        self.hide_values.setChecked(workspace.pref("hide_values"))
        self.hide_values.toggled.connect(lambda on: workspace.set_pref("hide_values", on))

        # -- mercado
        self.mercado_real = Switch()
        self.mercado_real.setChecked(workspace.mercado_real)
        self.mercado_real.toggled.connect(self._alternar_mercado)

        self.range_buttons: dict[str, PillButton] = {}
        ranges = QHBoxLayout()
        ranges.setSpacing(6)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for key in RANGES:
            btn = PillButton(key, height=34, pad=14, px=14)
            btn.clicked.connect(lambda _=False, k=key: workspace.set_pref("default_range", k))
            group.addButton(btn)
            ranges.addWidget(btn)
            self.range_buttons[key] = btn
        range_box = QWidget()
        range_box.setLayout(ranges)
        ranges.setContentsMargins(0, 0, 0, 0)

        # -- agentes e dados
        new_agent = ActionButton("Novo agente")
        new_agent.clicked.connect(self.add_agent_requested)
        reset_data = ActionButton("Restaurar", danger=True)
        reset_data.clicked.connect(self._reset_demo)
        reset_tabs = ActionButton("Restaurar", danger=True)
        reset_tabs.clicked.connect(self._reset_agents)

        github = LinkButton("GitHub")
        github.setToolTip(REPO_URL)
        github.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))

        sections = [
            SettingSection("PERFIL", [SettingRow("Nome", "Como o UBento chama você no topo da tela.", self.name)]),
            SettingSection("EXIBIÇÃO", [
                SettingRow("Ocultar valores", "Mascara saldos e valores em todas as telas. Também fica no ícone de olho do topo.", self.hide_values),
                SettingRow("Período padrão do gráfico", "Usado ao abrir o app e ao trocar de aba.", range_box),
            ]),
            SettingSection("MERCADO", [self._mercado_row()]),
            *([self._conexoes_section(conexoes, ouvintes)] if conexoes is not None else []),
            SettingSection("AGENTES", [
                SettingRow("Novo agente", "Cada agente é uma carteira com seus próprios saldos. Clique com o botão direito numa aba "
                     "para renomear, mudar a cor, duplicar, mover ou remover.", new_agent),
            ]),
            SettingSection("DADOS", [
                SettingRow("Dados de demonstração", "Volta saldos, swaps e decisões ao estado inicial. Nomes e cores dos agentes são mantidos.", reset_data),
                SettingRow("Abas padrão", "Descarta os agentes atuais e recria Pessoal e Empresa.", reset_tabs),
            ]),
            SettingSection("SOBRE", [SettingRow(f"UBento {__version__}", f"Código aberto, licença MIT · {REPO}", github)]),
        ]

        column = QVBoxLayout()
        column.setSpacing(16)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(Label("Configurações", 30, W.DemiBold))
        column.addWidget(Label("Preferências gerais do app. Valem para todas as abas.", 15, W.Normal, theme.MUTED))
        column.addSpacing(8)
        for s in sections:
            column.addWidget(s)
        column.addStretch(1)

        holder = QWidget()
        holder.setLayout(column)
        holder.setMaximumWidth(720)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(32, 16, 32, 36)
        outer.addStretch(1)
        outer.addWidget(holder, 100)
        outer.addStretch(1)

        workspace.prefs_changed.connect(self.sync)
        workspace.mercado_changed.connect(self.sync)
        self.sync()

    def _mercado_row(self) -> SettingRow:
        self._mercado_linha = SettingRow("Mercado real (Binance)", "", self.mercado_real)
        return self._mercado_linha

    def _alternar_mercado(self, ligado: bool) -> None:
        if ligado:
            texto = (f"Ligar o mercado real? Cada agente passa a ter uma carteira NOVA de US$ {CAPITAL_INICIAL_REAL:,.0f}".replace(",", ".") +
                     " simulados, com os preços ao vivo da Binance. Os saldos, decisões e gráficos de demonstração saem de cena. "
                     "As ordens continuam simuladas: nada é enviado à Binance.")
            botao = "Ligar"
        else:
            texto = "Voltar aos dados de demonstração? As carteiras do mercado real serão descartadas."
            botao = "Voltar"
        if self._confirm("Mercado real", texto, botao):
            self.ws.set_pref("mercado", "real" if ligado else "simulado")
            self.notify.emit("Mercado real ligado" if ligado else "Demonstração restaurada", True)
        else:
            self.sync()  # recusou: o interruptor volta ao que era

    def _conexoes_section(self, servico: ServicoConexoes, ouvintes=None):
        from .conexoes import ConexoesSection  # import tardio: só quem usa conexões paga por elas

        self.conexoes_section = ConexoesSection(servico, ouvintes=ouvintes)
        self.conexoes_section.notify.connect(self.notify)
        return self.conexoes_section

    def sync(self) -> None:
        """Reflete as preferências nos controles (ex.: o olho do header mudou o valor)."""
        self.hide_values.blockSignals(True)
        self.hide_values.setChecked(self.ws.pref("hide_values"))
        self.hide_values.blockSignals(False)
        self.mercado_real.blockSignals(True)
        self.mercado_real.setChecked(self.ws.mercado_real)
        self.mercado_real.blockSignals(False)
        self._mercado_linha.desc.setText(
            "Preços ao vivo da Binance e carteira nova, sem dados simulados. As ordens são simuladas: nada é enviado à corretora.\n" + self.ws.status_mercado())
        for key, btn in self.range_buttons.items():
            btn.setChecked(key == self.ws.pref("default_range"))
        if not self.name.hasFocus():
            self.name.setText(self.ws.pref("user_name"))

    def _save_name(self) -> None:
        name = self.name.text().strip() or "Você"
        self.name.setText(name)
        self.ws.set_pref("user_name", name)

    def _confirm(self, title: str, text: str, button: str) -> bool:
        box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=self)
        yes = box.addButton(button, QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is yes

    def _reset_demo(self) -> None:
        if self._confirm("Restaurar dados", "Voltar saldos, swaps e decisões ao estado de demonstração?", "Restaurar"):
            self.ws.reset_demo_data()
            self.notify.emit("Dados de demonstração restaurados", True)

    def _reset_agents(self) -> None:
        if self._confirm("Restaurar abas", "Descartar os agentes atuais e recriar Pessoal e Empresa?", "Restaurar"):
            self.ws.restore_default_agents()
            self.notify.emit("Abas padrão restauradas", True)
