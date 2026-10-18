"""Formulário de registro de execução de uma meta.

Registrar é uma confirmação INTERNA: a execução fica "pendente de comprovação" até existir registro externo correspondente.
Erros aparecem dentro do formulário e nada do que foi digitado se perde. Todas as regras vêm do núcleo/serviço.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout
from pydantic import ValidationError

from ..metas import ErroDeRegistro, PainelMeta
from ..nucleo.esquema import Execucao, LadoExecucao
from . import theme
from .components import ActionButton, Label

W = theme.W

ROTULOS = {
    "id": "Identificador", "quantidade_bruta": "Quantidade bruta", "taxa_no_ativo": "Taxa no próprio ativo", "quantidade_liquida": "Quantidade líquida",
    "preco_executado": "Preço executado", "taxa_na_cotacao": "Taxa na moeda de cotação", "custo_fixo_real": "Custo fixo", "executada_em": "Executada em",
    "confirmada_em": "Confirmada em", "fonte_id": "Fonte do registro", "estorna_execucao_id": "Estorna a execução", "referencias_externas": "Registro externo",
}
FORMATO_HORA = "%Y-%m-%d %H:%M"


class ErroDeFormulario(ValueError):
    pass


def decimal(texto: str, campo: str, *, obrigatorio=True) -> str:
    """Devolve o decimal como TEXTO (o núcleo nunca aceita float). Aceita vírgula; recusa notação científica."""
    limpo = texto.strip().replace(",", ".")
    if not limpo:
        if obrigatorio:
            raise ErroDeFormulario(f"{campo}: informe um valor")
        return "0"
    if "e" in limpo.lower():
        raise ErroDeFormulario(f"{campo}: use número simples, sem notação científica")
    try:
        valor = Decimal(limpo)
    except InvalidOperation as erro:
        raise ErroDeFormulario(f"{campo}: “{texto.strip()}” não é um número") from erro
    if not valor.is_finite():
        raise ErroDeFormulario(f"{campo}: valor inválido")
    return limpo


def instante(texto: str, campo: str) -> str:
    try:
        return datetime.strptime(texto.strip(), FORMATO_HORA).strftime("%Y-%m-%dT%H:%M:00Z")
    except ValueError as erro:
        raise ErroDeFormulario(f"{campo}: use AAAA-MM-DD HH:MM (horário UTC)") from erro


def mensagens(erro: ValidationError) -> list[str]:
    saida = []
    for e in erro.errors():
        campo = ROTULOS.get(str(e["loc"][0]) if e["loc"] else "", "Execução")
        saida.append(f"{campo}: {e['msg'].removeprefix('Value error, ')}")
    return saida


class ExecucaoDialog(QDialog):
    """`ao_salvar(execucao) -> bool` chama o serviço: True = gravou; False = já estava registrada; pode levantar ErroDeRegistro."""

    def __init__(self, painel: PainelMeta, ao_salvar: Callable[[Execucao], bool], parent=None):
        super().__init__(parent)
        self.painel, self.ao_salvar = painel, ao_salvar
        self.salvou = self.nova = False
        ativo, moeda = painel.ativo_id, painel.moeda_cotacao_id
        self.setWindowTitle("Registrar execução")
        self.setMinimumWidth(560)
        self.setStyleSheet(
            f"QDialog {{ background: {theme.BG_BOTTOM}; }} QLabel {{ color: {theme.TEXT}; }}"
            f"QLineEdit, QComboBox {{ background: {theme.PANEL}; color: {theme.TEXT}; border: 1px solid {theme.PANEL_EDGE};"
            f" border-radius: 10px; padding: 7px 10px; font-size: 14px; }} QLineEdit:focus {{ border-color: {theme.BLUE}; }}"
            f"QComboBox QAbstractItemView {{ background: {theme.PANEL}; color: {theme.TEXT}; }}"
        )

        def campo(texto="", dica="") -> QLineEdit:
            c = QLineEdit(texto)
            c.setPlaceholderText(dica)
            return c

        n = len(painel.execucoes) + 1
        self.campos = {
            "id": campo(f"exec-{n}", "ex.: exec-1"),
            "quantidade_bruta": campo(dica=f"{ativo} recebidos, antes das taxas"),
            "taxa_no_ativo": campo("0", f"{ativo} cobrados no próprio ativo"),
            "preco_executado": campo(dica=f"{moeda} por 1 {ativo}"),
            "taxa_na_cotacao": campo("0", f"em {moeda}"),
            "custo_fixo_real": campo("0", f"em {moeda}"),
            "executada_em": campo(dica="AAAA-MM-DD HH:MM (UTC)"),
            "confirmada_em": campo(dica="AAAA-MM-DD HH:MM (UTC)"),
            "fonte_id": campo("registro-manual"),
            "ref_fonte": campo(dica="fonte externa, ex.: corretora-sim"),
            "ref_id": campo(dica="id do fill/ordem na fonte"),
        }
        self.lado = QComboBox()
        self.lado.addItem("Compra", LadoExecucao.COMPRA.value)
        self.lado.addItem("Estorno de compra", LadoExecucao.ESTORNO_COMPRA.value)
        self.estorna = QComboBox()
        for r in painel.execucoes:
            if r.execucao.lado is LadoExecucao.COMPRA:
                self.estorna.addItem(f"{r.execucao.id} ({r.execucao.quantidade_liquida.normalize():f} {ativo})", r.execucao.id)
        self.origem = QComboBox()
        self.origem.addItem("Observado (dado real)", "observado")
        self.origem.addItem("Simulado", "simulado")
        self.liquida = QLabel("—")
        self.liquida.setStyleSheet(f"color: {theme.MUTED};")
        self.lado.currentIndexChanged.connect(self._atualizar_lado)
        for nome in ("quantidade_bruta", "taxa_no_ativo"):
            self.campos[nome].textChanged.connect(self._atualizar_liquida)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("Meta", QLabel(f"{painel.meta_id}  ·  ativo {ativo}  ·  cotação em {moeda}"))
        form.addRow("Identificador", self.campos["id"])
        form.addRow("Tipo", self.lado)
        form.addRow("Estorna a execução", self.estorna)
        form.addRow(f"Quantidade bruta ({ativo})", self.campos["quantidade_bruta"])
        form.addRow(f"Taxa no próprio ativo ({ativo})", self.campos["taxa_no_ativo"])
        form.addRow(f"Quantidade líquida ({ativo})", self.liquida)
        form.addRow(f"Preço executado ({moeda}/{ativo})", self.campos["preco_executado"])
        form.addRow(f"Taxa em {moeda}", self.campos["taxa_na_cotacao"])
        form.addRow(f"Custo fixo em {moeda}", self.campos["custo_fixo_real"])
        form.addRow("Executada em (UTC)", self.campos["executada_em"])
        form.addRow("Confirmada em (UTC)", self.campos["confirmada_em"])
        form.addRow("Fonte do registro", self.campos["fonte_id"])
        form.addRow("Origem do dado", self.origem)
        form.addRow("Registro externo · fonte", self.campos["ref_fonte"])
        form.addRow("Registro externo · id", self.campos["ref_id"])
        self._form = form

        aviso = QLabel(
            "Registrar é uma confirmação interna e NÃO comprova nada. A execução ficará pendente de comprovação "
            "até chegar um registro externo correspondente (mesma fonte e id acima). Sem a referência externa ela não poderá ser comprovada."
        )
        aviso.setWordWrap(True)
        aviso.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
        self.erros = QLabel("")
        self.erros.setWordWrap(True)
        self.erros.setStyleSheet(f"color: {theme.RED}; font-size: 13px;")
        self.erros.hide()
        self.salvar_btn = ActionButton("Registrar execução", primary=True, height=38, pad=20)
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
        v.addWidget(Label("Registrar execução", 22, W.DemiBold))
        v.addLayout(form)
        v.addWidget(aviso)
        v.addWidget(self.erros)
        v.addLayout(botoes)
        self._atualizar_lado()

    # -- comportamento -------------------------------------------------------------------------------------------------

    def _atualizar_lado(self) -> None:
        estorno = self.lado.currentData() == LadoExecucao.ESTORNO_COMPRA.value
        self._form.labelForField(self.estorna).setVisible(estorno)
        self.estorna.setVisible(estorno)

    def _atualizar_liquida(self) -> None:
        try:
            bruta = Decimal(decimal(self.campos["quantidade_bruta"].text(), "x"))
            taxa = Decimal(decimal(self.campos["taxa_no_ativo"].text(), "x", obrigatorio=False))
            self.liquida.setText(f"{(bruta - taxa).normalize():f}  (bruta − taxa; calculada pelo sistema)")
        except (ErroDeFormulario, InvalidOperation):
            self.liquida.setText("—")

    def definir(self, **valores: str) -> None:
        """Preenche campos pelo nome (usado em testes e para reabrir com os dados)."""
        for nome, valor in valores.items():
            self.campos[nome].setText(valor)

    def montar(self) -> Execucao:
        c = {n: w.text() for n, w in self.campos.items()}
        bruta = decimal(c["quantidade_bruta"], "Quantidade bruta")
        taxa = decimal(c["taxa_no_ativo"], "Taxa no próprio ativo", obrigatorio=False)
        liquida = format(Decimal(bruta) - Decimal(taxa), "f")
        estorno = self.lado.currentData() == LadoExecucao.ESTORNO_COMPRA.value
        if bool(c["ref_fonte"].strip()) != bool(c["ref_id"].strip()):
            raise ErroDeFormulario("Registro externo: informe a fonte E o id (ou deixe os dois vazios)")
        dados = {
            "id": c["id"].strip(), "meta_id": self.painel.meta_id, "ativo_id": self.painel.ativo_id, "lado": self.lado.currentData(),
            "quantidade_bruta": bruta, "taxa_no_ativo": taxa, "quantidade_liquida": liquida,
            "preco_executado": decimal(c["preco_executado"], "Preço executado"),
            "taxa_na_cotacao": decimal(c["taxa_na_cotacao"], "Taxa na moeda de cotação", obrigatorio=False),
            "custo_fixo_real": decimal(c["custo_fixo_real"], "Custo fixo", obrigatorio=False),
            "moeda_cotacao_id": self.painel.moeda_cotacao_id,
            "executada_em": instante(c["executada_em"], "Executada em"), "confirmada_em": instante(c["confirmada_em"], "Confirmada em"),
            "fonte_id": c["fonte_id"].strip(), "origem": self.origem.currentData(),
            "estorna_execucao_id": self.estorna.currentData() if estorno else None,
            "referencias_externas": [{"fonte_id": c["ref_fonte"].strip(), "id_externo": c["ref_id"].strip()}] if c["ref_id"].strip() else [],
        }
        return Execucao.model_validate(dados)

    def salvar(self) -> bool:
        """Valida e grava. Em qualquer erro o formulário continua aberto com tudo preenchido."""
        try:
            execucao = self.montar()
            gravou = self.ao_salvar(execucao)
        except ErroDeFormulario as erro:
            return self._mostrar([str(erro)])
        except ValidationError as erro:
            return self._mostrar(mensagens(erro))
        except ErroDeRegistro as erro:
            return self._mostrar([str(erro)])
        self.erros.hide()
        self.salvou, self.nova = True, gravou
        self.accept()
        return True

    def _mostrar(self, linhas: list[str]) -> bool:
        self.erros.setText("\n".join(f"• {m}" for m in linhas))
        self.erros.show()
        return False
