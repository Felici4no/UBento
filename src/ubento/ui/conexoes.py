"""Seção "Conexões" das Configurações: corretoras (chave somente leitura) e o bot do Telegram.

A chave de API, o segredo e o token do bot são digitados aqui, mas só vão para o cofre do sistema (nunca para o banco, o log ou a tela depois
de salvos). A rede é consultada fora da thread da interface; o banco e o cofre só são usados na thread principal.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QSizePolicy, QVBoxLayout, QWidget

from ..conexoes import CONECTADA, ERRO, PROVEDORES, REPROVADA, Conexao, ErroDeConfiguracao, ServicoConexoes
from . import theme
from .components import ActionButton, Card, Label, setup
from .controls import Chip

W = theme.W
log = logging.getLogger("ubento.ui.conexoes")
STATUS = {CONECTADA: ("Conectada", theme.GREEN), REPROVADA: ("Reprovada", theme.RED), ERRO: ("Falha na verificação", theme.WARNING)}
OUVINTE = {"ouvindo": ("Atendendo", theme.GREEN), "erro": ("Sem rede", theme.WARNING), "conflito": ("Bot em uso por outro programa", theme.RED), "parado": ("Parado", theme.DIM)}


def desenhar_logo(p: QPainter, area: QRectF, provedor_id: str, cor: str) -> None:
    """Marca simplificada do provedor, desenhada com QPainter (sem arquivos de imagem)."""
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
    elif provedor_id == "telegram":  # círculo azul com o avião de papel
        c, u = area.center(), area.width() * 0.34
        p.drawEllipse(c, u, u)
        aviao = QPainterPath()
        aviao.moveTo(QPointF(c.x() - u * 0.62, c.y() - u * 0.02))
        aviao.lineTo(QPointF(c.x() + u * 0.62, c.y() - u * 0.46))
        aviao.lineTo(QPointF(c.x() + u * 0.28, c.y() + u * 0.58))
        aviao.lineTo(QPointF(c.x() - u * 0.06, c.y() + u * 0.16))
        aviao.lineTo(QPointF(c.x() - u * 0.2, c.y() + u * 0.48))
        aviao.lineTo(QPointF(c.x() - u * 0.24, c.y() + u * 0.12))
        aviao.closeSubpath()
        p.setBrush(QColor("#FFFFFF"))
        p.drawPath(aviao)
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


ESTILO_DIALOGO = (
    f"QDialog {{ background: {theme.BG_BOTTOM}; }} QLabel {{ color: {theme.TEXT}; }}"
    f"QLineEdit {{ background: {theme.PANEL}; color: {theme.TEXT}; border: 1px solid {theme.PANEL_EDGE};"
    f" border-radius: 10px; padding: 8px 12px; font-size: 14px; selection-background-color: {theme.BLUE}; }}"
    f"QLineEdit:focus {{ border-color: {theme.BLUE}; }}"
)


def _nota(texto: str, cor: str = theme.MUTED) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setWordWrap(True)
    rotulo.setStyleSheet(f"color: {cor}; font-size: 13px;")
    return rotulo


class ConexaoDialog(QDialog):
    """Pede os dados, verifica a credencial no provedor e só então conecta. Qualquer erro mantém o diálogo aberto com o que foi digitado."""

    _resultado = Signal(object, object)

    def __init__(self, servico: ServicoConexoes, provedor_id: str = "binance", parent=None, sincrono: bool = False):
        super().__init__(parent)
        self.servico, self.provedor_id, self.sincrono = servico, provedor_id, sincrono
        self.conexao: Conexao | None = None
        self._limpas: dict[str, str] = {}
        provedor = PROVEDORES[provedor_id]
        if not provedor.disponivel:
            raise ValueError(f"{provedor.nome} ainda não está disponível para conexão")
        self.setWindowTitle(f"Conectar {provedor.nome}")
        self.setMinimumWidth(560)
        self.setStyleSheet(ESTILO_DIALOGO)
        topo = QHBoxLayout()
        topo.setSpacing(12)
        topo.addWidget(LogoProvedor(provedor_id, 48))
        titulo = QVBoxLayout()
        titulo.setSpacing(0)
        titulo.addWidget(Label(provedor.nome, 22, W.DemiBold))
        titulo.addWidget(Label(provedor.descricao, 13, W.Normal, theme.MUTED))
        topo.addLayout(titulo)
        topo.addStretch(1)

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
            self.campos[campo.nome] = edicao
            form.addRow(campo.rotulo, edicao)

        self.erro = _nota("", theme.RED)
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
        v.addLayout(form)
        v.addWidget(_nota(provedor.como_conectar))
        v.addWidget(_nota(provedor.garantia))
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
            self._mostrar_erro(str(erro) if isinstance(erro, ErroDeConfiguracao) else "Não foi possível verificar a credencial. Tente de novo.")
            return
        try:
            self.conexao = self.servico.gravar(self.provedor_id, self.apelido.text(), self._limpas, verificacao)  # cofre + banco: thread principal
        except ErroDeConfiguracao as e:
            self._mostrar_erro(str(e))
            return
        finally:
            self._limpas = {}
        self.accept()


class VinculoTelegramDialog(QDialog):
    """Mostra um código de uso único e espera a pessoa mandá-lo ao bot (`/vincular CODIGO`) para descobrir o chat que será atendido."""

    _preparado = Signal(object, object)
    _rodada = Signal(object, object)

    def __init__(self, servico: ServicoConexoes, ident: str, parent=None, sincrono: bool = False, automatico: bool = True):
        super().__init__(parent)
        self.servico, self.ident, self.sincrono, self.automatico = servico, ident, sincrono, automatico
        self.conexao: Conexao | None = None
        self.codigo: str | None = None
        self._offset: int | None = None
        self._ativo = True
        bot = servico.obter(ident).detalhes.get("bot_username", "seu bot")
        self.setWindowTitle("Vincular chat do Telegram")
        self.setMinimumWidth(520)
        self.setStyleSheet(ESTILO_DIALOGO)
        self.codigo_rotulo = Label("…", 34, W.DemiBold)
        self.estado = _nota("Preparando o código…")
        self.erro = _nota("", theme.RED)
        self.erro.hide()
        self.gerar = ActionButton("Gerar outro código", height=38, pad=20)
        self.gerar.clicked.connect(self.iniciar)
        fechar = ActionButton("Cancelar", height=38, pad=20)
        fechar.clicked.connect(self.reject)
        botoes = QHBoxLayout()
        botoes.addStretch(1)
        botoes.addWidget(self.gerar)
        botoes.addWidget(fechar)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(12)
        v.addWidget(Label("Vincular seu chat", 22, W.DemiBold))
        v.addWidget(_nota(f"No Telegram, abra uma conversa PRIVADA com @{bot} e envie a mensagem abaixo. "
                          "O bot passa a responder só a este chat (e a ninguém mais)."))
        self.mensagem = Label("", 18, W.Medium, theme.BLUE_SOFT)
        v.addWidget(self.mensagem)
        v.addWidget(self.estado)
        v.addWidget(self.erro)
        v.addLayout(botoes)
        self._preparado.connect(self._pronto)
        self._rodada.connect(self._resultado)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if self.codigo is None:
            self.iniciar()

    def done(self, resultado: int) -> None:
        self._ativo = False  # para de procurar
        super().done(resultado)

    # -- passos ---------------------------------------------------------------------------------------------------------------

    def _falha(self, texto: str) -> None:
        self.erro.setText(f"• {texto}")
        self.erro.show()
        self.estado.setText("Aguardando…" if self.codigo else "Não foi possível gerar o código.")

    def iniciar(self) -> None:
        self.erro.hide()
        self.codigo = None
        self.mensagem.setText("")
        self.estado.setText("Preparando o código…")
        try:
            cliente = self.servico.preparar_vinculo(self.ident)  # banco e cofre: thread principal
        except ErroDeConfiguracao as erro:
            self._falha(str(erro))
            return
        em_thread(lambda: self.servico.descartar_pendentes(cliente), self._pronto, self._preparado, self.sincrono)  # só rede

    def _pronto(self, offset, erro) -> None:
        if erro is not None:
            self._falha(str(erro) if isinstance(erro, ErroDeConfiguracao) else "Não foi possível falar com o Telegram.")
            return
        self._offset = offset
        self.codigo = self.servico.novo_codigo(self.ident)
        self.mensagem.setText(f"/vincular {self.codigo}")
        self.estado.setText("Aguardando você enviar a mensagem ao bot… (o código vale por 10 minutos e só pode ser usado uma vez)")
        if self.automatico:
            self.procurar()

    def procurar(self) -> None:
        """Uma rodada de procura (a rede espera até 2 s). Repete sozinha até achar, expirar ou o diálogo fechar."""
        if not self._ativo:
            return
        try:
            cliente = self.servico.preparar_busca(self.ident)
        except ErroDeConfiguracao as erro:
            self._falha(str(erro))
            return
        offset = self._offset
        em_thread(lambda: self.servico.buscar_atualizacoes(cliente, offset), self._resultado, self._rodada, self.sincrono)  # só rede

    def _resultado(self, atualizacoes, erro) -> None:
        if not self._ativo:
            return
        if erro is not None:
            self._falha(str(erro) if isinstance(erro, ErroDeConfiguracao) else "Não foi possível falar com o Telegram.")
            if self.automatico:
                QTimer.singleShot(3000, self.procurar)
            return
        try:
            chat, self._offset = self.servico.interpretar(self.ident, atualizacoes, self._offset)
        except ErroDeConfiguracao as erro2:
            self._falha(str(erro2))
            return
        if chat is None:
            if self.automatico:
                QTimer.singleShot(200, self.procurar)
            return
        self.conexao = self.servico.concluir_vinculo(self.ident, chat)  # banco: thread principal
        self.accept()


class ConexoesSection(Card):
    """Cartão das Configurações: uma linha por conexão (logo, apelido, status, ações) e o botão de adicionar."""

    notify = Signal(str, bool)
    _teste_pronto = Signal(object, object)
    _envio_pronto = Signal(object, object)

    def __init__(self, servico: ServicoConexoes, sincrono: bool = False, confirmar: Callable[[str, str, str], bool] | None = None,
                 ouvintes=None, parent=None):
        super().__init__(parent)
        self.servico, self.sincrono, self.ouvintes = servico, sincrono, ouvintes
        self._confirmar = confirmar or self._confirmar_padrao
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(24, 20, 24, 20)
        self._layout.setSpacing(10)
        self._linhas = QVBoxLayout()
        self._linhas.setSpacing(8)
        self.adicionar = ActionButton("Adicionar conexão", primary=True, height=38, pad=20)
        self.adicionar.clicked.connect(self.escolher_provedor)
        self._layout.addWidget(Label("CONEXÕES", 13, W.DemiBold, theme.MUTED))
        self._layout.addWidget(Label("Corretoras (chave de API somente leitura) e o bot do Telegram.", 13, W.Normal, theme.MUTED))
        self._layout.addLayout(self._linhas)
        botoes = QHBoxLayout()
        botoes.addWidget(self.adicionar)
        botoes.addStretch(1)
        self._layout.addLayout(botoes)
        self._teste_pronto.connect(self._teste_concluido)
        self._envio_pronto.connect(self._envio_concluido)
        self.refresh()
        if ouvintes is not None:  # o estado do ouvinte muda sozinho (rede cai, conflito): atualiza as etiquetas de tempos em tempos
            self._relogio = QTimer(self)
            self._relogio.timeout.connect(self.refresh)
            self._relogio.start(4000)

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
            self._linhas.addWidget(Label("Nenhuma conexão ainda. Comece pela Binance ou pelo bot do Telegram.", 14, W.Normal, theme.TEXT))
        for c in conexoes:
            self._linhas.addWidget(self._linha(c))
        for pr in PROVEDORES.values():  # lugares reservados para o futuro
            if not pr.disponivel:
                self._linhas.addWidget(self._reservado(pr))

    def _detalhe(self, c: Conexao) -> str:
        quando = c.status_em.astimezone().strftime("%d/%m/%Y %H:%M") if isinstance(c.status_em, datetime) else ""
        if c.provedor == "telegram":
            bot = f"@{c.detalhes['bot_username']}" if c.detalhes.get("bot_username") else "bot"
            chat = f"vinculado a {c.detalhes.get('chat_nome', 'um chat')}" if c.chat_vinculado else "chat ainda não vinculado: o bot não responde a ninguém"
            return f"{bot} · token {c.chave_mascarada} · {chat} · verificado em {quando}"
        return f"{c.nome_provedor} · chave {c.chave_mascarada} · verificada em {quando}"

    def _linha(self, c: Conexao) -> QWidget:
        """Duas faixas: em cima logo, nome, detalhes e etiquetas; embaixo as ações (assim o texto nunca é espremido pelos botões)."""
        w = QWidget()
        coluna = QVBoxLayout(w)
        coluna.setContentsMargins(0, 4, 0, 8)
        coluna.setSpacing(8)
        topo = QHBoxLayout()
        topo.setSpacing(12)
        topo.addWidget(LogoProvedor(c.provedor, 44), 0, Qt.AlignmentFlag.AlignTop)
        texto = QVBoxLayout()
        texto.setSpacing(1)
        texto.addWidget(Label(c.apelido, 16, W.Medium))
        detalhe = Label(self._detalhe(c), 12, W.Normal, theme.MUTED)
        detalhe.setWordWrap(True)
        texto.addWidget(detalhe)
        if c.status != CONECTADA:
            aviso = Label(c.mensagem, 12, W.Normal, theme.WARNING if c.status == ERRO else theme.RED)
            aviso.setWordWrap(True)
            texto.addWidget(aviso)
        topo.addLayout(texto, 1)
        etiquetas = QHBoxLayout()
        etiquetas.setSpacing(6)
        rotulo, cor = STATUS.get(c.status, ("—", theme.DIM))
        etiquetas.addWidget(Chip(rotulo, cor))
        if c.provedor == "telegram" and c.chat_vinculado and self.ouvintes is not None:
            nome, cor_o = OUVINTE.get(self.ouvintes.estado(c.id), OUVINTE["parado"])
            etiquetas.addWidget(Chip(nome, cor_o))
        topo.addLayout(etiquetas)
        coluna.addLayout(topo)

        acoes = QHBoxLayout()
        acoes.setSpacing(8)
        acoes.setContentsMargins(56, 0, 0, 0)  # alinhadas ao texto, depois do logo
        acoes.addStretch(1)
        if c.provedor == "telegram":
            if c.chat_vinculado:
                for texto_botao, acao in (("Enviar teste", self.enviar_teste), ("Desvincular", self.desvincular)):
                    b = ActionButton(texto_botao, height=32, pad=14)
                    b.clicked.connect(lambda _=False, i=c.id, a=acao: a(i))
                    acoes.addWidget(b)
            else:
                b = ActionButton("Vincular chat", primary=True, height=32, pad=14)
                b.clicked.connect(lambda _=False, i=c.id: self.vincular_chat(i))
                acoes.addWidget(b)
        testar = ActionButton("Testar", height=32, pad=14)
        testar.clicked.connect(lambda _=False, i=c.id: self.testar(i))
        remover = ActionButton("Remover", danger=True, height=32, pad=14)
        remover.clicked.connect(lambda _=False, i=c.id: self.remover(i))
        acoes.addWidget(testar)
        acoes.addWidget(remover)
        coluna.addLayout(acoes)
        return w

    def _reservado(self, pr) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 4, 0, 4)
        h.setSpacing(12)
        h.addWidget(LogoProvedor(pr.id, 44))
        texto = QVBoxLayout()
        texto.setSpacing(1)
        texto.addWidget(Label(pr.nome, 16, W.Medium, theme.MUTED))
        descricao = Label(pr.como_conectar, 12, W.Normal, theme.DIM)
        descricao.setWordWrap(True)
        texto.addWidget(descricao)
        h.addLayout(texto, 1)
        h.addWidget(Chip("Em breve", theme.DIM))
        return w

    # -- adicionar --------------------------------------------------------------------------------------------------------

    def criar_dialogo(self, provedor_id: str = "binance") -> ConexaoDialog:
        return ConexaoDialog(self.servico, provedor_id, self, self.sincrono)

    def escolher_provedor(self) -> None:
        menu = QMenu(self)
        for pid, pr in PROVEDORES.items():
            if pr.disponivel:
                menu.addAction(f"{pr.nome} · {pr.descricao}", lambda p=pid: self.abrir_dialogo(p))
        menu.exec(self.adicionar.mapToGlobal(self.adicionar.rect().bottomLeft()))

    def abrir_dialogo(self, provedor_id: str = "binance") -> None:
        dialogo = self.criar_dialogo(provedor_id)
        if dialogo.exec() and dialogo.conexao:
            self.notify.emit(f"{dialogo.conexao.apelido} conectada", True)
            self.refresh()
            if provedor_id == "telegram":  # o próximo passo natural: dizer qual chat o bot deve atender
                self.vincular_chat(dialogo.conexao.id)
        self.refresh()

    # -- ações -----------------------------------------------------------------------------------------------------------------

    def criar_vinculo(self, ident: str, automatico: bool = True) -> VinculoTelegramDialog:
        return VinculoTelegramDialog(self.servico, ident, self, self.sincrono, automatico)

    def vincular_chat(self, ident: str) -> None:
        dialogo = self.criar_vinculo(ident)
        if dialogo.exec() and dialogo.conexao:
            self.notify.emit(f"Chat de {dialogo.conexao.detalhes.get('chat_nome', '')} vinculado", True)
            if self.ouvintes is not None:
                self.ouvintes.iniciar(ident)  # a partir de agora o bot atende esse chat, enquanto o app estiver aberto
        self.refresh()

    def desvincular(self, ident: str) -> None:
        if self._confirmar("Desvincular chat", "O bot deixa de responder a este chat. O token continua guardado e você pode vincular de novo.", "Desvincular"):
            if self.ouvintes is not None:
                self.ouvintes.parar(ident)
            self.servico.desvincular(ident)
            self.notify.emit("Chat desvinculado", True)
            self.refresh()

    def enviar_teste(self, ident: str) -> None:
        try:
            chat_id, cliente = self.servico.preparar_teste(ident)  # banco e cofre: thread principal
        except ErroDeConfiguracao as erro:
            self.notify.emit(str(erro), False)
            return
        em_thread(lambda: self.servico.enviar_teste_rede(cliente, chat_id), self._envio_concluido, self._envio_pronto, self.sincrono)  # só rede

    def _envio_concluido(self, _resultado, erro) -> None:
        if erro is not None:
            self.notify.emit(str(erro) if isinstance(erro, ErroDeConfiguracao) else "Não foi possível enviar o teste agora.", False)
            return
        self.notify.emit("Mensagem de teste enviada ao seu chat", True)

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
        if self._confirmar("Remover conexão", f"Remover “{c.apelido}” deste computador? A credencial será apagada do cofre. "
                           "Para invalidá-la de vez, revogue-a também no site/app do provedor.", "Remover"):
            if self.ouvintes is not None:
                self.ouvintes.parar(ident)
            self.servico.remover(ident)
            self.notify.emit(f"{c.apelido} removida", True)
            self.refresh()
