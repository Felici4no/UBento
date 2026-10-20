"""Tela de configuração de um agente: identidade, algoritmo, limites, ativos e execução."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QGridLayout, QHBoxLayout, QLineEdit, QMessageBox, QVBoxLayout, QWidget,
)

from ..agent_config import (
    DAILY_GOAL_CHOICES, DAILY_STOP_CHOICES, FREQUENCIES, MODES, PARAMS, RISK_LABELS, RISK_PCT_CHOICES, STRATEGIES, STRATEGY_ICONS, TRADABLE, describe,
    next_run, num,
)
from ..workspace import COLORS, Workspace
from . import theme
from .components import ActionButton, Card, Label, PillButton, Switch
from .controls import CheckBox, ColorSwatches, OptionCard, ToggleChip, ValueSlider
from .settings import SettingRow, SettingSection

W = theme.W


def _when(moment: datetime, now: datetime) -> str:
    days = (moment.date() - now.date()).days
    day = "hoje" if days == 0 else "amanhã" if days == 1 else f"{moment.day:02d}/{moment.month:02d}"
    return f"{day}, {moment:%H:%M}"


class AgentConfigPage(QWidget):
    back_requested = Signal()
    notify = Signal(str, bool)

    def __init__(self, workspace: Workspace, agent_id: str, parent=None):
        super().__init__(parent)
        self.ws, self.agent_id = workspace, agent_id
        self.setMinimumWidth(640)
        self._syncing = False

        # -- cabeçalho
        self.back = ActionButton("Voltar", height=36, pad=16)
        self.back.clicked.connect(self.back_requested)
        self.title = Label("", 30, W.DemiBold)
        self.subtitle = Label("Tudo é salvo na hora. O algoritmo roda com os limites abaixo.", 15, W.Normal, theme.MUTED)

        # -- identidade
        self.name = QLineEdit()
        self.name.setFixedWidth(220)
        self.name.setMaxLength(24)
        self.name.setStyleSheet(
            f"QLineEdit {{ background: {theme.PANEL}; color: {theme.TEXT}; border: 1px solid {theme.PANEL_EDGE};"
            f" border-radius: 12px; padding: 9px 14px; font-size: 15px; selection-background-color: {theme.BLUE}; }}"
            f"QLineEdit:focus {{ border-color: {theme.BLUE}; }}"
        )
        self.name.editingFinished.connect(self._save_name)
        self.swatches = ColorSwatches(COLORS)
        self.swatches.picked.connect(lambda c: workspace.recolor(agent_id, c))
        self.active = Switch()
        self.active.toggled.connect(lambda on: self._set(active=on))

        # -- algoritmo
        self.strategy_cards: dict[str, OptionCard] = {}
        grid = QGridLayout()
        grid.setSpacing(12)
        grid.setContentsMargins(0, 8, 0, 8)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for i, (key, (name, desc)) in enumerate(STRATEGIES.items()):
            card = OptionCard(key, STRATEGY_ICONS[key], name, desc)
            card.clicked.connect(lambda _=False, k=key: self._set(strategy=k))
            group.addButton(card)
            grid.addWidget(card, i // 2, i % 2)
            self.strategy_cards[key] = card
        strategy_box = QWidget()
        strategy_box.setLayout(grid)

        # -- limites (um slider por parâmetro; só os relevantes ao algoritmo aparecem)
        self.sliders: dict[str, ValueSlider] = {}
        self.param_rows: dict[str, SettingRow] = {}
        for key, (lo, hi, step, suffix, title, desc) in PARAMS.items():
            slider = ValueSlider(lo, hi, step, suffix, RISK_LABELS if key == "risk" else None)
            slider.valueChanged.connect(lambda v, k=key: self._set(**{k: v}))
            self.sliders[key] = slider
            self.param_rows[key] = SettingRow(title, desc, slider)

        # -- regras padrão de risco (caixas de seleção)
        self.rule_boxes: dict[str, CheckBox] = {}
        self.rule_pills: dict[str, dict] = {}
        self.rule_rows: dict[str, SettingRow] = {}
        self._rule_fields: dict[str, tuple[str, str | None]] = {}  # chave da regra -> (campo da caixa, campo do valor)
        pacote = ActionButton("Aplicar pacote padrão", height=36, pad=16)
        pacote.clicked.connect(self._pacote_padrao)
        self.rules_pack = pacote
        regras = (
            ("risk", "rule_risk", "Risco por operação", "Nenhuma compra arrisca mais que esta fatia da conta: valor ≤ risco ÷ stop-loss.",
             {v: num(v) + "%" for v in RISK_PCT_CHOICES}, "rule_risk_pct"),
            ("stop", "rule_daily_stop", "Stop diário", "Para de comprar no dia ao perder este múltiplo do risco de uma operação. Vendas continuam permitidas.",
             {v: f"{v}×" for v in DAILY_STOP_CHOICES}, "rule_daily_stop_x"),
            ("goal", "rule_daily_goal", "Meta de ganho diária", "Para de comprar no dia ao ganhar este múltiplo do risco, para não devolver o lucro.",
             {v: f"{v}×" for v in DAILY_GOAL_CHOICES}, "rule_daily_goal_x"),
            ("sizing", "rule_sizing", "Tamanho pela fórmula", "Cada compra tem o tamanho = risco em US$ ÷ stop-loss (ex.: conta de US$ 10.000, risco de 1% e stop de 8% → US$ 1.250).",
             None, None),
        )
        for chave, campo, titulo, descricao, opcoes, campo_valor in regras:
            box = CheckBox()
            box.toggled.connect(lambda on, c=campo: self._set(**{c: on}))
            pills = self._pills(opcoes, lambda v, c=campo_valor: self._set(**{c: v})) if opcoes else None
            row = SettingRow(titulo, descricao, pills["box"] if pills else None)
            row.layout().insertWidget(0, box, 0, Qt.AlignmentFlag.AlignVCenter)
            self.rule_boxes[chave], self.rule_pills[chave], self.rule_rows[chave] = box, pills, row
            self._rule_fields[chave] = (campo, campo_valor)

        # -- ativos
        self.chips: dict[str, ToggleChip] = {}
        chips = QHBoxLayout()
        chips.setSpacing(8)
        chips.setContentsMargins(0, 0, 0, 0)
        for sym in TRADABLE:
            chip = ToggleChip(sym)
            chip.clicked.connect(self._assets_changed)
            self.chips[sym] = chip
            chips.addWidget(chip)
        chip_box = QWidget()
        chip_box.setLayout(chips)

        # -- execução
        self.mode_buttons = self._pills({k: v[0] for k, v in MODES.items()}, lambda k: self._set(mode=k))
        self.mode_hint = Label("", 13, W.Normal, theme.MUTED)
        self.freq_buttons = self._pills(FREQUENCIES, lambda k: self._set(frequency=k))
        self.schedule = Label("", 13, W.Normal, theme.MUTED)

        # -- resumo e ações
        self.summary = Label("", 15, W.Normal, theme.TEXT)
        self.summary.setWordWrap(True)
        self.run = ActionButton("Rodar agora", primary=True, height=40, pad=22)
        self.run.clicked.connect(self._run_now)
        reset = ActionButton("Restaurar padrão", danger=True, height=40, pad=20)
        reset.clicked.connect(self._reset)

        # -- montagem
        mode_row = SettingRow("Modo de execução", "O que o agente faz depois de decidir.", self.mode_buttons["box"])
        freq_row = SettingRow("Frequência", "Com que regularidade o algoritmo roda.", self.freq_buttons["box"])
        self.sections = {
            "identity": SettingSection("IDENTIDADE", [
                SettingRow("Nome", "Aparece na aba e nas decisões do Geral.", self.name),
                SettingRow("Cor", "Identifica o agente nos gráficos e listas.", self.swatches),
                SettingRow("Agente ativo", "Pausado, ele não roda nem propõe nada.", self.active),
            ]),
            "algorithm": SettingSection("ALGORITMO", [SettingRow("Como o agente decide", "Cada algoritmo usa parâmetros diferentes; só os relevantes aparecem abaixo.", None), ]),
            "limits": SettingSection("RISCO E LIMITES", list(self.param_rows.values())),
            "rules": SettingSection("REGRAS DE RISCO", [
                SettingRow("Pacote padrão", "Marca as quatro regras com valores moderados (risco de 0,75%, stop de 2×, meta de 3×). Dá para ajustar cada uma depois.", pacote),
                *self.rule_rows.values(),
            ]),
            "assets": SettingSection("ATIVOS", [SettingRow("Ativos permitidos", "O agente só compra e vende estes. Pelo menos um.", chip_box)]),
            "execution": SettingSection("EXECUÇÃO", [mode_row, freq_row]),
        }
        # a grade de algoritmos entra logo abaixo do título da seção
        self.sections["algorithm"].layout().insertWidget(2, strategy_box)

        summary_card = Card()
        sv = QVBoxLayout(summary_card)
        sv.setContentsMargins(24, 20, 24, 22)
        sv.setSpacing(10)
        sv.addWidget(Label("COMO ESTE AGENTE VAI AGIR", 13, W.DemiBold, theme.MUTED))
        sv.addWidget(self.summary)
        sv.addWidget(self.mode_hint)
        sv.addWidget(self.schedule)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addWidget(self.run)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        sv.addSpacing(4)
        sv.addLayout(buttons)

        column = QVBoxLayout()
        column.setSpacing(16)
        column.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.addWidget(self.back)
        top.addStretch(1)
        column.addLayout(top)
        column.addWidget(self.title)
        column.addWidget(self.subtitle)
        column.addSpacing(6)
        column.addWidget(summary_card)
        for key in ("identity", "algorithm", "limits", "rules", "assets", "execution"):
            column.addWidget(self.sections[key])
        column.addStretch(1)

        holder = QWidget()
        holder.setLayout(column)
        holder.setMaximumWidth(760)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(32, 16, 32, 36)
        outer.addStretch(1)
        outer.addWidget(holder, 100)
        outer.addStretch(1)

        workspace.agent_changed.connect(self._on_agent_changed)
        workspace.prefs_changed.connect(self.sync)
        workspace.changed.connect(self.sync)
        self.sync()

    # -- helpers ------------------------------------------------------------

    def _pills(self, options: dict[str, str], on_pick) -> dict:
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        group = QButtonGroup(box)
        group.setExclusive(True)
        buttons = {}
        for key, label in options.items():
            btn = PillButton(label, height=34, pad=14, px=14)
            btn.clicked.connect(lambda _=False, k=key: on_pick(k))
            group.addButton(btn)
            h.addWidget(btn)
            buttons[key] = btn
        return {"box": box, "buttons": buttons}

    @property
    def agent(self):
        return self.ws.agent(self.agent_id)

    def _set(self, **changes) -> None:
        if not self._syncing:
            self.ws.set_config(self.agent_id, **changes)

    def _assets_changed(self) -> None:
        chosen = [s for s, c in self.chips.items() if c.isChecked()]
        if not chosen:  # pelo menos um ativo
            self.chips[TRADABLE[0]].setChecked(True)
            chosen = [TRADABLE[0]]
            self.notify.emit("O agente precisa de pelo menos um ativo", False)
        self._set(assets=chosen)

    def _save_name(self) -> None:
        text = self.name.text().strip()
        if text and self.agent and text != self.agent.name:
            self.ws.rename(self.agent_id, text)

    def _on_agent_changed(self, agent_id: str) -> None:
        if agent_id == self.agent_id:
            self.sync()

    # -- sincronização estado → controles ------------------------------------

    def sync(self) -> None:
        agent = self.agent
        if agent is None:
            return
        cfg = agent.config
        self._syncing = True
        try:
            self.title.setText(f"Configurar {agent.name}")
            if not self.name.hasFocus():
                self.name.setText(agent.name)
            self.swatches.set_current(agent.color)
            self.active.setChecked(cfg.active)
            for key, card in self.strategy_cards.items():
                card.setChecked(key == cfg.strategy)
            for key, slider in self.sliders.items():
                slider.set_value(getattr(cfg, key))
                self.param_rows[key].setVisible(cfg.relevant(key))
            self.sections["limits"].setVisible(cfg.strategy != "manual")
            self.sections["rules"].setVisible(cfg.strategy != "manual")
            self._sync_rules(cfg)
            self.sections["assets"].setVisible(cfg.strategy != "manual")
            self.sections["execution"].setVisible(cfg.strategy != "manual")
            for sym, chip in self.chips.items():
                chip.setChecked(sym in cfg.assets)
            for key, btn in self.mode_buttons["buttons"].items():
                btn.setChecked(key == cfg.mode)
            for key, btn in self.freq_buttons["buttons"].items():
                btn.setChecked(key == cfg.frequency)
            self.mode_hint.setText(MODES[cfg.mode][1])
            self.summary.setText(describe(cfg))
            self._update_schedule(cfg)
            self.run.setEnabled(cfg.active and cfg.strategy != "manual")
            self.run.update()
        finally:
            self._syncing = False

    def _sync_rules(self, cfg) -> None:
        for chave, (campo, campo_valor) in self._rule_fields.items():
            ligada = bool(getattr(cfg, campo))
            box = self.rule_boxes[chave]
            box.setChecked(ligada)
            box.setEnabled(chave == "risk" or cfg.rule_risk)  # as outras regras partem do risco por operação
            self.rule_rows[chave].setEnabled(chave == "risk" or cfg.rule_risk)
            if self.rule_pills[chave]:
                for valor, botao in self.rule_pills[chave]["buttons"].items():
                    botao.setChecked(valor == getattr(cfg, campo_valor))
                    botao.setEnabled(ligada)
            box.update()

    def _pacote_padrao(self) -> None:
        self._set(rule_risk=True, rule_risk_pct=0.75, rule_daily_stop=True, rule_daily_stop_x=2, rule_daily_goal=True, rule_daily_goal_x=3, rule_sizing=True)
        self.notify.emit("Pacote padrão de risco aplicado", True)

    def _update_schedule(self, cfg) -> None:
        now = self.ws.mercado.agora()
        if cfg.strategy == "manual" or not cfg.active:
            self.schedule.setText("Sem execuções agendadas.")
            return
        last = f"Última execução: {_when(datetime.fromisoformat(cfg.last_run), now)}  ·  " if cfg.last_run else "Ainda não rodou  ·  "
        if not self.ws.pref("agendador"):
            self.schedule.setText(f"{last}execução automática desligada em Configurações: só “Rodar agora” executa")
            return
        try:
            referencia = datetime.fromisoformat(cfg.last_run) if cfg.last_run else now
        except ValueError:
            referencia = now
        proxima = next_run(cfg, referencia)
        quando = "vencida, roda em instantes" if proxima <= now else _when(proxima, now)
        self.schedule.setText(f"{last}próxima: {quando}  ·  roda só com o app aberto")

    # -- ações ---------------------------------------------------------------

    def _run_now(self) -> None:
        made, message = self.ws.run_agent(self.agent_id)
        self.notify.emit(message, made > 0)

    def _reset(self) -> None:
        box = QMessageBox(QMessageBox.Icon.Question, "Restaurar padrão", "Voltar este agente à configuração padrão?", parent=self)
        yes = box.addButton("Restaurar", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is yes:
            self.ws.reset_config(self.agent_id)
            self.notify.emit("Configuração restaurada", True)

