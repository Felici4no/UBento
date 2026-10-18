# Conexões (corretoras e bot do Telegram)

Em **Configurações → Conexões** a pessoa liga uma corretora ao UBento informando uma chave de API **somente leitura**, e um bot do Telegram
para consultar as metas pelo celular. Hoje há a **Binance** (spot) e o **Telegram**; os outros entram pelo mesmo caminho: um `Provedor` em `ubento/conexoes/provedores.py`, um cliente com
`verificar()` e o desenho do logo em `ui/conexoes.py`.

**Escopo desta etapa:** guardar a credencial com segurança e **verificar** que a chave é somente leitura. O UBento ainda **não importa
dados** da corretora (ordens, saldos): isso vem depois e entrará como registros externos para a conciliação.

## Bot do Telegram
Um bot para **consultar as metas pelo celular**. Só leitura: ele usa a mesma camada de consulta do MCP (`ubento.consulta`) e não importa, não
reavalia nem grava nada.

### Como configurar
1. No Telegram, abra o **@BotFather**, envie `/newbot`, escolha nome e @usuário e copie o **token** (`123456789:AA…`).
2. UBento → Configurações → Conexões → **Adicionar conexão → Telegram**, cole o token e clique em *Verificar e conectar*
   (o app chama `getMe` para confirmar que é um bot e mostra o @usuário).
3. Clique em **Vincular chat**: o UBento mostra um código (`/vincular 8E972995`). Abra uma conversa **privada** com o seu bot e envie essa mensagem.
   O código vale 10 minutos, só pode ser usado uma vez e só existe na memória do app.
4. Pronto: a linha mostra "vinculado a <seu nome>" e a etiqueta **Atendendo**. *Enviar teste* manda uma mensagem ao seu chat.

### Quem o bot atende
- **Só o chat vinculado** (conversa privada cujo id é o seu). Mensagens de qualquer outro usuário, de grupos ou de canais são **ignoradas em silêncio**:
  nem um "não autorizado" é enviado, então quem achar o bot não aprende nada. O texto das mensagens e o token nunca vão para o log.
- Código errado, código de grupo ou código expirado não vinculam nada. *Desvincular* faz o bot parar de responder (o token continua guardado).

### O que ele responde (só consulta)
`/metas`, `/progresso [meta]`, `/pendencias [meta]`, `/historico [meta] [n]`, `/ajuda`. Sem `[meta]`, vale a única meta existente.
**Toda resposta diz a data da última avaliação gravada e que não é tempo real**, e avisa quando há entradas mais novas que ela.
Qualquer outra coisa recebe "Não entendi" ou a ajuda: não existe comando que escreva.

### O que você precisa saber
- **Só atende com o UBento aberto**: o app escuta o bot enquanto roda (long polling, sem servidor nem webhook). Fechado, o bot fica mudo;
  o que for enviado nesse período é **descartado** ao reabrir (o app não responde a pedidos velhos).
- **Privacidade:** as respostas passam pelos servidores do Telegram (conversas com bots não têm criptografia de ponta a ponta) e ficam no
  histórico do seu chat. Só vincule um chat que você controla.
- **Um programa por bot:** o Telegram permite um único consumidor de `getUpdates` por bot. Se outro programa usar o mesmo bot (ou ele tiver
  webhook), o ouvinte para e a etiqueta mostra "Bot em uso por outro programa". Use um bot só para o UBento.
- O token é só do cofre (DPAPI); o banco guarda o @usuário do bot, o trecho mascarado e o chat vinculado (id e nome). Se o token vazar,
  revogue-o no @BotFather (`/revoke`) e remova a conexão.

### Limites conhecidos
- **Não foi testado contra o Telegram de verdade** (testes com transporte falso e com estado). Os métodos (`getMe`, `getUpdates` com `offset`
  e `timeout`, `sendMessage`) e os códigos de erro seguem a documentação do Bot API como eu a conheço; confira com um bot seu (roteiro abaixo).
- Sem avisos proativos (o bot só responde): empurrar notificações de mudança de estado fica para depois.
- Um chat vinculado por bot. Sem comandos de escrita, por desenho.

### Roteiro para conferir com o seu bot
1. Crie um bot de teste no @BotFather e conecte-o como acima. Esperado: **Conectada**, com o @usuário certo.
2. *Vincular chat* e envie o código. Esperado: "vinculado a …" e **Atendendo**.
3. No chat, envie `/metas`. Esperado: lista com "avaliada em …" e "não é tempo real" (ou "Nenhuma meta cadastrada").
4. Peça a outra pessoa (ou use uma segunda conta) para mandar `/metas` ao bot. Esperado: **nenhuma resposta**.
5. Feche o UBento e envie `/metas`: sem resposta. Reabra: o pedido antigo não é respondido.

## O que acontece ao conectar
1. **Validação local** (sem rede): os dois campos preenchidos, só letras e números, tamanho plausível; a mesma chave não conecta duas vezes.
2. **Verificação na corretora** (rede, fora da thread da interface): `GET /sapi/v1/account/apiRestrictions` assinado com HMAC-SHA256. A chave só
   é aceita se tiver **leitura** e **nenhum outro poder**: saques, transferências (internas/universal), negociação spot/margem, margem,
   futuros ou opções. Qualquer um deles reprova a conexão, e **nada é gravado**.
3. **Gravação** (só se aprovada): chave e segredo vão para o **cofre**; o banco guarda apenas o apelido, um trecho mascarado (`AbCd…StUv`),
   uma impressão (hash) para evitar duplicidade, o status e a mensagem da última verificação.

## Onde ficam os segredos
| Onde | O que guarda |
| --- | --- |
| Cofre (Windows: **DPAPI**, `cofre.json` ao lado do banco) | chave de API e segredo, cifrados para o seu usuário do Windows nesta máquina |
| SQLite (`conexoes`) | apelido, trecho mascarado, impressão, status, permissões da última verificação. **Nenhum segredo, nenhuma chave inteira** |
| Logs, mensagens de erro, MCP | nada: segredo e chave nunca entram (a chave/segredo que a corretora ecoar em erro é substituída por `***`) |

Fora do Windows o cofre usa o chaveiro do sistema se o pacote opcional `keyring` estiver instalado; sem ele o UBento **recusa conectar**
em vez de gravar a chave em texto puro. Testes e capturas de tela usam um cofre em memória: nunca tocam o cofre real.
O MCP local (`docs/MCP_LOCAL.md`) só lê metas e não enxerga conexões nem cofre (há um teste para isso).

## Estados e mensagens
- **Conectada**: a última verificação confirmou leitura e nada além disso.
- **Reprovada**: a chave passou a ter poderes demais (ou perdeu a leitura). Crie outra chave só de leitura e remova esta.
- **Falha na verificação**: rede, limite de requisições, relógio fora de sincronia, chave inválida ou apagada, IP não autorizado; a mensagem diz qual.
- **Testar** reverifica; **Remover** apaga a chave do cofre e a conexão do banco (a chave continua válida na Binance até ser revogada lá).

## Limites conhecidos
- **Não foi testado contra a Binance de verdade.** Os testes usam um transporte falso; o endpoint, os campos de permissão e os códigos de erro
  seguem a documentação da API como eu a conheço e **precisam ser conferidos com uma chave real somente leitura** (roteiro abaixo).
- Só a Binance spot (`api.binance.com`). Sem Testnet, sem outras regiões (ex.: Binance.US).
- A verificação exige internet. Sem ela não é possível conectar (não se grava chave não verificada).
- Uma chave comprometida no cofre do Windows é legível por processos do **mesmo usuário** (limite do DPAPI).

## Roteiro para conferir com a sua chave
1. Na Binance, crie uma chave com **só "Enable Reading"** (de preferência com restrição ao IP do computador).
2. UBento → Configurações → Conexões → **Adicionar conexão**, cole chave e segredo e clique em *Verificar e conectar*. Esperado: **Conectada**.
3. Teste a recusa: crie outra chave com "Enable Spot & Margin Trading" e tente conectar. Esperado: recusada, citando "negociação".
4. Confira que `ubento.db` não contém a chave: `python -c "print(open(r'%LOCALAPPDATA%\\UBento\\ubento.db','rb').read().count(b'SUA_CHAVE'))"` deve imprimir `0`.
