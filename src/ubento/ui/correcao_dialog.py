"""Corrigir um vínculo manual: revogar ou substituir. O vínculo original fica no histórico; nada vira execução nem estorno."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout
from pydantic import ValidationError

from ..metas import ErroDeRegistro, ExecucaoRegistrada
from ..nucleo.conciliacao.modelos import RegistroExterno
from . import theme
from .components import ActionButton, Label
from .vinculo_dialog import MINIMO_JUSTIFICATIVA, descrever

W = theme.W
REVOGAR, SUBSTITUIR = "revogar", "substituir"


class CorrecaoVinculoDialog(QDialog):
    """`ao_salvar(acao, fonte_novo, id_novo, autor, justificativa) -> bool`: True = corrigiu; False = já estava corrigido; pode levantar ErroDeRegistro."""

    def __init__(self, registrada: ExecucaoRegistrada, candidatos: list[RegistroExterno], ao_salvar: Callable[..., bool], parent=None):
        super().__init__(parent)
        assert registrada.vinculo is not None
        self.registrada, self.ao_salvar = registrada, ao_salvar
        self.salvou = self.nova = False
        v, e = registrada.vinculo, registrada.execucao
        self.setWindowTitle("Corrigir vínculo")
        self.setMinimumSize(520, 380)
        self.setStyleSheet(
            f"QDialog {{ background: {theme.BG_BOTTOM}; }} QLabel {{ color: {theme.TEXT}; }}"
            f"QLineEdit, QComboBox, QPlainTextEdit {{ background: {theme.PANEL}; color: {theme.TEXT}; border: 1px solid {theme.PANEL_EDGE};"
            f" border-radius: 10px; padding: 7px 10px; font-size: 14px; }} QLineEdit:focus, QPlainTextEdit:focus {{ border-color: {theme.BLUE}; }}"
            f"QComboBox QAbstractItemView {{ background: {theme.PANEL}; color: {theme.TEXT}; }}"
        )
        self.acao = QComboBox()
        self.acao.addItem("Revogar este vínculo", REVOGAR)
        self.acao.addItem("Substituir por outro registro", SUBSTITUIR)
        self.acao.currentIndexChanged.connect(self._atualizar)
        self.registro = QComboBox()
        for r in candidatos:
            self.registro.addItem(descrever(r), (r.fonte_id, r.id_externo))
        self.autor = QLineEdit()
        self.autor.setPlaceholderText("quem está tomando esta decisão")
        self.justificativa = QPlainTextEdit()
        self.justificativa.setPlaceholderText(f"por que o vínculo atual está errado (mínimo {MINIMO_JUSTIFICATIVA} caracteres)")
        self.justificativa.setFixedHeight(84)

        self.form = QFormLayout()
        self.form.setSpacing(10)
        self.form.addRow("Execução", QLabel(f"{e.id}  ·  {e.quantidade_liquida.normalize():f} {e.ativo_id}"))
        self.form.addRow("Vínculo atual", QLabel(f"{v.fonte_id} / {v.id_externo}  ·  por {v.autor}"))
        self.form.addRow("Ação", self.acao)
        self.form.addRow("Novo registro", self.registro)
        self.form.addRow("Autor", self.autor)
        self.form.addRow("Justificativa", self.justificativa)

        aviso = QLabel(
            "O vínculo original é preservado no histórico e a correção registra autor, justificativa e instante. "
            "Nenhuma execução nem estorno é criado: a meta é reavaliada e, se a prova anterior deixar de valer, ela é revertida pelo razão."
        )
        aviso.setWordWrap(True)
        aviso.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
        self.erros = QLabel("")
        self.erros.setWordWrap(True)
        self.erros.setStyleSheet(f"color: {theme.RED}; font-size: 13px;")
        self.erros.hide()
        self.salvar_btn = ActionButton("Corrigir vínculo", primary=True, danger=False, height=38, pad=20)
        self.salvar_btn.clicked.connect(self.salvar)
        cancelar = ActionButton("Cancelar", height=38, pad=20)
        cancelar.clicked.connect(self.reject)
        botoes = QHBoxLayout()
        botoes.addStretch(1)
        botoes.addWidget(cancelar)
        botoes.addWidget(self.salvar_btn)

        v_ = QVBoxLayout(self)
        v_.setContentsMargins(24, 20, 24, 20)
        v_.setSpacing(12)
        v_.addWidget(Label("Corrigir vínculo", 22, W.DemiBold))
        v_.addLayout(self.form)
        v_.addWidget(aviso)
        v_.addWidget(self.erros)
        v_.addLayout(botoes)
        self._atualizar()

    def _atualizar(self) -> None:
        substituir = self.acao.currentData() == SUBSTITUIR
        self.form.labelForField(self.registro).setVisible(substituir)
        self.registro.setVisible(substituir)

    def definir(self, acao: str | None = None, autor: str = "", justificativa: str = "", indice: int | None = None) -> None:
        if acao is not None:
            self.acao.setCurrentIndex(self.acao.findData(acao))
        self.autor.setText(autor)
        self.justificativa.setPlainText(justificativa)
        if indice is not None:
            self.registro.setCurrentIndex(indice)

    def salvar(self) -> bool:
        """Em qualquer erro o diálogo continua aberto com o que foi preenchido."""
        autor, justificativa = self.autor.text().strip(), self.justificativa.toPlainText().strip()
        acao = self.acao.currentData()
        if acao == SUBSTITUIR and self.registro.currentData() is None:
            return self._erro("Não há outro registro externo disponível. Importe a evidência primeiro, ou escolha revogar.")
        if not autor:
            return self._erro("Informe o autor da decisão.")
        if len(justificativa) < MINIMO_JUSTIFICATIVA:
            return self._erro(f"A justificativa precisa ter ao menos {MINIMO_JUSTIFICATIVA} caracteres ({len(justificativa)} até agora).")
        fonte, ident = self.registro.currentData() if acao == SUBSTITUIR else (None, None)
        try:
            self.nova = self.ao_salvar(acao, fonte, ident, autor, justificativa)
        except (ErroDeRegistro, ValidationError) as erro:
            return self._erro(str(erro).splitlines()[0])
        self.salvou = True
        self.accept()
        return True

    def _erro(self, mensagem: str) -> bool:
        self.erros.setText(f"• {mensagem}")
        self.erros.show()
        return False
