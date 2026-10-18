"""Seção Conexões das Configurações: adicionar, errar sem perder o digitado, testar, remover; o segredo nunca fica na tela nem no objeto."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit  # noqa: E402

from test_conexoes import CHAVE, LEITURA, SEGREDO, Rede  # noqa: E402
from ubento.conexoes import CONECTADA, ERRO, REPROVADA, CofreMemoria, ServicoConexoes  # noqa: E402
from ubento.metas import ServicoMetas  # noqa: E402
from ubento.persistencia import Repositorio  # noqa: E402
from ubento.ui import theme  # noqa: E402
from ubento.ui.components import Label  # noqa: E402
from ubento.ui.controls import Chip  # noqa: E402
from ubento.ui.main_window import MainWindow  # noqa: E402
from ubento.workspace import Workspace  # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(theme.APP_QSS)
    return a


@pytest.fixture
def janela(app):
    repo, rede, cofre = Repositorio(), Rede(), CofreMemoria()
    servico = ServicoConexoes(repo, cofre, rede)
    w = MainWindow(Workspace(), animations=False, metas=ServicoMetas(repo), conexoes=servico)
    w.show()
    w.select("settings")
    app.processEvents()
    secao = w.pages["settings"].widget().conexoes_section
    secao.sincrono = True
    w.rede, w.cofre = rede, cofre
    yield w, secao, servico
    w.close()


def textos(widget) -> str:
    return "\n".join([x.text() for x in widget.findChildren(Label)] + [c._text for c in widget.findChildren(Chip)])


def test_a_secao_aparece_nas_configuracoes_e_o_app_de_teste_nunca_toca_o_cofre_real(app):
    w = MainWindow(Workspace(), animations=False)  # sem serviço informado: cofre temporário em memória
    assert isinstance(w.conexoes.cofre, CofreMemoria)
    page = w.pages["settings"].widget()
    assert "CONEXÕES" in textos(page) and "Nenhuma conexão ainda" in textos(page)
    w.close()


def test_adicionar_binance_fluxo_completo_com_erros_que_preservam_o_digitado(janela):
    w, secao, servico = janela
    d = secao.criar_dialogo()
    assert d.campos["api_secret"].echoMode() == QLineEdit.EchoMode.Password and d.campos["api_key"].echoMode() == QLineEdit.EchoMode.Normal
    d.definir(apelido="Binance pessoal", api_key=CHAVE, api_secret="curto")
    d.conectar()
    assert "incompleto" in d.erro.text() and d.campos["api_key"].text() == CHAVE and d.apelido.text() == "Binance pessoal"  # nada se perdeu
    assert w.rede.pedidos == [] and servico.listar() == []  # formato inválido nem chega à rede

    w.rede.resposta = (200, {**LEITURA, "enableWithdrawals": True})  # chave com poder de saque
    d.definir(apelido="Binance pessoal", api_key=CHAVE, api_secret=SEGREDO)
    d.conectar()
    assert "saques" in d.erro.text() and d.botao.isEnabled() and d.campos["api_secret"].text() == SEGREDO  # continua aberto, tudo preenchido
    assert servico.listar() == [] and w.cofre._dados == {}

    w.rede.resposta = (200, LEITURA)  # a pessoa criou uma chave só de leitura e cola de novo
    d.conectar()
    assert d.conexao is not None and d.conexao.status == CONECTADA
    assert getattr(d, "_limpas", None) == {}  # o diálogo não segura o segredo depois de gravar
    secao.refresh()
    t = textos(secao)
    assert "Binance pessoal" in t and "AbCd…StUv" in t and "Conectada" in t
    assert CHAVE not in t and SEGREDO not in t  # a tela mostra só o trecho mascarado


def test_conectar_em_outra_thread_nao_trava_a_interface_e_entrega_no_fim(janela, app):
    w, secao, servico = janela
    d = secao.criar_dialogo()
    d.sincrono = False  # caminho real: rede em thread, banco e cofre na thread principal
    d.definir(apelido="", api_key=CHAVE, api_secret=SEGREDO)
    d.conectar()
    assert d.botao.isEnabled() is False and d.botao.text() == "Verificando…"
    limite = time.time() + 5
    while d.conexao is None and time.time() < limite:
        app.processEvents()
        time.sleep(0.01)
    assert d.conexao is not None and d.conexao.apelido == "Binance" and len(servico.listar()) == 1


def test_testar_e_remover_pela_secao(janela):
    w, secao, servico = janela
    c = servico.adicionar("binance", "Minha", {"api_key": CHAVE, "api_secret": SEGREDO})
    secao.refresh()
    avisos = []
    secao.notify.connect(lambda m, ok: avisos.append((m, ok)))

    w.rede.resposta = (200, {**LEITURA, "enableFutures": True})
    secao.testar(c.id)
    assert servico.listar()[0].status == REPROVADA and avisos[-1][1] is False and "futuros" in avisos[-1][0]
    assert "Reprovada" in textos(secao)

    w.rede.resposta = (503, {})
    secao.testar(c.id)
    assert servico.listar()[0].status == ERRO and "indisponível" in textos(secao)

    secao._confirmar = lambda *a: False  # cancelou: nada muda
    secao.remover(c.id)
    assert len(servico.listar()) == 1 and w.cofre._dados
    secao._confirmar = lambda *a: True
    secao.remover(c.id)
    assert servico.listar() == [] and w.cofre._dados == {} and "Nenhuma conexão" in textos(secao)
    secao.testar("inexistente")
    assert "não encontrada" in avisos[-1][0]
