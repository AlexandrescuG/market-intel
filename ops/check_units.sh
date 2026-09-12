#!/bin/bash
# ops/check_units.sh — сверка карты units.txt с реальностью, без правок.
#
# ЗАЧЕМ. Перед перезагрузкой хочется ответа на один вопрос: всё ли из карты
# вернётся само. `systemctl start`, который делает sbf-start-all.sh, отвечает
# только за текущую загрузку — а за следующую отвечает `enabled`. Здесь
# проверяются обе величины сразу и ничего не меняется.
#
# 🔴 Bash, а не sh: переменные с русскими именами /bin/sh не понимает и
# отвечает «command not found» — с кодом, который легко принять за «всё
# хорошо». Поймано на этом же скрипте 12.09.2026.
#
# Пустой вывод и «не enabled: 0, не active: 0» — значит после ребута
# поднимется всё.
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
bad_en=0; bad_ac=0; total=0
while read -r unit role _rest; do
  case "$role" in daemon|timer)
    total=$((total+1))
    e=$(systemctl --user is-enabled "$unit" 2>/dev/null)
    a=$(systemctl --user is-active "$unit" 2>/dev/null)
    [ "$e" = enabled ] || { echo "  НЕ ENABLED: $unit ($e)"; bad_en=$((bad_en+1)); }
    [ "$a" = active ]  || { echo "  НЕ ACTIVE:  $unit ($a)"; bad_ac=$((bad_ac+1)); } ;;
  esac
done < <(sed 's/#.*//' /mnt/sbfdata/sbf-platform/market_intel/ops/units.txt | awk 'NF>=3')
echo "итого по карте: $total юнитов, не enabled: $bad_en, не active: $bad_ac"
