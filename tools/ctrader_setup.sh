#!/usr/bin/env bash
# tools/ctrader_setup.sh — подключение cTrader Open API (01.09.2026).
#
# Учётные данные вводит владелец скрытым вводом. Они не передаются аргументами
# команды (иначе видны в `ps` и в истории оболочки), не печатаются на экран и
# попадают только в .env с правами 600. Ассистент их не видит.
#
# Перед записью доступ ПРОВЕРЯЕТСЯ живым подключением: авторизация приложения,
# авторизация счёта, список инструментов и реальные свечи H1. «Данные приняты» и
# «данные работают» — разные вещи, и узнать разницу лучше сейчас.
#
# Запуск:  bash tools/ctrader_setup.sh
set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE=".env"
PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"

cat <<'TXT'
Что нужно приготовить (см. инструкцию в чате):
  1. Счёт FxPro на cTrader (демо подойдёт) и cTrader ID.
  2. Приложение на https://openapi.ctrader.com/ → Applications.
  3. Кнопка Playground у этого приложения, scope = accounts → Get token.
     Со страницы Playground берутся Access token и Refresh token.

TXT

read -rp "Client ID: " CT_ID
read -rsp "Client Secret (не отображается): " CT_SECRET; echo
read -rsp "Access token (не отображается): " CT_TOKEN; echo
read -rsp "Refresh token (не отображается, можно пустым): " CT_REFRESH; echo
read -rp "Счета демо или живые? [demo/live, по умолчанию demo]: " CT_HOST
CT_HOST="${CT_HOST:-demo}"

if [ -z "$CT_ID" ] || [ -z "$CT_SECRET" ] || [ -z "$CT_TOKEN" ]; then
  echo "Пустые поля — ничего не записано." >&2
  exit 1
fi

echo
echo "Проверяю доступ:"
set +e
CT_CLIENT_ID="$CT_ID" CT_CLIENT_SECRET="$CT_SECRET" CT_ACCESS_TOKEN="$CT_TOKEN" \
  CT_HOST="$CT_HOST" "$PY" tools/ctrader_check.py
RC=$?
set -e

# 🔴 Ветку писал после того, как ровно на этом обжёгся в скрипте для Twelve
# Data: там проверка печатала «НЕ РАБОТАЕТ», а ключ всё равно уезжал в .env.
if [ "$RC" != "0" ]; then
  echo
  echo "Доступ не подтверждён — в .env ничего не записано." >&2
  echo "Частые причины: токен получен для другого scope; выбран demo, а счёт живой (или наоборот)." >&2
  exit 1
fi

touch "$ENV_FILE"; chmod 600 "$ENV_FILE"
sed -i '/^CTRADER_CLIENT_ID=/d;/^CTRADER_CLIENT_SECRET=/d;/^CTRADER_ACCESS_TOKEN=/d;/^CTRADER_REFRESH_TOKEN=/d;/^CTRADER_HOST=/d' "$ENV_FILE"
{
  echo "CTRADER_CLIENT_ID=$CT_ID"
  echo "CTRADER_CLIENT_SECRET=$CT_SECRET"
  echo "CTRADER_ACCESS_TOKEN=$CT_TOKEN"
  echo "CTRADER_REFRESH_TOKEN=$CT_REFRESH"
  echo "CTRADER_HOST=$CT_HOST"
} >> "$ENV_FILE"

echo
echo "Записано в $ENV_FILE (права 600)."
echo "Токен доступа живёт ~30 дней; refresh-токен бессрочный — обновление сделаю в коде."
echo "Теперь напишите ассистенту «cTrader готов»."
