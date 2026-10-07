#!/usr/bin/env bash
# ops/translators_setup.sh — ключи переводчиков в .env, скрытым вводом.
#
# 🔴 КЛЮЧИ ВВОДИТ ВЛАДЕЛЕЦ, И НИКТО БОЛЬШЕ ИХ НЕ ВИДИТ.
# Ни в аргументах команды (они видны в `ps` любому процессу и оседают в
# истории оболочки), ни на экране, ни в выводе этого скрипта. `read -rsp`
# гасит эхо; .env получает права 600.
#
# 🔴 ИМЕНА ПЕРЕМЕННЫХ ЛАТИНИЦЕЙ. Bash допускает только [A-Za-z_][A-Za-z0-9_]*;
# на русском имени строка разбирается как команда, а ошибка выглядит как
# сбой сети (так уже было с ops/bonsai_setup.sh).
#
# Запуск:   bash ops/translators_setup.sh
# Проверка: bash ops/translators_setup.sh --check     (ничего не спрашивает)
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"

# имя_переменной|человеческое имя|где взять
SERVICES=(
  "AZURE_TRANSLATOR_KEY|Azure Translator F0|portal.azure.com → Translator → Keys and Endpoint — 2 млн знаков в месяц"
  "AZURE_TRANSLATOR_REGION|Регион Azure|оттуда же, строка Location/Region, например westeurope. НЕ секрет"
  "GOOGLE_TRANSLATE_API_KEY|Google Cloud Translation|console.cloud.google.com → APIs → Credentials — ~500 тыс. знаков покрываются кредитом"
)

есть_значение() {   # 1 = в .env есть непустая строка с этим именем
  [ -f "$ENV_FILE" ] && grep -qE "^$1=.+" "$ENV_FILE"
}

показать_состояние() {
  echo "Ключи переводчиков в $ENV_FILE:"
  for item in "${SERVICES[@]}"; do
    IFS='|' read -r var human _ <<< "$item"
    if есть_значение "$var"; then
      # 🔴 Печатаем ТОЛЬКО факт наличия и длину. Ни первых символов, ни
      # последних: по четырём знакам ключ не восстановить, но в переписку
      # и в скриншот они попадают, а оттуда уже никуда не денутся.
      len=$(grep -E "^$var=" "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '\r\n' | wc -c)
      # Без %-28s: printf считает БАЙТЫ, а кириллица в UTF-8 весит два, и
      # колонка разъезжается ровно на русских подписях.
      printf "  ✓ %s — задан (%s знаков)\n" "$human" "$((len - 1))"
    else
      printf "  — %s — не задан\n" "$human"
    fi
  done
}

if [ "${1:-}" = "--check" ]; then
  показать_состояние
  exit 0
fi

echo "Порядок обращения в цепочке — по убыванию качества:"
echo "  Azure → Google Cloud → бесплатный Google → MyMemory"
echo "Незаданный ключ просто пропускается, это штатное состояние."
echo
показать_состояние
echo
echo "Пустой ввод оставляет текущее значение без изменений."
echo

umask 077
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

for item in "${SERVICES[@]}"; do
  IFS='|' read -r var human where <<< "$item"
  echo "── $human"
  echo "   $where"
  if [ "$var" = "AZURE_TRANSLATOR_REGION" ]; then
    read -rp "   $var: " value          # регион не секрет, эхо оставляем
  else
    read -rsp "   $var (ввод скрыт): " value
    echo
  fi
  if [ -z "$value" ]; then
    echo "   оставлено как было"
    echo
    continue
  fi
  # Пишем через временный файл: прямая правка sed -i на .env при обрыве
  # оставила бы файл без половины ключей.
  tmp=$(mktemp)
  chmod 600 "$tmp"
  grep -v -E "^$var=" "$ENV_FILE" > "$tmp" 2>/dev/null || true
  printf '%s=%s\n' "$var" "$value" >> "$tmp"
  mv "$tmp" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  unset value
  echo "   записано"
  echo
done

echo
показать_состояние
echo
echo "Проверить живой ответ служб:"
echo "  .venv/bin/python tools/check_translators.py"
echo "Перезапустить сайт, чтобы он подхватил ключи:"
echo "  systemctl --user restart sbf-web"
