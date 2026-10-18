# MCP local do UBento (v1: somente consulta)

Servidor [MCP](https://modelcontextprotocol.io) local que deixa um agente de IA **consultar** as metas persistidas. Não escreve nada.

```bash
python -m ubento.mcp_local              # banco: UBENTO_DB, ou %LOCALAPPDATA%/UBento/ubento.db
python -m ubento.mcp_local --db C:\caminho\ubento.db
```
Depois de `pip install -e .` há também o comando `ubento-mcp`. Exemplo de configuração de um cliente MCP (stdio):
```json
{ "mcpServers": { "ubento": { "command": "python", "args": ["-m", "ubento.mcp_local"], "env": { "PYTHONPATH": "C:\\caminho\\UBento\\src" } } } }
```

## O que o servidor garante
- **Somente leitura, de verdade.** O banco é aberto com `mode=ro` e `PRAGMA query_only`: o próprio SQLite recusa escrita. Consultar **não importa, não reavalia e não grava eventos**; um banco inexistente é erro (nunca é criado). Os testes comparam o hash do arquivo e a contagem de linhas antes e depois, e conferem que o código das consultas não chama nenhum método de escrita.
- **A cada chamada** o banco é aberto de novo: a resposta é sempre o que está gravado naquele momento (o app pode estar aberto escrevendo; o WAL permite a leitura).
- Decimais viajam como **texto**, instantes em ISO 8601 UTC (`...Z`).
- Transporte: JSON-RPC 2.0 por stdio, uma mensagem por linha, sem dependências além do UBento (o pacote `mcp` não é necessário). `stdout` é só do protocolo; avisos vão para `stderr`.

## Três coisas que as respostas nunca misturam
Toda resposta de meta traz o mesmo envelope:

| Campo | Significa |
| --- | --- |
| `estado_persistido` | o estado da **última avaliação gravada**. Não é recalculado ao consultar |
| `ultima_avaliacao` | **quando** ela foi feita (`avaliada_em`), versão do motor e se estava bloqueada por dados. O mundo pode ter andado depois |
| `cobertura_da_evidencia` | o que a evidência importada garante: registros externos, **coberturas de consulta** declaradas pela fonte (sem elas a ausência de um registro **não** prova que ele não existe) e o que chegou **depois** da última avaliação (`posterior_a_ultima_avaliacao`, `desatualizada`) |

`desatualizada: true` é um indicador por instantes (há registros, execuções, vínculos ou revogações mais novos que a última avaliação). O servidor **não** reavalia para resolvê-lo: quem decide reavaliar é o app.
`consulta` repete, em toda resposta, `somente_leitura: true`, `recalculou: false`, `gravou: false`.

## Ferramentas
Todas anotadas com `readOnlyHint: true`.

| Ferramenta | Argumentos | Devolve |
| --- | --- | --- |
| `listar_metas` | `agente_id?` | estado persistido, última avaliação, comprovado/alvo e se a evidência está desatualizada, por meta |
| `consultar_meta` | `meta_id` | objetivo (ativo, moeda, alvo, prazo), mercado/conta, ativação e posição no cenário |
| `consultar_progresso` | `meta_id` | quantidade **comprovada** (separada da **registrada pendente de comprovação**), preservada, fora da janela, atingimento, elegibilidade, orçamento e custos |
| `consultar_pendencias` | `meta_id` | pendências da conciliação, registros externos sem execução (relevantes e ignorados) e cada execução com sua situação e vínculo vigente |
| `consultar_historico` | `meta_id`, `limite` (1–500), `apos_sequencia` | eventos paginados por sequência, razão de conciliação, avaliações e a trilha de vínculos manuais com suas revogações |

Erros de uso (meta inexistente, argumento inválido) voltam como resultado com `isError: true` e uma mensagem; métodos e ferramentas desconhecidos voltam como erro JSON-RPC.

## Fora desta versão
Qualquer escrita (importar, avaliar, registrar, vincular, corrigir), recursos e prompts MCP, autenticação (o servidor é local, por stdio), notificações de mudança. Quando houver escrita, ela deve ser um servidor/perfil separado, com confirmação explícita.
