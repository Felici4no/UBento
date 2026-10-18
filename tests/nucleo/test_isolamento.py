import re
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
NUCLEO = SRC / "ubento" / "nucleo"
PROIBIDOS_NO_CODIGO = ("PySide6", "PyQt5", "PyQt6", "socket", "urllib", "http", "requests", "httpx", "sqlite3")


def test_nucleo_nao_carrega_qt_em_tempo_de_execucao():
    codigo = (
        "import sys; sys.path.insert(0, %r); import ubento.nucleo, ubento.nucleo.conciliacao, ubento.nucleo.avaliacao, ubento.nucleo.regras; "
        "qt = [m for m in sys.modules if m.split('.')[0] in {'PySide6', 'PyQt5', 'PyQt6'}]; "
        "print(qt); sys.exit(1 if qt else 0)"
    ) % str(SRC)
    resultado = subprocess.run([sys.executable, "-I", "-c", codigo], capture_output=True, text=True)
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr


def test_codigo_do_nucleo_nao_importa_qt_rede_nem_banco():
    """A fase 1 é só funções puras; persistência e rede entram como adaptadores nas fases seguintes."""
    for arquivo in NUCLEO.rglob("*.py"):
        for linha in arquivo.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*(?:from|import)\s+([A-Za-z0-9_]+)", linha)
            assert not (m and m.group(1) in PROIBIDOS_NO_CODIGO), f"{arquivo.name}: {linha.strip()}"


def test_nucleo_nao_le_o_relogio_do_sistema():
    for arquivo in NUCLEO.rglob("*.py"):
        texto = arquivo.read_text(encoding="utf-8")
        assert "datetime.now" not in texto and "utcnow" not in texto and "time.time" not in texto, arquivo.name
