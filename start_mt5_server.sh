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

# 🔴 Диск ПРОВЕРЯЕТСЯ, а не подразумевается.
#
# 19-20.08 /mnt/D был отмонтирован, а скрипт сразу шёл в `mkdir -p`. Итог:
# "mkdir: cannot create directory '/mnt/D/Bottles': Permission denied",
# выход 1, systemd перезапускает каждые 15 секунд — 973 раза подряд. Снаружи
# это выглядело как "MT5 иногда лежит", а по существу в журнале была одна
# строка про mkdir, которую никто не искал.
#
# Опаснее другой исход: будь /mnt доступен на запись, скрипт СОЗДАЛ бы пустое
# дерево бутылки на корневом диске. Wine поднялся бы на пустом префиксе, а
# монтирование настоящего диска сверху спрятало бы мусор. Поэтому проверка
# именно на точку монтирования, а не на существование каталога: существующий
# каталог здесь ничего не доказывает — он мог быть создан этим же скриптом.
if ! mountpoint -q /mnt/D; then
    echo "ОТКАЗ: /mnt/D не примонтирован — бутылки MT5 нет." >&2
    echo "Смонтируйте диск и повторите; каталоги на его месте не создаю." >&2
    exit 1
fi
if [ ! -d "${BOTTLE_PATH}/drive_c" ]; then
    echo "ОТКАЗ: ${BOTTLE_PATH}/drive_c не найден — диск примонтирован не тот" >&2
    echo "или бутылка Trading отсутствует." >&2
    exit 1
fi

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
