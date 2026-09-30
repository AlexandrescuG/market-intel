#!/usr/bin/env python3
"""analyze/llm_context_local.py — запасной синтез headline/context на локальной модели.

29.09.2026. Когда `claude -p` недоступен (у организации отключили доступ к
подписке — так брифинг стоял с 17 по 29 сентября), аналитическая часть
брифинга пропадает целиком. Ollama на этой машине уже есть и оплаты не
требует, поэтому она берёт на себя роль последнего рубежа.

ЧЕСТНО О КАЧЕСТВЕ. Локальная 7B пишет заметно беднее Claude: короче, суше,
иногда общими словами. Это не замена, а страховка — лучше сухой, но верный
текст, чем пустой блок. Написанное всё равно проходит через тот же валидатор
пуша, что и текст Claude, и не проходит — публикуется сокращённый вид.

ЗАМЕР НА ЭТОЙ МАШИНЕ (29.09): qwen2.5-coder:7b — 15,6 с на ответ;
sbf-reasoner (27B Q4) — больше десяти минут, в утреннее окно не годится.
Поэтому по умолчанию берётся 7B, а не самая «умная» из установленных.

Использование:
  python3 -m analyze.llm_context_local [--date YYYY-MM-DD] [--model ...]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import BASE_DIR, REPORTS_DIR  # noqa: E402

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen2.5-coder:7b"
TIMEOUT_SEC = 180
# Сколько брифа отдаём модели. 7B с длинным контекстом работает хуже и
# дольше, а всё нужное (котировки, календарь, темы) лежит в начале файла.
BRIEF_CHARS = 6000

# 🔴 ПРАВИЛА ЗДЕСЬ ДОЛЖНЫ ПОВТОРЯТЬ analyze/prompt.md, А НЕ ЖИТЬ СВОЕЙ ЖИЗНЬЮ.
# Это второй промпт для той же задачи, и 30.09.2026 выяснилось, что запрет
# «слух из соцсетей не выносится в headline» был добавлен только в основной.
# Цена расхождения известна: 17.09 заголовок «Соцсети: ФРС подняла ставку»
# уехал в title архивной страницы брифа, а архив не переписывается и именно
# title цитируют ИИ-поисковики. Запасной путь включается ровно тогда, когда
# за ним никто не смотрит, — расхождение промптов вскроется поздно.
PROMPT = """Ты — редактор утреннего рыночного обзора. На входе — сводка за сутки.

Верни СТРОГО JSON, без markdown и без пояснений:
{"headline": "...", "context": [{"text": "...", "confidence": "quotes"},
 {"text": "...", "confidence": "media"},
 {"text": "...", "confidence": "social_unverified"}]}

ПРАВИЛА:
- всё по-русски;
- headline — ОДНО предложение не длиннее 110 знаков, с конкретными числами;
- в headline — ТОЛЬКО подтверждённое котировками или лентами СМИ (уровни
  "quotes"/"media"). Слух из соцсетей в заголовок не выносится НИКОГДА, даже
  с пометкой «Соцсети:». Непроверенному место только в третьем пункте
  context с confidence "social_unverified";
- ровно три пункта context, каждый 1-2 предложения, каждое предложение не
  длиннее 25 слов;
- confidence: "quotes" — то, что видно в котировках; "media" — то, о чём
  пишут ленты; "social_unverified" — то, что говорят в соцсетях;
- бери только числа и факты из сводки, ничего не придумывай;
- ЗАПРЕЩЕНЫ слова: ожидается, продолжит, вырастет, упадёт, цель, прогноз,
  покупать, продавать, стоит, рекомендуем, лонг, шорт;
- десятичный разделитель — запятая.

СВОДКА:
{brief}"""


def _extract_json(raw: str) -> dict | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        text = re.sub(r"^json\s*", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


def generate(date: str, model: str = DEFAULT_MODEL) -> bool:
    brief_path = BASE_DIR / "data" / "briefs" / f"brief_{date}.md"
    out_path = REPORTS_DIR / f"context_{date}.json"
    try:
        brief = brief_path.read_text(encoding="utf-8")[:BRIEF_CHARS]
    except OSError as e:
        print(f"llm_context_local: {brief_path} не прочитан: {e}", file=sys.stderr)
        return False

    payload = {
        "model": model,
        "prompt": PROMPT.replace("{brief}", brief),
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 900},
    }
    try:
        req = urllib.request.Request(
            OLLAMA_URL, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        resp = json.load(urllib.request.urlopen(req, timeout=TIMEOUT_SEC))
    except Exception as e:
        print(f"llm_context_local: Ollama не ответила: {e}", file=sys.stderr)
        return False

    data = _extract_json(resp.get("response") or "")
    if not data:
        print("llm_context_local: ответ модели не разобран", file=sys.stderr)
        return False

    headline = (data.get("headline") or "").strip()
    context = data.get("context")
    if not headline or not isinstance(context, list) or len(context) != 3:
        print(f"llm_context_local: форма не годится (headline={bool(headline)}, "
              f"пунктов={len(context) if isinstance(context, list) else 'нет'})",
              file=sys.stderr)
        return False

    # Формат тот же, что пишет claude -p: дальше файл подхватывает
    # llm_context.py, и ему всё равно, кто автор.
    out = {"headline": headline[:140],
           "context": [{"text": (c.get("text") or "").strip()[:180],
                        "confidence": c.get("confidence", "media")}
                       for c in context if isinstance(c, dict)],
           "_source": f"ollama:{model}"}
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    except OSError as e:
        print(f"llm_context_local: не записан {out_path}: {e}", file=sys.stderr)
        return False
    print(f"llm_context_local: {out_path.name} записан локальной моделью {model}",
          file=sys.stderr)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()
    return 0 if generate(args.date, args.model) else 1


if __name__ == "__main__":
    sys.exit(main())
