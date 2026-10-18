"""Leitura segura de documentos YAML/JSON e validação contra o esquema.

Política: chaves duplicadas, números fracionários sem aspas, datas sem aspas, tipos não textuais como chave,
estruturas cíclicas ou muito profundas e arquivos grandes demais são **erros**, nunca conversões silenciosas.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

M = TypeVar("M", bound=BaseModel)

TAMANHO_MAXIMO = 1_048_576  # 1 MiB
PROFUNDIDADE_MAXIMA = 32


class ErroDeCarga(ValueError):
    """O texto não é um documento aceitável (sintaxe, duplicata, tipo proibido…)."""

    def __init__(self, mensagem: str, caminho: str = "$") -> None:
        curto = caminho if len(caminho) <= 60 else "…" + caminho[-59:]
        super().__init__(f"{curto}: {mensagem}")
        self.mensagem, self.caminho = mensagem, caminho


@dataclass(frozen=True)
class ErroCampo:
    caminho: str
    tipo: str
    mensagem: str


class ErroDeValidacao(ValueError):
    """O documento é bem formado, mas não respeita o esquema."""

    def __init__(self, erros: list[ErroCampo]) -> None:
        self.erros = erros
        super().__init__("\n".join(f"{e.caminho}: {e.mensagem}" for e in erros))


# -- leitura -------------------------------------------------------------------------------------


def _verificar(valor: Any, caminho: str = "$", profundidade: int = 0, ancestrais: frozenset[int] = frozenset()) -> None:
    if profundidade > PROFUNDIDADE_MAXIMA:
        raise ErroDeCarga(f"estrutura mais profunda que {PROFUNDIDADE_MAXIMA} níveis", caminho)
    if valor is None or isinstance(valor, (bool, int, str)):
        return
    if isinstance(valor, float):
        raise ErroDeCarga(f"número fracionário {valor!r} sem aspas; escreva como texto decimal, ex.: \"{valor}\"", caminho)
    if isinstance(valor, (dict, list)):
        if id(valor) in ancestrais:
            raise ErroDeCarga("referência circular", caminho)
        filhos = ancestrais | {id(valor)}
        if isinstance(valor, dict):
            for chave, item in valor.items():
                if not isinstance(chave, str):
                    raise ErroDeCarga(f"chave não textual {chave!r}", caminho)
                _verificar(item, f"{caminho}.{chave}", profundidade + 1, filhos)
        else:
            for i, item in enumerate(valor):
                _verificar(item, f"{caminho}[{i}]", profundidade + 1, filhos)
        return
    raise ErroDeCarga(
        f"tipo não permitido {type(valor).__name__} ({valor!r}); datas e horas devem estar entre aspas", caminho
    )


def ler_yaml(texto: str) -> Any:
    if len(texto) > TAMANHO_MAXIMO:
        raise ErroDeCarga(f"documento maior que {TAMANHO_MAXIMO} caracteres")
    yaml = YAML(typ="safe", pure=True)
    yaml.allow_duplicate_keys = False
    try:
        dados = yaml.load(StringIO(texto))
    except YAMLError as erro:
        resumo = " ".join(str(erro).split())  # junta as linhas do diagnóstico do ruamel
        raise ErroDeCarga(f"YAML inválido: {resumo[:240]}") from erro
    _verificar(dados)  # o modo seguro já devolve dict/list comuns; aqui barramos ciclos, profundidade e tipos
    return dados


def _sem_duplicatas(pares: list[tuple[str, Any]]) -> dict[str, Any]:
    saida: dict[str, Any] = {}
    for chave, valor in pares:
        if chave in saida:
            raise ErroDeCarga(f"chave duplicada {chave!r}")
        saida[chave] = valor
    return saida


def _recusar_float(texto: str) -> Any:
    raise ErroDeCarga(f"número fracionário {texto} sem aspas; escreva como texto decimal, ex.: \"{texto}\"")


def _recusar_constante(texto: str) -> Any:
    raise ErroDeCarga(f"constante não permitida: {texto}")


def ler_json(texto: str) -> Any:
    if len(texto) > TAMANHO_MAXIMO:
        raise ErroDeCarga(f"documento maior que {TAMANHO_MAXIMO} caracteres")
    try:
        dados = json.loads(texto, object_pairs_hook=_sem_duplicatas, parse_float=_recusar_float, parse_constant=_recusar_constante)
    except json.JSONDecodeError as erro:
        raise ErroDeCarga(f"JSON inválido: {erro.msg} (linha {erro.lineno}, coluna {erro.colno})") from erro
    _verificar(dados)
    return dados


# -- validação ----------------------------------------------------------------------------------------


def validar(modelo: type[M], dados: Any) -> M:
    """Valida dados já lidos; devolve o modelo ou levanta `ErroDeValidacao` com todos os problemas."""
    try:
        return modelo.model_validate(dados)
    except ValidationError as erro:
        raise ErroDeValidacao([
            ErroCampo(".".join(str(parte) for parte in e["loc"]) or "$", e["type"], e["msg"]) for e in erro.errors()
        ]) from None


def carregar_texto(modelo: type[M], texto: str, formato: str = "yaml") -> M:
    leitores = {"yaml": ler_yaml, "yml": ler_yaml, "json": ler_json}
    if formato not in leitores:
        raise ErroDeCarga(f"formato desconhecido: {formato!r} (use yaml ou json)")
    return validar(modelo, leitores[formato](texto))


def carregar_arquivo(modelo: type[M], caminho: str | Path) -> M:
    caminho = Path(caminho)
    formato = caminho.suffix.lower().lstrip(".")
    if formato not in ("yaml", "yml", "json"):
        raise ErroDeCarga(f"extensão não suportada: {caminho.suffix!r}")
    if caminho.stat().st_size > TAMANHO_MAXIMO * 4:
        raise ErroDeCarga(f"arquivo maior que o limite: {caminho.name}")
    return carregar_texto(modelo, caminho.read_text(encoding="utf-8-sig"), formato)


# -- escrita --------------------------------------------------------------------------------------------


def para_dict(modelo: BaseModel) -> dict[str, Any]:
    """Representação de intercâmbio: decimais e datas como texto, enums como valor."""
    return modelo.model_dump(mode="json")


def para_json(modelo: BaseModel, indentar: int | None = 2) -> str:
    return json.dumps(para_dict(modelo), ensure_ascii=False, indent=indentar, sort_keys=False)


def para_yaml(modelo: BaseModel) -> str:
    yaml = YAML(typ="safe", pure=True)
    yaml.default_flow_style = False
    yaml.allow_unicode = True
    saida = StringIO()
    yaml.dump(para_dict(modelo), saida)
    return saida.getvalue()
