# Modo mercado real

Liga em **Configurações → Mercado → Mercado real (Binance)**. É um interruptor com confirmação.

## O que muda quando está ligado

| | Demonstração (padrão) | Mercado real |
|---|---|---|
| Preços | fixos, de exemplo | ao vivo, da API pública da Binance (`/api/v3/ticker`, sem chave), a cada 15 s |
| Carteira | saldos de exemplo | **nova**: US$ 10.000 de caixa por agente (`CAPITAL_INICIAL_REAL`), sem posições |
| Decisões, atividade, gastos/receitas | de exemplo | vazios |
| Gráfico do saldo | série sintética | patrimônio **observado** (um ponto por minuto; antes da carteira existir, a linha é o capital inicial) |
| Variação da carteira cripto | fixa | variação real de 7 dias da Binance, ponderada pelo valor de cada ativo |
| Sinal dos agentes (estratégia Tendência) | simulado e limitado a −15%…+20% | variação real de 7 dias, sem cortes |

Desligar descarta as carteiras do mercado real e volta a demonstração (com os preços originais).

## Garantias

- **Nenhuma ordem vai à Binance.** O modo só LÊ preços públicos. As compras e vendas dos agentes são simuladas, com a taxa real da Binance spot (0,10%).
- **Sem preço fresco não se opera.** Se a última leitura tem mais de 120 s (ou ainda não chegou), os agentes não decidem e o swap é recusado ("Aguardando os preços ao vivo da Binance").
- **A resposta da Binance é aceita inteira ou recusada**: um par ausente, preço zero/negativo/não numérico ou variação inválida descarta a leitura. Nunca se mistura preço novo com velho.
- **Falha de rede** mantém o último preço (até vencer) e a tela mostra o motivo.
- USDT é a referência do dólar (US$ 1,00). O preço do USDC vem do par USDCUSDT.

## Limitações conhecidas

- **As carteiras do mercado real não persistem**: ao reiniciar o app, voltam ao capital inicial. (O modo em si persiste.)
- Uma decisão **aprovada** e executada depois usa os valores da proposta, não o preço do momento da execução.
- O swap manual ainda usa as taxas de demonstração (serviço 2,3% + gás).
- Os pares são fixos: ETH, SOL, AVAX, BNB e USDC.
