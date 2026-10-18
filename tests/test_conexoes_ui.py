"""Seção Conexões das Configurações: adicionar, errar sem perder o digitado, testar, remover; o segredo nunca fica na tela nem no objeto."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re  # noqa: E402
import time  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit  # noqa: E402

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


def test_provedor_reservado_aparece_como_em_breve_e_nao_abre_dialogo(janela, monkeypatch):
    from dataclasses import replace

    from ubento.conexoes import PROVEDORES

    w, secao, servico = janela
    monkeypatch.setitem(PROVEDORES, "futuro", replace(PROVEDORES["telegram"], id="futuro", nome="Futuro", como_conectar="Em breve: mais um provedor.", disponivel=False))
    secao.refresh()
    assert "Futuro" in textos(secao) and "Em breve" in textos(secao)
    with pytest.raises(ValueError, match="não está disponível"):
        secao.criar_dialogo("futuro")
    assert w.rede.pedidos == [] and servico.listar() == [] and w.cofre._dados == {}


def test_conectar_telegram_vincular_chat_enviar_teste_e_desvincular(janela):
    from test_telegram import DONO, TOKEN, FakeTelegram

    w, secao, servico = janela
    tg = FakeTelegram()
    servico.transportes["telegram"] = tg
    avisos = []
    secao.notify.connect(lambda m, ok: avisos.append((m, ok)))

    d = secao.criar_dialogo("telegram")
    assert d.campos["token"].echoMode() == QLineEdit.EchoMode.Password  # o token nunca aparece na tela
    assert any("BotFather" in x.text() for x in d.findChildren(QLabel))  # o passo a passo para criar o bot está no diálogo
    d.definir(apelido="Meu bot", token="123456789:curto")
    d.conectar()
    assert "incompleto" in d.erro.text() and d.campos["token"].text() == "123456789:curto" and tg.urls == []  # erro mantém o digitado, sem rede
    d.definir(apelido="Meu bot", token=TOKEN)
    d.conectar()
    c = d.conexao
    assert c is not None and c.detalhes["bot_username"] == "ubento_teste_bot" and not c.chat_vinculado
    secao.refresh()
    t = textos(secao)
    assert "@ubento_teste_bot" in t and "chat ainda não vinculado" in t and TOKEN not in t and "123456789:••••1234" in t

    # vínculo: código de uso único; só o chat privado que o enviar passa a ser atendido
    v = secao.criar_vinculo(c.id, automatico=False)
    v.iniciar()
    assert re.fullmatch(r"/vincular [0-9A-F]{8}", v.mensagem.text())
    tg.mandar(999, v.mensagem.text(), tipo="group")  # grupo com o código certo
    v.procurar()
    assert v.conexao is None and not servico.obter(c.id).chat_vinculado
    tg.mandar(DONO, v.mensagem.text())
    v.procurar()
    assert v.conexao is not None and servico.obter(c.id).detalhes["chat_id"] == DONO
    secao.refresh()
    assert "vinculado a Lucas F" in textos(secao)

    secao.enviar_teste(c.id)
    assert tg.enviadas[-1][0] == DONO and avisos[-1] == ("Mensagem de teste enviada ao seu chat", True)

    secao._confirmar = lambda *a: False
    secao.desvincular(c.id)
    assert servico.obter(c.id).chat_vinculado  # cancelou: nada muda
    secao._confirmar = lambda *a: True
    secao.desvincular(c.id)
    assert not servico.obter(c.id).chat_vinculado and "chat ainda não vinculado" in textos(secao)
    secao.remover(c.id)
    assert servico.listar() == [] and w.cofre._dados == {}  # token apagado do cofre
    secao.enviar_teste("inexistente")
    assert "não encontrada" in avisos[-1][0]


def test_o_ouvinte_so_inicia_depois_do_vinculo_pela_secao(janela, monkeypatch):
    from test_telegram import DONO, TOKEN, FakeTelegram
    from ubento.ui.conexoes import VinculoTelegramDialog

    w, secao, servico = janela
    tg = FakeTelegram()
    servico.transportes["telegram"] = tg
    eventos = []

    class Gerente:
        def iniciar(self, ident):
            eventos.append(("iniciar", ident))

        def parar(self, ident):
            eventos.append(("parar", ident))

        def estado(self, ident):
            return "ouvindo" if ("iniciar", ident) in eventos and ("parar", ident) not in eventos else "parado"

    secao.ouvintes = Gerente()
    c = servico.adicionar("telegram", "Bot", {"token": TOKEN})

    def exec_simulado(self):  # no lugar de abrir a janela: o usuário "envia" o código e o diálogo o encontra
        self.automatico = False
        self.iniciar()
        tg.mandar(DONO, self.mensagem.text())
        self.procurar()
        return 1 if self.conexao else 0

    monkeypatch.setattr(VinculoTelegramDialog, "exec", exec_simulado)
    secao.vincular_chat(c.id)
    assert eventos == [("iniciar", c.id)] and servico.obter(c.id).chat_vinculado and "Atendendo" in textos(secao)
    secao._confirmar = lambda *a: True
    secao.desvincular(c.id)  # desvincular para o ouvinte antes de limpar o chat
    assert eventos[-1] == ("parar", c.id) and "Parado" not in textos(secao)  # sem chat vinculado não há etiqueta de ouvinte
