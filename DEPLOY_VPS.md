# Deploy em VPS Ubuntu

Este guia assume Ubuntu 22.04/24.04 e uso do Vectorizer.AI com Playwright.

## Como vai ficar

- O codigo fica clonado em `/opt/telegram-vectorizer-bot`.
- O token do Telegram fica somente no arquivo `.env` da VPS.
- O bot roda como servico `systemd`, reiniciando sozinho se cair.
- O Chromium do Playwright roda com `Xvfb`, uma tela virtual para servidor sem monitor.
- Cookies/login do Vectorizer.AI ficam em `.vectorizer-ai-profile` na propria VPS.

## 1. Instalar dependencias da VPS

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip xvfb
```

## 2. Baixar o projeto

Depois que o repositorio estiver no GitHub:

```bash
sudo git clone https://github.com/SEU_USUARIO/telegram-vectorizer-bot.git /opt/telegram-vectorizer-bot
sudo chown -R $USER:$USER /opt/telegram-vectorizer-bot
cd /opt/telegram-vectorizer-bot
```

Se o repositorio for privado, use SSH ou autentique o GitHub na VPS antes do clone.

## 3. Criar ambiente Python

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install --with-deps chromium
```

## 4. Configurar `.env`

```bash
cp .env.example .env
nano .env
```

Preencha no minimo:

```env
TELEGRAM_BOT_TOKEN=SEU_TOKEN_DO_BOTFATHER
OUTPUT_FORMAT=eps
VECTORIZATION_PROVIDER=vectorizer_ai
VECTORIZER_AI_HEADLESS=false
VECTORIZER_AI_PROFILE_DIR=.vectorizer-ai-profile
```

Nao suba o `.env` para o GitHub.

## 5. Login do Vectorizer.AI

O perfil `.vectorizer-ai-profile` guarda a sessao do Vectorizer.AI. Em VPS existem duas formas praticas:

1. Fazer login em uma VPS com desktop/noVNC e usar o comando `/login` do bot.
2. Copiar a pasta `.vectorizer-ai-profile` da sua maquina local para a VPS.

Para copiar a pasta local por SSH:

```bash
scp -r .vectorizer-ai-profile usuario@IP_DA_VPS:/opt/telegram-vectorizer-bot/.vectorizer-ai-profile
```

Essa pasta contem cookies de login. Trate como arquivo sensivel.

## 6. Instalar o servico systemd

```bash
sudo cp deploy/telegram-vectorizer-bot.service /etc/systemd/system/telegram-vectorizer-bot.service
sudo systemctl daemon-reload
sudo systemctl enable telegram-vectorizer-bot
sudo systemctl start telegram-vectorizer-bot
```

Ver logs:

```bash
sudo journalctl -u telegram-vectorizer-bot -f
```

Reiniciar apos atualizar codigo:

```bash
cd /opt/telegram-vectorizer-bot
git pull
. .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart telegram-vectorizer-bot
```

## Observacoes

- Use uma VPS com pelo menos 2 GB de RAM; 4 GB e mais confortavel para Chromium.
- Se o Vectorizer.AI pedir login novamente, rode `/login` em ambiente com tela ou copie de novo o perfil local.
- O bot usa polling do Telegram, entao nao precisa abrir porta HTTP na VPS.
