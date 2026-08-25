#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""brief_image_job.py — картинка к утреннему брифингу (SPEC_brief_outliers §4.2/§5).

Читает уже собранный web/data/brief_today.json (build_brief_v2.py) и рисует
web/data/brief_image_<дата>.png: колонки котировок сверху, четыре часовых
графика за сутки ниже. Ничего не считает заново — те же числа, что в тексте
брифинга, иначе картинка и текст разойдутся в первый же день.

Запускается в analyze/run_daily.sh ПОСЛЕ build_brief_v2/llm_context.
Бот забирает файл по дате и шлёт отдельным сообщением (§5.4).

    python3 brief_image_job.py [--date YYYY-MM-DD] [--out путь.png]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core import brief_image as BI
from core.config import BASE_DIR
from core.symbols_registry import _load as _load_registry

WEB_DATA = BASE_DIR / "web" / "data"
RATIO_NOTE_THRESHOLD = 1.3      # тот же порог «×N нормы», что в боте (tg_adapt)
QUOTES_CAP = 5
KEEP_DAYS = 14                  # старые картинки чистит сам джоб (см. _prune)

log = logging.getLogger("brief_image_job")

DISCLAIMER = "Статистическое наблюдение, не рекомендация."


def image_path(date: str) -> Path:
    return WEB_DATA / f"brief_image_{date}.png"


def _ru_name(symbol: str) -> str:
    entry = _load_registry().get(symbol)
    if isinstance(entry, dict) and entry.get("ru"):
        return entry["ru"]
    return symbol


def _note(m: dict) -> str:
    ratio = m.get("ratio")
    if isinstance(ratio, (int, float)) and ratio >= RATIO_NOTE_THRESHOLD:
        return f"×{ratio:.1f} нормы".replace(".", ",")
    return ""


def build_rows(movers: dict) -> tuple[list[dict], list[dict]]:
    """(строки котировок, панели). Порядок один и тот же — по отклонению от
    своей нормы: в картинке сверху и на графиках должно быть одно и то же,
    иначе читающий ищет несуществующую связь."""
    rows = list(movers.get("up") or []) + list(movers.get("down") or [])
    rows = [r for r in rows if r.get("symbol")]
    rows.sort(key=lambda r: (r.get("ratio") or 0), reverse=True)

    numbers = [{
        "symbol": r["symbol"],
        "name": _ru_name(r["symbol"]),
        "chg_pct": r.get("chg_pct"),
        "close": r.get("close"),
        "note": _note(r),
    } for r in rows[:QUOTES_CAP]]

    panels = [{**p, "name": _ru_name(p["symbol"])} for p in BI.pick_symbols(movers)]
    return numbers, panels


def _prune(keep_days: int = KEEP_DAYS) -> int:
    """Картинка рисуется каждое утро и больше никем не читается через сутки.
    Без уборки папка растёт молча и навсегда — раз в день по сотне килобайт
    заметно не станет никогда, и именно поэтому чистить надо здесь, а не
    когда-нибудь руками."""
    cutoff = datetime.now(timezone.utc).timestamp() - keep_days * 86400
    removed = 0
    for f in WEB_DATA.glob("brief_image_*.png"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError as e:
            log.warning("картинка: не удалось убрать %s: %s", f, e)
    return removed


def run(date: str, out: Path | None = None) -> int:
    path = WEB_DATA / "brief_today.json"
    try:
        brief = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.error("картинка: %s не прочитан (%s) — рисовать нечего", path, e)
        return 1
    if brief.get("date") != date:
        # Протухший бриф: нарисовать по нему — выдать вчерашние числа за
        # сегодняшние. Лучше без картинки.
        log.error("картинка: brief_today.json датирован %s, ожидали %s",
                  brief.get("date"), date)
        return 1

    numbers, panels = build_rows(brief.get("movers") or {})
    if not numbers and not panels:
        log.error("картинка: в брифе нет движений — рисовать нечего")
        return 1

    out = out or image_path(date)
    result = BI.render(numbers, panels, out, date=date, disclaimer=DISCLAIMER)
    if result is None:
        log.error("картинка: ни одной панели и ни одной котировки не отрисовано")
        return 1
    pruned = _prune()
    print(f"brief_image: {result} ({len(numbers)} котировок, {len(panels)} панелей"
          + (f", убрано старых {pruned}" if pruned else "") + ")")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        return run(args.date, args.out)
    except Exception as e:
        # §5.4/§7: провал рендера — это отсутствие картинки и запись в лог,
        # а не падение утреннего пайплайна. Но код ненулевой: тихо «успешно
        # без картинки» — ровно тот класс отказа, который спека запрещает.
        log.exception("картинка: рендер упал: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
