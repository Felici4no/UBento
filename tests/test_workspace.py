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
