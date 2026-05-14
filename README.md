# Bot Telegram para vetorizar imagens

Este bot recebe uma imagem no Telegram e devolve um arquivo vetorizado. Por padrao ele usa a API HTTP oficial do Vectorizer.AI; tambem pode usar a automacao do site ou VTracer local como fallback.

## Como configurar

1. Crie o bot no Telegram pelo `@BotFather` e copie o token.
2. Instale as dependencias:

```powershell
cd C:\Users\Usuario\Downloads\PENAL\telegram-vectorizer-bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3. Crie o arquivo `.env`:

```powershell
Copy-Item .env.example .env
notepad .env
```

4. Preencha:

```env
TELEGRAM_BOT_TOKEN=token_do_botfather
```

5. Rode o bot:

```powershell
python bot.py
```

## Uso

Envie uma imagem para o bot. Para preservar qualidade e transparencia, envie PNG/JPG como arquivo/documento em vez de foto comprimida.

Comandos:

- `/start` inicia o bot.
- `/help` mostra os ajustes de vetorizacao.
- `/login` abre o navegador do Vectorizer.AI para fazer login e salvar cookies no perfil local.

## Ajustes

O parametro `VECTORIZATION_PROVIDER` no `.env` controla o provedor. Use `vectorizer_ai_api` para a API oficial do Vectorizer.AI, `vectorizer_ai` para automacao do site ou `local` para VTracer.

O parametro `OUTPUT_FORMAT` no `.env` controla o formato de retorno. Com `vectorizer_ai_api` ou `vectorizer_ai`, use `eps`, `svg`, `pdf`, `dxf` ou `png`. Com `local`, use `eps` ou `svg`.

Na Discloud, prefira `VECTORIZATION_PROVIDER=vectorizer_ai_api`, porque a automacao do site pode falhar ao conectar no WebSocket de processamento do Vectorizer.AI.

Os parametros `VTRACER_*` no `.env` controlam qualidade, quantidade de detalhes e velocidade. Para logotipos e artes simples, os valores padrao costumam funcionar bem.

## Deploy em VPS

Para rodar 24/7 em uma VPS Ubuntu, veja `DEPLOY_VPS.md`. O bot usa polling do Telegram, entao nao precisa expor porta HTTP.

## Deploy na Discloud

Para subir pela tela GitHub da Discloud, veja `DEPLOY_DISCLOUD.md`. O arquivo `discloud.config` ja esta na raiz do projeto.
