# Núcleo de metas: decisões e contrato (v0.2)

Complementa `analise-e-meta-especificacao.md` v0.1 e substitui as propostas da seção 3 de
`ANALISE_META_MOTOR.md` onde houver diferença. Este é o contrato que o código em
`src/ubento/nucleo` implementa; se código e texto divergirem, corrija um dos dois no mesmo commit.

Status: decisões fechadas em 18/10/2026. Itens marcados **(a confirmar)** mantêm a proposta da
análise e serão revistos na fase indicada.

## 1. Decisões

| # | Tema | Decisão |
| --- | --- | --- |
| D1 | **Progresso** | O objetivo da v1 é *acumular por aquisições*, não *manter um saldo*. O progresso é a soma das **execuções confirmadas vinculadas à meta**, em **quantidade líquida recebida** (descontadas taxas cobradas no próprio ativo). Depósitos e transferências externas não contam. Estorno gera execução compensatória (`estorno_compra`), nunca edição da execução original. Encerrar a meta não liquida a posição |
| D2 | **Empates** | Primeiro vale a **ordem efetiva** dos eventos (horário da evidência e, depois, sequência). Só quando não houver ordem mais precisa se aplica a prioridade `atingida → invalidada → expirada → entrada`. **"Atingida" exige execução comprovada**, nunca cotação ou sinal |
| D3 | **Prazo sem dados** | O contrato traz `carencia_dados`. A carência serve **apenas para receber evidências**: não estende o prazo de compras. Nela, nenhuma entrada é emitida e só comprovam o objetivo execuções ocorridas **até o prazo original**. Encerrada a carência sem evidência válida: `expirada` com motivo `prazo_sem_evidencia`. Reconciliação posterior é registrada como evento, sem reescrever o histórico |
| D4 | **Fontes divergentes** | Sem limite universal. A tolerância é declarada **por métrica, mercado e diferença máxima de horário**. Preço da última negociação, preço médio e cotação executável são **métricas distintas** e não são comparadas entre si. Excedida a tolerância, o dado é `divergente` e **bloqueia** quem o usa como obrigatório; nunca há média silenciosa |
| D5 | **Tipos de objetivo** | Somente `acumular_quantidade` na v1 |

### Decisões D12 a D17 (integração da conciliação ao avaliador; detalhes em `AVALIACAO_META.md`)

| # | Tema | Decisão |
| --- | --- | --- |
| D12 | **Escopo dos órfãos** | Um registro externo sem execução interna só bloqueia metas que ele pode afetar: ativo, mercado, moeda, origem, **conta**, vínculo (estorno só importa se aponta para registro da meta) e período `[ativação, prazo]`. Conta desconhecida não exclui (conservador, sinalizado). O contrato ganha `mercado.conta_id` (opcional) |
| D13 | **Quatro grandezas separadas** | Quantidade líquida comprovada, completude da conciliação, custos verificados e elegibilidade para concluir. Pendência nunca apaga progresso comprovado; só pendência que pode **reduzi-lo** (estorno) ou comprometer limite obrigatório impede concluir (`indeterminado`) |
| D14 | **Idade ≠ validade ≠ cobertura** | Execução conciliada não vence. A ausência de um registro só prova inexistência com **cobertura da consulta**; sem ela é `nao_verificavel` e a **prova anterior é preservada** no razão. Só contradição positiva reverte |
| D15 | **Custos sem evidência** | `custo_fixo_real` nunca é apresentado como verificado. O orçamento é avaliado com gasto mínimo (comprovado) e máximo (pior caso): `falso` se o mínimo estoura, `verdadeiro` se o máximo cabe, `indeterminado` no meio. Isso torna a **elegibilidade** indeterminada |
| D16 | **Reconciliação** | Correção posterior (estorno, cancelamento ou correção externa, evidência tardia) produz o evento `reconciliada`, **preserva** a conclusão anterior na história e recalcula o estado pela mesma função de evidência. Pendência (mera possibilidade) não reabre meta atingida. `cancelada` nunca é recalculada |
| D17 | **Invalidação e regras** | Uma invalidação já observada é fato histórico (não some se o preço voltar). `bloqueios` e `entrada` valem com `todos`; `invalidacao` com `algum`. Prazo e carência usam o instante **efetivo** da execução (`executada_em`), distinto do da chegada da evidência |

Mantidas como propostas, **(a confirmar)**: D8 condição `bloqueada_por_dados` separada do estado (fase 4);
D9 razão de reservas com invariante transacional (fase 3); D10 validade do dado no catálogo de métricas, que a
meta só pode apertar (fase 2); D11 `AprovacaoHumana` vinculada ao hash da análise (fase 3).

## 2. Proposta, aprovação e execução são coisas diferentes

| Conceito | O que é | Altera progresso? |
| --- | --- | --- |
| Alerta / proposta | O motor diz que uma regra de entrada foi satisfeita | Não |
| Aprovação (✓) | Um humano autoriza o que foi proposto | **Não** |
| Recusa (✕) | Um humano rejeita | Não |
| Execução | Registro **separado** de uma operação confirmada (quantidades, taxas e custos reais) | **Sim** |

Aprovar não registra compra nem aumenta o progresso. Somente uma `Execucao` confirmada faz isso.

> Nota: os botões ✓/✕ seguem esta seção desde a integração com a interface: ✓ só marca `approved`; a execução é
> registrada à parte, com confirmação (`PERSISTENCIA_E_INTERFACE.md` §3).

## 3. Correções técnicas

### 3.1 Hash do contrato

`Decimal` não basta para hash estável. A serialização canônica (`ubento.contrato.v1`) é:

1. Entrada: o **modelo validado** já completo (todos os campos, inclusive os de valor padrão), nunca o texto original.
2. Objetos: chaves ordenadas; nenhuma chave duplicada.
3. `Decimal`: texto decimal sem expoente e sem zeros desnecessários; `"1.0"`, `"1.00"` e `"1"` viram `"1"`; `-0` vira `"0"`.
4. Datas e horas: UTC, `YYYY-MM-DDTHH:MM:SSZ`, com microssegundos só se diferentes de zero. Datas sem fuso são rejeitadas antes de chegar aqui.
5. Ausência: `null` explícito. Campo opcional omitido e `null` são o mesmo valor depois da validação.
6. Texto: normalização Unicode NFC.
7. Listas mantêm a ordem; listas que são conjuntos (ex.: ativos permitidos) são ordenadas **na validação**, não no hash.
8. `float` é erro em qualquer ponto; booleanos e inteiros mantêm o tipo.
9. Conteúdo do hash do contrato: **apenas os termos congelados** (identidade, origem, objetivo, recursos, regras, políticas, reprodutibilidade). **Fora do hash:** estado, progresso, avaliações, alertas, execuções, horário e responsável da ativação (ficam em `Ativacao`, que referencia o hash).
10. Resultado: `sha256(b"ubento.contrato.v1\n" + json_canonico_utf8)` em hexadecimal.

### 3.2 Arredondamento depende da restrição

Não existe regra global. Cada grandeza usa a direção que preserva a restrição:

| Grandeza | Direção | Motivo |
| --- | --- | --- |
| Preço máximo de compra | para baixo | não exceder o orçamento |
| Quantidade máxima comprável | para baixo, no incremento do mercado | não exceder o orçamento |
| Quantidade mínima para atingir o alvo | para **cima**, no incremento permitido; depois **revalidar o orçamento** | o alvo exige no mínimo isso |
| Custo / orçamento necessário | para cima, na menor unidade da moeda | não subestimar |
| Valores exibidos | modo de exibição apenas | nunca entram em decisão |

O núcleo oferece `arredondar_para_baixo` e `arredondar_para_cima` (múltiplos exatos de um passo, em `Decimal`)
e cada fórmula escolhe explicitamente.

## 4. Stack e convenções

| Item | Escolha |
| --- | --- |
| Local | `src/ubento/nucleo`, sem importar Qt, rede nem relógio do sistema; a interface consome resultados |
| Nomes | Português sem acentos no domínio (`Meta`, `Analise`, `orcamento`), consistente com o contrato YAML/JSON |
| Validação | Pydantic v2, `extra="forbid"`, imutável |
| YAML | `ruamel.yaml` em modo seguro; chave duplicada é erro; números fracionários sem aspas são erro |
| Testes | `pytest` + `hypothesis` (dependência de desenvolvimento) |
| Persistência | SQLite como adaptador, fora das funções puras (`ubento.persistencia`, ver `PERSISTENCIA_E_INTERFACE.md`) |
| Dados da v1 | Arquivos de reprodução, com origem, horários e marca explícita de **dado simulado** |
| Python | 3.11 ou superior |

## 5. Fora do escopo desta fase

Catálogo completo de métricas (só o mínimo de regras necessário ao D3 existe), viabilidade, reservas, persistência, monitor e
interface. A fase 1 entregou tipos, esquema, carregamento seguro e hash canônico; a conciliação e o avaliador (D3) estão em
`ubento.nucleo.conciliacao` e `ubento.nucleo.avaliacao`.
