"""Tela de metas de um agente. Mostra as quatro grandezas SEPARADAS (comprovado, completude, custos, elegibilidade) e a história.

Tudo aqui vem do `ServicoMetas`; a tela não decide nada. Os dados de cenário são SIMULADOS e aparecem marcados como tal.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from ..metas import (
    COMPROVADA, PENDENTE_DE_COMPROVACAO, REVERTIDA, EvidenciaExterna, PainelMeta, ServicoMetas,
)
from ..nucleo.carregador import carregar_arquivo
from ..nucleo.esquema import EstadoMeta
from ..nucleo.tipos import Tri
from ..workspace import Workspace
from . import theme
from .components import ActionButton, Card, Label, PillButton, setup
from .controls import Chip
from .execucao_dialog import ExecucaoDialog

W = theme.W

ESTADO = {
    EstadoMeta.ATIVA: ("Ativa", theme.BLUE_SOFT), EstadoMeta.ATINGIDA: ("Atingida", theme.GREEN), EstadoMeta.EXPIRADA: ("Expirada", theme.WARNING),
    EstadoMeta.INVALIDADA: ("Invalidada", theme.RED), EstadoMeta.CANCELADA: ("Cancelada", theme.DIM), EstadoMeta.RASCUNHO: ("Rascunho", theme.DIM),
}
TRI = {Tri.VERDADEIRO: ("Sim", theme.GREEN), Tri.FALSO: ("Não", theme.RED), Tri.INDETERMINADO: ("Indeterminado", theme.WARNING)}


def num(valor: Decimal) -> str:
    texto = format(valor.normalize(), "f")
    return texto if "." not in texto else texto.rstrip("0").rstrip(".")


# os identificadores do domínio não têm acento; na tela eles voltam a ser português
ACENTOS = {
    "nao": "não", "execucao": "execução", "execucoes": "execuções", "pendencia": "pendência", "conciliacao": "conciliação",
    "conciliada": "conciliada", "avaliacao": "avaliação", "invalidacao": "invalidação", "evidencia": "evidência", "orcamento": "orçamento",
    "possivel": "possível", "verificavel": "verificável", "indeterminado": "indeterminado", "ate": "até", "registro": "registro",
    "reducao": "redução", "excecao": "exceção", "divergencia": "divergência", "revisao": "revisão", "movimentacao": "movimentação",
    "reconciliada": "reconciliada", "bloqueio": "bloqueio", "cotacao": "cotação", "periodo": "período", "ja": "já",
}


def legivel(identificador: str) -> str:
    return " ".join(ACENTOS.get(parte, parte) for parte in identificador.split("_"))


def exemplos_dir() -> Path | None:
    aqui = Path(__file__).resolve()
    for pai in aqui.parents:
        if (pai / "exemplos" / "avaliacao").is_dir():
            return pai / "exemplos" / "avaliacao"
    return None


class Barra(QWidget):
    """Progresso comprovado (sólido) e o que vale por prova anterior (tracejado claro), sobre o alvo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(14)
        self._comprovada = self._preservada = 0.0
        self._cor = theme.BLUE_SOFT

    def set_values(self, comprovada: Decimal, preservada: Decimal, alvo: Decimal, cor: str) -> None:
        alvo_f = float(alvo) or 1.0
        self._comprovada = max(0.0, min(1.0, float(comprovada) / alvo_f))
        self._preservada = max(0.0, min(self._comprovada, float(preservada) / alvo_f))
        self._cor = cor
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        r = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.BAR))
        p.drawRoundedRect(r, 7, 7)
        if self._comprovada > 0:
            p.setBrush(QColor(self._cor))
            p.drawRoundedRect(QRectF(r.x(), r.y(), max(14.0, r.width() * self._comprovada), r.height()), 7, 7)
        if self._preservada > 0:
            claro = QColor(theme.TEXT)
            claro.setAlpha(70)
            p.setBrush(claro)
            p.drawRoundedRect(QRectF(r.x(), r.y(), max(14.0, r.width() * self._preservada), r.height()), 7, 7)


def _bloco(titulo: str) -> tuple[Card, QVBoxLayout]:
    card = Card()
    card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
    v = QVBoxLayout(card)
    v.setContentsMargins(24, 20, 24, 20)
    v.setSpacing(8)
    v.addWidget(Label(titulo, 13, W.DemiBold, theme.MUTED))
    return card, v


def _linha(esq: str, dir_: str, cor: str = theme.TEXT) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(Label(esq, 14, W.Normal, theme.MUTED))
    h.addStretch(1)
    h.addWidget(Label(dir_, 14, W.Medium, cor))
    return w


def _texto(conteudo: str, cor: str = theme.MUTED, px: int = 13) -> Label:
    rotulo = Label(conteudo, px, W.Normal, cor)
    rotulo.setWordWrap(True)
    return rotulo


class MetasPage(QWidget):
    back_requested = Signal()
    notify = Signal(str, bool)

    def __init__(self, workspace: Workspace, servico: ServicoMetas, agent_id: str, parent=None):
        super().__init__(parent)
        self.ws, self.servico, self.agent_id = workspace, servico, agent_id
        self.meta_id: str | None = None
        self.setMinimumWidth(640)

        self.back = ActionButton("Voltar", height=36, pad=16)
        self.back.clicked.connect(self.back_requested)
        self.title = Label("", 30, W.DemiBold)
        self.subtitle = _texto("Dados de cenário SIMULADOS. Aprovar uma proposta não executa nada nem move o progresso.", theme.MUTED, 15)

        self.importar = ActionButton("Importar cenário…", height=38, pad=18)
        self.importar.clicked.connect(self._importar)
        self.avancar = ActionButton("Avançar momento", primary=True, height=38, pad=18)
        self.avancar.clicked.connect(self._avancar)
        self.reavaliar = ActionButton("Reavaliar", height=38, pad=18)
        self.reavaliar.clicked.connect(self._reavaliar)
        self.registrar = ActionButton("Registrar execução…", height=38, pad=18)
        self.registrar.clicked.connect(self._registrar)
        self.evidencia = ActionButton("Importar evidência…", height=38, pad=18)
        self.evidencia.clicked.connect(self._importar_evidencia)

        self.corpo = QVBoxLayout()
        self.corpo.setSpacing(16)
        self.corpo.setContentsMargins(0, 0, 0, 0)

        topo = QHBoxLayout()
        topo.addWidget(self.back)
        topo.addStretch(1)
        acoes = QHBoxLayout()
        acoes.setSpacing(10)
        acoes.addWidget(self.avancar)
        acoes.addWidget(self.reavaliar)
        acoes.addWidget(self.importar)
        acoes.addStretch(1)
        acoes2 = QHBoxLayout()
        acoes2.setSpacing(10)
        acoes2.addWidget(self.registrar)
        acoes2.addWidget(self.evidencia)
        acoes2.addStretch(1)

        coluna = QVBoxLayout()
        coluna.setSpacing(16)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.addLayout(topo)
        coluna.addWidget(self.title)
        coluna.addWidget(self.subtitle)
        coluna.addLayout(acoes)
        coluna.addLayout(acoes2)
        coluna.addLayout(self.corpo)
        coluna.addStretch(1)
        holder = QWidget()
        holder.setLayout(coluna)
        holder.setMaximumWidth(760)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(32, 16, 32, 36)
        outer.addStretch(1)
        outer.addWidget(holder, 100)
        outer.addStretch(1)

        workspace.agent_changed.connect(lambda i: self.refresh() if i == agent_id else None)
        self.refresh()

    # -- ações ---------------------------------------------------------------------------------------------------------

    def _importar(self) -> None:
        pasta = exemplos_dir()
        caminho, _ = QFileDialog.getOpenFileName(self, "Importar cenário de meta (dado simulado)", str(pasta or ""), "Cenários (*.yaml *.yml *.json)")
        if caminho:
            self.importar_arquivo(caminho)

    def importar_arquivo(self, caminho: str) -> None:
        try:
            self.meta_id = self.servico.importar(caminho, self.agent_id)
        except Exception as erro:  # arquivo inválido: o núcleo explica o motivo
            self.notify.emit(f"Cenário recusado: {str(erro).splitlines()[0][:120]}", False)
            return
        self.notify.emit("Meta ativada (cenário simulado)", True)
        self.refresh()

    def criar_formulario(self) -> ExecucaoDialog | None:
        if self.meta_id is None:
            return None
        return ExecucaoDialog(self.servico.painel(self.meta_id), self._gravar_execucao, self)

    def _registrar(self) -> None:
        dialogo = self.criar_formulario()
        if dialogo is not None:
            dialogo.exec()

    def _gravar_execucao(self, execucao) -> bool:
        """Chamado pelo formulário: grava e reavalia. Erros sobem para o formulário, que continua aberto."""
        nova = self.servico.registrar_execucao(self.meta_id, execucao)
        if nova:
            self.servico.reavaliar(self.meta_id, execucao.confirmada_em)
            self.notify.emit("Execução registrada, pendente de comprovação (ainda não é prova)", True)
        else:
            self.notify.emit("Esta execução já estava registrada. Nada foi duplicado", True)
        self.refresh()
        return nova

    def _importar_evidencia(self) -> None:
        caminho, _ = QFileDialog.getOpenFileName(self, "Importar evidência externa", "", "Evidência (*.yaml *.yml *.json)")
        if caminho:
            self.importar_evidencia_arquivo(caminho)

    def importar_evidencia_arquivo(self, caminho: str) -> None:
        if self.meta_id is None:
            return
        try:
            evidencia = carregar_arquivo(EvidenciaExterna, caminho)
            novos = self.servico.importar_evidencia(self.meta_id, evidencia)
            self.servico.reavaliar(self.meta_id, max((r.recebido_em for r in evidencia.registros_externos), default=None))
        except Exception as erro:
            self.notify.emit(f"Evidência recusada: {str(erro).splitlines()[0][:120]}", False)
            return
        self.notify.emit(f"{novos} registro(s) externo(s) novo(s). A conciliação decide o que comprova" if novos else "Evidência já importada. Nada foi duplicado", True)
        self.refresh()

    def _avancar(self) -> None:
        if self.meta_id is None:
            return
        try:
            feito = self.servico.avancar(self.meta_id)
        except Exception as erro:
            self.notify.emit(f"Falha ao avaliar: {str(erro)[:120]}", False)
            return
        if feito is None:
            self.notify.emit("O cenário não tem mais momentos", False)
        else:
            momento, resultado = feito
            novos = len(resultado.eventos)
            self.notify.emit(f"Avaliada em {momento.agora:%d/%m %H:%M}: {novos} evento(s) novo(s)", True)
        self.refresh()

    def _reavaliar(self) -> None:
        if self.meta_id is None:
            return
        painel = self.servico.painel(self.meta_id)
        if painel.avaliacao is None:
            self.notify.emit("Avalie um momento primeiro", False)
            return
        resultado = self.servico.avaliar(self.meta_id, painel.avaliacao.avaliada_em)
        self.notify.emit("Reavaliada: nenhum evento novo (sem duplicação)" if not resultado.eventos else f"{len(resultado.eventos)} evento(s) novo(s)", True)
        self.refresh()

    # -- desenho --------------------------------------------------------------------------------------------------------

    def refresh(self) -> None:
        agent = self.ws.agent(self.agent_id)
        self.title.setText(f"Metas · {agent.name}" if agent else "Metas")
        ids = self.servico.metas(self.agent_id)
        if self.meta_id not in ids:
            self.meta_id = ids[0] if ids else None
        while self.corpo.count():
            item = self.corpo.takeAt(0)
            if item.widget():
                antigo = item.widget()
                antigo.setParent(None)  # sai da tela já; a destruição é adiada
                antigo.deleteLater()
        self.avancar.setEnabled(False)
        self.reavaliar.setEnabled(False)
        self.registrar.setEnabled(self.meta_id is not None)
        self.evidencia.setEnabled(self.meta_id is not None)
        if self.meta_id is None:
            card, v = _bloco("NENHUMA META")
            v.addWidget(_texto("Este agente ainda não tem meta. Importe um cenário simulado para ver a avaliação passo a passo.", theme.TEXT, 15))
            self.corpo.addWidget(card)
            return
        if len(ids) > 1:
            self.corpo.addWidget(self._seletor(ids))
        painel = self.servico.painel(self.meta_id)
        self.avancar.setEnabled(painel.pode_avancar)
        self.avancar.setText(f"Avançar momento ({painel.proximo_momento}/{painel.momentos_total})")
        self.reavaliar.setEnabled(painel.avaliacao is not None)
        self.avancar.update()
        self.reavaliar.update()
        for bloco in self._blocos(painel):
            self.corpo.addWidget(bloco)

    def _seletor(self, ids: list[str]) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        for i in ids:
            b = PillButton(i, height=34, pad=14, px=14)
            b.setCheckable(True)
            b.setChecked(i == self.meta_id)
            b.clicked.connect(lambda _=False, m=i: self._escolher(m))
            h.addWidget(b)
        h.addStretch(1)
        return w

    def _escolher(self, meta_id: str) -> None:
        self.meta_id = meta_id
        self.refresh()

    def _blocos(self, painel: PainelMeta) -> list[QWidget]:
        blocos: list[QWidget] = []
        p, estado = painel.progresso, painel.estado
        nome, cor = ESTADO.get(estado, ("Não avaliada", theme.DIM)) if estado else ("Não avaliada", theme.DIM)

        resumo, v = _bloco("META")
        topo = QHBoxLayout()
        topo.setSpacing(8)
        topo.addWidget(Label(painel.meta_id, 20, W.DemiBold))
        topo.addWidget(Chip(nome, cor))
        topo.addWidget(Chip("Dados simulados", theme.WARNING))
        if painel.avaliacao and painel.avaliacao.bloqueada_por_dados:
            topo.addWidget(Chip("Bloqueada por dados", theme.WARNING))
        topo.addStretch(1)
        v.addLayout(topo)
        v.addWidget(_texto(painel.descricao, theme.TEXT, 14))
        v.addWidget(_linha("Ativo", painel.ativo_id))
        v.addWidget(_linha("Prazo", f"{painel.prazo:%d/%m/%Y %H:%M} UTC"))
        blocos.append(resumo)
        if p is None:
            vazio, vv = _bloco("AINDA NÃO AVALIADA")
            vv.addWidget(_texto("Use “Avançar momento” para rodar a primeira avaliação.", theme.TEXT, 14))
            blocos.append(vazio)
            blocos.append(self._historia(painel))
            return blocos

        prog, v = _bloco("PROGRESSO COMPROVADO")
        barra = Barra()
        barra.set_values(p.quantidade_comprovada, p.quantidade_preservada, p.quantidade_alvo, cor)
        v.addWidget(barra)
        v.addWidget(_linha("Comprovado (líquido, dentro da janela)", f"{num(p.quantidade_comprovada)} de {num(p.quantidade_alvo)} {painel.ativo_id}", theme.TEXT))
        if p.quantidade_preservada:
            v.addWidget(_linha("Vale por prova anterior, sem reverificação agora", num(p.quantidade_preservada), theme.WARNING))
        v.addWidget(_linha("Registrado, pendente de comprovação (NÃO conta como progresso)", num(p.quantidade_pendente), theme.WARNING if p.quantidade_pendente else theme.DIM))
        if p.quantidade_fora_da_janela:
            v.addWidget(_linha("Comprovado, mas fora da janela da meta (não conta)", num(p.quantidade_fora_da_janela)))
        if p.instante_atingimento:
            v.addWidget(_linha("Atingida na execução de", f"{p.instante_atingimento:%d/%m/%Y %H:%M} UTC", theme.GREEN))
        if p.em_carencia or p.aguardando_evidencia:
            v.addWidget(_texto("Prazo vencido: aguardando evidência dentro da carência." if p.em_carencia else "Aguardando evidência.", theme.WARNING))
        blocos.append(prog)

        concl, v = _bloco("CONCILIAÇÃO")
        v.addWidget(_linha("Completa", "Sim" if p.completude.completa else "Não", theme.GREEN if p.completude.completa else theme.WARNING))
        for pend in p.completude.pendencias:
            risco = "  ·  pode reduzir o progresso" if pend.pode_reduzir_progresso else ""
            v.addWidget(_texto(f"{pend.referencia}: {legivel(pend.motivo_avaliacao.value)}{risco}", theme.WARNING if pend.pode_reduzir_progresso else theme.MUTED))
        relevantes = [o for o in p.orfaos if o.relevante]
        ignorados = [o for o in p.orfaos if not o.relevante]
        for o in relevantes:
            v.addWidget(_texto(f"Registro externo sem execução interna: {o.id_externo} ({', '.join(legivel(m.value) for m in o.motivos)})", theme.WARNING))
        if ignorados:
            v.addWidget(_texto(f"{len(ignorados)} registro(s) externo(s) sem relação com esta meta, ignorados.", theme.DIM))
        blocos.append(concl)
        blocos.append(self._execucoes(painel))

        custos, v = _bloco("CUSTOS E ORÇAMENTO")
        for c in p.custos:
            v.addWidget(_linha(f"Taxas verificadas · {c.ativo_id}", num(c.verificado)))
            if c.nao_verificado:
                v.addWidget(_linha(f"Sem evidência · {c.ativo_id}", num(c.nao_verificado), theme.WARNING))
        o = p.orcamento
        rotulo, cor_o = TRI[o.resultado]
        v.addWidget(_linha(f"Orçamento {num(o.orcamento)} {o.moeda_id}", rotulo, cor_o))
        v.addWidget(_linha("Gasto mínimo (comprovado) até máximo (pior caso)", f"{num(o.gasto_minimo)} – {num(o.gasto_maximo)}"))
        if o.motivos:
            v.addWidget(_texto(", ".join(legivel(m.value) for m in o.motivos)))
        blocos.append(custos)

        elig, v = _bloco("PODE CONCLUIR?")
        rotulo, cor_e = TRI[p.elegibilidade.resultado]
        v.addWidget(_linha("Elegibilidade para concluir", rotulo, cor_e))
        if p.elegibilidade.motivos:
            v.addWidget(_texto(", ".join(legivel(m.value) for m in p.elegibilidade.motivos)))
        blocos.append(elig)
        blocos.append(self._historia(painel))
        return blocos

    def _execucoes(self, painel: PainelMeta) -> QWidget:
        card, v = _bloco("EXECUÇÕES REGISTRADAS")
        if not painel.execucoes:
            v.addWidget(_texto("Nenhuma execução registrada ainda. Use “Registrar execução…”."))
        rotulos = {COMPROVADA: ("Comprovada", theme.GREEN), PENDENTE_DE_COMPROVACAO: ("Pendente de comprovação", theme.WARNING), REVERTIDA: ("Comprovação revertida", theme.RED)}
        for r in painel.execucoes:
            e = r.execucao
            rotulo, cor = rotulos.get(r.situacao, ("Ainda não avaliada", theme.DIM))
            sinal = "−" if e.lado.value == "estorno_compra" else "+"
            linha = QWidget()
            h = QHBoxLayout(linha)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(Label(f"{e.id}  ·  {sinal}{num(e.quantidade_liquida)} {e.ativo_id}  ·  {e.executada_em:%d/%m %H:%M} UTC", 14, W.Normal, theme.TEXT))
            h.addStretch(1)
            h.addWidget(Chip(rotulo, cor))
            v.addWidget(linha)
        return card

    def _historia(self, painel: PainelMeta) -> QWidget:
        card, v = _bloco("LINHA DO TEMPO")
        if not painel.eventos:
            v.addWidget(_texto("Sem eventos ainda."))
        for e in painel.eventos:
            motivo = f" — {e.motivo}" if e.motivo else ""
            v.addWidget(_texto(f"{e.sequencia:>2}  {e.horario_evidencia:%d/%m %H:%M}  {legivel(e.tipo.value)}{motivo}", theme.TEXT, 13))
        return card
