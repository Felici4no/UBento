# Conciliação de execuções (núcleo)

Contrato do módulo `ubento.nucleo.conciliacao`. Complementa `ESPECIFICACAO_NUCLEO.md` (decisões D1–D5 e §2: proposta,
aprovação e execução são coisas diferentes). Não é um sistema contábil: não há razão geral, partidas dobradas nem
fechamento de período. O módulo responde só a uma pergunta por meta: **quanto do que foi registrado como comprado está
comprovado por registros externos?**

## 1. Duas conciliações que não se misturam

| | Conciliação de **execuções** | Conciliação de **saldos** |
| --- | --- | --- |
| Compara | Execução interna × registro(s) externo(s) de execução e taxas | Variação de saldo observado × movimentações |
| Pergunta | O que registramos foi mesmo executado, com estas quantidades e taxas? | A variação do saldo tem explicação nas movimentações conhecidas? |
| Altera o progresso da meta? | **Sim**: só execuções `conciliada` comprovam | **Nunca** |
| Diferença significa | Divergência a investigar naquela execução | Saldo não explicado; pode ser depósito, retirada, transferência ou ajuste não informado |

Uma diferença de saldo **não prova** erro de execução, e uma execução conciliada **não prova** que o saldo bate.
Os resultados aparecem lado a lado no relatório, sem causalidade entre eles.

## 2. Contrato de dados

Todos os modelos são imutáveis, estritos (`extra="forbid"`), com `Decimal` a partir de texto e datas com fuso (UTC).
Todo registro guarda `fonte_id`, `origem` (`observado` ou `simulado`) e `recebido_em`. **Nada é editado**: uma correção
é um novo registro.

| Modelo | Papel | Campos principais |
| --- | --- | --- |
| `Execucao` (existente, estendida) | Registro **interno** de uma compra ou estorno, vinculado a **uma** meta | `id`, `meta_id`, `ativo_id`, `lado`, `quantidade_bruta`, `taxa_no_ativo`, `quantidade_liquida`, `preco_executado`, `taxa_na_cotacao`, `custo_fixo_real`, `moeda_cotacao_id`, `taxas_outros_ativos`, `executada_em`, `confirmada_em`, `referencias_externas`, `estorna_execucao_id` |
| `ReferenciaExterna` | Elo **explícito** interno→externo | `fonte_id`, `id_externo`, `quantidade_bruta_alocada` (vazio = registro inteiro) |
| `RegistroExterno` | Execução reportada pela fonte (uma linha por versão) | `fonte_id`, `id_externo`, `versao`, `id_ordem`, `mercado_id`, `ativo_id`, `moeda_cotacao_id`, `lado`, `quantidade`, `preco`, `taxas[]`, `status`, `executado_em`, `recebido_em`, `estorna_id_externo` |
| `VinculoManual` | Decisão **humana** que resolve uma correspondência incerta | `execucao_id`, `fonte_id`, `id_externo`, `autor`, `justificativa`, `em` |
| `Movimentacao` | Movimento de saldo informado pela fonte | `fonte_id`, `id_externo`, `ativo_id`, `tipo`, `quantidade` (com sinal), `em`, `recebido_em`, `referencia_execucao_externa` |
| `SaldoObservado` | Saldo em um instante | `fonte_id`, `ativo_id`, `quantidade`, `observado_em`, `recebido_em` |
| `Cobertura` | Intervalo em que a fonte garante ter informado **todas** as movimentações de um ativo | `fonte_id`, `ativo_id`, `inicio`, `fim` |
| `PoliticaConciliacao` | Parâmetros explícitos (seção 7) | janelas e tolerâncias |

`status` do registro externo: `confirmado`, `pendente` ou `cancelado`. `tipo` de movimentação: `execucao`, `taxa`,
`deposito`, `retirada`, `transferencia_entrada`, `transferencia_saida`, `ajuste`.

Taxas do registro externo são uma lista `(ativo_id, valor)` e são classificadas em relação à execução:

| Taxa em… | Tratamento | Efeito |
| --- | --- | --- |
| o **ativo recebido** | `taxa_no_ativo` | **Reduz** a quantidade líquida (e o progresso) |
| a **moeda de cotação** | `taxa_na_cotacao` | Custo na moeda de cotação; não mexe na quantidade |
| **outro** ativo (ex.: token de desconto) | `taxas_outros_ativos` | Custo naquele ativo; **nunca** subtrai unidades de ativo diferente e **nunca** é convertida |

## 3. Regras de correspondência

Ordem de aplicação, para cada execução interna:

1. **Higiene dos registros internos.** Mesmo `id` com conteúdo idêntico: um só registro (duplicata inócua, anotada). Mesmo `id` com conteúdo diferente: todos os registros daquele `id` ficam fora do cálculo e viram `revisao`.
2. **Visibilidade temporal.** Só entra o que tem `recebido_em <= agora`. Reprocessar "como estava" em um instante passado reproduz o resultado daquele instante.
3. **Versões externas.** Registros com a mesma chave `(fonte_id, id_externo)` formam uma história. Vale a maior `versao`. Duas versões iguais com conteúdo idêntico são uma só; com conteúdo diferente, a chave é **conflitante** e quem a usa vai para `revisao`.
4. **Identificador estável.** A correspondência é feita **somente** por `referencias_externas` (ou `VinculoManual`). Preço, horário e quantidade **nunca** criam um elo.
5. **Sem referência.** A execução vai para `revisao` (`sem_identificador_externo`). O módulo pode listar **candidatos** (mesmo ativo e lado, quantidade e horário dentro da política) apenas como sugestão para a pessoa; eles não viram elo e não contam.
6. **Referência sem registro.** Dentro de `janela_atraso_segundos` após `confirmada_em`: `pendente` (dado pode estar atrasado). Depois disso: `sem_registro_externo`.
7. **Estado do registro.** `pendente` → `pendente`. `cancelado` → `divergente` (`cancelado_externamente`); a execução só deixa de contar se houver estorno interno conciliado.
8. **Alocação.** Para cada registro externo, a soma das quantidades alocadas por **todas** as execuções (de qualquer meta) não pode exceder a quantidade do registro. Excedeu: todas as execuções envolvidas vão para `revisao`. Usar o registro **inteiro** em duas execuções é o caso extremo e recebe o motivo específico `registro_externo_em_metas_diferentes` quando as metas diferem.
9. **Comparação de campos** (seção 4) → `conciliada` ou `divergente`.
10. **Estornos.** O estorno interno corresponde a um registro externo de `lado = estorno_compra`; esse registro deve apontar (`estorna_id_externo`) para um registro que a execução original referencia. O estorno só **vale** se a original estiver `conciliada`, for da mesma meta e a soma dos estornos não exceder a quantidade líquida dela; caso contrário, `revisao`.

## 4. Comparações

Todas exatas, em racionais (`Fraction`), sem arredondar para comparar. Tolerância só existe se a política a declarar.

| Campo | Regra |
| --- | --- |
| Ativo, lado, moeda de cotação | Iguais |
| Quantidade bruta | `Σ alocada` dos registros = `quantidade_bruta` interna (± tolerância por ativo) |
| Taxa no ativo recebido | `Σ taxa × alocada ÷ quantidade do registro` = `taxa_no_ativo` (alocação **proporcional**) |
| Quantidade líquida | `bruta − taxa no ativo` externa = `quantidade_liquida` interna |
| Preço | Média ponderada por quantidade dos registros = `preco_executado` (± tolerância relativa) |
| Taxa na cotação | Proporcional; igual a `taxa_na_cotacao` |
| Taxas em outros ativos | Mesmo conjunto de ativos e valores de `taxas_outros_ativos` |
| Horário | `|executado_em − executada_em| ≤ tolerancia_horario_segundos` |

Cada diferença gera um item `(campo, valor interno, valor externo)` e um motivo.

## 5. Resultados e motivos

### 5.1 Por execução

| Resultado | Significado | Conta no progresso? |
| --- | --- | --- |
| `conciliada` | Todos os registros existem, são únicos, confirmados e coincidem em todos os campos | **Sim** |
| `divergente` | Há correspondência por ID, mas algum campo difere ou o registro foi cancelado | Não |
| `pendente` | Falta registro ou ele ainda está `pendente`, dentro da janela de atraso | Não |
| `sem_registro_externo` | Referência sem registro depois da janela de atraso | Não |
| `revisao` | Correspondência ambígua, conflitante ou sem identificador; exige decisão humana | Não |

Motivos (códigos estáveis): `aguardando_registro_externo`, `registro_externo_pendente`, `registro_externo_nao_encontrado`,
`sem_identificador_externo`, `versao_externa_conflitante`, `id_interno_duplicado_conteudo_diferente`,
`registro_externo_em_varias_execucoes`, `registro_externo_em_metas_diferentes`, `alocacao_excede_registro_externo`,
`cancelado_externamente`, `ativo_diferente`, `lado_diferente`, `moeda_cotacao_diferente`, `quantidade_bruta_diferente`,
`taxa_no_ativo_diferente`, `quantidade_liquida_diferente`, `preco_diferente`, `taxa_na_cotacao_diferente`,
`taxa_outro_ativo_nao_registrada`, `taxa_outro_ativo_diferente`, `horario_fora_da_tolerancia`,
`estorno_sem_original`, `estorno_de_outra_meta`, `estorno_de_original_nao_conciliada`, `estorno_excede_original`,
`estorno_externo_aponta_para_outra_execucao`. Informativo (não bloqueia): `corrigido_externamente`, `duplicata_identica`.

### 5.2 Registro externo sem execução interna

`orfao`: execução da fonte que ninguém referencia. **Nunca** vira progresso sozinha; pode ser uma compra não registrada e
por padrão impede a confirmação (seção 6).

### 5.3 Por ativo e intervalo (saldos)

| Resultado | Significado |
| --- | --- |
| `explicada` | `saldo final − saldo inicial` = soma das movimentações do intervalo |
| `nao_explicada` | Sobra um resíduo; vira item de revisão, sem tocar nas execuções |
| `dados_insuficientes` | Falta saldo inicial/final ou a cobertura de movimentações não abrange o intervalo; **não** se afirma que há ou não resíduo |

Também são listadas as inconsistências entre execuções conciliadas e movimentações do tipo `execucao`/`taxa` (ausentes ou
de valor diferente), como informação para revisão.

## 6. Progresso e confirmação

Por meta, no relatório:

- `comprovado`: Σ da quantidade líquida das execuções `conciliada` (compra soma, estorno válido subtrai). **É o único valor que pode atingir o alvo.**
- `declarado`: Σ do que está registrado internamente (informativo).
- `nao_comprovado`: `declarado − comprovado`, com a contagem por resultado.
- `custos`: por ativo, sem conversão entre ativos, só das execuções conciliadas.
- `taxas_no_ativo`: total já descontado da quantidade.
- `confirmacao` (também no relatório geral) fala **só de execuções**; saldos têm resultado próprio e não a alteram. Vale `confirmada` **somente** se todas as execuções da meta estão `conciliada` e (por padrão) não há órfão do mesmo ativo; senão `incompleta`, com a lista de pendências. **Conciliação incompleta nunca é apresentada como confirmada.**

O corte do prazo (D3) pertence ao avaliador: cada resultado traz `executada_em` para que ele considere só o que ocorreu até
o prazo original.

## 7. Política (explícita, sem padrão universal)

| Parâmetro | Função |
| --- | --- |
| `janela_atraso_segundos` | Quanto esperar um registro externo antes de `sem_registro_externo` |
| `tolerancia_horario_segundos` | Diferença de horário aceita entre execução e registro |
| `janela_candidatos_segundos` | Raio de tempo para **sugerir** candidatos (nunca vincula) |
| `tolerancia_preco_relativa` | Fração; 0 exige igualdade exata |
| `tolerancias_quantidade` / `tolerancia_quantidade_padrao` | Folga absoluta por ativo (arredondamento da fonte) |
| `tolerancia_saldo` | Folga absoluta para considerar um saldo explicado |
| `orfaos_bloqueiam_confirmacao` | Se um registro externo sem dono impede `confirmada` |

## 8. Idempotência, correções e atrasos

- O relatório é **função pura** de `(registros, política, agora)`; `hash_entradas` e `hash_saida` permitem verificar a reprodução. Executar de novo com os mesmos dados dá exatamente o mesmo resultado; o progresso nunca é somado a um valor anterior, é **recalculado do conjunto**, e o conjunto é indexado por `id`.
- Dados atrasados mudam o resultado na próxima execução (`pendente` → `conciliada`). Nada é reescrito: o histórico fica nos relatórios anteriores.
- `diferenciar(anterior, atual)` produz **eventos compensatórios** com `delta_progresso` e identificador determinístico: `execucao_conciliada` (+), `conciliacao_revertida` (−, quando uma correção externa ou um cancelamento invalida o que estava comprovado), `divergencia_aberta`, `divergencia_encerrada`, `revisao_aberta`, `revisao_encerrada`, `orfao_detectado`. Aplicar o mesmo evento duas vezes é inofensivo (mesmo identificador). A soma dos `delta_progresso` de uma sequência de relatórios é igual ao `comprovado` final (propriedade testada).
- Estorno e correção **nunca editam** o registro original: o estorno é uma execução própria, conciliada como qualquer outra.

## 9. Fora do escopo e limitações

- `custo_fixo_real` é um dado **interno**: os registros externos não o trazem, então a conciliação não o verifica; ele só entra nos custos das execuções já conciliadas, e esse limite deve ser lembrado ao apresentar o custo como "confirmado".
- Custos de uma execução estornada não são devolvidos automaticamente: o estorno é uma execução própria e traz as suas taxas, se houver.
- Sem corretoras reais, sem ordens, sem conversão cambial, sem valoração de custos em uma moeda única.
- Sem lançamentos contábeis, sem partidas dobradas, sem fechamento de período.
- Taxas são comparadas por ativo; uma taxa em ativo sem cotação não é "somada" a nada.
- Alocação proporcional da taxa assume que a taxa do registro é distribuída pela quantidade; fontes que cobram taxa mínima por registro podem exigir `VinculoManual` ou tolerância.
- O fuso e o relógio entram sempre como parâmetro (`agora`); este módulo nunca lê o horário do sistema.
- Candidatos sugeridos são heurísticos e só servem para orientar uma pessoa.
