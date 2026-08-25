#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""broker_sparklines_job.py — спарклайны по всему каталогу (SPEC_chart_all_instruments §4, ярус 2).

ПОЧЕМУ ЗДЕСЬ НЕТ ОЧЕРЕДИ ПО ВИДИМОЙ ОБЛАСТИ. Спека закладывала запрос
спарклайнов пачками по мере прокрутки (IntersectionObserver + кэш), исходя из
того, что «~24 бара H1 на символ, то есть тысяча вызовов» — дорого. Замер
25.08 через мост: 0,22 с на символ (10 шт — 0,5 с, 50 — 5,2 с, 200 — 44 с),
то есть ВЕСЬ каталог из 842 обходится примерно за три минуты. Это укладывается
в то самое окно кэша в 10-15 минут, которое спека и предлагала.

Значит, целой подсистемы «спроси то, что видно, положи в кэш, покажи заглушку»
можно не строить: страница получает готовый файл со всеми рядами сразу, без
заглушек, дозагрузок и мигания при прокрутке. Меньше движущихся частей — и
меньше мест, где спарклайн молча не приедет.

ОБХОД ИДЁТ КУСКАМИ. Три минуты подряд держать мост нельзя: на нём же висит
ежечасная доливка баров и 15-секундный снимок котировок. Между кусками пауза,
соединение переоткрывается — мост свободен почти всё время обхода.

Расписание: sbf-broker-sparklines.timer, раз в 15 минут.

    python3 broker_sparklines_job.py [--limit N] [--verbose]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import rpyc

sys.path.insert(0, str(Path(__file__).parent))

from core.config import BASE_DIR

WEB_DATA = BASE_DIR / "web" / "data"
OUT_PATH = WEB_DATA / "broker_sparklines.json"
CATALOG_PATH = WEB_DATA / "broker_catalog.json"
QUOTES_PATH = WEB_DATA / "broker_quotes.json"

HOST, PORT = "127.0.0.1", 18812
CHUNK = 30                  # столько символов за одно соединение
PAUSE_SEC = 1.0             # пауза между кусками — мост нужен не только нам
BARS = 24                   # сутки по часам
RPC_TIMEOUT = 180

log = logging.getLogger("broker_sparklines")


def _symbols() -> list[str]:
    """Только те, по которым котировка вообще приходит: у остальных и баров
    нет, а перебирать их каждые 15 минут — впустую держать мост."""
    quotes = json.loads(QUOTES_PATH.read_text(encoding="utf-8"))
    fields = quotes.get("fields") or []
    i_sym, i_ts = fields.index("symbol"), fields.index("quote_ts")
    return [row[i_sym] for row in quotes["items"] if row[i_ts]]


def _fetch_chunk(names: list[str]) -> dict[str, list[float] | None]:
    conn = rpyc.classic.connect(HOST, PORT)
    conn._config["sync_request_timeout"] = RPC_TIMEOUT
    try:
        conn.execute("import MetaTrader5 as m; m.initialize()")
        conn.namespace["_names"] = names
        conn.namespace["_bars"] = BARS
        # Цикл выполняется НА СТОРОНЕ терминала: 30 символов по 24 бара — это
        # 720 значений, и тянуть их netref'ами по одному значило бы сотни
        # round-trip'ов вместо одного.
        conn.execute("""
_out = {}
for _s in _names:
    _r = m.copy_rates_from_pos(_s, m.TIMEFRAME_H1, 0, _bars)
    _out[_s] = [round(float(x['close']), 6) for x in _r] if _r is not None and len(_r) else None
""")
        return rpyc.classic.obtain(conn.namespace["_out"])
    finally:
        try:
            conn.close()
        except Exception:
            pass


def run(limit: int | None = None) -> int:
    try:
        names = _symbols()
    except (OSError, json.JSONDecodeError, ValueError) as e:
        log.error("спарклайны: снимок котировок не прочитан (%s) — обходить нечего", e)
        return 1
    if limit:
        names = names[:limit]
    if not names:
        log.error("спарклайны: в снимке нет ни одного символа с котировкой")
        return 1

    t0 = time.time()
    series: dict[str, list[float]] = {}
    empty = 0
    failed_chunks = 0
    for i in range(0, len(names), CHUNK):
        chunk = names[i:i + CHUNK]
        try:
            got = _fetch_chunk(chunk)
        except Exception as e:
            # Кусок не удался — остальные всё равно берём: половина рядов
            # лучше, чем ни одного, а тихо отдать пустой файл нельзя.
            failed_chunks += 1
            log.warning("спарклайны: кусок %d-%d не снят: %s", i, i + len(chunk), e)
            continue
        for sym, vals in got.items():
            if vals:
                series[sym] = vals
            else:
                empty += 1
        time.sleep(PAUSE_SEC)

    if not series:
        log.error("спарклайны: ни одного ряда не снято — файл не переписываем, "
                  "прошлый остаётся с прежней датой")
        return 1

    WEB_DATA.mkdir(parents=True, exist_ok=True)
    tmp = OUT_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({
        "updated": datetime.now(timezone.utc).isoformat(),
        "tf": "H1",
        "bars": BARS,
        "count": len(series),
        "asked": len(names),
        "series": series,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(OUT_PATH)

    took = time.time() - t0
    print(f"спарклайны: {len(series)} рядов из {len(names)} за {took:.0f} c "
          f"(пустых {empty}, неудачных кусков {failed_chunks}) -> {OUT_PATH.name}")
    # Частичный обход — ненулевой код: «прошло успешно, просто половина рядов
    # отсутствует» ровно тот отказ, который не должен выглядеть как норма.
    return 2 if failed_chunks else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="обойти только первые N (для проверки)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return run(args.limit)


if __name__ == "__main__":
    sys.exit(main())
