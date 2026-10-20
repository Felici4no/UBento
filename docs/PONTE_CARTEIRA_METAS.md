# Ponte carteira → metas

Passo 1 do [ADR-001](ADR-001-REVISAO-DE-ARQUITETURA.md). Antes dela, o que os agentes faziam no painel nunca chegava ao núcleo de metas: a execução de uma meta só existia se alguém a digitasse na tela de Metas.

## O que faz

Quando um agente **executa** uma compra, a ponte (`ubento/ponte_metas.py`) a registra como execução das metas **daquele agente** que miram o **mesmo ativo**. A conversão é explícita, porque a carteira e o núcleo falam línguas diferentes:

| Carteira | Núcleo |
|---|---|
| `float` | `Decimal`, sempre construído de texto, com as casas do ativo |
| hora local ingênua | UTC com fuso |
| `Trade(qty, usd, fee, preco)` | `Execucao(quantidade_bruta, taxa_no_ativo, quantidade_liquida, preco_executado)` |

Na compra, a taxa sai do que se recebe. Por isso: `quantidade_liquida` = o que a carteira recebeu; `taxa_no_ativo` = taxa em US$ ÷ preço da ordem; `quantidade_bruta` = líquida + taxa. Exemplo: compra de US$ 1.000 de ETH a US$ 2.000 → taxa de US$ 1,00 → líquida 0,4995, taxa 0,0005, bruta 0,5000 (e 0,5 × 2.000 = 1.000, que fecha com o caixa que saiu).

A execução leva o identificador `dec-<id da decisão>`, então registrar o mesmo evento duas vezes não duplica. O preço é o da **ordem** (`Trade.preco`), não o de hoje.

## O que a ponte nunca faz

- **Registrar o que não foi executado.** Aprovar uma proposta não registra nada; só a execução registra.
- **Registrar vendas.** O núcleo mede aquisição e só tem os lados compra e estorno de compra. Se as metas passarem a medir posição líquida, o contrato precisa de um lado de venda: é uma mudança do núcleo, fora deste passo.
- **Comprovar nada.** A execução nasce `simulado` e **sem registro externo**, então fica pendente até haver evidência correspondente. Registrar não é provar.
- **Registrar em meta real.** Só entram metas de cenário (`cenario=True`). A execução da carteira é simulada e só combina com evidência simulada; numa meta real ela viraria divergência de origem.
- **Registrar fora da janela da meta**: antes da ativação ou depois do prazo (no instante do prazo ainda vale), nem em meta já encerrada (atingida, expirada, invalidada, cancelada).
- **Registrar em outra moeda.** A meta precisa cotar em `usd` ou `usdt` (a referência do dólar da carteira).
- **Quebrar a carteira.** Qualquer falha da ponte vira um aviso na tela; a compra já aconteceu na carteira.

Swaps manuais não têm `Trade` e, por enquanto, ficam de fora.

## Como se liga

`Store.executed` (decisão com movimento executada) → `Workspace.decisao_executada(agente, decisão)` → `PonteCarteiraMetas.ao_executar` → `ServicoMetas.registrar_execucao`. A janela principal cria a ponte e, ao registrar, atualiza a tela de Metas se ela estiver aberta.

## Testes

`tests/test_ponte_carteira_metas.py` (22 testes): a conversão com contas à mão, cada recusa acima, o fluxo ponta a ponta com o agente e com aprovação, idempotência, isolamento entre agentes, falha do serviço e a janela. Foram feitas seis mutações no código (aceitar venda, ignorar meta real, ignorar meta encerrada, não somar a taxa na bruta, não exigir execução, não converter o fuso) e todas são pegas.
