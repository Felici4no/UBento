# Agendador dos agentes

Passo 6 do [ADR-001](ADR-001-REVISAO-DE-ARQUITETURA.md). Antes, a tela do agente mostrava "próxima execução" e a frequência (hora, dia, semana) era configurável, mas **nada rodava sozinho**: só o botão "Rodar agora". Agora roda.

## O que faz

Enquanto o UBento estiver aberto, a cada 30 s o agendador confere cada agente e roda os que venceram, pelo mesmo caminho do botão (`Workspace.run_agent`): o agente decide, e o modo dele manda (executar, pedir aprovação ou só sugerir). A tela mostra um aviso do tipo "Pessoal: 2 propostas aguardando você".

| Frequência | Vence |
|---|---|
| A cada hora | na virada da hora seguinte à última execução |
| Diária | às 9h do dia seguinte (ou do mesmo dia, se a última execução foi antes das 9h) |
| Semanal | na segunda-feira, às 9h |

## Regras

- **Referência.** O horário que vence é o seguinte ao `last_run` (guardado na configuração do agente, então sobrevive a reiniciar). Quem nunca rodou usa o instante em que o agendador nasceu: o 9h que passou antes de o app abrir não conta.
- **Horários perdidos.** Com o app fechado por dias, ao abrir roda **uma** vez, não uma rajada.
- **Atraso inicial de 10 s.** Dá tempo de a primeira leitura de preços chegar antes de qualquer operação.
- **Mercado real sem preço fresco.** O `run_agent` recusa ("Aguardando os preços ao vivo da Binance"); o agendador não marca como executado, tenta no próximo ciclo e não faz barulho. Chegando o preço, roda uma vez.
- **Não roda:** agente pausado, agente manual, ou agendador desligado em **Configurações → Agentes → Rodar os agentes sozinhos** (ligado por padrão). Religado, o que estava vencido roda.
- **Falha de um agente** vira aviso (uma vez, não a cada ciclo) e não impede os outros.
- O relógio é o `agora` do `Mercado` do Workspace, o mesmo de todo o domínio, então os testes não esperam tempo de verdade.

## O que a tela diz

Na configuração do agente: "próxima: amanhã, 09:00 · roda só com o app aberto"; "vencida, roda em instantes" quando já passou da hora; e, com o agendador desligado, "execução automática desligada em Configurações".

## Limites

- **Só com o app aberto.** Não há serviço em segundo plano nem tarefa do sistema operacional. Fechou o app, não roda.
- Os horários (9h, segunda-feira) são fixos: não há escolha de hora na tela.
- A hora é a local do computador.
- O modo **automático** de um agente executa as decisões sem pedir nada, como já fazia ao clicar em "Rodar agora". As ordens continuam simuladas: nada é enviado a corretora alguma.
