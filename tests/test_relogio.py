"""Relógio da avaliação: `agora` é parâmetro do núcleo; o serviço decide de onde ele vem.

- Meta de CENÁRIO (replay, dado simulado): o instante vem do cenário. O relógio do sistema nunca é consultado.
- Meta REAL: o aplicativo fornece o horário real, com fuso explícito (UTC), ao solicitar a avaliação.
- Nada avalia sozinho: a meta não expira porque o tempo passou; só uma ação (registrar, vincular, importar, reavaliar) dispara a avaliação.
"""

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from test_correcao_vinculo import CENARIO, JUST
from ubento.consulta import ConsultaMetas
from ubento.metas import EvidenciaExterna, ServicoMetas
from ubento.nucleo.avaliacao import ErroDeAvaliacao
from ubento.nucleo.avaliacao.reproducao import carregar_reproducao_meta
from ubento.nucleo.conciliacao import VinculoManual
from ubento.persistencia import Repositorio

UTC = timezone.utc
O = carregar_reproducao_meta(CENARIO)  # ativada 20/10 08:00Z, prazo 16:00Z, alvo 10 tokx
VAZIO = O.model_copy(update={"execucoes": (), "registros_externos": (), "coberturas_execucoes": ()})


class Relogio:
    def __init__(self, inicio):
        self.agora = inicio

    def __call__(self):
        return self.agora


def real(relogio=None, repo=None):
    r = relogio or Relogio(datetime(2026, 10, 20, 12, 0, tzinfo=UTC))
    sv = ServicoMetas(repo, relogio=r)
    mid = sv.importar(VAZIO, cenario=False)
    return sv, mid, r


def test_meta_real_e_avaliada_no_horario_real_com_fuso_explicito():
    sv, mid, relogio = real()
    r = sv.reavaliar(mid)
    assert r.avaliacao.avaliada_em == datetime(2026, 10, 20, 12, 0, tzinfo=UTC) and r.avaliacao.avaliada_em.utcoffset() == timedelta(0)
    # o mesmo instante dito em outro fuso (UTC-3) vira o mesmo instante absoluto
    relogio.agora = datetime(2026, 10, 20, 10, 30, tzinfo=timezone(timedelta(hours=-3)))  # 13:30Z
    assert sv.reavaliar(mid).avaliacao.avaliada_em == datetime(2026, 10, 20, 13, 30, tzinfo=UTC)
    assert sv.painel(mid).cenario is False


def test_relogio_sem_fuso_e_recusado():
    sv, mid, relogio = real()
    relogio.agora = datetime(2026, 10, 20, 12, 0)  # ingênuo: ambíguo
    with pytest.raises(ValueError, match="fuso"):
        sv.reavaliar(mid)


def test_o_tempo_das_avaliacoes_nunca_anda_para_tras():
    sv, mid, relogio = real()
    sv.reavaliar(mid)
    relogio.agora -= timedelta(hours=1)  # relógio do computador acertado para trás
    assert sv.reavaliar(mid).avaliacao.avaliada_em == datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def test_relogio_antes_da_ativacao_e_recusado():
    sv, mid, relogio = real(Relogio(datetime(2026, 10, 19, 12, 0, tzinfo=UTC)))
    with pytest.raises(ErroDeAvaliacao, match="anterior à ativação"):
        sv.reavaliar(mid)


def test_meta_de_cenario_ignora_o_relogio_do_sistema():
    sv = ServicoMetas(relogio=lambda: datetime(2030, 1, 1, tzinfo=UTC))
    mid = sv.importar(VAZIO)  # cenário por padrão (replay de dado simulado)
    sv.avancar(mid)
    assert sv.reavaliar(mid).avaliacao.avaliada_em == O.momentos[0].agora  # o instante do cenário, não 2030
    assert sv.painel(mid).cenario is True


def test_nada_avalia_sozinho_o_tempo_passar_nao_expira_a_meta():
    sv, mid, relogio = real()
    sv.reavaliar(mid)
    relogio.agora = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)  # já passou o prazo (20/10 16:00Z)...
    assert sv.painel(mid).estado.value == "ativa"  # ...e nada mudou: ninguém pediu uma avaliação
    n = len(sv.repo.avaliacoes(mid))
    consulta_antes = len(sv.repo.eventos(mid))
    assert len(sv.repo.avaliacoes(mid)) == n and len(sv.repo.eventos(mid)) == consulta_antes
    assert sv.reavaliar(mid).estado.value == "expirada"  # só a ação de avaliar aplica o prazo


def test_acoes_do_app_usam_o_horario_real_na_meta_real():
    sv, mid, relogio = real()
    e = O.execucoes[0].model_copy(update={"referencias_externas": (), "meta_id": mid})
    sv.registrar_execucao(mid, e.model_copy(update={"meta_id": mid}))
    sv.importar_evidencia(mid, EvidenciaExterna(registros_externos=O.registros_externos[:1]))
    relogio.agora = datetime(2026, 10, 20, 14, 15, tzinfo=UTC)
    sv.vincular_manualmente(mid, "ex-1", "corretora-sim", "fill-1", "Lucas", JUST)
    (v,) = sv.repo.entradas(mid, "vinculos_manuais", VinculoManual)
    assert v.em == datetime(2026, 10, 20, 14, 15, tzinfo=UTC)  # a decisão humana vale a partir de AGORA
    assert sv.repo.ultima_avaliacao(mid)[0].avaliada_em == v.em
    relogio.agora = datetime(2026, 10, 20, 14, 30, tzinfo=UTC)
    sv.revogar_vinculo(mid, "ex-1", "corretora-sim", "fill-1", "Marina", "Engano meu: não era esta compra, vide extrato.")
    assert sv.repo.ultima_avaliacao(mid)[0].avaliada_em == datetime(2026, 10, 20, 14, 30, tzinfo=UTC)


def test_o_modo_da_meta_sobrevive_a_reiniciar_e_a_consulta_diz_de_onde_veio_o_instante(tmp_path):
    db = tmp_path / "x.db"
    sv, mid, _ = real(repo=Repositorio(db))
    sv.reavaliar(mid)
    cen = sv.importar(VAZIO.model_copy(update={"meta": VAZIO.meta.model_copy(update={"id": "meta-cenario"})}))
    sv.avancar(cen)
    sv.repo.fechar()
    antes = hashlib.sha256(Path(db).read_bytes()).hexdigest()
    consulta = ConsultaMetas(Repositorio(db, somente_leitura=True))
    assert consulta.consultar_progresso(mid)["ultima_avaliacao"]["instante_vem_de"] == "relogio_real"
    assert consulta.consultar_progresso(cen)["ultima_avaliacao"]["instante_vem_de"] == "cenario"
    consulta.repo.fechar()
    assert hashlib.sha256(Path(db).read_bytes()).hexdigest() == antes  # consultar não reavalia nem grava


def test_a_tela_mostra_quando_a_avaliacao_ocorreu_e_de_onde_veio_o_instante():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from ubento.ui import theme
    from ubento.ui.components import Label
    from ubento.ui.controls import Chip
    from ubento.ui.main_window import MainWindow
    from ubento.workspace import Workspace

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme.APP_QSS)
    relogio = Relogio(datetime(2026, 10, 20, 12, 0, tzinfo=UTC))
    sv = ServicoMetas(relogio=relogio)
    janela = MainWindow(Workspace(), animations=False, metas=sv)
    janela.show()
    agente = janela.workspace.agents[0].id
    janela.open_metas(agente)
    page = janela.pages["metas:" + agente].widget()
    real_id = sv.importar(VAZIO, agente_id=agente, cenario=False)
    page.refresh()

    def textos():
        return "\n".join([x.text() for x in page.findChildren(Label)] + [c._text for c in page.findChildren(Chip)])

    assert page.reavaliar.isEnabled()  # meta real pode ser avaliada agora mesmo, sem avaliação anterior
    page.reavaliar.clicked.emit()
    t = textos()
    assert "20/10/2026 12:00 UTC · relógio real" in t and "não expira nem se reavalia sozinha" in t
    assert real_id in sv.metas(agente)
    janela.close()


def test_relogio_antes_da_ativacao_vira_aviso_na_tela_sem_quebrar():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from ubento.ui import theme
    from ubento.ui.main_window import MainWindow
    from ubento.workspace import Workspace

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme.APP_QSS)
    sv = ServicoMetas(relogio=Relogio(datetime(2026, 10, 19, 12, 0, tzinfo=UTC)))  # um dia ANTES de a meta ser ativada
    janela = MainWindow(Workspace(), animations=False, metas=sv)
    janela.show()
    agente = janela.workspace.agents[0].id
    janela.open_metas(agente)
    page = janela.pages["metas:" + agente].widget()
    sv.importar(VAZIO, agente_id=agente, cenario=False)
    page.refresh()
    avisos = []
    page.notify.connect(lambda m, ok: avisos.append((m, ok)))
    page.reavaliar.clicked.emit()
    assert avisos and avisos[-1][1] is False and "anterior à ativação" in avisos[-1][0]
    janela.close()
