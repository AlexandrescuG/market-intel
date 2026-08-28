#!/usr/bin/env bash
# tools/crm_setup.sh — подключение платформы к SBFCRM (27.08.2026).
#
# Пароль вводится здесь и попадает только в .env. Он не передаётся аргументом
# командной строки (иначе виден в `ps` и в истории оболочки) и не печатается
# на экран. Скрипт запускает владелец; ассистент пароля не видит.
#
# Запуск:  bash tools/crm_setup.sh
set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE=".env"

DEFAULT_URL="https://crm.sbf.md"
DEFAULT_EMAIL="gheorgiialexandrescu@gmail.com"
DEFAULT_ASSIGNEE="cmtd41n650096zatgl15sx4pz"   # он же в CRM, роль HEAD

read -rp "Адрес CRM [$DEFAULT_URL]: " CRM_URL
CRM_URL="${CRM_URL:-$DEFAULT_URL}"

read -rp "Email для входа [$DEFAULT_EMAIL]: " CRM_EMAIL
CRM_EMAIL="${CRM_EMAIL:-$DEFAULT_EMAIL}"

read -rsp "Пароль (не отображается): " CRM_PASS
echo

read -rp "ID пользователя, на кого вешать лиды [$DEFAULT_ASSIGNEE]: " CRM_ASSIGNEE
CRM_ASSIGNEE="${CRM_ASSIGNEE:-$DEFAULT_ASSIGNEE}"

if [ -z "$CRM_PASS" ]; then
  echo "Пароль пустой — ничего не записано." >&2
  exit 1
fi

# Проверяем ДО записи: незачем класть в .env заведомо нерабочее.
echo -n "Проверяю вход… "
CODE=$(curl -s -o /tmp/.crm_login_check -w '%{http_code}' --max-time 15 \
  -X POST "$CRM_URL/api/auth/login" -H 'Content-Type: application/json' \
  --data-binary @<(printf '{"email":%s,"password":%s}' \
      "$(printf '%s' "$CRM_EMAIL" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')" \
      "$(printf '%s' "$CRM_PASS"  | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')") || true)

if [ "$CODE" != "200" ] && [ "$CODE" != "201" ]; then
  echo "не удалось (HTTP $CODE)."
  echo "Ответ: $(head -c 200 /tmp/.crm_login_check 2>/dev/null)" >&2
  rm -f /tmp/.crm_login_check
  echo "В .env ничего не записано." >&2
  exit 1
fi
if ! grep -q '"token"' /tmp/.crm_login_check 2>/dev/null; then
  echo "вход прошёл, но токена в ответе нет — проверьте адрес CRM." >&2
  rm -f /tmp/.crm_login_check; exit 1
fi
rm -f /tmp/.crm_login_check
echo "ок."

touch "$ENV_FILE"; chmod 600 "$ENV_FILE"
# Старые значения убираем, чтобы не плодить дубли ключей в .env.
sed -i '/^SBFCRM_URL=/d;/^SBFCRM_EMAIL=/d;/^SBFCRM_PASSWORD=/d;/^SBFCRM_ASSIGNEE_ID=/d' "$ENV_FILE"
{
  echo "SBFCRM_URL=$CRM_URL"
  echo "SBFCRM_EMAIL=$CRM_EMAIL"
  echo "SBFCRM_PASSWORD=$CRM_PASS"
  echo "SBFCRM_ASSIGNEE_ID=$CRM_ASSIGNEE"
} >> "$ENV_FILE"

echo "Записано в $ENV_FILE (права 600)."
echo "Теперь перезапустите сайт:  systemctl --user restart sbf-web.service"
