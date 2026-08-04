#!/usr/bin/env bash
# setup_wine_python.sh — устанавливает Python 3.11 x64 и зависимости в Wine бутылку Trading.
#
# Запускать один раз. После завершения можно использовать start_mt5_server.sh.
#
# Что делает:
#   1. Скачивает Python 3.11.9 x64 installer
#   2. Устанавливает Python в Wine (тихая установка, только для текущего пользователя)
#   3. Устанавливает pip пакеты: MetaTrader5 rpyc

set -euo pipefail

BOTTLE_PATH="/mnt/D/Bottles/Trading"
RUNNER="/home/sbf/.var/app/com.usebottles.bottles/data/bottles/runners/soda-9.0-1/bin/wine64"
PY_INSTALLER_URL="https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
PY_INSTALLER="/tmp/python-3.11.9-amd64.exe"

export WINEPREFIX="${BOTTLE_PATH}"
export WINEDEBUG="-all"
export DISPLAY="${DISPLAY:-:0}"

# Шаг 1: Скачиваем Python installer
if [ ! -f "${PY_INSTALLER}" ]; then
    echo "Загружаем Python 3.11.9..."
    wget -q --show-progress "${PY_INSTALLER_URL}" -O "${PY_INSTALLER}"
else
    echo "Installer уже есть: ${PY_INSTALLER}"
fi

# Шаг 2: Устанавливаем Python (тихо, только для текущего пользователя)
echo "Устанавливаем Python 3.11 в Wine бутылку Trading..."
"${RUNNER}" "${PY_INSTALLER}" /quiet InstallAllUsers=0 PrependPath=0 Include_test=0

# Wine-пользователь бутылки Trading — "steamuser" (задан при создании бутылки
# в Bottles), НЕ линуксовый sbf. Из-за этого несовпадения путь был неверным и
# скрипт молча "падал" на шаге проверки, хотя Python успешно ставился.
PYTHON_WIN="C:\\users\\steamuser\\AppData\\Local\\Programs\\Python\\Python311\\python.exe"

# Шаг 3: Проверка
echo "Проверяем Python..."
"${RUNNER}" "${PYTHON_WIN}" --version

# Шаг 4: Устанавливаем пакеты
echo "Устанавливаем MetaTrader5 и rpyc..."
"${RUNNER}" "${PYTHON_WIN}" -m pip install MetaTrader5 rpyc --quiet

echo ""
echo "Готово! Теперь:"
echo "  1. Запустите MT5 в Bottles (бутылка Trading)"
echo "  2. ./start_mt5_server.sh    (rpyc-сервер)"
echo "  3. python mt5_pull.py       (загрузка данных)"
