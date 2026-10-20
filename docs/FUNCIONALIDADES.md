# Funcionalidades do UBento

Catálogo do que o app faz hoje, com o estado de cada coisa. Detalhes de cada área estão nos documentos ligados em cada seção.

**Legenda:** ✅ pronto e testado · 🟡 funciona com ressalva (dita ao lado) · 🔌 só testado com respostas simuladas, nunca contra o serviço real · ⏳ ainda não existe.

UBento é um painel financeiro de desktop (Windows), feito em Python + PySide6 + SQLite. Os dados de demonstração são o padrão. O **mercado real** troca preços e carteira por dados vivos, sem enviar nenhuma ordem a corretora alguma.

---

## 1. Painel e agentes

| Funcionalidade | Estado | Como funciona |
|---|---|---|
| Abas por agente + aba **Geral** | ✅ | Cada agente é uma carteira com saldos, decisões e configuração próprios. O Geral soma todos (somente leitura). |
| Gerenciar abas | ✅ | Botão `+` cria agente; botão direito na aba: renomear, mudar a cor, duplicar, mover, remover. Arrastar reordena. |
| Cards do painel | ✅ | Saldo em cripto, Saldo total (1S · 1M · 6M · 1A · Tudo), Resumo do mês, Atividade, Swap, Decisões, USDC, Agentes. Os principais expandem em tela cheia. |
| Swap manual | ✅ | Cotação com taxa de serviço e de rede, inverter, validação de saldo; a troca vira uma decisão no log. |
| **Decisões como log** | ✅ | Cada linha traz valor aplicado, taxa, resultado (verde no lucro, vermelho na perda) e data/hora. Resultado já líquido de taxa. Compra mostra "em aberto"; venda e troca mostram "realizado". |
| Ocultar valores | ✅ | Mascara todos os valores (ícone de olho ou Configurações). |
| Janela sem moldura | 🟡 | O header é a barra da janela: arrastar, duplo clique maximiza, minimizar/maximizar/fechar, redimensionar pela borda de 6 px. Testado em modo offscreen; falta conferir o arrastar e redimensionar com o mouse no Windows. |
| Configurações gerais | ✅ | Nome, ocultar valores, período padrão do gráfico, mercado real, conexões, restaurar dados e abas. |

## 2. Agentes que decidem

Configuração por agente (tela **Configurar**), salva na hora. Detalhes em [`REGRAS_DE_RISCO.md`](REGRAS_DE_RISCO.md).

| Funcionalidade | Estado | Como funciona |
|---|---|---|
| Algoritmos | ✅ | **Tendência** (compra ativos em alta, stop-loss e take-profit), **Rebalanceamento**, **Média de custo (DCA)**, **Conservador**, **Manual**. |
| Parâmetros | ✅ | Risco 1–5, posição máxima por ativo, reserva em caixa, tamanho de cada compra, stop-loss, take-profit, desvio para rebalancear. A tela só mostra os relevantes ao algoritmo. |
| Ativos permitidos | ✅ | ETH, SOL, AVAX, BNB (pelo menos um). |
| Modo de execução | ✅ | **Automático** (executa), **Pedir aprovação** (propõe), **Só sugerir** (registra, nunca executa). |
| Frequência e agendador | ✅ | A cada hora / diária (9h) / semanal (segunda, 9h). Com o app aberto, o agente roda sozinho no horário (um interruptor em Configurações desliga). Horários perdidos viram uma execução ao abrir; mercado real sem preço fresco espera. Só com o app aberto. Ver [`AGENDADOR.md`](AGENDADOR.md). |
| Aprovar ≠ executar | ✅ | Aprovar uma proposta (✓) só autoriza; os saldos mudam quando a execução é registrada, num passo separado. |
| **Regras de risco** (caixas) | ✅ | Risco por operação (0,5 · 0,75 · 1%), stop diário (2× · 3×), meta de ganho diária (2× · 3× · 4×) e tamanho da posição pela fórmula `risco ÷ stop`. Pacote padrão com um clique. Só as compras são limitadas; vendas nunca. |

## 3. Mercado real (Binance)

Detalhes em [`MERCADO_REAL.md`](MERCADO_REAL.md).

| Funcionalidade | Estado | Como funciona |
|---|---|---|
| Preços ao vivo | 🟡 | API pública da Binance (sem chave), a cada 15 s, em segundo plano. Consultada de verdade; falta uso prolongado. |
| Carteira própria | ✅ | Na primeira vez, US$ 10.000 simulados por agente, sem posições, decisões nem dados de demonstração. **Persiste** no SQLite: reiniciar ou desligar e religar o modo devolve saldos, custo médio, decisões e gráfico. Ver [`PERSISTENCIA_CARTEIRAS.md`](PERSISTENCIA_CARTEIRAS.md). |
| Histórico observado | ✅ | Gráfico do patrimônio realmente visto (um ponto por minuto); antes da carteira existir, a linha é o capital inicial. |
| Sinal real dos agentes | ✅ | A estratégia Tendência usa a variação real de 7 dias, sem cortes. |
| Segurança de preço | ✅ | Sem leitura nos últimos 120 s, agentes e swap não operam. Resposta inválida ou incompleta é descartada inteira. Falha de rede mantém o último preço e mostra o motivo. |
| Ordens | — | **Nenhuma ordem vai à Binance.** Compras e vendas são simuladas, com a taxa de 0,10% do spot. |

## 4. Metas, conciliação e avaliação

O coração do projeto: um núcleo determinístico, sem Qt, rede nem relógio do sistema. Contratos em [`ESPECIFICACAO_NUCLEO.md`](ESPECIFICACAO_NUCLEO.md), [`CONCILIACAO.md`](CONCILIACAO.md) e [`AVALIACAO_META.md`](AVALIACAO_META.md); persistência e tela em [`PERSISTENCIA_E_INTERFACE.md`](PERSISTENCIA_E_INTERFACE.md).

| Funcionalidade | Estado | Como funciona |
|---|---|---|
| Metas | ✅ | Documento YAML/JSON validado (tipos estritos, `Decimal`, UTC) com hash canônico; ativação, prazo, carência, escopo, orçamento. |
| Conciliação | ✅ | Compara cada execução interna com os registros externos (taxas, quantidade recebida, parciais, duplicidades, correções) e dá um status: conciliada, divergente, pendente, sem registro externo, não verificável, revisão. |
| Identidade do registro externo | ✅ | `(fonte, id externo)`. Reimportar a mesma operação (só muda o `recebido_em`) não cria conflito; mudar quantidade, preço, taxa ou status continua sendo detectado. |
| Contexto e origem | ✅ | Ativo, moeda, mercado e conta têm de bater com a meta; só prova observado×observado ou simulado×simulado; cada (conta, mercado) tem a sua fonte autorizada. |
| Avaliador | ✅ | Execução → conciliação → progresso → avaliação → eventos → estado, com carência, escopo de órfãos, orçamento (custo total, pior caso) e reconciliação posterior. Lista o que não avaliou. |
| Relógio explícito | ✅ | Meta de **cenário** usa o instante do cenário; meta **real** usa UTC do computador, que nunca anda para trás. Nada avalia sozinho: a meta não expira porque o tempo passou. |
| Persistência | ✅ | SQLite append-only (triggers), escrita exclusiva (`BEGIN IMMEDIATE`), timeout claro de banco ocupado. Banco ao lado do app. |
| Tela de **Metas** | ✅ | Progresso, pendências, eventos, última avaliação (com a origem do instante). |
| Registrar execução | ✅ | Formulário de execução da meta, com validação. |
| Vínculo manual e correção | ✅ | Ligar uma execução a um registro externo com justificativa; revogar ou substituir com trilha auditável; um registro não serve a duas metas. |
| **Ponte carteira → metas** | ✅ | Uma compra executada por um agente vira execução (simulada, sem registro externo, em `Decimal` e UTC) das metas de cenário do mesmo agente e do mesmo ativo. Vendas, metas reais e metas encerradas ficam de fora. Ver [`PONTE_CARTEIRA_METAS.md`](PONTE_CARTEIRA_METAS.md). |
| Cenários de exemplo | ✅ | `exemplos/` traz cenários fictícios de reprodução; `scripts/gerar_cenarios_*.py` os regenera. |

**Limitações conhecidas:** a evidência externa é um arquivo fornecido pelo usuário com campos autodeclarados, então a autenticidade não é provada; com duas fontes não há união automática; taxa em um terceiro ativo deixa o orçamento indeterminado; `exposicao_maxima` abaixo de 1 impede concluir a meta; bancos antigos com cenários simulados precisam reimportar os cenários regenerados.

## 5. Conexões e acesso externo

Detalhes em [`CONEXOES.md`](CONEXOES.md) e [`MCP_LOCAL.md`](MCP_LOCAL.md).

| Funcionalidade | Estado | Como funciona |
|---|---|---|
| Cofre de segredos | ✅ | Chave e segredo ficam só no cofre do Windows (DPAPI), nunca no banco. |
| Binance (chave somente leitura) | 🔌 | Confere na Binance o que a chave pode fazer e **recusa** qualquer poder além da leitura (saque, transferência, negociação, margem, futuros, opções). Várias conexões por provedor (por exemplo, uma por subconta). Hoje só guarda e verifica a credencial: **não lê saldos nem ordens ainda**. |
| Bot do Telegram | 🔌 | Token no cofre; o chat é vinculado por código de uso único; só o chat vinculado é atendido. Comandos de consulta: `/metas`, `/progresso`, `/pendencias`, `/historico`, `/ajuda`. Só responde com o app aberto; cada mensagem abre o banco somente para leitura. |
| Servidor MCP local | ✅ | Somente leitura (`python -m ubento.mcp_local`, SDK oficial, extra `ubento[mcp]`): `listar_metas`, `consultar_meta`, `consultar_progresso`, `consultar_pendencias`, `consultar_historico`. Não enxerga conexões nem cofre. |

## 6. Qualidade e distribuição

| Item | Estado |
|---|---|
| Testes automatizados | ✅ 855 testes (núcleo com testes de propriedade, concorrência, interface offscreen) e `pyflakes` limpo |
| Instalador Windows | 🟡 `scripts/build_windows.ps1` (PyInstaller + Inno Setup); não reexecutado nas últimas mudanças |
| Capturas de tela | ✅ `scripts/screenshot.py` renderiza a janela inteira para conferir o visual |

## 7. O que ainda não existe

- ⏳ **Ler dados da conta Binance** (saldos, execuções) como evidência externa: é o próximo passo natural da conexão.
- ⏳ Persistir as carteiras de **demonstração** (hoje só a do mercado real persiste, de propósito).
- ⏳ **Avaliação automática das metas**: o agendador roda os agentes, mas as metas só se avaliam quando alguém pede (reavaliar, registrar, vincular).
- ⏳ **Executar ordens reais**: por decisão de projeto, o app só lê; isso exigiria uma mudança explícita de política e de permissão de chave.
- ⏳ Testar Binance e Telegram contra os serviços reais, e o arrastar/redimensionar da janela com o mouse.
