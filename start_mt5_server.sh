#!/usr/bin/env bash
# start_mt5_server.sh — запускает rpyc-сервер для mt5linux внутри Wine бутылки Trading.
#
# Предварительно:
#   1. Запустить MT5 терминал в бутылке Trading (через Bottles или flatpak)
#   2. Убедиться что Python установлен в бутылке:  ./setup_wine_python.sh
#
# После запуска этого скрипта:
#   python mt5_pull.py           # в другом терминале

set -euo pipefail

BOTTLE_PATH="/mnt/D/Bottles/Trading"
RUNNER="/home/sbf/.var/app/com.usebottles.bottles/data/bottles/runners/soda-9.0-1/bin/wine64"
# Wine-пользователь бутылки Trading — "steamuser" (не sbf), см. setup_wine_python.sh
PYTHON_WIN="C:\\users\\steamuser\\AppData\\Local\\Programs\\Python\\Python311\\python.exe"
SERVER_SCRIPT="C:\\mt5_server\\mt5_server.py"

# Путь к скрипту относительно бутылки — копируем в drive_c
SCRIPT_SRC="$(dirname "$0")/mt5_server.py"
SCRIPT_DST="${BOTTLE_PATH}/drive_c/mt5_server"

mkdir -p "${SCRIPT_DST}"
cp "${SCRIPT_SRC}" "${SCRIPT_DST}/mt5_server.py"

echo "Копируем mt5_server.py → ${SCRIPT_DST}/mt5_server.py"

export WINEPREFIX="${BOTTLE_PATH}"
export WINEDEBUG="-all"
# Нужен DISPLAY для Wine (даже headless — используем виртуальный)
export DISPLAY="${DISPLAY:-:0}"

echo "Запускаем Python rpyc-сервер в Wine..."
echo "Нажмите Ctrl+C для остановки."
echo ""

exec "${RUNNER}" "${PYTHON_WIN}" "${SERVER_SCRIPT}"
