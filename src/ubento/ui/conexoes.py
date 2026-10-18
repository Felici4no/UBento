"""Seção "Conexões" das Configurações: lista de conexões com corretoras e o diálogo para adicionar uma nova.

A chave de API e o segredo são digitados aqui, mas só vão para o cofre do sistema (nunca para o banco, o log ou a tela depois de salvos).
A rede é consultada fora da thread da interface; o banco e o cofre só são usados na thread principal.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QSizePolicy, QVBoxLayout, QWidget

from ..conexoes import CONECTADA, ERRO, REPROVADA, PROVEDORES, Conexao, ErroDeConfiguracao, ServicoConexoes
from . import theme
from .components import ActionButton, Card, Label, PillButton, setup
from .controls import Chip

W = theme.W
log = logging.getLogger("ubento.ui.conexoes")
STATUS = {CONECTADA: ("Conectada", theme.GREEN), REPROVADA: ("Reprovada", theme.RED), ERRO: ("Falha na verificação", theme.WARNING)}


def desenhar_logo(p: QPainter, area: QRectF, provedor_id: str, cor: str) -> None:
    """Marca simplificada do provedor, desenhada com QPainter (sem arquivos de imagem). Hoje só a Binance."""
    p.save()
    setup(p)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(cor))
    if provedor_id == "binance":  # cinco losangos: um central e quatro ao redor, como na marca
        c, u = area.center(), area.width() * 0.105

        def losango(x: float, y: float, r: float) -> None:
            caminho = QPainterPath()
            caminho.moveTo(QPointF(x, y - r))
            caminho.lineTo(QPointF(x + r, y))
            caminho.lineTo(QPointF(x, y + r))
            caminho.lineTo(QPointF(x - r, y))
            caminho.closeSubpath()
            p.drawPath(caminho)

        losango(c.x(), c.y(), u * 1.05)
        d = u * 2.35
        for dx, dy in ((d, 0), (-d, 0), (0, d), (0, -d)):
            losango(c.x() + dx, c.y() + dy, u * 1.0)
    else:  # provedor sem logo próprio: inicial
        p.setPen(QColor(cor))
        p.setFont(theme.font(18, W.DemiBold))
        p.drawText(area, Qt.AlignmentFlag.AlignCenter, provedor_id[:1].upper())
    p.restore()


class LogoProvedor(QWidget):
    def __init__(self, provedor_id: str, tamanho: int = 44, parent=None):
        super().__init__(parent)
        self.provedor_id = provedor_id
        self.setFixedSize(tamanho, tamanho)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(QColor(theme.PANEL))
        p.setPen(QPen(QColor(theme.PANEL_EDGE), 1))
        p.drawRoundedRect(r, r.height() * 0.3, r.height() * 0.3)
        provedor = PROVEDORES.get(self.provedor_id)
        desenhar_logo(p, r, self.provedor_id, provedor.cor if provedor else theme.MUTED)


def em_thread(trabalho: Callable[[], object], concluir: Callable[[object, Exception | None], None], sinal: Signal, sincrono: bool) -> None:
    """Roda `trabalho` (só rede!) fora da thread da interface e entrega o resultado por `sinal` (que cai na thread certa)."""
    def corpo():
        try:
            resultado, erro = trabalho(), None
        except Exception as e:  # noqa: BLE001 - entregue à interface, que decide a mensagem
            resultado, erro = None, e
        if sincrono:
            concluir(resultado, erro)
        else:
            sinal.emit(resultado, erro)

    if sincrono:
        corpo()
    else:
        threading.Thread(target=corpo, daemon=True).start()


class ConexaoDialog(QDialog):
    """Pede os dados, verifica a chave na corretora e só então conecta. Qualquer erro mantém o diálogo aberto com o que foi digitado."""

    _resultado = Signal(object, object)

    def __init__(self, servico: ServicoConexoes, provedor_id: str = "binance", parent=None, sincrono: bool = False):
        super().__init__(parent)
        self.servico, self.provedor_id, self.sincrono = servico, provedor_id, sincrono
        self.conexao: Conexao | None = None
        provedor = PROVEDORES[provedor_id]
        self.setWindowTitle("Adicionar conexão")
        self.setMinimumWidth(560)
        self.setStyleSheet(
            f"QDialog {{ background: {theme.BG_BOTTOM}; }} QLabel {{ color: {theme.TEXT}; }}"
            f"QLineEdit {{ background: {theme.PANEL}; color: {theme.TEXT}; border: 1px solid {theme.PANEL_EDGE};"
            f" border-radius: 10px; padding: 8px 12px; font-size: 14px; selection-background-color: {theme.BLUE}; }}"
            f"QLineEdit:focus {{ border-color: {theme.BLUE}; }}"
        )
        topo = QHBoxLayout()
        topo.setSpacing(12)
        topo.addWidget(LogoProvedor(provedor_id, 48))
        titulo = QVBoxLayout()
        titulo.setSpacing(0)
        titulo.addWidget(Label(provedor.nome, 22, W.DemiBold))
        titulo.addWidget(Label(provedor.descricao, 13, W.Normal, theme.MUTED))
        topo.addLayout(titulo)
        topo.addStretch(1)
        escolha = QHBoxLayout()
        escolha.setSpacing(6)
        for pid, pr in PROVEDORES.items():
            b = PillButton(pr.nome, height=32, pad=14, px=13)
            b.setCheckable(True)
            b.setChecked(pid == provedor_id)
            escolha.addWidget(b)
        escolha.addWidget(Label("mais corretoras em breve", 12, W.Normal, theme.DIM))
        escolha.addStretch(1)

        self.apelido = QLineEdit()
        self.apelido.setPlaceholderText(f"ex.: {provedor.nome} pessoal (opcional)")
        self.campos: dict[str, QLineEdit] = {}
        form = QFormLayout()
        form.setSpacing(10)
        form.addRow("Apelido", self.apelido)
        for campo in provedor.campos:
            edicao = QLineEdit()
            edicao.setPlaceholderText(campo.dica)
            if campo.secreto:
                edicao.setEchoMode(QLineEdit.EchoMode.Password)
            edicao.setClearButtonEnabled(False)
            self.campos[campo.nome] = edicao
            form.addRow(campo.rotulo, edicao)

        ajuda = QLabel(provedor.como_conectar)
        ajuda.setWordWrap(True)
        ajuda.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
        garantia = QLabel("A chave e o segredo ficam só no cofre deste computador (Windows) e nunca no banco do UBento. "
                          "O UBento só lê dados: não negocia nem saca.")
        garantia.setWordWrap(True)
        garantia.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
        self.erro = QLabel("")
        self.erro.setWordWrap(True)
        self.erro.setStyleSheet(f"color: {theme.RED}; font-size: 13px;")
        self.erro.hide()
        self.botao = ActionButton("Verificar e conectar", primary=True, height=38, pad=20)
        self.botao.clicked.connect(self.conectar)
        cancelar = ActionButton("Cancelar", height=38, pad=20)
        cancelar.clicked.connect(self.reject)
        botoes = QHBoxLayout()
        botoes.addStretch(1)
        botoes.addWidget(cancelar)
        botoes.addWidget(self.botao)

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(12)
        v.addLayout(topo)
        v.addLayout(escolha)
        v.addLayout(form)
        v.addWidget(ajuda)
        v.addWidget(garantia)
        v.addWidget(self.erro)
        v.addLayout(botoes)
        self._resultado.connect(self._concluir)

    def definir(self, apelido: str = "", **campos: str) -> None:
        self.apelido.setText(apelido)
        for nome, valor in campos.items():
            self.campos[nome].setText(valor)

    def _mostrar_erro(self, mensagem: str) -> None:
        self.erro.setText(f"• {mensagem}")
        self.erro.show()
        self.botao.setEnabled(True)
        self.botao.setText("Verificar e conectar")
        self.botao.update()

    def conectar(self) -> None:
        self.erro.hide()
        credenciais = {n: c.text() for n, c in self.campos.items()}
        try:
            limpas = self.servico.preparar(self.provedor_id, credenciais)  # só banco: thread principal
        except ErroDeConfiguracao as erro:
            self._mostrar_erro(str(erro))
            return
        self.botao.setEnabled(False)
        self.botao.setText("Verificando…")
        self.botao.update()
        self._limpas = limpas
        em_thread(lambda: self.servico.verificar(self.provedor_id, limpas), self._concluir, self._resultado, self.sincrono)  # só rede

    def _concluir(self, verificacao, erro) -> None:
        if erro is not None:
            if not isinstance(erro, ErroDeConfiguracao):
                log.error("falha inesperada ao verificar a conexão", exc_info=erro)
            self._mostrar_erro(str(erro) if isinstance(erro, ErroDeConfiguracao) else "Não foi possível verificar a chave. Tente de novo.")
            return
        try:
            self.conexao = self.servico.gravar(self.provedor_id, self.apelido.text(), self._limpas, verificacao)  # cofre + banco: thread principal
        except ErroDeConfiguracao as e:
            self._mostrar_erro(str(e))
            return
        finally:
            self._limpas = {}
        self.accept()


class ConexoesSection(Card):
    """Cartão das Configurações: uma linha por conexão (logo, apelido, status, Testar, Remover) e o botão de adicionar."""

    notify = Signal(str, bool)
    _teste_pronto = Signal(object, object)

    def __init__(self, servico: ServicoConexoes, sincrono: bool = False, confirmar: Callable[[str, str, str], bool] | None = None, parent=None):
        super().__init__(parent)
        self.servico, self.sincrono = servico, sincrono
        self._confirmar = confirmar or self._confirmar_padrao
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(24, 20, 24, 20)
        self._layout.setSpacing(10)
        self._linhas = QVBoxLayout()
        self._linhas.setSpacing(8)
        self.adicionar = ActionButton("Adicionar conexão", primary=True, height=38, pad=20)
        self.adicionar.clicked.connect(self.abrir_dialogo)
        self._layout.addWidget(Label("CONEXÕES", 13, W.DemiBold, theme.MUTED))
        self._layout.addWidget(Label("Ligue corretoras ao UBento com uma chave de API somente leitura.", 13, W.Normal, theme.MUTED))
        self._layout.addLayout(self._linhas)
        botoes = QHBoxLayout()
        botoes.addWidget(self.adicionar)
        botoes.addStretch(1)
        self._layout.addLayout(botoes)
        self._teste_pronto.connect(self._teste_concluido)
        self.refresh()

    # -- desenho ---------------------------------------------------------------------------------------------------------

    def refresh(self) -> None:
        while self._linhas.count():
            item = self._linhas.takeAt(0)
            if item.widget():
                velho = item.widget()
                velho.setParent(None)
                velho.deleteLater()
        conexoes = self.servico.listar()
        if not conexoes:
            vazio = Label("Nenhuma conexão ainda. A Binance é a primeira disponível.", 14, W.Normal, theme.TEXT)
            self._linhas.addWidget(vazio)
        for c in conexoes:
            self._linhas.addWidget(self._linha(c))

    def _linha(self, c: Conexao) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 4, 0, 4)
        h.setSpacing(12)
        h.addWidget(LogoProvedor(c.provedor, 44))
        texto = QVBoxLayout()
        texto.setSpacing(1)
        texto.addWidget(Label(c.apelido, 16, W.Medium))
        rotulo, cor = STATUS.get(c.status, ("—", theme.DIM))
        quando = c.status_em.astimezone().strftime("%d/%m/%Y %H:%M") if isinstance(c.status_em, datetime) else ""
        detalhe = Label(f"{c.nome_provedor} · chave {c.chave_mascarada} · verificada em {quando}", 12, W.Normal, theme.MUTED)
        detalhe.setWordWrap(True)
        texto.addWidget(detalhe)
        if c.status != CONECTADA:
            aviso = Label(c.mensagem, 12, W.Normal, theme.WARNING if c.status == ERRO else theme.RED)
            aviso.setWordWrap(True)
            texto.addWidget(aviso)
        h.addLayout(texto, 1)
        h.addWidget(Chip(rotulo, cor))
        testar = ActionButton("Testar", height=32, pad=14)
        testar.clicked.connect(lambda _=False, i=c.id: self.testar(i))
        remover = ActionButton("Remover", danger=True, height=32, pad=14)
        remover.clicked.connect(lambda _=False, i=c.id: self.remover(i))
        h.addWidget(testar)
        h.addWidget(remover)
        return w

    # -- ações ---------------------------------------------------------------------------------------------------------------

    def criar_dialogo(self, provedor_id: str = "binance") -> ConexaoDialog:
        return ConexaoDialog(self.servico, provedor_id, self, self.sincrono)

    def abrir_dialogo(self) -> None:
        dialogo = self.criar_dialogo()
        if dialogo.exec() and dialogo.conexao:
            self.notify.emit(f"{dialogo.conexao.apelido} conectada (somente leitura)", True)
        self.refresh()

    def testar(self, ident: str) -> None:
        try:
            atual, credenciais = self.servico.credenciais_de(ident)  # banco e cofre: thread principal
        except ErroDeConfiguracao as erro:
            self.notify.emit(str(erro), False)
            return
        self._testando = ident
        em_thread(lambda: self.servico.conferir(atual, credenciais), self._teste_concluido, self._teste_pronto, self.sincrono)  # só rede

    def _teste_concluido(self, resultado, erro) -> None:
        if erro is not None:
            log.error("falha inesperada ao testar a conexão", exc_info=erro)
            self.notify.emit("Não foi possível testar a conexão agora.", False)
            return
        c = self.servico.registrar_teste(self._testando, resultado)
        self.notify.emit(f"{c.apelido}: {c.mensagem}", c.status == CONECTADA)
        self.refresh()

    def _confirmar_padrao(self, titulo: str, texto: str, botao: str) -> bool:
        caixa = QMessageBox(QMessageBox.Icon.Question, titulo, texto, parent=self)
        sim = caixa.addButton(botao, QMessageBox.ButtonRole.DestructiveRole)
        caixa.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        caixa.exec()
        return caixa.clickedButton() is sim

    def remover(self, ident: str) -> None:
        c = next((x for x in self.servico.listar() if x.id == ident), None)
        if c is None:
            return
        if self._confirmar("Remover conexão", f"Remover “{c.apelido}” deste computador? A chave será apagada do cofre. "
                           "Para invalidá-la de vez, revogue-a também no site da corretora.", "Remover"):
            self.servico.remover(ident)
            self.notify.emit(f"{c.apelido} removida", True)
            self.refresh()
