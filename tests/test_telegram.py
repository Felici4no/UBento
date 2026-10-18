"""Bot do Telegram: conexão, vínculo do chat por código, ouvinte restrito ao chat vinculado e comandos somente leitura."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from test_correcao_vinculo import JUST, base
from ubento.conexoes import CofreMemoria, ErroDeConexao, ErroDeConfiguracao, ServicoConexoes
from ubento.consulta import abrir
from ubento.metas import ServicoMetas
from ubento.persistencia import Repositorio
from ubento.telegram_comandos import AJUDA, NAO_ENTENDI, responder
from ubento.telegram_ouvinte import ERRO_GENERICO, GerenteOuvintes, OuvinteTelegram

TOKEN = "123456789:AAFakeTokenFakeTokenFakeToken_1234"
SEGREDO_DO_TOKEN = TOKEN.split(":")[1]
DONO = 777  # id do chat privado do dono (num chat privado, o id do chat é o id do usuário)


class FakeTelegram:
    """Transporte falso e com estado: guarda a fila de mensagens e o que o bot enviou. Nunca toca a rede."""

    def __init__(self):
        self.fila: list[dict] = []
        self.enviadas: list[tuple[int, str]] = []
        self.bot = {"id": 123456789, "is_bot": True, "username": "ubento_teste_bot"}
        self.erro: tuple[int, dict] | Exception | None = None
        self.proximo = 1000
        self.urls: list[str] = []

    def mandar(self, chat_id: int, texto: str, tipo: str = "private", remetente: int | None = None):
        self.proximo += 1
        self.fila.append({"update_id": self.proximo, "message": {"chat": {"id": chat_id, "type": tipo}, "from": {"id": remetente or chat_id, "first_name": "Lucas", "last_name": "F"}, "text": texto}})

    def __call__(self, metodo, url, dados, tempo):
        self.urls.append(url)
        if isinstance(self.erro, Exception):
            raise self.erro
        if self.erro:
            status, corpo = self.erro
            return status, json.dumps(corpo).encode()
        assert f"/bot{TOKEN}/" in url
        nome = url.rsplit("/", 1)[1]
        if nome == "getMe":
            return 200, json.dumps({"ok": True, "result": self.bot}).encode()
        if nome == "getUpdates":
            offset = int(dados["offset"]) if dados and "offset" in dados else None
            if offset == -1:
                ultimas, self.fila = self.fila[-1:], []
                return 200, json.dumps({"ok": True, "result": ultimas}).encode()
            if offset is not None:
                self.fila = [u for u in self.fila if u["update_id"] >= offset]
            if not self.fila:
                time.sleep(0.01)
            return 200, json.dumps({"ok": True, "result": list(self.fila)}).encode()
        if nome == "sendMessage":
            self.enviadas.append((int(dados["chat_id"]), dados["text"]))
            return 200, json.dumps({"ok": True, "result": {}}).encode()
        raise AssertionError(nome)


def servico(tg=None, relogio=None, repo=None):
    tg = tg or FakeTelegram()
    return ServicoConexoes(repo or Repositorio(), CofreMemoria(), agora=relogio or (lambda: datetime.now(timezone.utc)), transporte_telegram=tg), tg


def conectar(sv):
    return sv.adicionar("telegram", "Meu bot", {"token": TOKEN})


def vincular(sv, tg, ident=None, chat=DONO):
    ident = ident or sv.listar()[0].id
    codigo, offset = sv.iniciar_vinculo(ident)
    tg.mandar(chat, f"/vincular {codigo}")
    encontrado, _ = sv.procurar_vinculo(ident, offset)
    return sv.concluir_vinculo(ident, encontrado)


# -- conexão ----------------------------------------------------------------------------------------------------------------------


def test_token_valido_conecta_guarda_so_no_cofre_e_mostra_o_usuario_do_bot(tmp_path):
    db = tmp_path / "x.db"
    sv, tg = servico(repo=Repositorio(db))
    c = conectar(sv)
    assert c.provedor == "telegram" and c.status == "conectada" and c.detalhes == {"bot_id": 123456789, "bot_username": "ubento_teste_bot"}
    assert c.chave_mascarada == "123456789:••••1234" and not c.chat_vinculado
    assert sv.cofre.ler(f"conexao:{c.id}:token") == TOKEN
    sv.repo.fechar()
    bruto = db.read_bytes() + b"".join(p.read_bytes() for p in tmp_path.glob("x.db-*"))
    assert TOKEN.encode() not in bruto and SEGREDO_DO_TOKEN.encode() not in bruto  # o banco nunca vê o token


@pytest.mark.parametrize("token", ["", "abc", "123456789", "123456789:curto", "123456789:" + "x" * 40 + " espaço", "tokenSemDoisPontos" + "A" * 40])
def test_token_malformado_e_recusado_sem_tocar_a_rede(token):
    sv, tg = servico()
    with pytest.raises(ErroDeConfiguracao):
        sv.adicionar("telegram", "", {"token": token})
    assert tg.urls == []


@pytest.mark.parametrize("erro,trecho", [
    ((401, {"ok": False, "error_code": 401, "description": "Unauthorized"}), "recusou o token"),
    ((404, {"ok": False, "error_code": 404, "description": "Not Found"}), "recusou o token"),
    ((409, {"ok": False, "error_code": 409, "description": "Conflict: terminated by other getUpdates request"}), "Outro programa"),
    ((429, {"ok": False, "error_code": 429, "description": "Too Many Requests: retry after 5"}), "limitou"),
    ((502, {}), "indisponível"),
])
def test_erros_do_telegram_viram_mensagens_claras_sem_vazar_o_token(erro, trecho, caplog):
    sv, tg = servico()
    tg.erro = erro
    with caplog.at_level(logging.DEBUG), pytest.raises(ErroDeConfiguracao, match=trecho) as exc:
        conectar(sv)
    assert TOKEN not in str(exc.value) and SEGREDO_DO_TOKEN not in str(exc.value) and TOKEN not in caplog.text and SEGREDO_DO_TOKEN not in caplog.text
    assert sv.listar() == [] and sv.cofre._dados == {}


def test_token_que_nao_e_de_bot_e_falha_de_rede():
    sv, tg = servico()
    tg.bot = {"id": 5, "is_bot": False, "username": "pessoa"}
    with pytest.raises(ErroDeConfiguracao, match="não é de um bot"):
        conectar(sv)
    tg.erro = ErroDeConexao("Não foi possível falar com o Telegram. Confira a conexão com a internet e tente de novo.", "URLError")
    with pytest.raises(ErroDeConfiguracao, match="internet"):
        conectar(sv)


def test_a_mesma_token_nao_conecta_duas_vezes():
    sv, _ = servico()
    conectar(sv)
    with pytest.raises(ErroDeConfiguracao, match="já está conectada"):
        conectar(sv)


# -- vínculo do chat ------------------------------------------------------------------------------------------------------------


def test_vinculo_so_com_o_codigo_certo_vindo_de_chat_privado():
    sv, tg = servico()
    c = conectar(sv)
    tg.mandar(DONO, "/start")  # mensagem antiga: será descartada
    codigo, offset = sv.iniciar_vinculo(c.id)
    assert re.fullmatch(r"[0-9A-F]{8}", codigo) and tg.fila == []  # a fila antiga foi descartada
    tg.mandar(999, f"/vincular {codigo}", tipo="group")  # grupo com o código certo: ignorado
    tg.mandar(111, "/vincular 00000000")  # privado com código errado: ignorado
    tg.mandar(111, "oi, bot")  # conversa solta: ignorada
    achado, offset = sv.procurar_vinculo(c.id, offset)
    assert achado is None and not sv.obter(c.id).chat_vinculado
    tg.mandar(DONO, f"/vincular {codigo.lower()}")  # o certo (maiúsculas ou minúsculas)
    achado, offset = sv.procurar_vinculo(c.id, offset)
    assert achado.chat_id == DONO and achado.nome == "Lucas F"
    vinculada = sv.concluir_vinculo(c.id, achado)
    assert vinculada.chat_vinculado and vinculada.detalhes["chat_id"] == DONO and vinculada.detalhes["bot_username"] == "ubento_teste_bot"
    with pytest.raises(ErroDeConfiguracao, match="Gere um código"):  # o código é de uso único
        sv.procurar_vinculo(c.id, offset)


def test_codigo_expira_e_desvincular_remove_o_chat():
    agora = [datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)]
    sv, tg = servico(relogio=lambda: agora[0])
    c = conectar(sv)
    codigo, offset = sv.iniciar_vinculo(c.id)
    agora[0] += timedelta(minutes=11)
    tg.mandar(DONO, f"/vincular {codigo}")
    with pytest.raises(ErroDeConfiguracao, match="expirou"):
        sv.procurar_vinculo(c.id, offset)
    assert not sv.obter(c.id).chat_vinculado
    vinculada = vincular(sv, tg)
    assert vinculada.chat_vinculado
    assert not sv.desvincular(c.id).chat_vinculado


def test_enviar_teste_exige_chat_vinculado_e_manda_a_mensagem():
    sv, tg = servico()
    c = conectar(sv)
    with pytest.raises(ErroDeConfiguracao, match="Vincule um chat"):
        sv.enviar_teste(c.id)
    vincular(sv, tg)
    sv.enviar_teste(c.id)
    assert tg.enviadas[-1][0] == DONO and "/ajuda" in tg.enviadas[-1][1] and "enquanto o UBento estiver aberto" in tg.enviadas[-1][1]


def test_remover_apaga_token_e_codigo():
    sv, tg = servico()
    c = conectar(sv)
    sv.iniciar_vinculo(c.id)
    sv.remover(c.id)
    assert sv.listar() == [] and sv.cofre._dados == {} and sv._codigos == {}


# -- ouvinte -------------------------------------------------------------------------------------------------------------------------


def ouvinte_de(tg, responder_fn):
    from ubento.conexoes import ClienteTelegram

    return OuvinteTelegram(ClienteTelegram(TOKEN, tg), DONO, responder_fn, espera=0)


def test_ouvinte_responde_so_ao_chat_vinculado_e_ignora_os_outros_em_silencio(caplog):
    tg = FakeTelegram()
    tg.mandar(DONO, "/metas")  # enviada com o app fechado: descartada ao iniciar
    ouvinte = ouvinte_de(tg, lambda t: f"resposta a {t}")
    ouvinte.preparar()
    assert tg.fila == []
    tg.mandar(DONO, "/metas")
    tg.mandar(555, "/metas")  # outro usuário
    tg.mandar(DONO, "/metas", tipo="group")  # o mesmo id, mas em grupo
    tg.mandar(-100, "/metas", tipo="supergroup", remetente=DONO)  # grupo em que o dono fala
    tg.mandar(DONO, "bom dia")  # sem barra: só aponta a ajuda
    with caplog.at_level(logging.DEBUG):
        respondidas = ouvinte.uma_rodada()
    assert respondidas == 2 and ouvinte.ignoradas == 3
    assert tg.enviadas == [(DONO, "resposta a /metas"), (DONO, "Envie /ajuda para ver os comandos.")]  # ninguém mais recebeu nada
    assert "/metas" not in caplog.text and "bom dia" not in caplog.text and TOKEN not in caplog.text  # o texto das mensagens não vai para o log
    assert ouvinte.uma_rodada() == 0  # nada é respondido duas vezes (o offset avançou)


def test_falha_ao_montar_a_resposta_nao_derruba_o_ouvinte_nem_vaza_detalhes(caplog):
    tg = FakeTelegram()

    def quebra(_):
        raise RuntimeError("detalhe técnico secreto /caminho/interno")

    ouvinte = ouvinte_de(tg, quebra)
    ouvinte.preparar()
    tg.mandar(DONO, "/metas")
    with caplog.at_level(logging.ERROR):
        assert ouvinte.uma_rodada() == 1
    assert tg.enviadas == [(DONO, ERRO_GENERICO)] and "detalhe técnico" in caplog.text  # a pessoa recebe uma frase simples; o detalhe fica no log


def test_ouvinte_em_thread_responde_e_para():
    tg = FakeTelegram()
    ouvinte = ouvinte_de(tg, lambda t: "ok")
    ouvinte.iniciar()
    limite = time.time() + 5
    while ouvinte.estado != "ouvindo" and time.time() < limite:
        time.sleep(0.01)
    tg.mandar(DONO, "/metas")
    while not tg.enviadas and time.time() < limite:
        time.sleep(0.01)
    assert tg.enviadas == [(DONO, "ok")]
    ouvinte.parar(esperar=5)
    assert ouvinte.estado == "parado"


def test_conflito_com_outro_programa_ou_webhook_para_o_ouvinte_e_avisa():
    tg = FakeTelegram()
    tg.erro = (409, {"ok": False, "error_code": 409, "description": "Conflict: can't use getUpdates method while webhook is active"})
    ouvinte = ouvinte_de(tg, lambda t: "")
    ouvinte.iniciar()
    limite = time.time() + 5
    while ouvinte.estado != "conflito" and time.time() < limite:
        time.sleep(0.01)
    assert ouvinte.estado == "conflito"
    ouvinte._thread.join(5)
    assert not ouvinte._thread.is_alive() and ouvinte.estado == "conflito"  # parou de tentar e continua avisando


def test_gerente_so_ouve_bot_com_chat_vinculado_e_para_tudo():
    sv, tg = servico()
    c = conectar(sv)
    criados = []

    class Falso:
        def __init__(self, cliente, chat_id, responder, espera):
            self.chat_id, self.iniciado, self.parado, self.estado = chat_id, False, False, "ouvindo"
            criados.append(self)

        def iniciar(self):
            self.iniciado = True

        def parar(self, esperar=0):
            self.parado = True

    gerente = GerenteOuvintes(sv, lambda: (lambda t: ""), criar=Falso)
    assert gerente.iniciar(c.id) is None and criados == []  # sem chat vinculado o bot não atende ninguém
    vincular(sv, tg)
    assert gerente.iniciar(c.id) is criados[0] and criados[0].iniciado and criados[0].chat_id == DONO and gerente.estado(c.id) == "ouvindo"
    gerente.iniciar(c.id)  # reiniciar para o ouvinte anterior
    assert criados[0].parado and len(criados) == 2
    gerente.parar_todos()
    assert criados[1].parado and gerente.estado(c.id) == "parado"


# -- comandos (somente leitura) ----------------------------------------------------------------------------------------------------------


@pytest.fixture
def banco(tmp_path):
    db = tmp_path / "ubento.db"
    sv = ServicoMetas(Repositorio(db))
    _, a, *_ = base(sv)
    for n in (1, 2, 3):
        sv.vincular_manualmente(a, f"ex-{n}", "corretora-sim", f"fill-{n}", "Lucas", JUST)
    _, b, *_ = base(sv, meta_id="meta-b")
    sv.avancar(b)
    sv.repo.fechar()
    return db, a, b


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_comandos_respondem_com_a_data_da_ultima_avaliacao_e_sem_alterar_o_banco(banco):
    db, a, b = banco
    antes = sha(db)

    def r(texto):
        return responder(texto, lambda: abrir(db))

    metas = r("/metas")
    assert a in metas and b in metas and "atingida" in metas and "não é tempo real" in metas and "avaliada em" in metas
    prog = r(f"/progresso {a}")
    assert "Comprovado:" in prog and "Última avaliação gravada:" in prog and "Não é tempo real" in prog
    pend = r(f"/pendencias {b}")
    assert "conciliação" in pend and "compra não conciliada" in pend and "Não é tempo real" in pend
    hist = r(f"/historico {a} 2")
    assert "evento(s); últimos 2" in hist and hist.count("#") == 2
    assert r("/ajuda") == AJUDA and r("/start") == AJUDA and r("/progresso@ubento_teste_bot " + a).startswith(a)
    assert r("/apagar tudo") == NAO_ENTENDI and r("oi") == NAO_ENTENDI
    assert "Informe a meta" in r("/progresso")  # há duas metas: precisa dizer qual
    assert "meta desconhecida" in r("/progresso nao-existe")
    assert "inteiro" in r(f"/historico {a} muitos")
    assert sha(db) == antes  # nenhum comando escreveu


def test_comando_sem_banco_responde_com_mensagem_e_nao_cria_arquivo(tmp_path):
    ausente = tmp_path / "nada.db"
    assert "Não consegui ler os dados" in responder("/metas", lambda: abrir(ausente)) and not ausente.exists()


# -- migração -------------------------------------------------------------------------------------------------------------------------


def test_banco_antigo_sem_coluna_detalhes_e_migrado_sem_perder_conexoes(tmp_path):
    db = tmp_path / "antigo.db"
    con = sqlite3.connect(db)
    con.executescript("""CREATE TABLE conexoes (id TEXT PRIMARY KEY, provedor TEXT NOT NULL, apelido TEXT NOT NULL, chave_mascarada TEXT NOT NULL,
        impressao TEXT NOT NULL UNIQUE, criada_em TEXT NOT NULL, status TEXT NOT NULL, status_em TEXT NOT NULL, permissoes TEXT NOT NULL, mensagem TEXT NOT NULL);
        INSERT INTO conexoes VALUES ('c1','binance','Antiga','AbCd…StUv','imp','2026-10-18T12:00:00+00:00','conectada','2026-10-18T12:00:00+00:00','{}','ok');""")
    con.commit()
    con.close()
    sv = ServicoConexoes(Repositorio(db), CofreMemoria())
    (c,) = sv.listar()
    assert c.apelido == "Antiga" and c.detalhes == {}
    sv.repo.fechar()
