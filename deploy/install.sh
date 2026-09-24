#!/usr/bin/env bash
# Установка игры на чистый сервер Ubuntu/Debian одной командой:
#   curl -sL https://raw.githubusercontent.com/Ilyas-GR/Game/main/deploy/install.sh | sudo bash
# Повторный запуск обновляет игру до последней версии, база игроков сохраняется.
set -euo pipefail

DIR=/opt/gamebot

if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
    echo "==> Устанавливаю Docker"
    curl -fsSL https://get.docker.com | sh
fi
command -v git >/dev/null || { apt-get update -q && apt-get install -yq git; }

if [ -d "$DIR/.git" ]; then
    echo "==> Обновляю код"
    git -C "$DIR" pull -q
else
    echo "==> Скачиваю игру"
    git clone -q https://github.com/Ilyas-GR/Game.git "$DIR"
fi
cd "$DIR"

if [ ! -f .env ]; then
    read -rp "Токен бота от @BotFather: " TOKEN </dev/tty
    read -rp "Твой Telegram ID для админки (Enter — пропустить): " ADMIN </dev/tty
    sed -e "s|^BOT_TOKEN=.*|BOT_TOKEN=$TOKEN|" -e "s|^ADMIN_IDS=.*|ADMIN_IDS=$ADMIN|" .env.example > .env
    chmod 600 .env
fi

echo "==> Запускаю бота"
docker compose up -d --build
sleep 5
docker compose logs --tail 20
echo
echo "Готово! Бот работает круглосуточно и сам поднимется после перезагрузки сервера."
echo "Логи:      cd $DIR && docker compose logs -f"
echo "Обновить:  повтори команду установки"
