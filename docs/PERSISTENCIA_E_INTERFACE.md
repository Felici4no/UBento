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

**Duas coisas diferentes com o mesmo verbo.** Na carteira de demonstração (`Store`), “Registrar” aplica a operação aprovada aos saldos. Numa **meta**, “Registrar execução…” (formulário, §4) cria uma `Execucao` *registrada*: confirmação interna, **sem valor de prova**. O modo “automático” do agente de demonstração continua simulando a execução na hora; isso é demonstração, não o contrato.

## 4. Tela de Metas

Acesso: botão **Metas** na faixa do agente ou botão direito na aba → “Metas…”. Mostra, **separados**: progresso comprovado (e o que vale por prova anterior), **quantidade registrada pendente de comprovação**, completude da conciliação (pendências, órfãos), execuções registradas com sua situação, custos verificados × sem evidência com orçamento mínimo–máximo, elegibilidade para concluir e a linha do tempo. Ações: importar cenário (dado simulado, marcado como tal), avançar momento, reavaliar, **registrar execução** e **importar evidência**.

### Registrar execução → comprovar
1. **Formulário.** Ativo e moeda de cotação vêm da meta (somente leitura), com unidade em cada campo; horários em UTC (`AAAA-MM-DD HH:MM`); a quantidade líquida é calculada (bruta − taxa no ativo), nunca digitada. Informe a **fonte e o id do registro externo**: sem eles a execução não poderá ser comprovada.
2. **Validação.** Formato (decimal com ponto ou vírgula, sem notação científica) e as regras do núcleo (`Execucao`). Regras do serviço: ativo igual ao da meta; estorno só de compra já registrada; o mesmo registro externo não vincula duas execuções da meta. Erros aparecem no próprio formulário e **nada digitado é perdido**.
3. **Duplicidade.** Reenviar os mesmos dados não grava nada (“já estava registrada”); reutilizar o id com dados diferentes é recusado (registros não são editados).
4. **Depois de salvar:** a execução aparece como **registrada, pendente de comprovação** e o progresso comprovado não muda.
5. **Importar evidência** (`EvidenciaExterna`: registros externos + cobertura) e reavaliar: só se a conciliação casar o registro externo com a execução ela vira **comprovada** e entra no progresso. Reimportar o mesmo arquivo não duplica.
6. As avaliações usam como instante o mais tardio entre a última avaliação e o registro/recebimento novo (nunca o relógio do sistema).

### Vincular depois (execução registrada sem referência externa)
Uma execução registrada sem fonte/id externo não pode ser comprovada e aparece com o aviso e o botão **Vincular…**. O vínculo é uma **decisão humana** (`VinculoManual` do núcleo): escolha de um registro externo já importado, **autor** e **justificativa** (mínimo 10 caracteres).
- **Histórico:** a execução não é editada; o vínculo é acrescentado (append-only) e a meta é reavaliada num instante de referência (nunca o relógio do sistema). Eventos e razão anteriores permanecem; a comprovação entra como evento novo.
- **Duplicidade:** repetir o mesmo vínculo não grava nada; um registro externo não pode pertencer a duas execuções da meta (nem por vínculo, nem por referência declarada no formulário); registro não importado ou execução inexistente são recusados.
- **Quem comprova continua sendo a conciliação:** o vínculo só diz qual registro corresponde. Quantidade, ativo, taxas e horários ainda são conferidos; se não baterem, nada é comprovado.

### Corrigir um vínculo manual (revogar ou substituir)
- **Preserva o original.** O vínculo nunca é apagado nem editado: a correção é uma `RevogacaoVinculo` acrescentada ao histórico, com **autor, justificativa (mínimo 10 caracteres) e instante**, apontando para o vínculo pelo hash do conteúdo (`id_do_vinculo`). Numa **substituição**, a revogação e o novo vínculo são gravados juntos, numa transação, e a revogação traz `substituido_por_id`.
- **Não cria execução nem estorno financeiro.** Só retira ou troca a correspondência. A conciliação e o estado são recalculados pelos mecanismos de sempre: a prova que deixa de valer vira **reversão compensatória no razão** (contradição positiva), e, se a meta já estava atingida, o caminho é o do evento `reconciliada`, que mantém a conclusão antiga na história. As avaliações anteriores permanecem.
- **Instante.** A correção vale a partir de um instante estritamente posterior ao do vínculo (nunca antes da última avaliação, nunca o relógio do sistema). Reproduzir um instante anterior à correção devolve o mundo como era; a revogação não retroage.
- **Repetição.** Pedir de novo a mesma revogação ou substituição não grava nada. Depois de revogado, a execução volta a poder receber um vínculo (o novo vínculo é outro registro, com outro conteúdo).
- **Recusas.** Não se revoga uma referência declarada no próprio registro da execução (só vínculos manuais); substituir exige registro já importado e livre pela regra abaixo.

### Regra de exclusividade do registro externo (vale entre TODAS as metas)
Uma compra real, identificada por `(fonte, id externo)`, é **um único fato**. Nenhuma meta, **de qualquer conta**, pode contá-la duas vezes:
- A reivindicação **integral** (sem alocação) é exclusiva do banco inteiro. Reivindicações **parciais** (`quantidade_bruta_alocada`) convivem entre metas enquanto a **soma não exceder a quantidade do registro**.
- A conta da meta **não** é critério de exclusividade: o id da fonte já identifica a compra, e uma meta de outra conta reivindicando-a é um conflito a recusar, não uma permissão. (A conta continua valendo só para o escopo de órfãos.)
- **Aplicação.** (1) Ao registrar uma execução com referência e ao vincular/substituir, o serviço recusa a duplicidade, inclusive entre metas (“da meta X”). Revogar libera o registro. (2) Como rede de segurança (cenários importados, escrita concorrente), a avaliação concilia **todas as metas juntas**: o núcleo marca a mesma compra reivindicada duas vezes como revisão nas duas, sem progresso em dobro. Os ids de execução das outras metas ganham prefixo, porque o núcleo trata o id como global.
- **Antes** desta regra a exclusividade valia só dentro de cada meta, o que deixava a mesma compra contar duas vezes em metas diferentes.

## 5. Onde fica o banco

`UBENTO_DB` se definido; senão `%LOCALAPPDATA%/UBento/ubento.db` (pasta de dados do usuário). Sem banco informado (testes, capturas) o serviço usa memória.

## 6. Ainda isolado

Monitor/agendamento e adaptadores de dados reais; conversão entre moedas; cancelamento de meta pela tela; edição ou remoção de registros (por desenho: correções são novos registros/estornos).

## 7. Confirmações antes do MCP (identidade, concorrência, reavaliação)

### 7.1 Identidade de um registro externo
- A **chave** é `(fonte_id, id_externo)` (`RegistroExterno.chave`). A **conta** (`conta_id`) é um atributo do registro e **não** faz parte da identidade; o mesmo id em **outra fonte** é outra operação.
- **Reimportação da mesma operação:** conteúdo idêntico (mesma chave, mesma versão) é a mesma operação. O banco não grava de novo (`entradas` deduplica por hash do conteúdo) e a conciliação também a deduplica (`importar_evidencia` devolve 0 novos).
- **Correção pela fonte:** a mesma chave com `versao` maior. As versões antigas ficam guardadas; vale a mais alta e a execução é reconciliada contra ela.
- **Mesma chave e mesma versão com conteúdo diferente** (inclusive só a conta): conflito. O registro fica em revisão e nada é comprovado por ele.
- Testes: `tests/test_identidade_registro.py`.

### 7.2 Alocações simultâneas
- **Antes:** a verificação de exclusividade e a gravação eram passos separados (leitura, depois escrita em outra transação). Com duas conexões (dois processos, duas threads com conexões próprias) as duas passavam na verificação e as duas gravavam: a quantidade do registro podia ser ultrapassada. Os testes de concorrência reproduziram a falha (vermelho) antes da correção.
- **Agora:** `registrar_execucao`, `vincular_manualmente`, `revogar_vinculo`, `substituir_vinculo` e `importar_evidencia` rodam dentro de uma seção de escrita **exclusiva** (`BEGIN IMMEDIATE`): quem chega depois espera e enxerga o que o primeiro gravou. Entra na mesma transação o que vem depois: a reavaliação da meta e das metas afetadas (tudo grava, ou nada).
- Testes (`tests/test_concorrencia_metas.py`): dois vínculos simultâneos do mesmo registro (um vence), duas alocações parciais que somadas passam da quantidade (uma vence), alocações que cabem (as duas passam). Desligar a exclusividade faz os três falharem.
- Limites: o SQLite tem um único escritor por arquivo; o tempo de espera é de 10 s e, estourado, a operação falha com `database is locked` (não é traduzida). Cada thread deve ter a sua conexão.

### 7.3 Reavaliação das metas afetadas
- **Antes:** vincular, revogar ou substituir reavaliava só a meta de quem corrigiu. Outra meta que dependia daquela quantidade (disputa que se resolve, ou registro que volta a ser órfão) continuava com o resultado antigo até alguém reavaliá-la.
- **Agora:** depois de vincular, revogar, substituir ou registrar execução com referência declarada, o serviço reavalia **toda outra meta que já tenha avaliação** e que reivindique o registro ou o tenha importado, no instante de referência (nunca o relógio do sistema). Metas nunca avaliadas não são avaliadas por tabela. `importar_evidencia` não reavalia nada (a evidência só vale quando alguém vincula, registra ou reavalia).
- Testes (`tests/test_correcao_vinculo.py`): liberar e tomar um registro muda os órfãos da outra meta; revogar numa meta resolve a disputa da outra (que passa a comprovar).
