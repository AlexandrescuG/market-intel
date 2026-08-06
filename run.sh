#!/usr/bin/env bash
# Запуск цикла коллекторов (real-time сбор + алерты).
cd "$(dirname "$0")"
export PYTHONPATH="$PWD"
[ -f .venv/bin/activate ] && source .venv/bin/activate || true
# flock -n: если предыдущий запуск ещё держит браузерный профиль (SingletonLock),
# этот запуск просто пропускается, а не падает в гонке за profile-директорией.
exec flock -n /tmp/sbf-browser.lock python3 -m collectors.run "$@"
