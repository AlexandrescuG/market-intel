#!/usr/bin/env python3
"""crypto_pull.py — свечи по криптовалютам с бирж в кэш свечей.

Модель ровно та же, что у ctrader_pull.py: отдельный процесс наполняет
data/candle_cache.db, а веб-обработчик только читает с диска. Сетевой вызов
внутри HTTP-запроса связывает живучесть сайта с живучестью чужого соединения —
этот урок в проекте оплачен дважды (мост MT5, спарклайны).

ЧТО ЗАКРЫВАЕТ. Пять монет, по которым у брокера нет баров вовсе или котировка
замерла: SHIBUSD (121 день), BTGUSD, ETHBTC, MELANIAUSD, PAX_GOLD. Плюс
подстраховка по остальным двенадцати — если брокерский фид замрёт, свечи
продолжат приходить, и это не потребует правки кода.

Запуск:  python3 crypto_pull.py [--once] [--verbose] [--only SYMBOL]
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

from core import candle_cache, crypto_feed  # noqa: E402

MAP_PATH = ROOT / "data" / "crypto_map.json"

# Таймфреймы и глубина. Дневки и недельки берём максимумом — на них считаются
# уровни и зоны, а уровень тем ценнее, чем дольше цена его помнит. Минутные
# ряды короче: они нужны для внутридневного графика, а не для истории.
TF_LIMIT = {"M1": 500, "M5": 700, "M15": 1000, "M30": 1000,
            "H1": 1000, "H4": 1000, "D1": 1000, "W1": 500}

# Пауза между запросами. Бюджет Binance — около 3000 запросов свечей в минуту,
# у Gate 200 за 10 секунд на эндпоинт. Наши 17 символов на 8 таймфреймов это
# 136 запросов за проход; четверти секунды хватает, чтобы не приблизиться к
# лимиту даже наполовину.
SLEEP_SEC = 0.25
CYCLE_SEC = 300

log = logging.getLogger("crypto_pull")


BLOCKLIST_PATH = ROOT / "data" / "instrument_blocklist.json"


def load_map() -> dict:
    raw = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    out = {k: v for k, v in raw.items()
           if not k.startswith("_") and isinstance(v, dict)}
    # Скрытые с витрины не тянем вовсе: незачем ходить на биржу за данными,
    # которые никто не увидит, и незачем держать их свежими в кэше.
    try:
        bl = json.loads(BLOCKLIST_PATH.read_text(encoding="utf-8"))
        blocked = {k for k in bl if not k.startswith("_")}
    except Exception:
        blocked = set()
    return {k: v for k, v in out.items() if k not in blocked}


def run_once(only: str | None = None, verbose: bool = False) -> tuple[int, int]:
    symbols = load_map()
    if only:
        symbols = {k: v for k, v in symbols.items() if k == only}
    ok = fail = 0
    for our_key, sources in symbols.items():
        got_any = False
        for tf, limit in TF_LIMIT.items():
            bars, src = crypto_feed.klines(sources, tf, limit)
            if bars:
                candle_cache.put(our_key, tf, bars)
                got_any = True
                if verbose:
                    last = time.strftime("%Y-%m-%d %H:%M", time.gmtime(bars[-1]["time"]))
                    print(f"  {our_key:12s} {tf:3s} {len(bars):5d} баров, до {last}, {src}")
            elif verbose:
                print(f"  {our_key:12s} {tf:3s} пусто")
            time.sleep(SLEEP_SEC)
        if got_any:
            ok += 1
        else:
            # 🔴 Ни одного бара ни по одному таймфрейму — это отказ, а не «пусто».
            # Молча пройти мимо значило бы повторить историю с SHIBUSD: символ
            # мёртв полгода, а узнали об этом от пользователя.
            fail += 1
            log.error("ни одного бара: %s (%s)", our_key,
                      ", ".join(f"{k}={v}" for k, v in sources.items() if v and k != "коммент"))
    return ok, fail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="один проход и выход")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--only", help="только этот инструмент")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    while True:
        t0 = time.time()
        ok, fail = run_once(a.only, a.verbose)
        log.info("проход: %d инструментов со свечами, %d без, %.1f с",
                 ok, fail, time.time() - t0)
        if a.once:
            # Ненулевой код возврата, только если не получили НИЧЕГО. Отдельный
            # мёртвый символ — не повод считать прогон неудачным, иначе юнит
            # будет краснеть из-за одной делистнутой монеты.
            return 0 if ok else 1
        time.sleep(max(30, CYCLE_SEC - (time.time() - t0)))


if __name__ == "__main__":
    raise SystemExit(main())
