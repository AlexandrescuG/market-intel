#!/usr/bin/env bash
# Дневной пайплайн (cron 06:00): бриф → анализ Claude Code → отчёт в Telegram.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD"

# Обеспечиваем PATH для cron/systemd: claude живёт в ~/.local/bin
export PATH="$HOME/.local/bin:$PATH"

# Загрузка .env (TELEGRAM_BOT_TOKEN и др.)
[ -f .env ] && set -a && source .env && set +a || true

# venv если есть
[ -f .venv/bin/activate ] && source .venv/bin/activate || true

TODAY="$(date +%F)"
BRIEF="data/briefs/brief_${TODAY}.md"
REPORT="data/reports/report_${TODAY}.md"
CONTEXT_FILE="data/reports/context_${TODAY}.json"
FOCUS_ANALYSIS_PATTERN="data/focus/analysis_${TODAY}_<ТИКЕР>.txt"

echo "[$(date +%T)] 0/3 Focus Engine (ATR-кэш + фокус дня)…"
mkdir -p data/focus
# Некритично для основного отчёта -- если движок упал, build_brief.py сам
# обнаружит отсутствие focus_state и молча пропустит блок «В ФОКУСЕ» (см.
# try/except там же). Также подстрахован таймером sbf-focus-batch.timer в
# 05:50 -- запуск дважды за 10 мин безвреден (INSERT OR REPLACE везде).
python3 focus_batch_job.py --verbose || echo "focus_batch_job упал, продолжаем без блока фокуса"

echo "[$(date +%T)] 1/3 сборка брифа…"
python3 -m analyze.build_brief --hours 24

echo "[$(date +%T)] 2/3 анализ через Claude Code…"
# claude -p headless: читает бриф, пишет отчёт. allowedTools — без интерактивных запросов.
claude -p "$(cat analyze/prompt.md)

ИСХОДНЫЙ БРИФ лежит в файле: ${BRIEF}
Сегодняшняя дата и время (локальное): $(date '+%Y-%m-%d %H:%M %Z').
Прочитай бриф (Read) и запиши готовый отчёт в файл: ${REPORT} (Write).
Файл для ГЛАВНОЙ ЗАДАЧИ (headline+context, см. инструкции выше) запиши по
пути: ${CONTEXT_FILE} (Write).
Сверяй заявления из соцсетей с блоком РЕАЛЬНОЕ СОСТОЯНИЕ РЫНКА.
События, уже прошедшие к этой дате/времени, разбирай по факту, а не как прогноз.
Если в брифе есть блок «В ФОКУСЕ СЕГОДНЯ» — см. раздел «ДОПОЛНИТЕЛЬНО — ФОКУС
ДНЯ» выше в инструкциях. Там может быть НЕСКОЛЬКО инструментов списком — для
КАЖДОГО запиши отдельный файл по шаблону пути: ${FOCUS_ANALYSIS_PATTERN}
(замени <ТИКЕР> на тикер этого инструмента из скобок в брифе, Write).
Если блока «В ФОКУСЕ СЕГОДНЯ» в брифе нет — файлы фокуса не создавай.
Верни в stdout только путь к отчёту." \
  --allowedTools "Read" "Write" \
  --output-format text \
  || { echo "claude -p упал"; exit 1; }

if [ ! -s "$REPORT" ]; then
  echo "Отчёт не создан: $REPORT"; exit 1
fi

echo "[$(date +%T)] 2b/3 деривация brief_today.json (SPEC_morning_brief_v2.md,
  раньше запускалась только вручную -- см. docs/BRIEF_V2_PROGRESS.md)…"
# Некритично для отчёта/Telegram-дайджеста выше -- build_brief_v2.py и
# llm_context.py пишут ОТДЕЛЬНЫЙ файл (web/data/brief_today.json), который
# report.json/Telegram-отправка ниже не читают. Порядок важен: build_brief_v2
# перезаписывает brief_today.json целиком, llm_context.py домердживает
# headline/context ПОВЕРХ него -- в обратном порядке правки потерялись бы.
python3 -m analyze.build_brief_v2 || echo "build_brief_v2 упал, brief_today.json не обновлён"
python3 -m analyze.llm_context || echo "llm_context упал, headline/context не смержены"

echo "[$(date +%T)] 3/3 отправка в Telegram + публикация на сайт…"
python3 -m core.telegram --send-file "$REPORT"
# обновить report.json, чтобы дашборд показал свежий отчёт
PYTHONPATH="$PWD" python3 publish.py >/dev/null 2>&1 || true

echo "[$(date +%T)] готово: $REPORT"
