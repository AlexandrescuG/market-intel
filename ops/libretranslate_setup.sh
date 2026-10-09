#!/usr/bin/env bash
# ops/libretranslate_setup.sh — контейнер своего переводчика.
#
#   bash ops/libretranslate_setup.sh            пересоздать с нуля (с pull)
#   bash ops/libretranslate_setup.sh --ensure   поднять; создать, если его нет
#
# 🔴 ПОЧЕМУ ПОЯВИЛСЯ --ensure, И ЭТО ИСПРАВЛЕНИЕ МОЕЙ ЖЕ ОШИБКИ.
# 07.10.2026 я развёл роли так: скрипт создаёт контейнер, юнит только его
# запускает. Рассуждение было верное — держать длинную команду docker run
# в двух местах значит развести их через месяц. Следствие оказалось хуже
# болезни: 08.10 контейнер кто-то удалил (чем именно — из журналов уже не
# достать, они прокрутились), и юнит навсегда встал в failed, потому что
# `docker start` нечего стартовать. Сутки перевод работал без последнего
# запасного пути, и заметили это не мы.
# Теперь юнит зовёт этот же скрипт в режиме --ensure: команда docker run
# по-прежнему ровно одна, но удаление контейнера лечится само.
# В --ensure НЕТ `docker pull`: иначе каждая загрузка машины ходила бы в
# сеть, и сервис зависел бы от доступности реестра.
#
# 🔴 ИМЕНА ПЕРЕМЕННЫХ ЛАТИНИЦЕЙ (в bash иначе нельзя).
#
# Что важно в параметрах:
#   LT_LOAD_ONLY=en,ru,ro — без него образ тянет модели ВСЕХ языков,
#       это десятки гигабайт. С ним — 531 МБ, замерено 07.10.2026.
#   -p 127.0.0.1:5055 — слушает ТОЛЬКО локально. Это внутренняя служба,
#       наружу ей нельзя: у LibreTranslate нет авторизации по умолчанию,
#       и открытый порт стал бы бесплатным переводчиком для всего мира
#       за наш процессор. Порт 5055, а не 5000: 5000-5003 заняты.
#   -v на Базы/libretranslate — модели переживают пересоздание контейнера.
#       Каталог принадлежит uid 1032 изнутри образа; если chown недоступен,
#       777 допустимо — там только скачанные модели, секретов нет.
set -u

CONTAINER=sbf-libretranslate
IMAGE=libretranslate/libretranslate:latest
PORT=5055
MODELS=/mnt/sbfdata/Базы/libretranslate
ENSURE=0
[ "${1:-}" = "--ensure" ] && ENSURE=1

if ! command -v docker >/dev/null; then
  echo "✗ docker не найден"; exit 1
fi

есть_контейнер() { docker inspect "$CONTAINER" >/dev/null 2>&1; }
работает()       { [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" = "true" ]; }

создать() {
  mkdir -p "$MODELS"
  chown -R 1032:65534 "$MODELS" 2>/dev/null || chmod 777 "$MODELS"
  docker rm -f "$CONTAINER" 2>/dev/null
  docker run -d --name "$CONTAINER" \
    --restart unless-stopped \
    -p 127.0.0.1:$PORT:5000 \
    -e LT_LOAD_ONLY=en,ru,ro \
    -e LT_DISABLE_WEB_UI=true \
    -e LT_THREADS=4 \
    -v "$MODELS":/home/libretranslate/.local/share/argos-translate \
    "$IMAGE"
}

дождаться() {
  for _ in $(seq 1 60); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
         "http://127.0.0.1:$PORT/languages" || true)" = "200" ] && return 0
    sleep 5
  done
  return 1
}

if [ "$ENSURE" = "1" ]; then
  if работает; then
    echo "уже работает"; exit 0
  elif есть_контейнер; then
    echo "контейнер есть, запускаю"
    docker start "$CONTAINER" >/dev/null || exit 1
  else
    # 🔴 Ровно тот случай, ради которого режим и написан.
    echo "⚠ контейнера НЕТ — создаю заново (его удалили извне)"
    создать >/dev/null || exit 1
  fi
else
  echo "Контейнер: $CONTAINER, порт $PORT, модели в $MODELS"
  docker pull "$IMAGE" || exit 1
  создать || exit 1
fi

if дождаться; then
  echo "✓ отвечает на 127.0.0.1:$PORT"
  exit 0
fi

echo "✗ за пять минут не ответил. Лог:"
docker logs --tail 20 "$CONTAINER"
exit 1
