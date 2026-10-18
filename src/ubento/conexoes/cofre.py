"""Cofre de segredos das conexões (chaves de API). O banco e os logs NUNCA guardam segredo: só o cofre.

  - Windows: DPAPI (`CryptProtectData`). O segredo só é legível pelo mesmo usuário do Windows, nesta máquina.
  - Outros sistemas: o chaveiro do sistema, se o pacote opcional `keyring` estiver instalado; senão o cofre se recusa a guardar
    (melhor não conectar do que gravar uma chave em texto puro).
  - `CofreMemoria`: para testes e capturas de tela; some ao fechar o app.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path
from typing import Protocol


class ErroDeCofre(RuntimeError):
    """O segredo não pôde ser guardado ou lido. A mensagem nunca contém o segredo."""


class Cofre(Protocol):
    nome: str

    def guardar(self, chave: str, segredo: str) -> None: ...
    def ler(self, chave: str) -> str | None: ...
    def apagar(self, chave: str) -> None: ...


class CofreMemoria:
    nome = "memória (temporário)"

    def __init__(self) -> None:
        self._dados: dict[str, str] = {}

    def guardar(self, chave: str, segredo: str) -> None:
        self._dados[chave] = segredo

    def ler(self, chave: str) -> str | None:
        return self._dados.get(chave)

    def apagar(self, chave: str) -> None:
        self._dados.pop(chave, None)


class CofreIndisponivel:
    nome = "indisponível"

    def __init__(self, motivo: str):
        self.motivo = motivo

    def guardar(self, chave: str, segredo: str) -> None:
        raise ErroDeCofre(self.motivo)

    def ler(self, chave: str) -> str | None:
        return None

    def apagar(self, chave: str) -> None:
        return None


# -- DPAPI (Windows) ---------------------------------------------------------------------------------------------------------


def _dpapi(dados: bytes, proteger: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    ponteiro = ctypes.POINTER(Blob)
    funcao = crypt32.CryptProtectData if proteger else crypt32.CryptUnprotectData
    funcao.argtypes = [ponteiro, wintypes.LPCWSTR if proteger else ctypes.c_void_p, ponteiro, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ponteiro]
    funcao.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]

    def blob(b: bytes):
        buf = ctypes.create_string_buffer(b, len(b))
        return Blob(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    entrada, _manter1 = blob(dados)
    entropia, _manter2 = blob(ENTROPIA)
    saida = Blob()
    if not funcao(ctypes.byref(entrada), "UBento" if proteger else None, ctypes.byref(entropia), None, None, 0, ctypes.byref(saida)):
        raise ErroDeCofre("o Windows recusou proteger/abrir o segredo (DPAPI)")
    try:
        return ctypes.string_at(saida.pbData, saida.cbData)
    finally:
        kernel32.LocalFree(saida.pbData)


ENTROPIA = b"ubento.conexoes.v1"


class CofreDpapi:
    nome = "Windows (DPAPI)"

    def __init__(self, arquivo: str | Path):
        self.arquivo = Path(arquivo)

    def _carregar(self) -> dict[str, str]:
        try:
            return json.loads(self.arquivo.read_text(encoding="utf-8")) if self.arquivo.exists() else {}
        except (OSError, ValueError) as erro:
            raise ErroDeCofre("o arquivo do cofre está ilegível") from erro

    def _gravar(self, dados: dict[str, str]) -> None:
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        temporario = self.arquivo.with_suffix(".tmp")
        temporario.write_text(json.dumps(dados), encoding="utf-8")
        os.replace(temporario, self.arquivo)  # troca atômica: nunca fica um cofre pela metade

    def guardar(self, chave: str, segredo: str) -> None:
        dados = self._carregar()
        dados[chave] = base64.b64encode(_dpapi(segredo.encode("utf-8"), True)).decode("ascii")
        self._gravar(dados)

    def ler(self, chave: str) -> str | None:
        bruto = self._carregar().get(chave)
        return None if bruto is None else _dpapi(base64.b64decode(bruto), False).decode("utf-8")

    def apagar(self, chave: str) -> None:
        dados = self._carregar()
        if chave in dados:
            del dados[chave]
            self._gravar(dados)


class CofreChaveiro:
    nome = "chaveiro do sistema"

    def __init__(self, keyring_modulo):
        self._kr = keyring_modulo

    def guardar(self, chave: str, segredo: str) -> None:
        self._kr.set_password("ubento", chave, segredo)

    def ler(self, chave: str) -> str | None:
        return self._kr.get_password("ubento", chave)

    def apagar(self, chave: str) -> None:
        try:
            self._kr.delete_password("ubento", chave)
        except Exception:  # noqa: BLE001 - apagar algo que não existe não é erro
            pass


def cofre_padrao(pasta: str | Path) -> Cofre:
    if sys.platform == "win32":
        return CofreDpapi(Path(pasta) / "cofre.json")
    try:
        import keyring  # type: ignore[import-not-found]

        return CofreChaveiro(keyring)
    except ImportError:
        return CofreIndisponivel("Neste sistema não há cofre seguro (instale o pacote opcional `keyring`). O UBento não guarda chaves em texto puro.")
