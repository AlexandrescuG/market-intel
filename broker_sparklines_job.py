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

# 🔴 ПОЧЕМУ D1 ПЕРВЫМ, А НЕ H1 (13.10.2026).
# Прежняя версия брала ТОЛЬКО H1 не старше суток — и рисовала кривую у 15
# инструментов из 842. Причина не в джобе: в кэше свечей свежий H1 есть
# лишь у 19 символов (ctrader_pull тянет внутридневные бары по узкому
# списку), тогда как D1 свежий за неделю — у 738. То есть данные для линии
# почти у всех ЕСТЬ, просто на дневном таймфрейме, а джоб их не смотрел.
# Для мини-графика в списке дневные бары даже уместнее: 24 дневных бара —
# это ~месяц формы цены, обычный спарклайн на финансовых витринах, а не
# «последние сутки по часам», которые по неактивному инструменту всё
# равно почти прямая.
#
# Порядок: сначала D1 (покрытие), при его отсутствии/устаревании — H1
# (внутридневная картина для активных инструментов). Правило «нет данных —
# нет линии» ниже сохраняется: оставшиеся ~100 — это делистнутые бумаги
# (#FACEBOOK, #CITRIXSYSTEMS и т.п.), по ним честнее пусто, чем прямая.
BARS = 24
ПОПЫТКИ = (
    ("D1", 7 * 24 * 3600),   # дневной бар на выходных не обновляется — неделя
    ("H1", 24 * 3600),       # фоллбэк: суточная внутридневная динамика
)

log = logging.getLogger("broker_sparklines")


def catalog_symbols() -> list[str]:
    try:
        items = json.loads(CATALOG_PATH.read_text(encoding="utf-8")).get("items") or []
    except Exception as e:
        log.error("каталог не прочитан: %s", e)
        return []
    return [it.get("symbol") for it in items if it.get("symbol")]


def _ряд(sym: str, now: float) -> tuple[list[float], str] | None:
    """Первый таймфрейм из ПОПЫТКИ, у которого есть свежий ряд ≥3 точек.
    Возвращает (closes, tf) или None. Каждый TF по символу запрашивается
    у кэша не больше раза за счёт порядка перебора — дальше первого
    успешного не идём."""
    for tf, max_age in ПОПЫТКИ:
        bars, _stale = candle_cache.get(sym, tf)
        if not bars or now - bars[-1]["time"] > max_age:
            continue
        closes = [round(float(b["close"]), 6) for b in bars[-BARS:]]
        # Меньше трёх точек — не кривая, а шум: линия по ним создаёт
        # впечатление движения там, где его не измеряли.
        if len(closes) >= 3:
            return closes, tf
    return None


def build(verbose: bool = False) -> int:
    symbols = catalog_symbols()
    now = time.time()
    series: dict[str, list[float]] = {}
    # Таймфрейм — ПО СИМВОЛУ: у части инструментов линия дневная, у части
    # часовая. Для мини-графика это допустимо (он показывает форму, не
    # абсолютный период), но фронт должен знать, чтобы не подписать период
    # неверно. Пишем карту sym→tf рядом с рядами.
    tf_of: dict[str, str] = {}
    skipped = 0

    for sym in symbols:
        got = _ряд(sym, now)
        if got is None:
            skipped += 1
            continue
        series[sym], tf_of[sym] = got

    OUT_PATH.write_text(json.dumps({
        "updated": int(now),
        "bars": BARS,
        "count": len(series),
        "asked": len(symbols),
        "source": "candle_cache",
        "tf_of": tf_of,
        "series": series,
    }, separators=(",", ":")), encoding="utf-8")

    if verbose:
        from collections import Counter
        по_тф = Counter(tf_of.values())
        print(f"рядов записано: {len(series)} из {len(symbols)} инструментов каталога "
              f"(без свежих свечей: {skipped}); по ТФ: {dict(по_тф)}")
    return len(series)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    raise SystemExit(0 if build(a.verbose) >= 0 else 1)
