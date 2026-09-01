#!/usr/bin/env bash
# tools/twelvedata_setup.sh — подключение ключа Twelve Data (31.08.2026).
#
# Ключ вводится здесь и попадает только в .env. Он не передаётся аргументом
# командной строки (иначе виден в `ps` и в истории оболочки) и не печатается на
# экран. Скрипт запускает владелец; ассистент ключа не видит.
#
# Перед записью ключ ПРОВЕРЯЕТСЯ живым запросом и печатается сводка: какой
# тариф, сколько кредитов в минуту, доступны ли внутридневные интервалы и
# отдаются ли акции США. Без этой проверки «ключ есть» и «ключ работает для
# наших задач» — разные вещи, а узнать разницу хочется до, а не после.
#
# Запуск:  bash tools/twelvedata_setup.sh
set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE=".env"

echo "Ключ берётся на https://twelvedata.com/account/api-keys (после регистрации)."
read -rsp "Ключ Twelve Data (не отображается): " TD
echo
if [ -z "$TD" ]; then
  echo "Ключ пустой — ничего не записано." >&2
  exit 1
fi

echo -n "Проверяю ключ… "
# set +e — чтобы поймать код 2 (частичная доступность), а не вылететь по -e.
set +e
TD="$TD" python3 - <<'PY'
import json, os, sys, urllib.parse, urllib.request, urllib.error

KEY = os.environ["TD"]
API = "https://api.twelvedata.com"


def call(path, **params):
    params["apikey"] = KEY
    q = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    try:
        with urllib.request.urlopen(f"{API}/{path}?{q}", timeout=25) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"status": "error", "code": e.code, "message": e.read()[:200].decode("utf-8", "replace")}
    except Exception as e:
        return {"status": "error", "message": str(e)}


usage = call("api_usage")
if usage.get("status") == "error":
    print("НЕ РАБОТАЕТ.")
    print("  ответ сервиса:", usage.get("message"), file=sys.stderr)
    sys.exit(1)

print("ок.\n")
print("Тариф и лимиты:")
for k in ("plan_category", "plan_daily_limit", "current_usage", "daily_usage",
          "plan_limit", "timestamp"):
    if k in usage:
        print(f"  {k}: {usage[k]}")

# Что реально доступно — проверяем на трёх типах инструментов и на
# внутридневном интервале, потому что именно он нужен графикам.
print("\nДоступность данных (1 кредит на проверку):")
checks = [("EUR/USD", "1h", "форекс, внутридневка"),
          ("AAPL", "1h", "акции США, внутридневка"),
          ("BTC/USD", "1h", "крипта, внутридневка")]
ok_all = True
for sym, iv, label in checks:
    d = call("time_series", symbol=sym, interval=iv, outputsize=3, timezone="UTC")
    if d.get("status") == "error":
        ok_all = False
        print(f"  {label:<28} НЕТ — {str(d.get('message'))[:90]}")
    else:
        vals = d.get("values") or []
        last = vals[0]["datetime"] if vals else "—"
        print(f"  {label:<28} есть, {len(vals)} баров, последний {last}")

# 🔴 Спрашивать здесь нельзя: stdin занят самим heredoc, input() упал бы с
# EOFError уже после того, как владелец ввёл ключ. Решение принимает bash,
# питон только сообщает исход кодом возврата: 0 — всё доступно, 2 — частично.
sys.exit(0 if ok_all else 2)
PY
RC=$?
set -e

# 🔴 Проверено сухим прогоном: без этой ветки скрипт печатал «НЕ РАБОТАЕТ» и
# всё равно писал ключ в .env — то есть отчитывался об отказе и делал своё.
if [ "$RC" != "0" ] && [ "$RC" != "2" ]; then
  echo "Ключ не прошёл проверку — в .env ничего не записано." >&2
  exit 1
fi

if [ "$RC" = "2" ]; then
  read -rp "Часть данных недоступна на этом тарифе. Ключ всё равно записать? [y/N] " YN
  if [ "${YN,,}" != "y" ]; then
    echo "Ничего не записано."
    exit 1
  fi
fi

touch "$ENV_FILE"; chmod 600 "$ENV_FILE"
# Старые значения убираем, чтобы не плодить дубли ключей в .env.
sed -i '/^TWELVEDATA_KEY=/d;/^TD_KEY=/d' "$ENV_FILE"
{
  # Два имени намеренно: TD_KEY ждёт существующий twelvedata_pull.py,
  # TWELVEDATA_KEY — то, что будет читать новый код витрины. Одно значение,
  # чтобы не разъехались.
  echo "TWELVEDATA_KEY=$TD"
  echo "TD_KEY=$TD"
} >> "$ENV_FILE"

echo
echo "Записано в $ENV_FILE (права 600)."
echo "Теперь напишите ассистенту «ключ готов» — дальше он."
