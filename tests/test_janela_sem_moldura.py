"""Janela sem moldura: o header vira a barra da janela (arrastar, maximizar, minimizar, fechar) e a borda de 6 px redimensiona."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, QSize, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ubento.ui import theme  # noqa: E402
from ubento.ui.header import HEIGHT, TabHeader  # noqa: E402
from ubento.ui.main_window import MARGEM_REDIMENSIONAR, MainWindow, bordas_em, cursor_da_borda  # noqa: E402
from ubento.workspace import Workspace  # noqa: E402

E = Qt.Edge


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(theme.APP_QSS)
    return a


@pytest.fixture
def janela(app):
    w = MainWindow(Workspace(), animations=False)
    w.resize(1000, 700)
    w.show()
    app.processEvents()
    yield w
    w.close()


def clicar(header: TabHeader, ponto: QPointF, botao=Qt.MouseButton.LeftButton):
    QTest.mouseClick(header, botao, pos=ponto.toPoint())


def centro(header: TabHeader, nome: str) -> QPointF:
    return header._controles_rects()[nome].center()


# -- as bordas ---------------------------------------------------------------------------------------------------------------------


def test_a_janela_nao_tem_moldura_do_sistema(janela):
    assert janela.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert janela.header._controles  # o header assumiu o papel de barra de título


def test_faixa_de_redimensionamento_nas_quatro_bordas_e_cantos():
    t = QSize(1000, 700)
    m = MARGEM_REDIMENSIONAR
    assert bordas_em(QPoint(0, 300), t) == E.LeftEdge and bordas_em(QPoint(999, 300), t) == E.RightEdge
    assert bordas_em(QPoint(500, 0), t) == E.TopEdge and bordas_em(QPoint(500, 699), t) == E.BottomEdge
    assert bordas_em(QPoint(0, 0), t) == E.LeftEdge | E.TopEdge and bordas_em(QPoint(999, 699), t) == E.RightEdge | E.BottomEdge
    assert bordas_em(QPoint(m - 1, 300), t) == E.LeftEdge and not bordas_em(QPoint(m, 300), t)  # a faixa tem exatamente `m` pixels
    assert not bordas_em(QPoint(500, 350), t)


def test_cursor_certo_para_cada_borda():
    assert cursor_da_borda(E.LeftEdge) == cursor_da_borda(E.RightEdge) == Qt.CursorShape.SizeHorCursor
    assert cursor_da_borda(E.TopEdge) == cursor_da_borda(E.BottomEdge) == Qt.CursorShape.SizeVerCursor
    assert cursor_da_borda(E.LeftEdge | E.TopEdge) == cursor_da_borda(E.RightEdge | E.BottomEdge) == Qt.CursorShape.SizeFDiagCursor
    assert cursor_da_borda(E.RightEdge | E.TopEdge) == cursor_da_borda(E.LeftEdge | E.BottomEdge) == Qt.CursorShape.SizeBDiagCursor
    assert cursor_da_borda(Qt.Edge(0)) is None


def test_puxar_a_borda_entrega_o_redimensionamento_ao_sistema(janela, app):
    pedidos = []
    janela.redimensionar = lambda bordas: pedidos.append(bordas)  # o sistema real não existe no teste
    QTest.mousePress(janela.centralWidget(), Qt.MouseButton.LeftButton, pos=QPoint(2, 300))
    QTest.mousePress(janela.centralWidget(), Qt.MouseButton.LeftButton, pos=QPoint(998, 698))
    QTest.mousePress(janela.centralWidget(), Qt.MouseButton.LeftButton, pos=QPoint(500, 400))  # no meio: não é borda
    assert pedidos == [E.LeftEdge, E.RightEdge | E.BottomEdge]


def test_maximizada_nao_ha_borda_para_puxar(janela, app):
    janela.showMaximized()
    app.processEvents()
    pedidos = []
    janela.redimensionar = lambda bordas: pedidos.append(bordas)
    QTest.mousePress(janela.centralWidget(), Qt.MouseButton.LeftButton, pos=QPoint(1, 300))
    assert pedidos == []


def test_fechar_a_janela_solta_o_filtro_e_o_cursor(janela, app):
    pedidos = []
    janela.redimensionar = lambda bordas: pedidos.append(bordas)
    janela.close()
    app.processEvents()
    QTest.mousePress(janela.centralWidget(), Qt.MouseButton.LeftButton, pos=QPoint(2, 300))
    assert pedidos == [] and QApplication.overrideCursor() is None


# -- os botões e o arrastar do header ---------------------------------------------------------------------------------------------


def test_header_tem_tres_botoes_no_canto_e_o_resto_continua_cabendo(janela):
    h = janela.header
    r = h._controles_rects()
    assert list(r) == ["min", "max", "close"]
    assert r["close"].right() <= h.width() - 8 and r["min"].left() < r["max"].left() < r["close"].left()
    eye, gear = h._right_rects()
    assert gear.right() < r["min"].left()  # engrenagem e olho não ficam sob os botões
    _, mais = h._rects()
    assert mais.right() < eye.left()  # as abas ainda cabem (1000 px)


def test_cada_botao_emite_o_seu_pedido(janela):
    h, emitidos = janela.header, []
    h.minimize_requested.connect(lambda: emitidos.append("min"))
    h.maximize_requested.connect(lambda: emitidos.append("max"))
    h.close_requested.connect(lambda: emitidos.append("close"))
    for nome in ("min", "max", "close"):
        clicar(h, centro(h, nome))
    assert emitidos == ["min", "max", "close"]


def test_arrastar_pelo_espaco_vazio_e_duplo_clique_maximiza_mas_aba_nao_arrasta_a_janela(janela):
    h, eventos = janela.header, []
    h.drag_requested.connect(lambda: eventos.append("arrastar"))
    h.maximize_requested.connect(lambda: eventos.append("maximizar"))
    vazio = QPointF(h._rects()[1].right() + 80, HEIGHT / 2)  # entre as abas e os botões
    assert h._hit(vazio) is None
    clicar(h, vazio)
    QTest.mouseDClick(h, Qt.MouseButton.LeftButton, pos=vazio.toPoint())
    assert eventos[0] == "arrastar" and "maximizar" in eventos
    antes = len(eventos)
    clicar(h, h._rects()[0][0][1].center())  # clicar numa aba só seleciona
    assert len(eventos) == antes


def test_botao_direito_nos_controles_nao_abre_menu_de_aba(app):
    h, abertos = TabHeader(), []  # sozinho: dentro da janela o menu abriria de verdade (e bloquearia o teste)
    h.set_window_controls(True)
    h.resize(1000, HEIGHT)
    h.context_requested.connect(lambda chave, pos: abertos.append(chave))
    clicar(h, centro(h, "close"), Qt.MouseButton.RightButton)
    assert abertos == [None]  # trata como espaço vazio (menu de "Novo agente"), nunca como uma aba


def test_minimizar_maximizar_restaurar_e_fechar_funcionam_de_verdade(janela, app):
    h = janela.header
    clicar(h, centro(h, "max"))
    app.processEvents()
    assert janela.isMaximized() and h._maximizada  # o ícone passa a ser "restaurar"
    clicar(h, centro(h, "max"))
    app.processEvents()
    assert not janela.isMaximized() and not h._maximizada
    clicar(h, centro(h, "min"))
    app.processEvents()
    assert janela.isMinimized()
    janela.showNormal()
    app.processEvents()
    clicar(h, centro(h, "close"))
    app.processEvents()
    assert not janela.isVisible()
