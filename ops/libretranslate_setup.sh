#!/usr/bin/env bash
# ops/libretranslate_setup.sh — создать (или пересоздать) контейнер своего
# переводчика. Юнит sbf-libretranslate.service только ЗАПУСКАЕТ созданный:
# длинная команда docker run должна жить в одном месте, иначе через месяц
# в юните и в скрипте окажутся разные -e.
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

ИМЯ=sbf-libretranslate            # используется только в сообщениях
CONTAINER=sbf-libretranslate
IMAGE=libretranslate/libretranslate:latest
PORT=5055
MODELS=/mnt/sbfdata/Базы/libretranslate

echo "Контейнер: $CONTAINER, порт $PORT, модели в $MODELS"

if ! command -v docker >/dev/null; then
  echo "✗ docker не найден"; exit 1
fi

mkdir -p "$MODELS"
chown -R 1032:65534 "$MODELS" 2>/dev/null || chmod 777 "$MODELS"

docker pull "$IMAGE" || exit 1
docker rm -f "$CONTAINER" 2>/dev/null

docker run -d --name "$CONTAINER" \
  --restart unless-stopped \
  -p 127.0.0.1:$PORT:5000 \
  -e LT_LOAD_ONLY=en,ru,ro \
  -e LT_DISABLE_WEB_UI=true \
  -e LT_THREADS=4 \
  -v "$MODELS":/home/libretranslate/.local/share/argos-translate \
  "$IMAGE" || exit 1

echo "Жду, пока поднимется (первый старт качает модели)…"
for i in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:$PORT/languages" || true)
  [ "$code" = "200" ] && { echo "✓ отвечает, языки:"; \
    curl -s "http://127.0.0.1:$PORT/languages" | head -c 200; echo; exit 0; }
  sleep 5
done

echo "✗ за пять минут не ответил. Лог:"
docker logs --tail 20 "$CONTAINER"
exit 1
