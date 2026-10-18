# Conexões com corretoras

Em **Configurações → Conexões** a pessoa liga uma corretora ao UBento informando uma chave de API **somente leitura**. Hoje existe um
provedor, a **Binance** (spot); os outros entram pelo mesmo caminho: um `Provedor` em `ubento/conexoes/provedores.py`, um cliente com
`verificar()` e o desenho do logo em `ui/conexoes.py`.

**Escopo desta etapa:** guardar a credencial com segurança e **verificar** que a chave é somente leitura. O UBento ainda **não importa
dados** da corretora (ordens, saldos): isso vem depois e entrará como registros externos para a conciliação.

## Lugar reservado: bot do Telegram
O catálogo já tem o **Telegram** como provedor *reservado* (`disponivel=False`): aparece em Conexões com o logo e o selo "Em breve", não se escolhe
no diálogo e o serviço recusa conectá-lo ("ainda não está disponível"). **Nada é pedido, enviado nem guardado.** Para ativá-lo depois: declarar o
campo do token do bot, escrever um cliente com `verificar()` (por exemplo, `getMe`), trocar `disponivel=True` e decidir o que o bot faz
(avisos, consultas somente leitura). O token terá o mesmo tratamento da chave da Binance: só no cofre, nunca no banco, no log ou no MCP.

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
