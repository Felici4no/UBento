# Análise do documento "Análise e meta" e proposta de base em Python

Referência: `analise-e-meta-especificacao.md` v0.1 (18/10/2026).
Objetivo deste texto: dizer o que o documento já resolve, o que ele deixa em aberto e
como transformar o resto em um núcleo Python testável, que sirva de base para os models
(Análise, Meta, Avaliação, Evento…) e depois alimente o UBento.

> **Atualização (18/10/2026):** as decisões D1–D5 e as duas correções técnicas (hash canônico e arredondamento
> por restrição) foram fechadas e estão em [`ESPECIFICACAO_NUCLEO.md`](ESPECIFICACAO_NUCLEO.md). Onde este texto
> divergir dele (seção 3.1, D6 e D7), vale a especificação. O restante continua como análise e roadmap.

## 1. Veredito

A especificação está **boa o bastante para começar a implementar o núcleo**, desde que
as 7 decisões da seção 3 sejam fechadas antes das partes que dependem delas. O desenho
central é sólido: análise separada de meta, contrato congelado, estado derivado de
eventos, lógica de três valores e núcleo determinístico. Ela é deliberadamente pequena
no escopo (um tipo de meta, sem ordens, sem IA), o que é a decisão certa.

Os riscos reais não estão no algoritmo em si, e sim em quatro lugares onde o texto
descreve a intenção mas não fecha a regra: **o que mede o progresso de uma meta**,
**quem vence quando dois eventos coincidem**, **o que acontece no prazo sem dados** e
**como se reconciliam fontes divergentes**. Sem isso, duas implementações corretas do
texto dariam resultados diferentes, o que contraria o próprio critério de sucesso do
documento (reproduzir cada decisão).

## 2. O que já está sólido (manter como está)

| Ponto | Por que é bom | Implicação no código |
| --- | --- | --- |
| Análise ≠ Meta; meta aponta para **uma versão** publicada | Evita meta "viva" apoiada em evidência que mudou | `Meta.analise_id` + `analise_versao` + hash da análise no contrato |
| Contrato congelado; estado derivado de eventos | Auditoria e reprodução sem reescrever história | Tabelas `meta_contrato` (imutável) e `meta_evento` (só inserção); estado = `dobrar(eventos)` |
| Lógica `verdadeiro/falso/indeterminado` | Falta de dado não vira "falso" nem "verdadeiro" | `Tri` enum; todas as comparações devolvem `Tri` + explicação |
| Bloqueios separados de sinais | Um `any` favorável não contorna dado inválido | Avaliação em duas fases (seção 6.2) |
| `Decimal` e razões (`"0.05"`), nunca `float` | Dinheiro exato, hash estável | Tipos de domínio só aceitam `str`/`Decimal` |
| Cálculos puros; I/O fora | Reprodutível e fácil de testar | "Núcleo funcional, casca imperativa" |
| Idempotência por chave | Reprocessar não duplica alerta/reserva | `chave = hash(meta_id, regra_id, snapshot_id)` |
| Lista de verificações (seção 13) | Já é uma suíte de testes | Cada item vira um teste de aceitação |

## 3. Lacunas e ambiguidades a decidir

Ordenadas por impacto. As recomendações são minhas e estão marcadas como **proposta**.

### 3.1 Bloqueantes (decidir antes de codificar a parte afetada)

| # | Ponto | Por que importa | Proposta |
| --- | --- | --- | --- |
| D1 | **Medida de progresso** de `acumular_quantidade` | O texto fala em "dados ou execuções aceitos", mas não diz se conta o saldo total ou só o acumulado pela meta. Depósitos/retiradas externos distorceriam o saldo, e o sistema "não envia ordens" (então de onde vêm as execuções?) | Progresso = **soma das execuções confirmadas de compra vinculadas à meta**, líquidas de custos. Saldo observado serve só como conferência. Execuções entram por registro manual/importação, com `execucao_id` único |
| D2 | **Precedência** no mesmo instante | Só está definido "invalidação > nova entrada" e "objetivo até o prazo inclusive". Faltam conclusão × invalidação e conclusão × prazo | Ordenar eventos por horário da **evidência**. Empate exato: `atingida` > `invalidada` > `expirada` > entrada. Racional: objetivo atingido é fato consumado; a invalidação só afeta novas entradas (o texto diz que a posição continua existindo) |
| D3 | **Prazo sem dados** | `registrar_bloqueio_e_tratar_prazo_sem_inventar_resultados` não diz o resultado | Contrato traz `carencia_dados`. Passada a carência sem evidência válida: `expirada` com motivo `prazo_sem_evidencia`; um evento de reconciliação posterior pode corrigir o estado (com autoria e motivo), como o documento já prevê |
| D4 | **Reconciliação de fontes** (`divergente`) | O texto exige "política explícita" e não define | Por métrica, no catálogo: lista de fontes por prioridade e `tolerancia_relativa` (padrão `0.01` para preço). Acima disso a observação é `divergente` e **bloqueia** quem a usa; nunca faz média silenciosa |
| D5 | **Tipo de objetivo da v1** | Os três tipos exigem dados muito diferentes (`atingir_valor_liquido` precisa de profundidade de livro e deslizamento) | Só `acumular_quantidade` na v1, como o próprio texto sugere. Os outros dois entram com fórmula de progresso escrita e testada |

### 3.2 Importantes (decidir durante a implementação)

| # | Ponto | Observação / proposta |
| --- | --- | --- |
| D6 | **Hash do contrato** | O texto exige o hash e não diz de quê. Proposta: SHA-256 de JSON canônico (chaves ordenadas, sem espaços, `Decimal` normalizado para string, UTC), incluindo `schema_versao`, hash da análise e versão do motor. Verificado no protótipo: independe de ordem e de zeros à direita (`"1000.00"` == `"1000"`) |
| D7 | **Arredondamento** | O documento manda "documentar precisão e arredondar por ativo" mas não a direção. Verificado: arredondar o preço máximo do exemplo para cima (9,9005) **estoura** o orçamento em 0,00025 USD. Regra proposta: limites de preço e quantidade **sempre para o lado conservador** (preço máximo para baixo, quantidade para baixo no incremento do mercado) |
| D8 | **Estado × condição operacional** | `bloqueada_por_dados` é ortogonal ao estado (uma meta `ativa` pode estar bloqueada). Modelar como campo derivado separado, não como sétimo estado |
| D9 | **Exposição conjunta e reservas** | "Não comprometer o mesmo saldo duas vezes" exige um razão de reservas. Proposta: tabela `reserva` com invariante `soma(reservas ativas) ≤ saldo disponível`, criada na mesma transação da ativação (`BEGIN IMMEDIATE` no SQLite) |
| D10 | **Validade do dado** | "Idade comparada com a validade configurada" — configurada onde? Proposta: campo `validade_maxima` no catálogo de métricas; a meta pode apertar, nunca afrouxar |
| D11 | **Aprovação humana** | Premissas qualitativas exigem aprovação registrada. Falta o formato. Proposta: entidade `AprovacaoHumana(autor, justificativa, hash_da_analise, em)`; sem ela, a viabilidade daquela pergunta é `indeterminado` |

### 3.3 Menores (anotar)

- A seção 5 usa razões (`0.05`) e o UBento usa percentuais na interface; a conversão fica na borda da UI.
- `substitui_meta_id` aparece só no texto da seção 3; precisa entrar no esquema do contrato.
- "Retorno relativo B/A" exige janelas iguais; o catálogo deve rejeitar janelas diferentes em vez de reamostrar.
- Regras obrigatórias não podem ter lista vazia (o texto já diz). Confirmado no protótipo que `all([])` seria `verdadeiro` e `any([])` `falso`, ou seja, uma lista vazia **autorizaria** silenciosamente: o validador do esquema precisa rejeitar.

## 4. O que verifiquei (protótipo descartável)

| Afirmação do documento | Resultado |
| --- | --- |
| `preco_maximo = (1000 − 5) / (100 × 1,005) ≈ 9,9005` | Confere (9,90049…). Ao preço exato, o custo total é 1000,00 |
| `all`/`any`/`not` do texto são a lógica forte de Kleene | Confere: `all` = mínimo e `any` = máximo na ordem `falso < indeterminado < verdadeiro`; De Morgan vale. Isso permite testes de propriedade |
| Hash estável com `Decimal` | Confere; com `float`, `0.1 + 0.2 != 0.3` |
| Quantidade respeita o incremento do mercado | A 9,91 com passo 0,01 compra-se 99,90 (< 100): a meta fica inviável nesse preço, e o motor precisa dizer isso, não arredondar para 100 |

## 5. Arquitetura Python proposta

Princípios: **núcleo funcional, casca imperativa**; o núcleo não importa Qt, rede nem
relógio do sistema; tudo que varia (hora, dados, armazenamento) entra por parâmetro.

```
src/ubento/nucleo/              (novo, sem dependência de Qt)
  tipos.py        Tri, helpers de Decimal/Razao/Unidade, UTC obrigatório, arredondamento por ativo
  esquema.py      modelos estritos: Ativo, Metrica, Observacao, Indicador, Evidencia, Cenario,
                  Analise, Meta, Avaliacao, Evento, Execucao, AprovacaoHumana
  carregador.py   YAML seguro (rejeita chave duplicada/campo desconhecido), JSON, hash canônico
  metricas.py     catálogo versionado + funções puras (retorno, spread, volume relativo, volatilidade…)
  regras.py       árvore de condições → Tri + explicação estruturada
  viabilidade.py  as 8 perguntas → compativel / incompativel / indeterminado
  metas.py        rascunho → ativação (congela, reserva, hash), tipos de objetivo
  estado.py       dobrar(eventos) → estado + condição operacional; política de ordem
  avaliador.py    avaliar_meta(contrato, eventos, snapshot, agora) → Avaliacao + eventos novos
  monitor.py      (casca) coleta snapshot, chama o avaliador, persiste de forma idempotente
  repositorio.py  Protocol + implementação em memória + SQLite
  auditoria.py    reexecuta uma avaliação a partir do snapshot e compara resultado/hash
```

Dependências sugeridas: `pydantic` v2 (modo estrito, `extra="forbid"`), `ruamel.yaml`
(rejeita chaves duplicadas por padrão; o PyYAML não), `hypothesis` (testes de propriedade).
Python ≥ 3.11 (o ambiente atual já é 3.11).

### 5.1 Nomes

Proposta: **domínio em português sem acento, igual ao documento** (`Meta`, `Analise`,
`Avaliacao`, campos `orcamento`, `analise_versao`…). Assim o contrato YAML/JSON e o
código se correspondem 1:1 e a revisão do texto vira revisão do código. Infraestrutura
(repositórios, adaptadores) pode seguir o inglês já usado no restante do UBento.

## 6. Algoritmos

### 6.1 Condições tri-valoradas

```python
class Tri(StrEnum):
    VERDADEIRO = "verdadeiro"; FALSO = "falso"; INDETERMINADO = "indeterminado"

def todos(xs):   # all: falso vence; só é verdadeiro se todos forem
    xs = list(xs)
    if any(x is Tri.FALSO for x in xs): return Tri.FALSO
    return Tri.VERDADEIRO if all(x is Tri.VERDADEIRO for x in xs) else Tri.INDETERMINADO

def algum(xs):   # any: verdadeiro vence
    xs = list(xs)
    if any(x is Tri.VERDADEIRO for x in xs): return Tri.VERDADEIRO
    return Tri.FALSO if all(x is Tri.FALSO for x in xs) else Tri.INDETERMINADO
```

Comparação de métrica: se a observação estiver `ausente`, `invalida`, `divergente`,
vencida ou com unidade diferente da esperada → `INDETERMINADO` com o motivo. A
explicação guarda: valor, unidade, fonte, horário, idade, limite e resultado.

### 6.2 Avaliação em duas fases

```
avaliar_regras(conjunto, snapshot, agora):
    bloqueios = [avaliar(c) for c in conjunto.bloqueios_obrigatorios]    # qualidade, liquidez, limites
    if algum bloqueio == FALSO            -> resultado = NEGADO
    elif algum bloqueio == INDETERMINADO  -> resultado = BLOQUEADO_POR_DADOS
    else                                  -> sinal = todos/algum(conjunto.sinais)
```
Sinal favorável nunca compensa bloqueio. Não existe nota agregada.

### 6.3 Viabilidade (antes de ativar)

Cada uma das 8 perguntas vira uma verificação com resultado `Tri` e motivo. Resultado
final = `todos(...)`: `VERDADEIRO` → `compativel`; `FALSO` → `incompativel`; resto →
`indeterminado`. Só `compativel` ativa. Pergunta 7 (premissa e contraevidência) exige
`AprovacaoHumana` vinculada ao hash da análise.

Parte numérica da v1 (`acumular_quantidade`):

```python
def preco_maximo_unitario(orcamento, quantidade, custo_fixo, taxa, casas_preco):
    bruto = (orcamento - custo_fixo) / (quantidade * (1 + taxa))
    return arredondar_para_baixo(bruto, casas_preco)          # D7: lado conservador
```
Entrada fica elegível quando `preco_executavel <= preco_maximo_unitario` **e** a
quantidade líquida (já no incremento do mercado) fecha a meta. Taxa já embutida na
cotação não é descontada de novo.

### 6.4 Estado a partir de eventos

```python
def estado_de(eventos_ordenados) -> EstadoMeta:
    estado = RASCUNHO
    for e in eventos_ordenados:                 # ordem: (horario_evidencia, sequencia)
        estado = TRANSICOES[(estado, e.tipo)]   # tabela fechada; transição ilegal = erro
    return estado

# condição operacional derivada, não é estado:
bloqueada_por_dados = existe_bloqueio_aberto(eventos)
```
Eventos: `criada, ativada, avaliada, alerta_emitido, bloqueio_iniciado, bloqueio_encerrado,
execucao_registrada, atingida, expirada, invalidada, cancelada, reconciliada, substituida`.
Estados terminais não aceitam novos eventos de domínio, só `reconciliada`.

### 6.5 Avaliar uma meta (resumo do `AVALIAR_META`)

```
avaliar_meta(contrato, eventos, snapshot, agora):
    estado = estado_de(eventos);  se terminal -> []
    se dados_obrigatorios_invalidos(snapshot, agora):
        -> evento bloqueio_iniciado (se ainda não aberto); aplica D3 se agora > prazo + carencia
    candidatos = [atingida?, invalidada?, expirada?]   # cada um com horário de evidência
    vencedor   = menor horário; empate -> atingida > invalidada > expirada   (D2)
    se há vencedor -> eventos de encerramento + liberação de reserva (transacional)
    senão se bloqueios de entrada passam -> alerta_emitido(chave_idempotente)
    devolve Avaliacao(snapshot_id, hash_entradas, resultados, explicacoes) + eventos
```
`snapshot_id` = hash das observações usadas (ids + versões). Reexecutar com o mesmo
snapshot, contrato, `agora` e versão do motor **tem de** reproduzir o mesmo hash de
saída; é o que `auditoria.py` confere.

### 6.6 Reservas e concorrência

Ativar = uma transação: relê saldo e reservas ativas, grava `reserva`, congela o
contrato, grava o evento `ativada`. A chave de idempotência da ativação é o hash do
contrato, então repetir a chamada não reserva duas vezes. No encerramento, a reserva
não utilizada é liberada na mesma transação do evento terminal.

## 7. Persistência (SQLite, mesma base do app)

| Tabela | Regra |
| --- | --- |
| `analise_versao` | Imutável após publicar; `hash` e `analise_id + versao` únicos |
| `observacao` | Só inserção; revisão do provedor = nova linha, nunca update |
| `meta_contrato` | Imutável; `hash` único; gatilho bloqueia `UPDATE`/`DELETE` |
| `meta_evento` | Só inserção; `(meta_id, sequencia)` único; guarda horário da evidência e de ingestão |
| `meta_avaliacao` | Só inserção; guarda `snapshot_id`, hash das entradas e das saídas |
| `reserva` | Invariante verificada na transação de ativação/encerramento |
| `execucao` | `execucao_id` único (idempotência de importação); separa custo estimado e real |

Gatilhos de imutabilidade tornam o requisito "meta ativa não aceita alteração" uma
garantia do banco, não só do código.

## 8. Relação com o UBento atual

O que existe hoje (`agent_config.py`, `engine.py`, `store.py`) é uma **simulação de
interface**: números em `float`, sinais de mercado sorteados com semente, decisões que
alteram saldos em memória, nenhum versionamento nem hash. Isso é adequado para
prototipar a tela, mas **não é a base certa** para o documento: viola Decimal, a
reprodução e a separação análise/meta/evento.

Proposta de convivência:

1. O núcleo nasce em `ubento/nucleo`, sem tocar a interface.
2. O agente passa a ter **metas** (uma ou várias); a faixa do agente e a tela de
   configuração ganham a lista de metas e seus estados.
3. Alertas do monitor (`entrada`, `invalidação`) viram `Decision` com status `proposed`,
   reaproveitando os botões ✓/✕ que já existem. Aprovar continua sendo um ato humano;
   o núcleo não envia ordens.
4. Os algoritmos heurísticos atuais ficam marcados como **demonstração** até serem
   substituídos ou removidos; nada novo depende deles.
5. Conversão `Decimal` ↔ `float` só na fronteira de exibição do `Store`.

## 9. Estratégia de testes

- **Aceitação:** cada item da seção 13 do documento vira um teste nomeado.
- **Propriedade (Hypothesis):** De Morgan e equivalência com min/max para `todos/algum/nao`; hash invariável à ordem das chaves; `soma(reservas) ≤ saldo` sob sequências aleatórias de ativar/encerrar; reprocessar N vezes gera o mesmo conjunto de eventos.
- **Golden files:** exemplos YAML válidos/inválidos (chave duplicada, campo extra, unidade errada, lista vazia, `float` no lugar de string) com a saída esperada.
- **Reprodução:** gravar snapshots reais/sintéticos e exigir que `auditoria` reproduza hash de saída.
- **Simulação de estratégia (seção 13, último parágrafo):** fica fora da suíte do software; usa só informação disponível em cada instante, separa desenvolvimento de validação e inclui custos e latência.

## 10. Roadmap sugerido

| Fase | Entrega | Pronto quando |
| --- | --- | --- |
| 0 | Fechar D1–D5 por escrito (v0.2 do documento) | Decisões registradas |
| 1 | `tipos`, `esquema`, `carregador`, hash canônico | Exemplos válidos/ inválidos passam; hash estável |
| 2 | `metricas`, `regras` (Tri + explicações) | Propriedades de lógica e fórmulas de referência passam |
| 3 | `viabilidade`, `metas` (rascunho → ativa), reservas | Itens 2, 3, 7 e 9 da seção 13 passam |
| 4 | `estado`, `avaliador`, eventos, idempotência | Itens 4, 5, 6, 8 e 10 passam; reprodução confere |
| 5 | Análise versionada + publicação + SQLite com gatilhos | Itens 1 e 3 passam contra o banco |
| 6 | Monitor com provedor "replay" (arquivos) + integração à interface | Alertas aparecem como propostas no agente |
| 7 | Adaptador de dados real | Fora do escopo desta análise |

## 11. Decisões pedidas

1. **D1–D5** acima: aceita as propostas ou quer outra regra? (Em especial D1, que muda o modelo de dados, e D2.)
2. **Nomes em português** no domínio, como no documento?
3. **Pydantic v2 + ruamel.yaml + hypothesis** como dependências do núcleo?
4. **Convivência** com os agentes atuais: manter como demonstração enquanto o núcleo nasce, como em §8?
5. **Fonte de dados da v1:** arquivos de reprodução (CSV/JSON) primeiro, adaptador real depois?
