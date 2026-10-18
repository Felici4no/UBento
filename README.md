# UBento

Painel financeiro de desktop, feito em **Python + PySide6** (SQLite entra na próxima etapa).
Esta primeira fase é só interface: todas as telas funcionam com dados de demonstração em memória.

## O que já funciona

| Card | Interação |
|---|---|
| Saldo em cripto | Barra de alocação por ativo; passe o mouse para ver a participação |
| Saldo total | Períodos 1S / 1M / 6M / 1A / Tudo com animação; cursor mostra data e valor da barra |
| Resumo | Gastos, receitas e transferências do mês, com barras proporcionais |
| Atividade | Mapa de pontos do mês (semana × dia); tooltip com a contagem do dia |
| Trocar | Cotação, taxa de serviço e de rede em tempo real; seletor de moeda; inverter; valida saldo; executa e atualiza todos os cards |
| Transferências | Lista rolável; a troca executada aparece no topo |
| USDC | Saldo, minigráfico com cursor, `+` leva ao Trocar já preenchido (USD → USDC) |

## Rodando

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python -m ubento
```

Testes: `pytest`. Captura de tela para conferir o visual: `python scripts/screenshot.py saida.png`.

## Núcleo de metas (em construção)

`src/ubento/nucleo` é o núcleo determinístico de análises e metas: tipos estritos (`Decimal`, UTC), esquema
Pydantic, carregamento seguro de YAML/JSON e hash canônico do contrato. Não depende de Qt, rede nem do relógio
do sistema. Contrato e decisões em [`docs/ESPECIFICACAO_NUCLEO.md`](docs/ESPECIFICACAO_NUCLEO.md); análise e
roadmap em [`docs/ANALISE_META_MOTOR.md`](docs/ANALISE_META_MOTOR.md); documentos de exemplo (dados simulados) em
`exemplos/nucleo/`.

```bash
pytest tests/nucleo          # inclui testes de propriedade (Hypothesis)
```

## Instalador (Windows)

```powershell
./scripts/build_windows.ps1
```

Gera `dist\UBento\UBento.exe` (PyInstaller) e, se o [Inno Setup 6](https://jrsoftware.org/isinfo.php)
estiver instalado, `Output\UBento-Setup-<versão>.exe`.

## Estrutura

```
src/ubento/
  nucleo/         núcleo de análises e metas (sem Qt)
  store.py        estado em memória + lógica de troca (demonstração)
  formatting.py   números, moeda e datas em pt-BR
  ui/
    theme.py      cores, fontes, QSS global
    components.py botões, rótulos, toast… (tudo desenhado com QPainter)
    cards/        um módulo por card
    main_window.py
```

## Licença

MIT
