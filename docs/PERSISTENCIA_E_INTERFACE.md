# Persistência e interface das metas (v0.1)

Liga o núcleo puro ao SQLite e à tela. Nada disto vive em `ubento.nucleo`: o núcleo continua sem sqlite, Qt, rede e relógio.

## 1. Camadas

| Camada | Onde | Papel |
| --- | --- | --- |
| Núcleo | `ubento.nucleo` | regras, conciliação, avaliação (puro, testado com Hypothesis e mutação) |
| Persistência | `ubento.persistencia.Repositorio` | SQLite append-only; grava e lê os modelos como JSON validado |
| Serviço | `ubento.metas.ServicoMetas` | orquestra: lê → concilia → avalia → grava; recebe `agora` como parâmetro |
| Interface | `ubento.ui.metas_page.MetasPage` | só exibe o `PainelMeta` e dispara ações; não decide nada |

## 2. Garantias do banco

- `metas`, `eventos`, `razao`, `avaliacoes` e `entradas` são **append-only**: gatilhos recusam `UPDATE` e `DELETE`. Só o `cursor` (posição de quem navega o cenário) é mutável e não é fato do domínio.
- O contrato ativo é imutável: reimportar a mesma meta com outro contrato falha (`ErroDeContrato`); na leitura o hash é conferido (banco adulterado é detectado).
- Eventos têm sequência contínua por meta (`UNIQUE(meta_id, sequencia)` e verificação em `gravar`); outra escrita concorrente produz `ErroDeSequencia`, nunca história torta.
- `gravar` é **uma transação**: eventos, razão e avaliação entram juntos ou não entram.
- Reprocessar não duplica: ids de eventos e do razão são determinísticos; reimportar o mesmo cenário cai nas mesmas chaves.
- Entradas (execuções, registros externos, coberturas…) guardam a **posição** além do conteúdo: dois itens idênticos no mesmo arquivo continuam sendo duas entradas (um feed duplicado é um fato que a conciliação precisa enxergar).
- Cada avaliação é um registro de auditoria: reavaliar o mesmo instante não gera eventos novos, mas acrescenta uma avaliação (as entradas de hash mudam porque a história cresceu).

## 3. Aprovar não é executar

| Ação na tela | Efeito |
| --- | --- |
| ✓ numa proposta | status `approved`; **não** muda saldos nem o progresso de meta alguma |
| ✕ | status `rejected` |
| “Registrar” numa decisão aprovada | pede confirmação; só então aplica a operação (saldos) e marca `executed` |

Pendências do agente (`pending_count`, ponto no header e chip “N pendentes”) incluem propostas **e** aprovadas sem execução registrada.

**Limite desta fase:** a execução registrada aqui é a do **demonstrativo de carteira** (`Store`). O registro de uma `Execucao` de **meta** existe no serviço (`ServicoMetas.registrar_execucao`) e é coberto por testes, mas ainda não há formulário na tela: no UI as metas são alimentadas por cenários simulados importados. O modo “automático” do agente de demonstração continua simulando a execução na hora; isso é demonstração, não o contrato.

## 4. Tela de Metas

Acesso: botão **Metas** na faixa do agente ou botão direito na aba → “Metas…”. Mostra, **separados**: progresso comprovado (e o que vale por prova anterior), completude da conciliação (pendências, órfãos relevantes/ignorados), custos verificados × sem evidência com orçamento mínimo–máximo, elegibilidade para concluir, e a linha do tempo de eventos. Ações: importar cenário (dado simulado, marcado como tal), avançar momento, reavaliar.

## 5. Onde fica o banco

`UBENTO_DB` se definido; senão `%LOCALAPPDATA%/UBento/ubento.db` (pasta de dados do usuário). Sem banco informado (testes, capturas) o serviço usa memória.

## 6. Ainda isolado

Monitor/agendamento e adaptadores de dados reais; formulário de execução de meta; conversão entre moedas; cancelamento de meta pela tela.
