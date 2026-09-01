#!/usr/bin/env bash
# ops/check_ctrader.sh — проверить, что ключи cTrader рабочие.
#
# Смысл в том, чтобы неверный ключ обнаружился СЕЙЧАС, за минуту, а не через
# неделю в виде невнятной ошибки протокола посреди торгового цикла. Проверка
# ничего не меняет и ничего не торгует: только авторизуется и просит список
# счетов.
set -euo pipefail
cd /mnt/sbfdata/sbf-platform/market_intel

# Зависимость ставится в venv проекта только если её ещё нет: молча тянуть
# пакеты в прод при каждом запуске — плохая привычка.
./.venv/bin/python3 -c "import ctrader_open_api" 2>/dev/null || {
  echo "ставлю ctrader-open-api в venv проекта…"
  ./.venv/bin/pip -q install ctrader-open-api service_identity
}

exec ./.venv/bin/python3 ops/check_ctrader.py
