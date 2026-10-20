# Persistência das carteiras do mercado real

Passo 4 do [ADR-001](ADR-001-REVISAO-DE-ARQUITETURA.md). Antes, reiniciar o app devolvia cada carteira do mercado real aos US$ 10.000 iniciais. Agora ela volta como estava.

## O que persiste

Só a carteira do **mercado real**. A demonstração continua efêmera e nunca toca no banco (testado).

| O quê | Onde (SQLite, mesmo banco das metas) |
|---|---|
| Saldos, custo médio, decisões (com a ordem: lado, quantidade, valor, taxa e **preço**), atividade do mês | `carteiras` (uma linha por agente, JSON) |
| Patrimônio observado, um ponto por minuto (o gráfico) | `carteira_pontos` |
| Último preço lido da Binance e a variação de 7 dias | `mercado_ultimo` |

Essas tabelas são **mutáveis**, ao contrário das metas: são o estado de trabalho da carteira, não evidência. Não têm os gatilhos de append-only.

## Fronteira entre os mundos

Dentro do app a carteira continua em `float` e hora local ingênua. No banco:

- valores são **texto decimal**: o `repr` do float, que volta idêntico bit a bit (testado com `0.1 + 0.2` e `1000/3`);
- instantes são **UTC com `Z`**.

A conversão fica em `ubento/carteira_serial.py`. A leitura valida tudo antes de tocar na carteira: versão do estado, números finitos e não negativos, ativos conhecidos, datas, status e lados. Estado inválido levanta `ErroDeEstado` e a carteira fica como estava. Migrar a carteira inteira para `Decimal` é a opção B do ADR e fica para depois.

## Quando grava e quando restaura

- **Ao abrir o app já no mercado real, ou ao ligar o modo:** cada agente recebe a carteira guardada **antes** de qualquer gravação. A carteira nova do início nunca vai para o banco por cima da guardada.
- **Ao mudar:** grava com um pequeno atraso (1 s) para juntar várias mudanças, e só se o estado da carteira mudou. Uma leitura de preço sozinha não regrava saldos.
- **Antes de ligar ou desligar o modo:** grava na hora, porque as carteiras em memória vão sair de cena.
- **Desligar o mercado real** guarda as carteiras; religar as devolve.
- **Último preço:** volta junto, para o patrimônio fazer sentido desde o primeiro quadro, mas como leitura **vencida**: agentes e swap continuam bloqueados até chegar um preço novo.

## Falhas

- **Estado ilegível ou JSON corrompido:** o app não cai, a carteira daquele agente começa nova, o dado guardado **não é sobrescrito** nesta sessão e a tela avisa. O dado fica no banco para análise.
- **Falha ao gravar** (disco cheio, banco ocupado): vira aviso uma vez; a carteira em memória segue intacta e a gravação é tentada de novo na próxima mudança.

## Agentes removidos

Remover um agente, ou voltar às abas padrão, **arquiva** a carteira dele (`arquivada_em`), nunca apaga. As **metas** do agente removido continuam no banco, no servidor MCP e no bot do Telegram; só a tela do app deixa de mostrá-las, porque não há mais aba.

## Limites

- A demonstração não persiste (de propósito).
- Os ids dos agentes vêm do `QSettings`. Se esse arquivo for apagado, as carteiras guardadas ficam sem dono e entram em nova carteira.
- O histórico guarda no máximo 20 mil pontos por agente em memória (cerca de 14 dias a um ponto por minuto); o banco acumula todos.
- Um estado de versão futura (`versao` ≠ 1) é tratado como ilegível, não migrado.
