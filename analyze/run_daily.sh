#!/usr/bin/env bash
PATH=/home/sbf/.local/bin:/usr/local/bin:/usr/bin:/bin
# Дневной пайплайн (cron 06:00):
#   1. бриф → Claude → трейдерский отчёт → Telegram (REPORT_CHAT)
#   2. тот же бриф → Claude → контент-идеи → Telegram (CHAT_ID)
#   3. извлечь НОВЫЕ_НАБЛЮДЕНИЯ → дописать в data/observations.md
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD"

[ -f .venv/bin/activate ] && source .venv/bin/activate || true

TODAY="$(date +%F)"
BRIEF="data/briefs/brief_${TODAY}.md"
REPORT="data/reports/report_${TODAY}.md"
CONTENT="data/reports/content_${TODAY}.md"
OBS="data/observations.md"

# ── 1/4 Сборка брифа ──────────────────────────────────────────────────────────
echo "[$(date +%T)] 1/4 сборка брифа…"
python3 -m analyze.build_brief --hours 24

# ── 2/4 Трейдерский отчёт ─────────────────────────────────────────────────────
echo "[$(date +%T)] 2/4 трейдерский анализ (Claude Code)…"
claude -p "$(cat analyze/prompt.md)

ИСХОДНЫЙ БРИФ: ${BRIEF}
Прочитай его (Read) и запиши готовый отчёт в: ${REPORT} (Write).
Сегодняшняя дата: ${TODAY}. В stdout верни только путь к файлу отчёта." \
  --allowedTools "Read" "Write" \
  --output-format text \
  || { echo "claude -p (отчёт) упал"; exit 1; }

[ -s "$REPORT" ] || { echo "Отчёт не создан: $REPORT"; exit 1; }

# ── 3/4 Контент-идеи (отдельный вызов) ───────────────────────────────────────
echo "[$(date +%T)] 3/4 контент-идеи (Claude Code)…"
claude -p "$(cat analyze/prompt_content.md)

ИСХОДНЫЙ БРИФ: ${BRIEF}
Прочитай его (Read) и запиши контент-идеи в: ${CONTENT} (Write).
Сегодняшняя дата: ${TODAY}. В stdout верни только путь к файлу." \
  --allowedTools "Read" "Write" \
  --output-format text \
  || echo "claude -p (контент) упал — продолжаем"

# ── 4/4 Отправка в Telegram ───────────────────────────────────────────────────
echo "[$(date +%T)] 4/4 отправка в Telegram…"

# Трейдерский отчёт → REPORT_CHAT (или CHAT_ID если не задан отдельно)
python3 -m core.telegram --send-file "$REPORT"

# Контент-идеи → тот же чат (но отдельным сообщением, с разделителем)
if [ -s "$CONTENT" ]; then
  python3 -m core.telegram --send-file "$CONTENT"
fi

# ── Извлечение новых наблюдений → observations.md ────────────────────────────
# Берём всё что идёт после заголовка "## 📋 НОВЫЕ_НАБЛЮДЕНИЯ"
# и соответствует формату "YYYY-MM-DD | ..."
python3 - <<'PYEOF'
import re, pathlib, sys

report = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
import os, glob
today = os.environ.get("TODAY", "")
matches = glob.glob(f"data/reports/report_{today}.md")
if not matches:
    print("observations: отчёт не найден, пропускаем"); sys.exit(0)

text = pathlib.Path(matches[0]).read_text(encoding="utf-8")
# Ищем раздел после НОВЫЕ_НАБЛЮДЕНИЯ
m = re.search(r"##\s*📋\s*НОВЫЕ_НАБЛЮДЕНИЯ.*?\n(.*?)(?=\n##|\Z)", text, re.S)
if not m:
    print("observations: раздел не найден"); sys.exit(0)

obs_path = pathlib.Path("data/observations.md")
if not obs_path.exists():
    obs_path.write_text("# История наблюдений\n\n", encoding="utf-8")

existing = obs_path.read_text(encoding="utf-8")
new_lines = []
for line in m.group(1).splitlines():
    line = line.strip()
    if re.match(r"\d{4}-\d{2}-\d{2}\s*\|", line) and line not in existing:
        new_lines.append(line)

if new_lines:
    with obs_path.open("a", encoding="utf-8") as f:
        f.write("\n".join(new_lines) + "\n")
    print(f"observations: добавлено {len(new_lines)} наблюдений")
else:
    print("observations: новых наблюдений нет")
PYEOF

echo "[$(date +%T)] готово: $REPORT"
