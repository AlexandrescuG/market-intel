#!/usr/bin/env bash
# ops/bonsai_setup.sh — поэтапная проверка Bonsai 2 27B как запасной модели.
#
# 🔴 ИМЕНА ПЕРЕМЕННЫХ ЗДЕСЬ ЛАТИНИЦЕЙ, И ЭТО НЕ ВКУСОВЩИНА. Bash допускает
# в именах только [A-Za-z_][A-Za-z0-9_]*; на `ДОМ=/путь` он разбирает
# строку как команду и падает с «No such file or directory», а `${ДОМ}`
# даёт «bad substitution». Первая версия этого файла была написана с
# русскими именами (как весь остальной код проекта — в Python и JS они
# законны) и не пережила первый же запуск. Комментарии по-русски, имена —
# латиницей: в shell иначе нельзя.
#
# 🔴 ЗАЧЕМ ПОЭТАПНО. Bonsai 2 — тернарная сборка Qwen3.8-27B: 5,95 ГБ
# вместо 54 при 98,2% качества FP16. По цифрам она решает ровно ту беду,
# на которой 29.09 срезался Ollama-фоллбэк: обычная 2-битная сборка того
# же Qwen даёт 72,59 против 84,78 и разваливается именно на длинных
# рассуждениях (AIME26: 57,5 против 95,83) — это и был «Золото подорвало
# уровень $4200».
#
# 🔴 ТРИ РИСКА, КОТОРЫЕ РЕШАЕТ ТОЛЬКО ЗАМЕР НА ЭТОЙ МАШИНЕ:
#   1. Ollama её не загрузит вообще: PQ2_0 и PTQ1_0 мейнлайн не знает, а
#      файл F16 стоковый llama.cpp грузит и выдаёт мусор БЕЗ ошибки.
#      Нужен форк PrismML (их же KNOWN_ISSUES).
#   2. У нас GTX 1080 — Pascal 2016 года. В их таблице производительности
#      самая старая карта — A100; Pascal не упомянут вовсе.
#   3. VRAM 8 ГБ, из них ~2,8 заняты. Модель 5,95 ГБ впритык не влезает, а
#      они отдельно пишут, что 32K контекста не помещается и в 12 ГБ.
#
# Запуск:
#   bash ops/bonsai_setup.sh check   # ничего не качает: пути, адреса, curl
#   bash ops/bonsai_setup.sh 1       # бинарник форка (159 МБ) + видит ли GPU
#   bash ops/bonsai_setup.sh 2       # модель PTQ1_0 (5,95 ГБ) + sha256
#   bash ops/bonsai_setup.sh 3       # llama-bench: токенов в секунду
set -uo pipefail

HOME_DIR="/mnt/sbfdata/Базы/llm/bonsai2"
TAG="prism-b10709-9a9394a"

# 🔴 КАКУЮ СБОРКУ БРАТЬ. Первым взяли CUDA 12.8 — и она не запустилась:
# «libcudart.so.12: cannot open shared object file». CUDA Toolkit на этой
# машине не установлен вовсе (ldconfig не знает ни одной libcudart, пакетов
# cuda нет), есть только libcuda.so.1 из драйвера. Ставить Toolkit ради
# замера — вмешательство в систему, которое надо обсуждать отдельно;
# сначала меряем тем, что работает без установки.
#   cpu    — 16 МБ, ничего не требует, ответ в худшем случае
#   vulkan — 33 МБ, GTX 1080 умеет Vulkan; но у них PQ2_0 на Vulkan молча
#            уходит на процессор, а PTQ1_0 декодит медленнее, чем должен
#   cuda   — 159 МБ, нужен CUDA-рантайм 12 (libcudart, libcublas)
BUILD="${BONSAI_BUILD:-cpu}"
case "$BUILD" in
  cpu)
    ARCHIVE="llama-${TAG}-bin-ubuntu-x64.tar.gz"
    ARCHIVE_SHA="48b487f00fd2b27bc3ef77c701b43c1c23a4af484d2a203ae87d0efc41506728" ;;
  vulkan)
    ARCHIVE="llama-${TAG}-bin-ubuntu-vulkan-x64.tar.gz"
    ARCHIVE_SHA="4d7f858539d0207cf64e90beb83fcb7e076580d52856580f223cbecdd3ef6d03" ;;
  cuda)
    # CUDA 12.8, а не 13.3: у 13.3 на Linux сегфолт (их KNOWN_ISSUES).
    ARCHIVE="llama-${TAG}-bin-linux-cuda-12.8-x64.tar.gz"
    ARCHIVE_SHA="8aec67eb023b251712c7e6490f367b5671bf587eced1436a9b85f4a90c3b7d3d" ;;
  *) echo "BONSAI_BUILD: cpu, vulkan или cuda"; exit 2 ;;
esac
ARCHIVE_URL="https://github.com/PrismML-Eng/llama.cpp/releases/download/${TAG}/${ARCHIVE}"

MODEL="Ternary-Bonsai-2-27B-PTQ1_0.gguf"
MODEL_URL="https://huggingface.co/prism-ml/Ternary-Bonsai-2-27B-gguf/resolve/main/${MODEL}"
MODEL_SHA="53107f530aa52eb00912263ab1ee29bd199261c87cd7b4ad4ca1318c1fe33ee3"
MODEL_BYTES=5946648928

BIN=""

# Ищем llama-cli каждый раз заново: архив кладёт его то в корень, то в bin/.
find_bin() {
  if [ -x "$HOME_DIR/bin/llama-cli" ]; then
    BIN="$HOME_DIR/bin/llama-cli"
  else
    BIN="$(find "$HOME_DIR" -name llama-cli -type f -perm -u+x 2>/dev/null | head -1)"
  fi
  [ -n "$BIN" ]
}

download() {   # url, файл, sha256
  local url="$1" path="$2" want="$3"
  if [ -s "$path" ]; then
    echo "  уже на диске: $(basename "$path")"
  else
    echo "  качаю $(basename "$path") …"
    # -C - продолжает оборванную закачку: 5,95 ГБ с одной попытки берутся
    # не всегда, а начинать заново из-за обрыва — терять полчаса.
    curl -fL -C - --retry 3 --retry-delay 5 --progress-bar \
         -o "$path.part" "$url" || { echo "✗ скачать не удалось"; return 1; }
    mv "$path.part" "$path"
  fi
  echo "  считаю sha256 (на 6 ГБ это с полминуты) …"
  local got
  got="$(sha256sum "$path" | cut -d' ' -f1)"
  if [ "$got" != "$want" ]; then
    # 🔴 Молча принять чужой файл нельзя: битую или подменённую модель
    # видно только по бессмыслице на выходе — то есть слишком поздно.
    echo "✗ sha256 НЕ СОВПАЛ — файл битый или не тот"
    echo "   ждали: $want"
    echo "   факт:  $got"
    return 1
  fi
  echo "  sha256 совпал"
}

step_check() {
  echo "═══ ХОЛОСТАЯ ПРОВЕРКА: ничего не качаем ═══"
  echo "  каталог:  $HOME_DIR"
  echo "  архив:    $ARCHIVE"
  echo "  адрес:    $ARCHIVE_URL"
  echo "  модель:   $MODEL ($((MODEL_BYTES/1024/1024)) МБ)"
  echo "  адрес:    $MODEL_URL"
  echo
  command -v curl >/dev/null || { echo "✗ curl не установлен"; return 1; }
  command -v sha256sum >/dev/null || { echo "✗ sha256sum не найден"; return 1; }
  command -v tar >/dev/null || { echo "✗ tar не найден"; return 1; }
  echo "  curl, sha256sum, tar — на месте"
  mkdir -p "$HOME_DIR/bin" || { echo "✗ каталог не создаётся"; return 1; }
  echo "  каталог создан/существует"
  local avail
  avail=$(df -BG --output=avail "$HOME_DIR" | tail -1 | tr -dc '0-9')
  echo "  свободно: ${avail} ГБ (нужно ~6)"
  [ "${avail:-0}" -lt 8 ] && { echo "✗ мало места"; return 1; }
  echo "  проверяю, что ссылки живые (только заголовки, тело не тянем) …"
  local code
  code=$(curl -fsSIL -o /dev/null -w '%{http_code}' "$ARCHIVE_URL" 2>/dev/null)
  echo "    бинарник: HTTP ${code:-нет ответа}"
  code=$(curl -fsSIL -o /dev/null -w '%{http_code}' "$MODEL_URL" 2>/dev/null)
  echo "    модель:   HTTP ${code:-нет ответа}"
  echo
  echo "✅ Готово к шагу 1."
}

step1() {
  echo "═══ ШАГ 1: бинарник форка и видит ли он GTX 1080 ═══"
  mkdir -p "$HOME_DIR/bin" || return 1
  download "$ARCHIVE_URL" "$HOME_DIR/$ARCHIVE" "$ARCHIVE_SHA" || return 1
  echo "  распаковываю …"
  tar -xzf "$HOME_DIR/$ARCHIVE" -C "$HOME_DIR/bin" --strip-components=1 2>/dev/null \
    || tar -xzf "$HOME_DIR/$ARCHIVE" -C "$HOME_DIR/bin" || return 1
  if ! find_bin; then
    echo "✗ llama-cli в архиве не найден. Что распаковалось:"
    find "$HOME_DIR/bin" -maxdepth 2 -type f -perm -u+x | head -10
    return 1
  fi
  echo "  бинарник: $BIN  (сборка: $BUILD)"
  echo
  # 🔴 ТРИ ИСХОДА, А НЕ ДВА. Первая версия проверяла только «есть ли в
  # выводе слово CUDA» — и когда бинарник не запустился вовсе
  # («libcudart.so.12: cannot open shared object file»), уверенно
  # сообщила «CUDA-устройства нет, пойдёт на процессоре». Это разные
  # вещи: «карта не поддержана» и «программа не стартовала». Отличаем
  # по коду возврата, а неудачу показываем целиком.
  local out rc
  out="$("$BIN" --list-devices 2>&1)"; rc=$?
  echo "  --- вывод --list-devices (код $rc) ---"
  echo "$out" | head -20
  echo
  if [ $rc -ne 0 ] || echo "$out" | grep -qiE "error while loading|cannot open shared object"; then
    echo "✗ БИНАРНИК НЕ ЗАПУСТИЛСЯ — про карту это ничего не говорит."
    if echo "$out" | grep -q "libcudart"; then
      echo "   Не хватает CUDA-рантайма (libcudart/libcublas): Toolkit не"
      echo "   установлен, есть только libcuda.so.1 из драйвера."
      echo "   Дальше: BONSAI_BUILD=cpu (ничего ставить не надо) либо"
      echo "   ставить CUDA 12 — это решение владельца."
    fi
    return 1
  fi
  if echo "$out" | grep -qiE "CUDA|NVIDIA|Vulkan"; then
    echo "✅ Ускоритель виден. Есть смысл в шаге 2."
  else
    echo "ℹ️  Ускорителя нет — сборка процессорная, так и задумано."
    echo "   Модель упирается в память, не в вычисления: мерить шагом 3."
  fi
}

step2() {
  echo "═══ ШАГ 2: модель PTQ1_0, 5,95 ГБ ═══"
  mkdir -p "$HOME_DIR" || return 1
  local avail
  avail=$(df -BG --output=avail "$HOME_DIR" | tail -1 | tr -dc '0-9')
  echo "  свободно: ${avail} ГБ"
  [ "${avail:-0}" -lt 8 ] && { echo "✗ мало места"; return 1; }
  download "$MODEL_URL" "$HOME_DIR/$MODEL" "$MODEL_SHA" || return 1
  local got
  got=$(stat -c%s "$HOME_DIR/$MODEL")
  [ "$got" = "$MODEL_BYTES" ] || { echo "✗ размер $got ≠ $MODEL_BYTES"; return 1; }
  echo "✅ модель на месте и целая. Можно шаг 3."
}

step3() {
  echo "═══ ШАГ 3: сколько токенов в секунду ═══"
  [ -s "$HOME_DIR/$MODEL" ] || { echo "✗ сначала шаг 2"; return 1; }
  find_bin || { echo "✗ сначала шаг 1"; return 1; }
  local bench; bench="$(dirname "$BIN")/llama-bench"
  if [ ! -x "$bench" ]; then
    echo "  llama-bench в сборке нет — беру llama-cli с замером времени"
    local t0 t1
    t0=$(date +%s)
    timeout 1800 "$BIN" -m "$HOME_DIR/$MODEL" -ngl 99 -c 8192 -n 256 \
        -p "Одним предложением: что такое стоп-лосс?" 2>&1 | tail -20
    t1=$(date +%s)
    echo "  заняло $((t1-t0)) с на 256 токенов потолка"
    return 0
  fi
  # У процессорной сборки GPU-ветки нет вовсе: гонять -ngl 99 значит
  # ждать те же двадцать минут ради строки, которая ничем не отличается.
  if [ "$BUILD" != "cpu" ]; then
    echo "  --- на ускорителе (-ngl 99: выгрузить всё, что влезет) ---"
    timeout 1800 "$bench" -m "$HOME_DIR/$MODEL" -p 512 -n 128 -ngl 99 2>&1 | tail -12
    echo
  fi
  echo "  --- процессор, 8 потоков ---"
  # -t 8 по числу логических ядер i7-7700K (4 физических, HT).
  timeout 2400 "$bench" -m "$HOME_DIR/$MODEL" -p 512 -n 128 -ngl 0 -t 8 2>&1 | tail -12
  echo
  echo "🔴 Ориентир: брифингу нужно ~2000 токенов при reasoning_effort medium."
  echo "   4 ток/с — восемь минут, укладываемся. 1 ток/с — больше получаса."
}

case "${1:-}" in
  check|проверка) step_check ;;
  1) step1 ;;
  2) step2 ;;
  3) step3 ;;
  all|все) step_check && step1 && step2 && step3 ;;
  *) echo "Укажите: check (ничего не качает), 1, 2, 3 или all"; exit 2 ;;
esac
