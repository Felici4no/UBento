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

A **conciliação** (`ubento.nucleo.conciliacao`) compara execuções internas com registros externos (taxas, quantidades
recebidas, parciais, duplicidades, correções) e, separadamente, explica variações de saldo. Contrato em
[`docs/CONCILIACAO.md`](docs/CONCILIACAO.md); cenários fictícios de reprodução em `exemplos/conciliacao/`.

O **avaliador de metas** (`ubento.nucleo.avaliacao`) integra execução → conciliação → progresso → avaliação → eventos → estado, com
carência, escopo de órfãos, orçamento com pior caso e reconciliação posterior. Contrato em
[`docs/AVALIACAO_META.md`](docs/AVALIACAO_META.md); metas acompanhadas de ponta a ponta com dados simulados em `exemplos/avaliacao/`.

As **conexões** (Binance com chave somente leitura e o bot do Telegram para consultar as metas, segredos no cofre do sistema) estão em [`docs/CONEXOES.md`](docs/CONEXOES.md).

O **MCP local** (somente consulta, `python -m ubento.mcp_local`) está em [`docs/MCP_LOCAL.md`](docs/MCP_LOCAL.md).

A **persistência** (SQLite append-only, fora do núcleo) e a **tela de Metas** estão descritas em
[`docs/PERSISTENCIA_E_INTERFACE.md`](docs/PERSISTENCIA_E_INTERFACE.md). Aprovar uma proposta (✓) não executa nada: a execução é registrada à parte.

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
  persistencia/   SQLite das metas (append-only)
  conexoes/       corretoras: cofre de segredos, cliente Binance somente leitura
  metas.py        serviço: núcleo + banco + o que a tela mostra
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
