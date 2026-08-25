#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""broker_sparklines_job.py — спарклайны по всему каталогу (SPEC_chart_all_instruments §4, ярус 2).

РОТАЦИЯ С БЮДЖЕТОМ ВРЕМЕНИ, А НЕ ПОЛНЫЙ ОБХОД. Первый замер (0,22 с на
символ на валютах) обещал, что весь каталог берётся за три минуты, и первая
версия ходила подряд по всем 834. На живом прогоне 25.08 это оказалось
неправдой: 569 рядов за 1881 с, а на хвосте каталога — больше 6 с на символ,
потому что по акциям терминал докачивает историю с сервера брокера при первом
обращении.

🔴 Чем это кончилось, и почему здесь теперь бюджет. Тридцать минут занятого
моста уронили САЙТ: serve.py зовёт мост синхронно из обработчика запроса
(_mt5_tail <- /api/chart/tail), а сервер однопоточный — один ждущий запрос
заморозил все остальные, и снаружи пришёл bad gateway. Ограничение времени
ответа в serve.py добавлено отдельно, но фоновая работа не имеет права
создавать такое давление в принципе.

Поэтому: каждый прогон берёт символы, у которых ряд самый старый, и работает
не дольше BUDGET_SEC. Файл ДОПОЛНЯЕТСЯ, а не переписывается — за несколько
прогонов каталог покрывается целиком, и ни один из них не держит мост дольше
пары минут.

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
STATE_FILE = BASE_DIR / "data" / "sparklines_state.json"
CATALOG_PATH = WEB_DATA / "broker_catalog.json"
QUOTES_PATH = WEB_DATA / "broker_quotes.json"

HOST, PORT = "127.0.0.1", 18812
# 🔴 Размер куска и таймаут выставлены по ЗАМЕРУ, а не по интуиции. Первый
# полный обход 25.08: 569 рядов из 834 за 1881 с, и последние девять кусков по
# 30 символов отвалились с "result expired" — на хвосте каталога уходит больше
# 6 с на символ (терминал докачивает историю с сервера брокера при первом
# обращении), и кусок в 30 не помещался в 180 с. Куски по 10 при таймауте 300 с
# дают троекратный запас даже на самых медленных символах.
CHUNK = 10
PAUSE_SEC = 0.4             # пауза между кусками — мост нужен не только нам
BARS = 24                   # сутки по часам
RPC_TIMEOUT = 120
BUDGET_SEC = 120            # столько мост занимает ОДИН прогон, не дольше
REFRESH_SEC = 3600          # ряд старше часа считается устаревшим

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


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


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

    prev = _load_json(OUT_PATH, {}).get("series") or {}
    state = _load_json(STATE_FILE, {})
    now = time.time()

    # Сначала те, у кого ряда нет вовсе, потом самые старые. Так первый
    # прогон покрывает начало каталога, следующие — остальное, и ни один не
    # перебирает уже свежее.
    stale = [n for n in names if (now - state.get(n, 0)) > REFRESH_SEC]
    stale.sort(key=lambda n: state.get(n, 0))
    if not stale:
        print(f"спарклайны: все {len(names)} рядов свежее {REFRESH_SEC // 60} мин, обход не нужен")
        return 0

    t0 = time.time()
    series = dict(prev)
    done = empty = failed_chunks = 0
    for i in range(0, len(stale), CHUNK):
        if time.time() - t0 > BUDGET_SEC:
            break
        chunk = stale[i:i + CHUNK]
        try:
            got = _fetch_chunk(chunk)
        except Exception as e:
            failed_chunks += 1
            log.warning("спарклайны: кусок %d-%d не снят: %s", i, i + len(chunk), e)
            continue
        stamp = int(time.time())
        for sym, vals in got.items():
            state[sym] = stamp          # отметку ставим и пустым: иначе символ
            if vals:                    # без баров перебирался бы каждый прогон
                series[sym] = vals
                done += 1
            else:
                empty += 1
                series.pop(sym, None)
        time.sleep(PAUSE_SEC)

    if not series:
        log.error("спарклайны: ни одного ряда — файл не переписываем, "
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
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")

    took = time.time() - t0
    left = max(0, len(stale) - done - empty)
    print(f"спарклайны: обновлено {done} за {took:.0f} c, всего в файле {len(series)}/{len(names)}, "
          f"осталось устаревших {left} (пустых {empty}, неудачных кусков {failed_chunks})")
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
