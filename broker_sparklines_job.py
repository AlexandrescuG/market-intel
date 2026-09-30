#!/usr/bin/env python3
"""broker_sparklines_job.py — маленькие кривые рядом с ценой в списке инструментов.

ЧТО ИЗМЕНИЛОСЬ (02.09.2026). Раньше джоб обходил каталог через синхронный мост
MT5: куски по 10 символов, бюджет 120 с на прогон, и всё равно 25.08 обход 842
инструментов насытил мост и уронил сайт. После аварии таймер выключили, а
chart.html продолжал грузить файл — и девять дней рисовал кривые недельной
давности как сегодняшние. Это хуже, чем отсутствие кривых: неверные данные
выглядят достоверно.

Теперь данные берутся из core/candle_cache — того же кэша, из которого сайт
отдаёт графики. Там уже 781 инструмент, наполняет его ctrader_pull и обычные
показы графиков. К брокеру этот джоб не ходит ВООБЩЕ: ни к MT5, ни к cTrader.
Причина, по которой его выключили, отпала вместе с обращениями к мосту.

🔴 НЕТ ДАННЫХ — НЕТ ЛИНИИ. Инструмент, которого нет в кэше, просто отсутствует
в файле, и список рисует пустое место. Дорисовывать последнюю известную кривую
или тянуть прямую нельзя: пустота честно говорит «неизвестно», а линия говорит
«вот как было», и это разные утверждения.

Запуск:  python3 broker_sparklines_job.py [--verbose]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core import candle_cache  # noqa: E402

WEB_DATA = ROOT / "web" / "data"
OUT_PATH = WEB_DATA / "broker_sparklines.json"
CATALOG_PATH = WEB_DATA / "broker_catalog.json"

TF = "H1"
BARS = 24          # сутки по часам — столько же, сколько рисовал прежний джоб
# Ряд, последняя точка которого старше суток, в файл не идёт. Кривая суточной
# давности рядом с сегодняшней ценой — ровно та беда, из-за которой этот джоб
# и переписан.
MAX_AGE_SEC = 24 * 3600

log = logging.getLogger("broker_sparklines")


def catalog_symbols() -> list[str]:
    try:
        items = json.loads(CATALOG_PATH.read_text(encoding="utf-8")).get("items") or []
    except Exception as e:
        log.error("каталог не прочитан: %s", e)
        return []
    return [it.get("symbol") for it in items if it.get("symbol")]


def build(verbose: bool = False) -> int:
    symbols = catalog_symbols()
    now = time.time()
    series: dict[str, list[float]] = {}
    skipped_empty = skipped_old = 0

    for sym in symbols:
        bars, _stale = candle_cache.get(sym, TF)
        if not bars:
            skipped_empty += 1
            continue
        if now - bars[-1]["time"] > MAX_AGE_SEC:
            skipped_old += 1
            continue
        closes = [round(float(b["close"]), 6) for b in bars[-BARS:]]
        # Меньше трёх точек — не кривая, а шум: нарисованная по ним линия
        # создаёт впечатление движения там, где его не измеряли.
        if len(closes) >= 3:
            series[sym] = closes

    OUT_PATH.write_text(json.dumps({
        "updated": int(now),
        "tf": TF,
        "bars": BARS,
        "count": len(series),
        "asked": len(symbols),
        "source": "candle_cache",
        "series": series,
    }, separators=(",", ":")), encoding="utf-8")

    if verbose:
        print(f"рядов записано: {len(series)} из {len(symbols)} инструментов каталога "
              f"(нет в кэше: {skipped_empty}, устарели: {skipped_old})")
    return len(series)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    raise SystemExit(0 if build(a.verbose) >= 0 else 1)
