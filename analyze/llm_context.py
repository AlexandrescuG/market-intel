#!/usr/bin/env python3
"""
analyze/llm_context.py — SPEC_morning_brief_v2.md, Этап 4.

Читает data/reports/context_{date}.json (модель пишет его через Write —
см. новую "ГЛАВНАЯ ЗАДАЧА" в начале analyze/prompt.md), валидирует форму и
домерживает headline/context в УЖЕ написанный analyze/build_brief_v2.py
web/data/brief_today.json. Числа сюда не попадают вообще — только заголовок
и три пункта, которые пишет модель.

Если файла нет, он битый или не проходит валидацию формы — headline/context
просто не появляются в brief_today.json (и попадают в _meta.empty_blocks),
БЕЗ заглушек и без падения (см. спеку §3.2 "правило пустых блоков").

Использование:
  python3 -m analyze.llm_context [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import BASE_DIR, REPORTS_DIR  # noqa: E402

WEB_DATA = BASE_DIR / "web" / "data"

MAX_HEADLINE_LEN = 140
MAX_CONTEXT_LEN = 180
MAX_UNKNOWN_LEN = 140
CONTEXT_COUNT = 3
ALLOWED_CONFIDENCE = {"quotes", "media", "social_unverified"}


def _today_str() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def validate(payload: dict) -> tuple[str, list[dict], str | None] | None:
    """None если форма не годится -- вызывающий код решает, что делать
    (не подставлять заглушку, просто не публиковать).

    "unknown" (SPEC_tg_morning_brief_v2.md §2) необязателен и не топит весь
    payload сам по себе -- невалидный/отсутствующий unknown просто даёт None
    третьим элементом, headline/context остаются в силе."""
    if not isinstance(payload, dict):
        return None
    headline = payload.get("headline")
    if not isinstance(headline, str) or not headline.strip() or len(headline) > MAX_HEADLINE_LEN:
        return None
    context = payload.get("context")
    if not isinstance(context, list) or len(context) != CONTEXT_COUNT:
        return None
    clean_context = []
    for item in context:
        if not isinstance(item, dict):
            return None
        text = item.get("text")
        confidence = item.get("confidence")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_CONTEXT_LEN:
            return None
        if confidence not in ALLOWED_CONFIDENCE:
            return None
        clean_context.append({"text": text.strip(), "confidence": confidence})

    unknown = payload.get("unknown")
    if isinstance(unknown, str) and unknown.strip() and len(unknown) <= MAX_UNKNOWN_LEN:
        clean_unknown = unknown.strip()
    else:
        clean_unknown = None

    return headline.strip(), clean_context, clean_unknown


def merge(date: str | None = None) -> bool:
    """True если headline/context реально добавлены. Возвращает False (не
    бросает исключение) на любую форму отсутствия/невалидности -- это
    ожидаемое состояние до первого реального прогона claude -p, не ошибка."""
    date = date or _today_str()
    context_file = REPORTS_DIR / f"context_{date}.json"
    brief_file = WEB_DATA / "brief_today.json"

    if not brief_file.exists():
        print(f"llm_context: {brief_file} не существует -- сначала build_brief_v2", file=sys.stderr)
        return False

    brief = json.loads(brief_file.read_text())
    meta = brief.setdefault("_meta", {})
    empty_blocks = set(meta.get("empty_blocks", []))

    validated = None
    if context_file.exists():
        try:
            raw = json.loads(context_file.read_text())
            validated = validate(raw)
        except (json.JSONDecodeError, OSError):
            validated = None

    if validated is None:
        empty_blocks.update({"headline", "context"})
        meta["empty_blocks"] = sorted(empty_blocks)
        brief_file.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"llm_context: {context_file} отсутствует/невалиден -- headline/context не опубликованы", file=sys.stderr)
        return False

    headline, context, unknown = validated
    brief["headline"] = headline
    brief["context"] = context
    empty_blocks.discard("headline")
    empty_blocks.discard("context")
    # "unknown" -- в отличие от headline/context, необязателен по своей сути
    # (отсутствует в большинство дней, когда исход дня не является реально
    # неопределённым) -- отсутствие НЕ считается "пустым блоком" (это не
    # проблема данных, это нормальное состояние), поэтому в empty_blocks не
    # попадает вовсе.
    if unknown is not None:
        brief["unknown"] = unknown
    else:
        brief.pop("unknown", None)
    meta["empty_blocks"] = sorted(empty_blocks)
    brief_file.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"llm_context: headline+{len(context)} пункта context добавлены в {brief_file}", file=sys.stderr)
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None)
    args = parser.parse_args()
    merge(args.date)


if __name__ == "__main__":
    main()
