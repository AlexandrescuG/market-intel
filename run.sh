#!/usr/bin/env bash
# Запуск цикла коллекторов (real-time сбор + алерты).
cd "$(dirname "$0")"
export PYTHONPATH="$PWD"
[ -f .venv/bin/activate ] && source .venv/bin/activate || true
exec python3 -m collectors.run "$@"
