#!/usr/bin/env bash
# start_mt5_server_real.sh — rpyc-сервер для ВТОРОГО терминала (реальный счёт).
#
# Отличия от start_mt5_server.sh ровно два и оба обязательны:
#   · свой префикс Wine  -> свой wineserver. Два MT5 в одном префиксе дерутся
#     за общие ресурсы: проверено 16.09, второе окно поднималось и не
#     принимало ни одного клика.
#   · свой порт 18813    -> mt5_server держит ОДНУ сессию MetaTrader5 на
#     процесс; второй счёт на том же сервере вытеснил бы первый.
set -euo pipefail
BOTTLE_PATH="/mnt/D/Bottles/TradingReal"
RUNNER="/home/sbf/.var/app/com.usebottles.bottles/data/bottles/runners/soda-9.0-1/bin/wine64"
PYTHON_WIN="C:\\users\\steamuser\\AppData\\Local\\Programs\\Python\\Python311\\python.exe"
SERVER_SCRIPT="C:\\mt5_server\\mt5_server.py"
mountpoint -q /mnt/D || { echo "ОТКАЗ: /mnt/D не смонтирован" >&2; exit 1; }
export WINEPREFIX="$BOTTLE_PATH" DISPLAY="${DISPLAY:-:0}" MT5_PORT=18813
exec "$RUNNER" "$PYTHON_WIN" "$SERVER_SCRIPT"
