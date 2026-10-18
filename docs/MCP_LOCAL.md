# MCP local do UBento (v1: somente consulta)

Servidor [MCP](https://modelcontextprotocol.io) local que deixa um agente de IA **consultar** as metas persistidas. Não escreve nada.
Usa o **SDK oficial** (`mcp`); a lógica de consulta continua em `ubento.consulta`, que o SDK só expõe.

```bash
pip install -e ".[mcp]"                  # o SDK é opcional: o app de desktop não precisa dele
python -m ubento.mcp_local               # banco: UBENTO_DB, ou %LOCALAPPDATA%/UBento/ubento.db
python -m ubento.mcp_local --db C:\caminho\ubento.db
```
Depois da instalação há também o comando `ubento-mcp`. Configuração de um cliente MCP (stdio):
```json
{ "mcpServers": { "ubento": { "command": "python", "args": ["-m", "ubento.mcp_local", "--db", "C:\\caminho\\ubento.db"],
                              "env": { "PYTHONPATH": "C:\\caminho\\UBento\\src" } } } }
```

## O que o servidor garante
- **Somente leitura, de verdade.** O banco é aberto com `mode=ro` e `PRAGMA query_only`: o próprio SQLite recusa escrita. Consultar **não importa, não reavalia e não grava eventos**; um banco inexistente é erro (nunca é criado). Os testes comparam o hash do arquivo e a contagem de linhas antes e depois, e conferem que o código das consultas não chama nenhum método de escrita.
- **A cada chamada** o banco é aberto de novo: a resposta é o que está gravado naquele momento (o app pode estar aberto escrevendo; o WAL permite a leitura).
- Decimais viajam como **texto**, instantes em ISO 8601 UTC (`...Z`).
- **`stdout` é só do protocolo.** Logs (`logging`) e avisos vão para `stderr`; um teste lê o `stdout` cru e exige que toda linha seja uma mensagem JSON-RPC.

## Três coisas que as respostas nunca misturam
Toda resposta de meta traz o mesmo envelope:

| Campo | Significa |
| --- | --- |
| `estado_persistido` | o estado da **última avaliação gravada**. Não é recalculado ao consultar |
| `ultima_avaliacao` | **quando** ela foi feita (`avaliada_em`), versão do motor, se estava bloqueada por dados e **de onde veio o instante** (`instante_vem_de`: `relogio_real` ou `cenario`) |
| `leitura` | `tempo_real: false` e um **aviso em texto** que diz a data da última avaliação e que os dados não são atualizados em tempo real (e, se for o caso, que há entradas mais novas que ela) |
| `cobertura_da_evidencia` | o que a evidência importada garante: registros externos, **coberturas de consulta** declaradas pela fonte (sem elas a ausência de um registro **não** prova que ele não existe) e o que chegou **depois** da última avaliação (`posterior_a_ultima_avaliacao`, `desatualizada`) |

`desatualizada: true` é um indicador por instantes (há registros, execuções, vínculos ou revogações mais novos que a última avaliação). O servidor **não** reavalia para resolvê-lo: quem decide reavaliar é o app.
`consulta` repete, em toda resposta, `somente_leitura: true`, `recalculou: false`, `gravou: false`.

## Ferramentas
Todas anotadas com `readOnlyHint: true` (e `destructiveHint: false`, `idempotentHint: true`).

| Ferramenta | Argumentos | Devolve |
| --- | --- | --- |
| `listar_metas` | `agente_id?`, `somente_com_pendencias?` | estado persistido, última avaliação, comprovado/alvo, pendências abertas e se a evidência está desatualizada, por meta |
| `consultar_meta` | `meta_id` | objetivo (ativo, moeda, alvo, prazo), mercado/conta, ativação e posição no cenário |
| `consultar_progresso` | `meta_id` | quantidade **comprovada** (separada da **registrada pendente de comprovação**), preservada, fora da janela, atingimento, elegibilidade, orçamento e custos |
| `consultar_pendencias` | `meta_id` | pendências da conciliação, registros externos sem execução (relevantes e ignorados) e cada execução com sua situação e vínculo vigente |
| `consultar_historico` | `meta_id`, `limite` (1–500), `apos_sequencia` | eventos paginados por sequência, razão de conciliação, avaliações e a trilha de vínculos manuais com suas revogações |

Erros de uso (meta inexistente, argumento inválido, ferramenta desconhecida) voltam como resultado com `isError: true` e uma mensagem; falhas inesperadas voltam sem detalhe técnico e o detalhe vai para o log (`stderr`).

## Validação com um cliente MCP real
| Item | Valor |
| --- | --- |
| Cliente | **SDK oficial `mcp`**, `mcp.client.Client` sobre `stdio` (um cliente MCP completo, em processo separado do servidor) |
| Versão | `mcp` 2.3.0 (`mcp-types` 2.3.0), Python 3.11.15, Windows 11 |
| Servidor | `python -m ubento.mcp_local --db <banco>` (processo real, por stdio) |
| Testes | `tests/test_mcp_local.py` (10), `tests/test_timeout_escrita.py` (3); suíte inteira verde |

O que foi conferido, e como:
- **Inicialização e versão.** O cliente propôs `2026-07-28`; o servidor respondeu com a mesma. Com cliente cru: pedir `2025-06-18` devolve `2025-06-18`; pedir uma versão que não existe (`1999-01-01`) faz o servidor **propor a sua** em vez de repetir (a implementação própria anterior repetia qualquer versão).
- **Descoberta.** As cinco ferramentas, com esquema de entrada (obrigatórios, limites de `limite`) e anotações de somente leitura.
- **Chamadas válidas e inválidas.** Meta inexistente, `meta_id` ausente ou do tipo errado, `limite` 0 e 501, `apos_sequencia` negativo e ferramenta inexistente voltam todos como `isError: true` com mensagem legível.
- **Encerramento.** Sair do cliente fecha o `stdin`; o servidor termina sozinho com código 0.
- **stdout limpo.** Conversa em JSON-RPC cru: toda linha do `stdout` é JSON-RPC; o aviso de inicialização aparece no `stderr`.
- **Não escreve.** Hash do arquivo do banco e contagem de linhas idênticos antes e depois de dezenas de consultas; a conexão recusa `INSERT`/`CREATE`/`UPDATE`.

**Não validado:** clientes de produto (Claude Desktop, IDEs). Roteiro curto para conferir localmente:
1. `pip install -e ".[mcp]"` e gere um banco de teste: `python scripts/demo_mcp.py --db C:\temp\demo.db`.
2. Adicione o JSON de configuração acima ao cliente (com `--db C:\temp\demo.db`) e reinicie o cliente.
3. Confirme as 5 ferramentas e pergunte “quais metas estão pendentes?”. A resposta deve citar a data da última avaliação e dizer que não é tempo real.

## SDK oficial × implementação própria
A primeira versão tinha um servidor JSON-RPC próprio (sem dependências). Validada contra o cliente do SDK, ela interoperava, mas tinha lacunas que o SDK já resolve:

| Ponto | Própria | SDK oficial |
| --- | --- | --- |
| Negociação de versão | repetia qualquer versão pedida | responde com a pedida se suportada; senão propõe a sua |
| Validação de argumentos | escrita à mão (tipos, obrigatórios) | gerada do tipo da função (`Annotated[int, Field(ge=1, le=500)]`), esquema publicado automaticamente |
| Esquema das ferramentas | dicionário mantido à mão | derivado da assinatura (não diverge do código) |
| Argumentos desconhecidos | recusados | **ignorados** (diferença aceita) |
| Ferramenta inexistente | erro JSON-RPC `-32602` | resultado `isError: true` |
| Falha inesperada | propagava | resposta genérica, detalhe só no log |
| Fim da entrada (EOF) | processava tudo | encerra de imediato; requisições em voo se perdem, então um cliente real só fecha o `stdin` **depois** de receber as respostas (o teste cru faz isso) |
| Evolução do protocolo | manutenção nossa | acompanha o SDK |
| Tamanho do módulo | 175 linhas | 109 linhas (as ferramentas são as mesmas funções de `ubento.consulta`) |
| Custo | nenhum | dependência (`mcp` traz `anyio`, `httpx2`, `starlette`, `uvicorn`, `pydantic`, `pywin32` no Windows…) |

Decisão: **SDK**, porque não há restrição concreta contra a dependência. Ela é **opcional** (`pip install "ubento[mcp]"`): o app de desktop e o núcleo não a importam, e sem o SDK o módulo explica como instalá-lo. A camada de consulta (`ubento.consulta`) não depende do SDK nem do transporte.

## Timeout de escrita
Quando outra escrita segura o banco por mais tempo que o limite de espera (10 s, configurável em `Repositorio(timeout=...)`), a operação **falha por inteiro**: `ErroBancoOcupado` (`ErroDeRegistro` para quem chama o serviço), com a mensagem “O banco de dados está ocupado por outra operação de escrita e a espera acabou. Nada foi gravado. Tente novamente em instantes.”. O erro técnico (`database is locked`) fica no log `ubento.persistencia` (nível ERROR, com traceback) e na cadeia `__cause__`, mas **não** vaza para a mensagem. Toda escrita começa com `BEGIN IMMEDIATE`, então o bloqueio aparece no início, antes de qualquer linha ser inserida; se aparecer no meio (por exemplo, numa reavaliação), a transação inteira é desfeita. Os testes provam as duas situações comparando eventos, razão, avaliações e vínculos antes e depois, e que a mesma operação funciona quando o outro escritor termina. As consultas do MCP não sofrem esse timeout: leem em WAL enquanto outro processo escreve.

## Demonstração (banco persistido de teste, dados simulados)
Saída de `python scripts/demo_mcp.py`: o script grava o banco em disco, fecha-o e fala com o servidor por um cliente MCP real. A narração é gerada pelo script a partir das respostas das ferramentas, como um agente de IA faria.

```text
Banco persistido de teste: <pasta temporária>/ubento-demo.db

Cliente MCP: SDK oficial `mcp` | protocolo negociado: 2026-07-28 | servidor: ubento-metas 0.1.0
Dados SIMULADOS. A narração é gerada por este script a partir das respostas das ferramentas.

PERGUNTA 1: quais metas estão pendentes?  →  listar_metas(somente_com_pendencias=true)
  • meta-empresa-tokx: estado gravado 'ativa', última avaliação em 20/10/2026 14:00 UTC; 3 execução(ões) por comprovar, 3 pendência(s) aberta(s).
    Atenção: há evidência importada DEPOIS dessa avaliação; ela ainda não foi considerada.
  Observação: Cada meta mostra o estado da sua última avaliação gravada (ultima_avaliacao_em); nada aqui é atualizado em tempo real.

PERGUNTA 2: explique a pendência de meta-empresa-tokx.  →  consultar_pendencias
  Estado gravado: 'ativa' (avaliado em 20/10/2026 14:00 UTC).
  • ex-1: compra não conciliada.
  • ex-2: compra não conciliada.
  • ex-3: compra não conciliada.
    - execução ex-1: 3.98 tokx em 20/10/2026 10:00 UTC, situação 'pendente de comprovação' (sem referência externa: não pode ser comprovada até ser vinculada a um registro)
    - execução ex-2: 2.985 tokx em 20/10/2026 11:00 UTC, situação 'pendente de comprovação' (sem referência externa: não pode ser comprovada até ser vinculada a um registro)
    - execução ex-3: 3.085 tokx em 20/10/2026 12:00 UTC, situação 'pendente de comprovação' (sem referência externa: não pode ser comprovada até ser vinculada a um registro)
  Evidência: 4 registro(s) externo(s) importado(s), 1 chegou(aram) depois da última avaliação; NÃO há cobertura de consulta (sem ela, a ausência de um registro não prova nada).
  Observação: Estes dados refletem a última avaliação gravada, feita em 20/10/2026 14:00 UTC. Não são atualizados em tempo real: o que mudou depois dela só aparece quando o app reavaliar a meta. Há entradas mais novas que essa avaliação (veja cobertura_da_evidencia.posterior_a_ultima_avaliacao).

PERGUNTA 3: mostre o histórico de meta-empresa-tokx.  →  consultar_historico(limite=10)
  # 1 20/10/2026 08:00 UTC  ativada
  1 evento(s) no total; 4 avaliação(ões); a última foi em 20/10/2026 14:00 UTC.
  Observação: Estes dados refletem a última avaliação gravada, feita em 20/10/2026 14:00 UTC. Não são atualizados em tempo real: o que mudou depois dela só aparece quando o app reavaliar a meta. Há entradas mais novas que essa avaliação (veja cobertura_da_evidencia.posterior_a_ultima_avaliacao).
```

Repare em como cada resposta situa o tempo: a **última avaliação** (20/10/2026 14:00 UTC) vem sempre dita, o estado é o **gravado** (`ativa`), e a evidência que chegou depois é apontada como **ainda não considerada**. Nada sugere atualização em tempo real.

## Fora desta versão
Qualquer escrita (importar, avaliar, registrar, vincular, corrigir), recursos e prompts MCP, autenticação (o servidor é local, por stdio), notificações de mudança. Quando houver escrita, ela deve ser um servidor/perfil separado, com confirmação explícita.
