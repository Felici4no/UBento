"""Vínculo manual: liga, depois, uma execução registrada a um registro externo já importado.

É uma decisão humana e fica no histórico (autor, justificativa e instante); a execução em si não é editada. O vínculo só diz QUAL
registro externo corresponde: se isso comprova ou não, quem decide é a conciliação.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout
from pydantic import ValidationError

from ..metas import ErroDeRegistro, ExecucaoRegistrada
from ..nucleo.conciliacao.modelos import RegistroExterno
from . import theme
from .components import ActionButton, Label

W = theme.W
MINIMO_JUSTIFICATIVA = 10


def descrever(r: RegistroExterno) -> str:
    return f"{r.fonte_id} / {r.id_externo}  ·  {r.quantidade.normalize():f} {r.ativo_id}  ·  {r.executado_em:%d/%m %H:%M} UTC  ·  {r.status.value}"


class VinculoDialog(QDialog):
    """`ao_salvar(fonte_id, id_externo, autor, justificativa) -> bool`: True = vinculou; False = já estava vinculada; pode levantar ErroDeRegistro."""

    def __init__(self, registrada: ExecucaoRegistrada, candidatos: list[RegistroExterno], ao_salvar: Callable[..., bool], parent=None):
        super().__init__(parent)
        self.registrada, self.ao_salvar = registrada, ao_salvar
        self.salvou = self.nova = False
        e = registrada.execucao
        self.setWindowTitle("Vincular a registro externo")
        self.setMinimumSize(520, 340)
        self.setStyleSheet(
            f"QDialog {{ background: {theme.BG_BOTTOM}; }} QLabel {{ color: {theme.TEXT}; }}"
            f"QLineEdit, QComboBox, QPlainTextEdit {{ background: {theme.PANEL}; color: {theme.TEXT}; border: 1px solid {theme.PANEL_EDGE};"
            f" border-radius: 10px; padding: 7px 10px; font-size: 14px; }} QLineEdit:focus, QPlainTextEdit:focus {{ border-color: {theme.BLUE}; }}"
            f"QComboBox QAbstractItemView {{ background: {theme.PANEL}; color: {theme.TEXT}; }}"
        )
        self.registro = QComboBox()
        for r in candidatos:
            self.registro.addItem(descrever(r), (r.fonte_id, r.id_externo))
        self.autor = QLineEdit()
        self.autor.setPlaceholderText("quem está tomando esta decisão")
        self.justificativa = QPlainTextEdit()
        self.justificativa.setPlaceholderText(f"por que este registro corresponde a esta execução (mínimo {MINIMO_JUSTIFICATIVA} caracteres)")
        self.justificativa.setFixedHeight(84)

        form = QFormLayout()
        form.setSpacing(10)
        form.addRow("Execução", QLabel(f"{e.id}  ·  {e.quantidade_liquida.normalize():f} {e.ativo_id}  ·  {e.executada_em:%d/%m %H:%M} UTC"))
        form.addRow("Registro externo", self.registro)
        form.addRow("Autor", self.autor)
        form.addRow("Justificativa", self.justificativa)

        aviso = QLabel(
            "O vínculo fica registrado no histórico (a execução não é editada) e a meta é reavaliada. "
            "Quem decide se o registro comprova a execução é a conciliação: quantidade, ativo, taxas e horários ainda são conferidos."
        )
        aviso.setWordWrap(True)
        aviso.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
        self.erros = QLabel("")
        self.erros.setWordWrap(True)
        self.erros.setStyleSheet(f"color: {theme.RED}; font-size: 13px;")
        self.erros.hide()
        self.salvar_btn = ActionButton("Vincular", primary=True, height=38, pad=20)
        self.salvar_btn.clicked.connect(self.salvar)
        cancelar = ActionButton("Cancelar", height=38, pad=20)
        cancelar.clicked.connect(self.reject)
        botoes = QHBoxLayout()
        botoes.addStretch(1)
        botoes.addWidget(cancelar)
        botoes.addWidget(self.salvar_btn)

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(12)
        v.addWidget(Label("Vincular a registro externo", 22, W.DemiBold))
        if not candidatos:
            sem = QLabel("Não há registro externo disponível. Importe a evidência primeiro (ou todos já estão vinculados).")
            sem.setWordWrap(True)
            sem.setStyleSheet(f"color: {theme.WARNING}; font-size: 13px;")
            v.addWidget(sem)
            self.salvar_btn.setEnabled(False)
        v.addLayout(form)
        v.addWidget(aviso)
        v.addWidget(self.erros)
        v.addLayout(botoes)

    def definir(self, autor: str = "", justificativa: str = "", indice: int | None = None) -> None:
        self.autor.setText(autor)
        self.justificativa.setPlainText(justificativa)
        if indice is not None:
            self.registro.setCurrentIndex(indice)

    def salvar(self) -> bool:
        """Em qualquer erro o diálogo continua aberto com o que foi preenchido."""
        autor, justificativa = self.autor.text().strip(), self.justificativa.toPlainText().strip()
        if self.registro.currentData() is None:
            return self._erro("Escolha o registro externo.")
        if not autor:
            return self._erro("Informe o autor da decisão.")
        if len(justificativa) < MINIMO_JUSTIFICATIVA:
            return self._erro(f"A justificativa precisa ter ao menos {MINIMO_JUSTIFICATIVA} caracteres ({len(justificativa)} até agora).")
        fonte, id_externo = self.registro.currentData()
        try:
            self.nova = self.ao_salvar(fonte, id_externo, autor, justificativa)
        except (ErroDeRegistro, ValidationError) as erro:
            return self._erro(str(erro).splitlines()[0])
        self.salvou = True
        self.accept()
        return True

    def _erro(self, mensagem: str) -> bool:
        self.erros.setText(f"• {mensagem}")
        self.erros.show()
        return False
