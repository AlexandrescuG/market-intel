#!/usr/bin/env bash
# ops/set_ctrader_env.sh — заполнить ключи cTrader Open API в .env.
#
# ЗАЧЕМ ОТДЕЛЬНЫЙ СКРИПТ, А НЕ `echo 'X=...' >> .env`
# Всё, что набрано в оболочке, оседает в ~/.bash_history. Токен доступа
# живёт 30 суток, refresh-токен — бессрочно; попав в историю, он там и
# останется. Здесь секреты читаются через `read -rs`: не печатаются на
# экране и не проходят через историю команд.
#
# В этом проекте уже был случай: боевой токен бота и админ-пароль лежали
# в env.example — файле-шаблоне для коммита — во всех 36 коммитах истории
# (найдено 04.08.2026, ротация не сделана до сих пор). Поэтому осторожность
# здесь не формальность.
#
# Запуск:  bash ops/set_ctrader_env.sh
set -euo pipefail

ENV_FILE="/mnt/sbfdata/sbf-platform/market_intel/.env"

[ -f "$ENV_FILE" ] || { echo "нет $ENV_FILE"; exit 1; }

# Бэкап до любых правок: .env не в git, восстановить будет неоткуда.
BAK="$ENV_FILE.bak-$(date +%Y%m%d-%H%M%S)"
cp "$ENV_FILE" "$BAK"
chmod 600 "$BAK"
echo "бэкап: $BAK"
echo

ask()      { local p="$1"; local v; read -r  -p "$p: " v; printf '%s' "$v"; }
ask_secret(){ local p="$1"; local v; read -rs -p "$p: " v; echo >&2; printf '%s' "$v"; }

echo "Значения берутся с openapi.ctrader.com (Applications → View и Playground)."
echo "Секреты при вводе не отображаются — это нормально, печатайте вслепую."
echo

CLIENT_ID=$(ask       "Client ID")
CLIENT_SECRET=$(ask_secret "Client Secret")
ACCESS_TOKEN=$(ask_secret  "Access token")
REFRESH_TOKEN=$(ask_secret "Refresh token")
ACCOUNT_ID=$(ask      "ctidTraderAccountId (только цифры)")

read -r -p "Счёт демо? [Y/n]: " IS_DEMO
if [[ "${IS_DEMO,,}" == "n" ]]; then
  HOST="live.ctraderapi.com"; DEMO=0
  echo
  echo "⚠ ВЫБРАН БОЕВОЙ КОНТУР. Предохранитель assert_demo в analyze/mt5_safety.py"
  echo "  проверяет trade_mode терминала и на реальном счёте откажет. Для cTrader"
  echo "  аналогичная проверка ещё не написана — до неё торговать вживую нельзя."
  read -r -p "  Понимаю, продолжить? [y/N]: " C
  [[ "${C,,}" == "y" ]] || { echo "отменено"; exit 1; }
else
  HOST="demo.ctraderapi.com"; DEMO=1
fi

# Проверки формы до записи: пустое поле молча сломает авторизацию,
# и разбираться потом придётся по невнятной ошибке протокола.
[ -n "$CLIENT_ID" ]     || { echo "Client ID пуст";     exit 1; }
[ -n "$CLIENT_SECRET" ] || { echo "Client Secret пуст"; exit 1; }
[ -n "$ACCESS_TOKEN" ]  || { echo "Access token пуст";  exit 1; }
[[ "$ACCOUNT_ID" =~ ^[0-9]+$ ]] || { echo "ctidTraderAccountId должен быть числом"; exit 1; }

# Удаляем прежние значения, чтобы не плодить дубли: python-dotenv возьмёт
# последнее, а глазами потом не разобрать, какое из них рабочее.
sed -i '/^CTRADER_[A-Z_]*=/d' "$ENV_FILE"

{
  echo ""
  echo "# cTrader Open API — заполнено $(date +%Y-%m-%d) через ops/set_ctrader_env.sh"
  echo "# Хост демо и реала РАЗНЫЕ, порт общий (проверено на ctrader_open_api.EndPoints)."
  echo "CTRADER_CLIENT_ID=$CLIENT_ID"
  echo "CTRADER_CLIENT_SECRET=$CLIENT_SECRET"
  echo "CTRADER_ACCESS_TOKEN=$ACCESS_TOKEN"
  echo "CTRADER_REFRESH_TOKEN=$REFRESH_TOKEN"
  echo "CTRADER_ACCOUNT_ID=$ACCOUNT_ID"
  echo "CTRADER_HOST=$HOST"
  echo "CTRADER_PORT=5035"
  echo "CTRADER_DEMO=$DEMO"
} >> "$ENV_FILE"

chmod 600 "$ENV_FILE"

echo
echo "Записано в .env (значения скрыты):"
grep -E '^CTRADER_' "$ENV_FILE" | sed -E 's/(=.{0,4}).*/\1…/'
echo
echo "Дальше: bash ops/check_ctrader.sh — проверит, что ключи рабочие."
