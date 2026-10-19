# Regras padrão de gestão de risco

Na configuração de cada agente (**Regras de risco**), quatro caixas de seleção. Valem para qualquer algoritmo, menos o manual. O botão **Aplicar pacote padrão** marca as quatro (risco de 0,75%, stop de 2×, meta de 3×).

| Caixa | Valores | O que faz |
|---|---|---|
| **Risco por operação** | 0,5% · 0,75% · 1% da conta | Nenhuma compra arrisca mais que essa fatia da conta: `valor da compra ≤ risco em US$ ÷ stop-loss`. Compra maior é reduzida e a decisão registra o ajuste. |
| **Stop diário** | 2× · 3× o risco de uma operação | Ao perder esse múltiplo no dia, o agente para de **comprar** até o dia seguinte. |
| **Meta de ganho diária** | 2× · 3× · 4× | Ao ganhar esse múltiplo no dia, para de comprar, para não devolver o lucro. |
| **Tamanho pela fórmula** | — | Cada compra passa a ter exatamente `risco em US$ ÷ stop-loss`, em vez do tamanho que o algoritmo pediria (limitado ao caixa gastável e à posição máxima por ativo). |

As três últimas dependem da primeira: sem o risco por operação não há base de cálculo, então ficam desabilitadas e desmarcadas.
Com o risco ligado, o **stop-loss** aparece na tela para qualquer algoritmo, porque ele é a distância usada na conta.

## Contas

- Conta = patrimônio total do agente. Risco em US$ = conta × % escolhido.
- Tamanho = risco em US$ ÷ (stop-loss %). Exemplo: conta de US$ 10.000, risco de 1%, stop de 8% → 100 ÷ 0,08 = **US$ 1.250**.
- Limite do stop diário = N × risco em US$ (com a conta acima e N = 2: US$ 200). Atinge ao chegar em −US$ 200,00 ou menos.
- Resultado do dia = soma do resultado (já líquido de taxa) das decisões **executadas** hoje. Propostas e decisões sem dinheiro não contam. Uma compra recém-feita só pesa a taxa; o ganho ou a perda da posição aparece quando ela é vendida.

## Adaptação à cripto spot

A fórmula original da regra de tamanho era para contratos de índice (`contratos = risco em R$ ÷ (stop em pontos × R$ 0,20)`). Em cripto spot não há contratos nem valor por ponto. A mesma ideia vira **valor da compra = risco em US$ ÷ stop %**, e as quantidades saem do preço do ativo.

## Limites

- Vendas nunca são bloqueadas nem reduzidas: reduzir exposição é sempre permitido, inclusive depois do stop diário.
- As regras valem para as decisões que o **algoritmo do agente** gera. O swap manual não passa por elas.
- O resultado do dia não marca posições abertas a mercado.
- Uma decisão proposta ontem e aprovada hoje não é redimensionada.
