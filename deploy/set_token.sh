#!/usr/bin/env bash
# Вписывает токен бота в .env и перезапускает бота.
#   ssh -t сервер ~/gamebot/deploy/set_token.sh
set -eu
cd "$(dirname "$0")/.."

read -rp "Вставь токен бота и нажми Enter: " input
token=$(printf '%s' "$input" | grep -oE '[0-9]{8,12}:[A-Za-z0-9_-]{35}' | head -1 || true)
if [ -z "$token" ]; then
    echo "❌ Это не похоже на токен. Он выглядит так: 1234567890:AAH...(35 символов). Запусти ещё раз."
    exit 1
fi

sed -i "s|^BOT_TOKEN=.*|BOT_TOKEN=$token|" .env
docker compose -p gamebot up -d --force-recreate >/dev/null 2>&1
echo "⏳ Запускаю бота..."
sleep 10
if docker compose -p gamebot logs --since 15s 2>&1 | grep -q "401"; then
    docker compose -p gamebot stop >/dev/null 2>&1
    echo "❌ Telegram не принял токен (401). Возьми актуальный в @BotFather: /mybots → бот → API Token."
    exit 1
fi
if docker compose -p gamebot ps --format '{{.Status}}' | grep -q '^Up'; then
    echo "✅ Бот работает! Открой его в Telegram и нажми /start"
else
    echo "❌ Бот не запустился. Последние строки лога:"
    docker compose -p gamebot logs --tail 10
fi
