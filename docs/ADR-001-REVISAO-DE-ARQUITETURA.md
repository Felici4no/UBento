# ADR-001: Revisão da arquitetura e ligação entre carteira e metas

**Status:** Aceito (passo 1 concluído em 2026-10-20)
**Data:** 2026-10-20
**Quem decide:** Lucas (dono do projeto)

## Contexto

O UBento tem hoje ~13,3 mil linhas de Python (745 testes) e dois grandes blocos que cresceram em momentos diferentes:

- **Núcleo de metas** (`nucleo/`, `persistencia/`, `metas.py`, `consulta.py`, `mcp_local.py`, Telegram): determinístico, `Decimal`, UTC com fuso, SQLite append-only, sem Qt, rede nem relógio.
- **Painel de carteiras** (`store.py`, `workspace.py`, `engine.py`, `agent_config.py`, `ui/`): nasceu como demonstração, ganhou agentes, regras de risco e o modo mercado real. Usa `float`, `datetime` ingênuo local, estado em memória e `QSettings`.

Esta revisão olha o conjunto: o que está sólido, o que é frágil e o que decidir antes de o app crescer mais (leitura de dados da Binance, carteiras persistentes, agendador).

Método: leitura do código, mapa de imports por camada, contagem de relógios e estado global, e conferência dos testes que impõem fronteiras. Nada aqui foi inferido só da documentação.

## O que está sólido (manter)

1. **Camadas de baixo isoladas e verificadas.** `nucleo/`, `persistencia/` e `conexoes/` não importam Qt nem a UI (conferido por busca de imports). O isolamento do núcleo é imposto por teste (`tests/nucleo/test_isolamento.py`: sem Qt, rede, banco nem relógio do sistema). Poucos projetos desse tamanho têm isso.
2. **Persistência de metas com garantias reais.** Append-only por trigger, escrita exclusiva (`BEGIN IMMEDIATE`), leitura somente-leitura separada para MCP e Telegram, timeout claro de banco ocupado.
3. **Segredos fora do banco.** Cofre do sistema, tabela de conexões sem coluna de segredo (testado), mensagens de erro sem credencial.
4. **Thread de rede sem tocar em Qt.** O atualizador de preços só enfileira; um timer da interface entrega os sinais. Foi a correção de um crash intermitente real e está documentada no código.
5. **`engine.py` puro e as regras de risco como pós-filtro puro.** Fáceis de testar com contas feitas à mão, o que foi feito.

## Achados (do mais grave ao menos grave)

### A1. Dois mundos desconectados: o produto central não é alimentado pelo resto
Aprovar e executar uma decisão no painel (`Workspace.registrar_execucao` → `Store.registrar_execucao`) **não gera nenhuma execução no núcleo**. A execução de uma meta (`ServicoMetas.registrar_execucao`) só nasce do formulário digitado à mão na tela de Metas, ou de cenários de exemplo. Resultado: a conciliação e o avaliador, que são a parte mais cuidadosa do sistema, nunca veem o que os agentes fazem. Hoje a "prova" de uma meta é um arquivo fornecido pelo usuário.

### A2. Dinheiro e tempo com duas semânticas
Carteira: `float` arredondado a 8 casas, `datetime` ingênuo local (`Decision.moment`, `resultado_do_dia`). Núcleo: `Decimal` construído de texto, UTC com fuso obrigatório. Cada fronteira entre os dois exigirá conversão, e erros de arredondamento no livro (`holdings`, `cost_basis`) se acumulam sem alarme. Os testes do livro usam `approx`, o que mascara o problema.

### A3. Preço como estado global mutável
`ASSETS` é mutado no lugar por `MERCADO.aplicar` e lido direto por `store`, `engine` e dezenas de pontos da UI. `Store.validate` e `Workspace.run_agent` leem `datetime.now()` e `MERCADO` diretamente (11 chamadas a `datetime.now()` fora do núcleo, em 5 arquivos). Consequências: não dá para ter dois mercados ao mesmo tempo (por exemplo comparar demonstração e real), cada teste precisa de uma fixture que restaura o global, e o relógio está espalhado, justamente o que o núcleo evita.

### A4. Persistência dividida em três lugares sem integridade entre eles
Configuração e preferências em `QSettings` (JSON), metas e conexões em SQLite, carteiras só em memória. `metas.agente_id` aponta para ids guardados no `QSettings`; `Workspace.remove` não trata as metas do agente removido, que ficam órfãs, e não há restrição que as ligue. As carteiras do mercado real não sobrevivem a reiniciar (limitação já documentada).

### A5. Módulos com várias responsabilidades
`store.py` (494 linhas) mistura dados de demonstração, livro (saldos, custo médio, decisões), cotação e swap, histórico sintético vs. observado, estado do mercado real. `workspace.py` (340) mistura configuração, persistência, orquestração de execução e mercado. `ui/conexoes.py` (561) é a maior tela. Nada está quebrado, mas cada mudança nova (e as duas últimas, mercado real e regras, tocaram os dois) aumenta o custo de entender e testar.

### A6. O domínio importa o adaptador de rede
`workspace.py` importa `Cotacoes` de `conexoes.mercado`. O tipo de dado de mercado pertence ao domínio; o cliente HTTP é que deveria depender dele, não o contrário.

### A7. A interface promete uma coisa que não existe
A tela do agente mostra "próxima execução", e a frequência (hora/dia/semana) é configurável, mas **não há agendador**: nada roda sozinho. É uma lacuna de produto com custo de arquitetura (o agendador precisa de relógio injetado, para continuar testável).

### A8. Padrões de thread diferentes
O atualizador de preços usa fila + timer; o ouvinte do Telegram tem o seu próprio laço. Não revisei a fundo se o ouvinte do Telegram toca em objetos Qt a partir da thread dele. Vale checar com o mesmo critério do atualizador, antes de ligar mais fontes.

## Opções consideradas

### Opção A: ponte por evento (carteira → núcleo)
Manter `Store` como está e criar um adaptador que, a cada execução registrada, converte a decisão (float, hora local) em `Execucao` do núcleo (`Decimal`, UTC) e a entrega ao `ServicoMetas` da meta do agente.

| Dimensão | Avaliação |
|---|---|
| Complexidade | Baixa a média: um adaptador e um teste de equivalência |
| Risco | Baixo: não mexe no livro nem no núcleo |
| Resolve A1 | Sim |
| Resolve A2/A4 | Não: a conversão passa a ser explícita, mas a dívida continua |

**Prós:** destrava a integração já, preserva o que funciona. **Contras:** duas fontes de verdade continuam; a conversão float→Decimal precisa de regra (arredondar pela casa do ativo).

### Opção B: um só modelo (livro em `Decimal` + SQLite)
Mover saldos, custo médio e decisões para o banco, em `Decimal` e UTC, e fazer a UI e o núcleo lerem a mesma fonte. Persistência das carteiras sai de graça.

| Dimensão | Avaliação |
|---|---|
| Complexidade | Alta: toca `store`, `workspace`, `engine`, cards e testes |
| Risco | Médio: muitos testes com `float` e `approx` mudam |
| Resolve A1, A2, A4 | Sim |

**Prós:** uma fonte de verdade, sem conversão, carteiras persistentes. **Contras:** custo alto e risco de regressão na UI.

### Opção C: manter separados
Tratar a carteira como painel de simulação e as metas como sistema à parte, alimentado só por evidência de arquivo ou de conta Binance lida.

| Dimensão | Avaliação |
|---|---|
| Complexidade | Nenhuma |
| Resolve A1 | Não, por escolha: aceita que os agentes não alimentam metas |

**Prós:** zero trabalho. **Contras:** o produto fica com duas metades que não se falam, e o modo mercado real perde sentido.

## Decisão proposta

**Opção A agora, Opção B como destino**, e as duas juntas com uma regra: *toda fronteira entre os blocos passa por um tipo do núcleo (`Decimal`, UTC)*. A ponte (A) entra primeiro porque é pequena e prova o fluxo ponta a ponta; a migração do livro (B) acontece junto com a persistência das carteiras, que já é uma pendência, para fazer uma mudança só no livro.

## Análise de trade-offs

- **Velocidade vs. dívida:** A entrega a integração em dias e deixa a dívida de A2/A4 visível e delimitada num único adaptador. B paga a dívida inteira, mas bloqueia a integração por mais tempo.
- **Risco vs. benefício:** B mexe no que o usuário vê todo dia (cards, histórico, swap). A só adiciona.
- **Coerência com a filosofia do projeto:** o núcleo foi construído para ser a fonte de verdade auditável. Deixar a carteira de fora dele é a exceção, e a ponte a reduz a um ponto controlado.

## Consequências

- **Fica mais fácil:** uma decisão executada pelo agente passa a contar como progresso de meta, com conciliação e trilha; testar a integração ponta a ponta; ligar a leitura de dados da Binance como evidência.
- **Fica mais difícil:** o adaptador vira ponto crítico (regra de arredondamento, taxa em ativo diferente do negociado, fuso da hora local → UTC); é preciso decidir como uma execução simulada se distingue de observada na conciliação (a regra de origem do núcleo já existe e deve ser usada).
- **Reavaliar depois:** quando a carteira persistir, decidir se `QSettings` continua guardando agentes ou se tudo vai para o banco.

## Plano de ação (em ordem)

1. [x] **Ponte carteira → núcleo** (feito: [`PONTE_CARTEIRA_METAS.md`](PONTE_CARTEIRA_METAS.md)). Adaptador `Decisão executada → Execucao`, com conversão explícita (casas do ativo, hora local → UTC), origem *simulada* no mercado real e na demonstração, e teste de equivalência com contas à mão.
2. [x] **Extrair o tipo de mercado do adaptador de rede** (feito): `Cotacoes` vive em `ubento/cotacoes.py`; `conexoes.mercado` depende dele (A6).
3. [x] **Fonte de preços e relógio injetáveis** (feito, A3): `ubento/mercado.py` traz `Mercado` (preços, sinais, frescor e relógio). Cada `Workspace` tem o seu e o entrega a todos os `Store`; um `Store` avulso cria o próprio. Não existem mais `ASSETS` nem `MERCADO` globais e o domínio e as telas não chamam `datetime.now()` (testado). O cadastro dos ativos (`ATIVOS`) é imutável.
4. [x] **Persistir as carteiras do mercado real** (feito, A4): ver [`PERSISTENCIA_CARTEIRAS.md`](PERSISTENCIA_CARTEIRAS.md). Valores em texto decimal e instantes em UTC; carteira de agente removido é arquivada; as metas dele continuam no banco.
5. [~] **Teste de arquitetura para as camadas** (parcial, `tests/test_camadas.py`): núcleo, persistência e conexões não importam a UI; o domínio da carteira não importa adaptadores nem banco; o núcleo não importa o resto do app. Falta a regra "a UI não importa `conexoes` direto, só serviços", que a UI de Configurações hoje não cumpre.
6. [x] **Agendador com relógio injetado** (feito, A7): ver [`AGENDADOR.md`](AGENDADOR.md). Os agentes rodam sozinhos na frequência deles com o app aberto; o relógio é o do `Mercado`.
7. [ ] **Revisar a thread do Telegram** com o critério do atualizador de preços (A8).
8. [ ] **Quebrar `store.py`** em mercado/preços, livro e dados de demonstração, quando o passo 3 ou 4 já tiver mexido nele (A5).
