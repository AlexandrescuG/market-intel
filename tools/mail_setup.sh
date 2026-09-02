#!/usr/bin/env bash
# tools/mail_setup.sh — почта отправителя для рассылок (02.09.2026).
#
# ЗАЧЕМ. Сейчас письма уходят с личного ящика gheorgiisbf@gmail.com — так
# настроен SMTP в SBFAcademy_bot/.env, и рассылка просто взяла оттуда готовое.
# Для писем клиентам это плохо по трём причинам:
#   • получатель видит личный gmail вместо адреса компании;
#   • у Gmail жёсткий предел на исходящие (порядка 500 в сутки), и рассылка
#     упрётся в него раньше, чем вырастет база;
#   • с этого же ящика уходят коды входа. Жалоба на спам из-за рассылки бьёт
#     по доставке кодов, то есть по возможности вообще войти на платформу.
#
# Пароль вводится здесь и попадает только в market_intel/.env. Он не передаётся
# аргументом команды (иначе виден в `ps` и в истории оболочки) и не печатается
# на экран. Скрипт запускает владелец; ассистент пароля не видит.
#
# Запуск:  bash tools/mail_setup.sh
set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE=".env"

echo "Почта для рассылок SBF. Нужны данные почтового ящика компании."
echo

read -rp "Адрес отправителя [contact@sbf.md]: " FROM
FROM="${FROM:-contact@sbf.md}"
read -rp "SMTP-сервер [mail.sbf.md]: " HOST
HOST="${HOST:-mail.sbf.md}"
read -rp "Порт [465 для SSL, 587 для STARTTLS]: " PORT
PORT="${PORT:-465}"
read -rp "Логин [$FROM]: " USER
USER="${USER:-$FROM}"
read -rsp "Пароль (не отображается): " PASS; echo

if [ -z "$PASS" ]; then
  echo "Пароль пустой — ничего не записано." >&2
  exit 1
fi

echo
echo -n "Проверяю вход на сервер… "
set +e
SMTP_HOST="$HOST" SMTP_PORT="$PORT" SMTP_USER="$USER" SMTP_PASS="$PASS" \
python3 - <<'PY'
import os, smtplib, ssl, sys
host, port = os.environ["SMTP_HOST"], int(os.environ["SMTP_PORT"])
user, pwd = os.environ["SMTP_USER"], os.environ["SMTP_PASS"]
try:
    if port == 465:
        s = smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=20)
    else:
        s = smtplib.SMTP(host, port, timeout=20); s.starttls(context=ssl.create_default_context())
    s.login(user, pwd); s.quit()
    print("ок.")
except Exception as e:
    print("НЕ УДАЛОСЬ."); print("  ", str(e)[:200], file=sys.stderr); sys.exit(1)
PY
RC=$?
set -e
# 🔴 Проверка ДО записи. На скрипте для Twelve Data я на этом уже обжёгся:
# печаталось «не работает», а значение всё равно уезжало в .env.
if [ "$RC" != "0" ]; then
  echo "В .env ничего не записано." >&2
  exit 1
fi

touch "$ENV_FILE"; chmod 600 "$ENV_FILE"
sed -i '/^SMTP_HOST=/d;/^SMTP_PORT=/d;/^SMTP_USER=/d;/^SMTP_PASS=/d;/^SMTP_FROM=/d' "$ENV_FILE"
{
  echo "SMTP_HOST=$HOST"
  echo "SMTP_PORT=$PORT"
  echo "SMTP_USER=$USER"
  echo "SMTP_PASS=$PASS"
  echo "SMTP_FROM=$FROM"
} >> "$ENV_FILE"

echo
echo "Записано в market_intel/$ENV_FILE (права 600)."
echo "Рассылка будет брать эти настройки, а не почту SBFAcademy."
echo "Проверить письмо:  .venv/bin/python brief_email_job.py --only ВАШ_АДРЕС --send"
