# Avaliação de metas (D3): da execução ao estado da meta

Contrato do módulo `ubento.nucleo.avaliacao`. Fecha o fluxo que o documento de especificação exige comprovar
primeiro:

```
execuções internas ─┐
registros externos ─┼─► conciliação ─► razão de conciliação ─► progresso ─► avaliação ─► eventos da meta ─► estado
cobertura da consulta┘                                          ▲
dados de mercado (snapshot) ─► regras do contrato ──────────────┘
```

Nada aqui envia ordens, acessa corretoras ou lê o relógio do sistema: `agora` é sempre um parâmetro.
Aprovar uma proposta não entra neste fluxo: o avaliador só consome **execuções conciliadas** (ver §8).

## 1. Quatro coisas que nunca viram um número só

| Conceito | Pergunta | Campo |
| --- | --- | --- |
| **Quantidade líquida comprovada** | Quanto do que se comprou está confirmado por registro externo, dentro da janela da meta? | `quantidade_comprovada` |
| **Completude da conciliação** | Resta alguma pendência? Alguma pode *reduzir* o progresso? | `completude` (lista de `Pendencia`) |
| **Custos verificados** | O que dos custos foi conferido contra evidência externa e o que não? | `custos[].verificado` / `.nao_verificado`; `orcamento` |
| **Elegibilidade para concluir** | Pode-se declarar a meta atingida? | `elegibilidade` (verdadeiro / falso / indeterminado + motivos) |

Consequências, todas testadas:

- Uma pendência **não apaga** quantidade já comprovada (`quantidade_comprovada` não cai por haver compra pendente).
- Completude falsa **não impede** concluir se a pendência não pode reduzir o progresso nem violar um limite (compra extra pendente).
- Uma pendência que **pode reduzir** o progresso (estorno ainda não comprovado) torna a elegibilidade `indeterminado`: a conclusão é adiada.
- Um limite obrigatório (orçamento) que depende de custo sem evidência torna a elegibilidade `indeterminado`.

`elegibilidade = todos(quantidade, ausência de redutor pendente, orçamento)` na lógica de três valores: `falso` vence,
depois `indeterminado`.

## 2. Instante efetivo, evidência e janela

Três tempos diferentes, nunca confundidos:

| Tempo | O que é | Uso |
| --- | --- | --- |
| `executada_em` | Quando a execução **aconteceu** | Prazo, janela da meta, instante de conclusão, precedência entre eventos |
| `recebido_em` / `consultada_em` | Quando a evidência **chegou** ao sistema | Visibilidade (“o que se sabia em `agora`”), cobertura da consulta, `registrado_em` do evento |
| `agora` | Instante da avaliação | Carência, idade, validade do dado de mercado |

- **Janela da meta:** uma compra só conta se `ativada_em ≤ executada_em ≤ prazo` (inclusive). Fora da janela, a quantidade aparece em `quantidade_fora_da_janela` e não conta. Um **estorno** conta se a compra que ele desfaz conta, mesmo que ele próprio ocorra depois do prazo.
- **Instante de conclusão:** o da execução que fez a quantidade passar a valer de forma sustentada (última vez que cruzou o alvo), nunca o da chegada da evidência. O evento `atingida` carrega `horario_evidencia = executada_em` e `registrado_em = agora`.

### 2.1 Idade da execução × validade da evidência × cobertura da consulta

| Conceito | Responde | Efeito |
| --- | --- | --- |
| **Idade da execução** (`agora − confirmada_em`) | O registro externo *já deveria existir*? | Dentro de `janela_atraso_segundos`: `pendente`. Depois: precisa de cobertura para concluir algo |
| **Cobertura da consulta** (`CoberturaExecucoes`) | A consulta teria *visto* o registro? | Só uma consulta que cobria fonte, ativo, o período da execução (± tolerância) e foi feita depois de a fonte ter tido tempo de publicar **prova a ausência** (`sem_registro_externo`). Sem isso: `nao_verificavel` |
| **Validade do dado** (`validade_maxima_segundos`) | O dado *de mercado* ainda vale? | Só para regras (preço, retorno…). **Execução conciliada não vence**: a das 10h01 não fica inválida às 12h |

Ausência em recorte incompleto não prova ausência de execução.

### 2.2 Prova anterior é preservada

O avaliador mantém um **razão de conciliação** (`EventoConciliacao`). O progresso vigente de cada execução é o que o razão já
aplicou, ajustado só por evidência nova:

| Resultado da conciliação agora | Efeito no razão |
| --- | --- |
| `conciliada` | Soma (ou ajusta) o efeito |
| `divergente`, `revisao`, `sem_registro_externo` (**ausência provada**) | **Contradição positiva**: reverte com evento compensatório |
| `pendente`, `nao_verificavel`, ou execução fora do relatório | **Falta de verificação**: nada é revertido; a prova anterior vale e a execução fica `preservada` (completude falsa, `evidencia_preservada_sem_reverificacao`) |

Assim, uma janela de consulta que não traz um registro antigo nunca apaga histórico válido.

## 3. Escopo dos registros externos sem dono (órfãos)

Um registro externo que nenhuma execução interna referencia **só bloqueia as metas que ele pode afetar**. Critérios, em
ordem; o primeiro que exclui encerra a análise (`avaliar_escopo_orfao`):

| # | Critério | Exclui quando | Motivo |
| --- | --- | --- | --- |
| 1 | Ativo | difere do ativo do objetivo | `ativo_diferente` |
| 2 | Mercado | difere de `mercado.mercado_id` do contrato | `mercado_diferente` |
| 3 | Moeda de cotação | difere da do objetivo | `moeda_cotacao_diferente` |
| 4 | Origem | a origem do registro não está entre as origens dos dados da meta (dado simulado não bloqueia meta com dado observado, e vice-versa) | `origem_diferente` |
| 5 | **Conta** | difere da conta do contrato. **Conta desconhecida** (no registro ou no contrato) **não exclui**: é conservador e sinalizado | `conta_diferente` / `conta_indeterminada` |
| 6 | Lado e vínculo | **estorno** só importa se aponta para um registro que a meta usa; uma **compra** segue adiante | `estorno_de_outra_compra` |
| 7 | Período | **compra** executada fora de `[ativada_em, prazo]` | `fora_do_periodo` |
| — | (nenhum excluiu) | — | `compra_possivelmente_da_meta` / `estorno_de_registro_da_meta` |

Efeito de um órfão **relevante**:

- **Estorno da meta**: pendência que **pode reduzir** o progresso → elegibilidade `indeterminado`.
- **Compra possivelmente da meta**: não reduz progresso; entra no **pior caso do orçamento** (e conta como evidência potencial para a carência).
- **Irrelevante**: aparece em `orfaos` com o motivo da exclusão, mas não gera pendência nem bloqueia nada.

O contrato ganhou `mercado.conta_id` (opcional). O campo `conta_id` do registro externo identifica a conta na fonte.

## 4. Orçamento: limite obrigatório com pior caso explícito

Na moeda do orçamento (`recursos.moeda_orcamento_id`):

- **gasto mínimo** = só o comprovado: valor pago e taxa na cotação das execuções conciliadas (líquidos de estornos comprovados) + o que o razão já tinha provado;
- **gasto máximo** = mínimo + **custo fixo** (`custo_fixo_real` nunca tem evidência externa) + tudo o que ainda não foi conciliado + compras órfãs relevantes.

| Resultado | Quando |
| --- | --- |
| `falso` | o gasto **mínimo** já excede o orçamento (excesso comprovado) |
| `verdadeiro` | o gasto **máximo** cabe no orçamento |
| `indeterminado` | caso contrário (a diferença é custo sem evidência), ou moeda incompatível ou desconhecida |

`custo_fixo_real` **não** é apresentado como verificado: aparece em `custos[].nao_verificado`. A exposição máxima
(`recursos.exposicao_maxima`) **não** é avaliada nesta fase (exige valoração da carteira).

## 5. Estado, carência e expiração

O contrato é imutável (o avaliador recusa um contrato cujo hash difere do ativado). O **estado é função da evidência**; os
eventos são a diferença entre o estado já registrado e o que a evidência mostra agora.

Candidatos a estado final, cada um com o instante da **evidência**:

| Candidato | Condição | Instante |
| --- | --- | --- |
| `atingida` | elegibilidade `verdadeiro` | `executada_em` da execução que fechou a meta |
| `invalidada` | alguma condição de invalidação observada (ou já registrada na história) | `observado_em` do dado; **uma invalidação já ocorrida é fato histórico e não some se o preço voltar** |
| `expirada` | `agora > prazo` e não há evidência que ainda possa fechar a meta | `prazo` (`prazo_encerrado`) |
| `expirada` | `agora > prazo + carência` e ainda havia evidência pendente | `prazo + carência` (`prazo_sem_evidencia`) |

- **Precedência (D2):** vale o menor instante de evidência; empate exato pela `ordem_empate` congelada no contrato.
- **Carência (D3):** só **para receber evidência**. Durante ela a meta fica `ativa` com `aguardando_evidencia`, **sem novas entradas**, e só execuções ocorridas até o prazo original contam. Só há carência se existe evidência que ainda poderia fechar a meta (quantidade pendente ou órfã que, somada à comprovada, atinge o alvo, ou elegibilidade indeterminada); senão a meta expira de imediato.
- **Regras do contrato:** `bloqueios` e `entrada` valem com `todos`; `invalidacao` vale com `algum`. Dado ausente, vencido, de qualidade ruim, unidade incompatível ou fontes divergentes dá `indeterminado`: a meta continua `ativa`, marcada `bloqueada_por_dados` (condição, não estado), e **nenhuma entrada é sinalizada**. Alerta de entrada: só em meta ativa, dentro do prazo, sem bloqueio, com limite de orçamento não violado; idempotente por (meta, regras, snapshot).

## 6. Correção posterior: o evento `reconciliada`

Se a evidência muda o resultado de uma meta já em `atingida`, `expirada` ou `invalidada` (estorno depois da conclusão,
correção ou cancelamento externo, evidência tardia, uma execução anterior à invalidação):

1. o evento anterior **permanece na história**;
2. é emitido `reconciliada` (autor `sistema:avaliador`, motivo textual, `dados.estado_anterior` e `dados.estado_resultante`);
3. o estado é **recalculado** pela mesma função de evidência (reabre para `ativa` se ainda há prazo, vira `expirada` se o prazo passou, volta a `atingida` se a evidência tardia comprova).

Regras de política:

- **Pendência não reabre.** Uma meta `atingida` com um estorno apenas *pendente* (indeterminado) é **mantida**; só uma redução comprovada, ou um limite comprovadamente violado, a reabre.
- `cancelada` é ato humano e **nunca** é recalculada.
- Eventos nascem depois de `atingida` (nova compra, por exemplo) só no razão de conciliação, não na história da meta.

## 7. Idempotência

- Todo evento tem `id` determinístico (meta, tipo, chave de conteúdo). O que já está na história não é recriado.
- A diferença contra o razão e contra o estado registrado é zero quando nada mudou: **reavaliar nunca gera evento**. Cada cenário de reprodução reprocessa o mesmo momento e exige zero eventos novos.
- Entradas duplicadas (execução ou registro externo) e a ordem das listas não alteram o resultado (propriedades testadas).

## 8. Proposta não é execução

O avaliador não tem canal de entrada para propostas, aprovações ou alertas como progresso. O progresso vem exclusivamente de
`RelatorioConciliacao` (execuções internas comprovadas por registro externo). `alerta_emitido` na história não soma nada.

## 9. Caminhos integrados × componentes isolados

| Caminho | Situação |
| --- | --- |
| execução → conciliação → razão → progresso → avaliação → eventos → estado | **Integrado e testado ponta a ponta** (`executar_meta`, 29 cenários) |
| Regras do contrato (bloqueio, invalidação, entrada) sobre observações | **Integrado** (motor mínimo; sem catálogo de métricas) |
| Conciliação de **saldos** | Componente **isolado**: roda dentro do relatório, mas não alimenta o avaliador (e não deve) |
| Persistência (SQLite) do razão, eventos e avaliações | **Não existe**: tudo é passado por parâmetro |
| Monitor / agendamento / adaptadores de dados | **Não existem** (a fonte é o arquivo de reprodução) |
| Interface do UBento | **Não conectada**: nenhuma tela usa o núcleo; os botões ✓/✕ ainda executam ao aprovar (contradiz §8 e a especificação §2) |
| Cancelamento da meta, viabilidade, análise publicada | Fora desta fase |
| Métricas (retorno, spread, volatilidade…) e exposição conjunta | Fora desta fase |

## 10. Limitações conhecidas

- `ordem_empate` e a política de reabertura vêm do contrato/versão do motor (`motor-0.3.0`); mudar uma delas muda resultados, e por isso entram em `versao_algoritmo`.
- A conta do órfão depende de a fonte informá-la; sem isso o critério é conservador (bloqueia e sinaliza).
- O pior caso de gasto de compras órfãs usa o preço e as taxas do próprio registro; não há conversão entre moedas (moeda diferente ⇒ indeterminado).
- Cobertura da consulta é declarada pela fonte; o sistema não a infere.
