# Radar de Milhas — montagem em 15 minutos

Depois disto, o radar roda sozinho: um robô do GitHub varre 39 fontes a cada 30 minutos,
publica o resultado no seu site e te manda a promoção no Telegram. Nada depende do Claude
nem do seu computador estar ligado.

---

## Passo 1 — criar o repositório (3 min)

1. Entre em <https://github.com/new>.
2. Nome: `radar-milhas`. Marque **Public** (o GitHub Pages grátis exige repositório público;
   o conteúdo aqui é só notícia pública de milhas).
3. Crie sem README, sem .gitignore.
4. Na tela seguinte, clique em **uploading an existing file** e arraste **todo o conteúdo
   desta pasta** — inclusive a pasta `.github`. Se o navegador não deixar arrastar a
   `.github`, use o botão "choose your files" e selecione tudo.
5. Clique em **Commit changes**.

> Se a pasta `.github` não subir, o robô não roda. Confira depois se a aba **Actions**
> mostra o fluxo "Radar de Milhas".

## Passo 2 — ligar o site (2 min)

1. No repositório: **Settings → Pages**.
2. Em "Source", escolha **Deploy from a branch**; branch **main**, pasta **/ (root)**.
3. Salve. Em 1 ou 2 minutos o endereço aparece no topo da mesma tela, algo como
   `https://SEU-USUARIO.github.io/radar-milhas/`.

Esse é o endereço do app. Abra no celular e instale:

- **iPhone (Safari):** botão de compartilhar → *Adicionar à Tela de Início*.
- **Android (Chrome):** menu ⋮ → *Instalar app*.

## Passo 3 — criar o bot do Telegram (3 min)

1. No Telegram, procure por **@BotFather** e envie `/newbot`.
2. Dê um nome qualquer (ex.: `Radar de Milhas`) e um usuário terminado em `bot`
   (ex.: `gabriel_radar_milhas_bot`).
3. Ele responde com um **token** parecido com `8123456789:AAH...`. Guarde.
4. Abra uma conversa com o **seu** bot e mande qualquer mensagem (um "oi" basta).
   Sem isso o Telegram bloqueia o bot de te escrever primeiro.
5. Descubra o seu **chat id**: procure por **@userinfobot** no Telegram e mande `/start`.
   Ele responde com o seu `Id` — um número, às vezes com sinal de menos.

## Passo 4 — guardar os segredos no GitHub (2 min)

No repositório: **Settings → Secrets and variables → Actions → New repository secret**.
Crie dois:

| Nome | Valor |
|---|---|
| `TELEGRAM_TOKEN` | o token do BotFather |
| `TELEGRAM_CHAT_ID` | o número do @userinfobot |

Os segredos ficam guardados pelo GitHub e não aparecem no código nem nos logs.

## Passo 5 — primeira rodada na mão (1 min)

1. Aba **Actions** → fluxo **Radar de Milhas** → botão **Run workflow** → **Run workflow**.
2. Em 2 ou 3 minutos ele termina. Abra o log para ver a linha final, algo como
   `novos: 371 | alertas enviados: 11 | total no dados.json: 371`.
3. Se houver boa promoção, ela chega no Telegram na hora.

Pronto. A partir daí roda sozinho a cada 30 minutos.

---

## O que vira notificação

**1. Erro de tarifa — prioridade máxima.** Vai em seção própria no topo do app e chega no
Telegram com 🚨, antes de qualquer outra coisa. Além do texto do título, o radar reconhece
pela própria URL (Secret Flying e TarifasError põem `error-fare` / `tarifa-error` no link).

**2. Bônus de transferência acima da régua do programa de destino.** Um percentual sozinho
não diz nada: 25% na LATAM ou na Iberia é o patamar que vale agir, e 25% na Smiles não é
notícia nenhuma. A régua:

| Programa de destino | Bônus que vira alerta |
|---|---|
| LATAM Pass | 25% |
| Iberia / Avios | 25% |
| ConnectMiles (Copa) | 65% |
| Smiles | 80% |
| Azul Fidelidade | 80% |
| TAP Miles&Go | qualquer um (praticamente nunca tem) |
| programa não reconhecido | 80% |

**3. Promo award e resgate com desconto** — Flying Blue Promo Rewards, award sale da Iberia,
descontos Smiles e LATAM.

**4. Compra de pontos com 100% de bônus** ou mais.

**5. Executiva ou primeira com preço estimado até R$ 6.000** ida e volta.

Para mexer nos números, edite o topo de `scripts/radar.py`:

```python
LIMIAR_BONUS = {
    "LATAM Pass":   25,
    "Iberia/Avios": 25,
    "Smiles":       80,
    "Azul":         80,
    "ConnectMiles": 65,
    "TAP":           1,
}
LIMIAR_PADRAO = 80          # programa não reconhecido
TETO_EXECUTIVA_BRL = 6000   # preço máximo de cabine premium para virar alerta
```

No app, o teto de preço também é editável em **Filtros**, mas ali vale só para o que você
vê na tela; quem decide a notificação é o `radar.py`.

## Mexer nas fontes

Em `scripts/radar.py`, a lista `SOURCES` tem 39 linhas no formato
`("Nome", "url do feed", "tipo", "idioma", "região")`. O tipo é `rss` para feed normal,
`tg` para canal público de Telegram e `sf` para a Secret Flying, que precisa de um
tratamento próprio. Para remover uma fonte, apague a linha; para adicionar, copie o
formato. Depois de editar, **Commit changes** — a próxima rodada já usa a lista nova.

## Manutenção e pegadinhas

- **O GitHub desliga fluxos agendados em repositório parado há 60 dias.** Se você não
  mexer no repositório por dois meses, ele avisa por e-mail e basta reativar num clique.
  Um commit qualquer reinicia a contagem.
- **O horário do cron é UTC** e o GitHub costuma atrasar alguns minutos em horário de pico.
  Para erro de tarifa isso é aceitável; se quiser mais frequência, troque `*/30` por
  `*/15` no arquivo `.github/workflows/radar.yml` (abaixo de 15 min o GitHub ignora).
- **O robô comita `dados.json` e `estado.json` a cada rodada.** Isso enche o histórico de
  commits — é normal e não atrapalha.
- **O `estado.json` guarda o que já foi avisado**, para você não receber a mesma promoção
  duas vezes. Ele também agrupa por assunto: um bônus de 25% para a LATAM Pass sai no
  Passageiro de Primeira, no Pontos pra Voar e no Telegram do Melhores Destinos, e você
  recebe **uma** mensagem — as outras ficam guardadas por 48h. Erro de tarifa nunca é
  agrupado, porque cada um é um voo diferente. Se apagar esse arquivo, a próxima rodada
  reenvia tudo que estiver ativo.
- **Fonte com erro não quebra a rodada.** O log lista quais falharam, e o app mostra o
  mesmo em "estado das fontes". Reddit costuma dar 429 de vez em quando; é passageiro.
- **Aparecendo muita notificação**, suba o número do programa que estiver enchendo o saco
  em `LIMIAR_BONUS`, ou baixe `TETO_EXECUTIVA_BRL`. **Aparecendo pouca**, faça o contrário.
  Os valores da régua vieram do Super Mapa do Vitão e do seu ajuste — revise quando o
  mercado mudar de patamar.

## Como testar o Telegram sem esperar

Aba **Actions** → **Run workflow**. Se nada chegar, confira nessa ordem: você mandou
mensagem para o bot primeiro; o `TELEGRAM_CHAT_ID` é o seu número e não o do bot; e o
log da rodada não traz uma linha começando com `! telegram:`.
