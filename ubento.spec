# PyInstaller: `pyinstaller ubento.spec --noconfirm`
from pathlib import Path

root = Path(SPECPATH)

a = Analysis(
    [str(root / "src" / "ubento" / "__main__.py")],
    pathex=[str(root / "src")],
    datas=[(str(root / "assets" / "ubento.svg"), "assets")],
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="UBento",
    console=False,
    icon=str(root / "assets" / "ubento.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="UBento")
