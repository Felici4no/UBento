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
- **Não há desvincular:** corrigir um vínculo errado exige um novo registro/estorno (lacuna conhecida e deliberada nesta fase).

## 5. Onde fica o banco

`UBENTO_DB` se definido; senão `%LOCALAPPDATA%/UBento/ubento.db` (pasta de dados do usuário). Sem banco informado (testes, capturas) o serviço usa memória.

## 6. Ainda isolado

Monitor/agendamento e adaptadores de dados reais; conversão entre moedas; cancelamento de meta pela tela; edição ou remoção de registros (por desenho: correções são novos registros/estornos).
