"""Atualizador de preços em segundo plano: entrega na thread da interface, sobrevive a falhas e para de verdade."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading  # noqa: E402
import time  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QObject, QThread  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ubento.atualizador_mercado import AtualizadorDeMercado  # noqa: E402
from ubento.conexoes.binance import ErroDeConexao  # noqa: E402
from ubento.conexoes.mercado import Cotacoes  # noqa: E402

COT = Cotacoes({"ETH": 2000.0}, {"ETH": 1.0})


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class Cliente:
    def __init__(self, *respostas):
        self.respostas, self.chamadas = list(respostas), 0

    def cotacoes(self):
        self.chamadas += 1
        r = self.respostas[min(self.chamadas - 1, len(self.respostas) - 1)]
        if isinstance(r, Exception):
            raise r
        return r


def esperar(app, condicao, segundos=3.0):
    fim = time.time() + segundos
    while time.time() < fim and not condicao():
        app.processEvents()
        time.sleep(0.01)
    return condicao()


class Receptor(QObject):
    def __init__(self):
        super().__init__()
        self.recebidas, self.threads = [], []

    def receber(self, c):
        self.recebidas.append(c)
        self.threads.append(QThread.currentThread())


def test_entrega_a_cotacao_na_thread_da_interface(app):
    r = Receptor()
    a = AtualizadorDeMercado(Cliente(COT), intervalo=0.05)
    a.cotacoes.connect(r.receber)  # método de um QObject da interface: a entrega é enfileirada para a thread dele
    a.iniciar()
    try:
        assert esperar(app, lambda: len(r.recebidas) >= 2)
        assert r.recebidas[0] is COT and set(r.threads) == {app.thread()}  # nunca na thread de rede
    finally:
        a.parar()


def test_falha_vira_sinal_e_a_leitura_continua(app):
    falhas, cotacoes = [], []
    a = AtualizadorDeMercado(Cliente(ErroDeConexao("sem rede"), RuntimeError("bug"), COT), intervalo=0.02)
    a.falhou.connect(falhas.append)
    a.cotacoes.connect(cotacoes.append)
    a.iniciar()
    try:
        assert esperar(app, lambda: cotacoes)
        assert falhas[0] == "sem rede" and "inesperado" in falhas[1]  # a segunda falha não derrubou a leitura
    finally:
        a.parar()


def test_parar_para_de_ler_de_verdade_e_nao_entrega_leitura_atrasada(app):
    cliente = Cliente(COT)
    a = AtualizadorDeMercado(cliente, intervalo=0.02)
    recebidas = []
    a.cotacoes.connect(recebidas.append)
    a.iniciar()
    assert esperar(app, lambda: recebidas)
    a.parar()
    time.sleep(0.15)
    parado = cliente.chamadas
    time.sleep(0.15)
    assert cliente.chamadas == parado and not a.ativo


def test_iniciar_duas_vezes_nao_cria_duas_leituras(app):
    cliente = Cliente(COT)
    a = AtualizadorDeMercado(cliente, intervalo=5.0)
    a.iniciar()
    a.iniciar()
    try:
        assert esperar(app, lambda: cliente.chamadas >= 1)
        time.sleep(0.1)
        assert cliente.chamadas == 1 and sum(t.name == "ubento-mercado" for t in threading.enumerate()) >= 1
    finally:
        a.parar()


def test_depois_de_parar_pode_iniciar_de_novo(app):
    cliente = Cliente(COT)
    a = AtualizadorDeMercado(cliente, intervalo=5.0)
    a.iniciar()
    assert esperar(app, lambda: cliente.chamadas == 1)
    a.parar()
    a.iniciar()
    try:
        assert esperar(app, lambda: cliente.chamadas == 2)
    finally:
        a.parar()


def test_leitura_em_andamento_quando_desliga_nao_entra_nem_depois_de_religar(app):
    class Lento:
        def __init__(self):
            self.chamadas = 0

        def cotacoes(self):
            self.chamadas += 1
            time.sleep(0.3 if self.chamadas == 1 else 0)
            return Cotacoes({"ETH": float(self.chamadas)}, {})

    cliente, recebidas = Lento(), []
    a = AtualizadorDeMercado(cliente, intervalo=5.0)
    a.cotacoes.connect(recebidas.append)
    a.iniciar()
    time.sleep(0.05)  # a 1ª leitura está na rede
    a.parar()
    a.iniciar()  # religar na hora: a leitura velha termina, mas pertence ao ciclo anterior
    try:
        assert esperar(app, lambda: recebidas)
        time.sleep(0.4)
        app.processEvents()
        assert [c.precos["ETH"] for c in recebidas] == [2.0]  # só a do ciclo novo
    finally:
        a.parar()
