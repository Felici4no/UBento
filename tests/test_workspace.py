import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402

from ubento.workspace import Workspace  # noqa: E402


def test_settings_roundtrip(tmp_path):
    path = str(tmp_path / "cfg.ini")
    ws = Workspace(QSettings(path, QSettings.Format.IniFormat))
    first = ws.agents[0]
    ws.rename(first.id, "Minha conta")
    ws.recolor(first.id, "#EF4B3F")
    ws.add("Reserva")

    again = Workspace(QSettings(path, QSettings.Format.IniFormat))
    assert [a.name for a in again.agents] == ["Minha conta", "Empresa", "Reserva"]
    assert again.agents[0].color == "#EF4B3F"


def test_duplicate_copies_balances():
    ws = Workspace()
    src = ws.agents[0]
    copy = ws.duplicate(src.id)
    assert ws.agents[1] is copy
    assert copy.store.holdings == src.store.holdings
    assert copy.store.holdings is not src.store.holdings


def test_prefs_persist_and_hide_values_masks_formatting(tmp_path):
    from ubento import formatting

    path = str(tmp_path / "cfg.ini")
    ws = Workspace(QSettings(path, QSettings.Format.IniFormat))
    try:
        ws.set_pref("user_name", "Lucas")
        ws.set_pref("hide_values", True)
        ws.set_pref("default_range", "6M")
        ws.set_pref("default_range", "bogus")  # inválido é ignorado
        assert formatting.money(1234.5) == "$••••"

        again = Workspace(QSettings(path, QSettings.Format.IniFormat))
        assert again.prefs == {"user_name": "Lucas", "hide_values": True, "default_range": "6M"}
        assert formatting.is_hidden()
    finally:
        formatting.set_hidden(False)


def test_restore_defaults_and_demo_reset():
    ws = Workspace()
    ws.add("Extra")
    ws.restore_default_agents()
    assert [a.name for a in ws.agents] == ["Pessoal", "Empresa"]

    store = ws.agents[0].store
    store.execute("USD", "ETH", 500)
    ws.reset_demo_data()
    assert store.holdings["USD"] == 6900.0


def test_ids_dos_agentes_padrao_sobrevivem_a_reinicio_sem_nenhuma_alteracao(tmp_path):
    """Metas se ligam ao id do agente. Se o id padrão (aleatório) não fosse gravado, reiniciar deixaria as metas órfãs."""
    from PySide6.QtCore import QSettings

    caminho = str(tmp_path / "ws.ini")
    primeira = Workspace(QSettings(caminho, QSettings.Format.IniFormat))
    segunda = Workspace(QSettings(caminho, QSettings.Format.IniFormat))
    assert [a.id for a in primeira.agents] == [a.id for a in segunda.agents]
