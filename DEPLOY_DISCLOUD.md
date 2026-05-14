# Deploy na Discloud

Este projeto pode ser enviado pela tela de deploy GitHub da Discloud usando a branch `main`.

## Configuracao criada

O arquivo `discloud.config` fica na raiz do projeto, como a Discloud exige:

```env
NAME=bot-vectorize-IA
TYPE=bot
MAIN=bot.py
RAM=1024
VERSION=latest
AUTORESTART=true
APT=tools, puppeteer
BUILD=python -m playwright install chromium
START=python bot.py
```

O `APT=puppeteer` instala bibliotecas Linux usadas por Chromium. O `BUILD` instala o Chromium do Playwright.

## Variaveis de ambiente

Na tela da Discloud, em "Variaveis de ambiente", use "Colar .env" e cole:

```env
TELEGRAM_BOT_TOKEN=COLE_SEU_TOKEN_REAL_AQUI
TELEGRAM_MAX_FILE_MB=20
TELEGRAM_TIMEOUT_SECONDS=180
OUTPUT_FORMAT=eps
VECTORIZATION_PROVIDER=vectorizer_ai
VECTORIZER_AI_URL=https://pt.vectorizer.ai/
VECTORIZER_AI_HEADLESS=true
VECTORIZER_AI_PROFILE_DIR=.vectorizer-ai-profile
VECTORIZER_AI_TIMEOUT_SECONDS=300
VECTORIZER_AI_LOGIN_SECONDS=300
VECTORIZER_AI_INPUT_MAX_PIXELS=3000000
VECTORIZER_AI_OFFSCREEN_PROCESSING=false
VECTORIZER_AI_FINAL_DOWNLOAD_DELAY_SECONDS=0
VECTORIZER_AI_DIRECT_DOWNLOAD_TIMEOUT_SECONDS=90
VECTORIZER_AI_DOWNLOAD_LINK_TIMEOUT_SECONDS=90
PLAYWRIGHT_AUTO_INSTALL=true
VECTORIZER_AI_COOKIE_NAME=VK
VECTORIZER_AI_COOKIE_VALUE=
VECTORIZER_AI_COOKIE_DOMAIN=.vectorizer.ai
VECTORIZER_AI_COOKIE_HEADER=
VECTORIZER_AI_COOKIES_JSON=COLE_A_LINHA_EXPORTADA_AQUI
VECTORIZER_AI_COOKIES_FILE=
```

Nao cole aspas. Nao coloque o token no GitHub.

Se a Discloud nao baixar o Chromium durante o build, `PLAYWRIGHT_AUTO_INSTALL=true` faz o bot baixar automaticamente na primeira tentativa de abrir o navegador.

O jeito mais confiavel e usar `VECTORIZER_AI_COOKIES_JSON`, porque ele leva o `VK` e os cookies auxiliares do Vectorizer.AI juntos. Deixe `VECTORIZER_AI_COOKIE_VALUE` vazio quando usar o JSON completo.

Para usar todos os cookies do perfil local, rode `python scripts/export_vectorizer_ai_cookies.py` no seu PC com o bot parado. Ele gera `.vectorizer-ai-cookies.env`; cole a linha `VECTORIZER_AI_COOKIES_JSON=...` nas variaveis da Discloud.

## Limitacao importante

Na Discloud, o navegador precisa rodar em modo `headless=true`, porque a hospedagem nao fornece uma janela visual como no seu PC. Se o Vectorizer.AI bloquear ou travar em modo headless, a alternativa correta e usar uma VPS com `Xvfb`, conforme `DEPLOY_VPS.md`.

## Arquivos ignorados

O arquivo `.discloudignore` impede envio de `.env`, `.venv`, logs, cache, cookies e temporarios.
