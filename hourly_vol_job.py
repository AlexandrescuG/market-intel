#!/usr/bin/env python3
"""
hourly_vol_job.py — SBF_Charts_Layer3_Spec, Фаза 2.2 (полоска типичной
волатильности по часам).

Офлайн-джоб (еженедельно, см. sbf-hourly-vol.timer): для каждого инструмента
с M30 OHLCV (web/data/ohlc_{symbol}_M30.json — тот же файл, что рисует
chart.html) считает средний диапазон (high-low) по часу суток (UTC) за
последние 90 дней (столько доступно — история M30 короче 90 дней для части
символов, это не ошибка джоба, а честный предел глубины истории) → до 24
значений. Полный пересчёт с нуля каждый прогон (DELETE+INSERT), как
остальные джобы Layer1/2/3.

Использование:
  python3 hourly_vol_job.py [--verbose]
"""
import argparse
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import core.price_bars as _price_bars

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
_WEB_DATA = Path(__file__).parent / "web" / "data"

WINDOW_DAYS = 90


def compute_symbol(symbol: str, now_ts: int, verbose=False):
    # WP1.2 SPEC_alpha_engine_implementation.md: раньше свой парсинг
    # ohlc_{symbol}_M30.json -- теперь price_bars напрямую.
    candles = _price_bars.load_candles(symbol, "30m")
    if not candles:
        return []
    cutoff = now_ts - WINDOW_DAYS * 86400
    buckets = {h: [] for h in range(24)}
    for c in candles:
        ts = c["ts"]
        if ts < cutoff:
            continue
        try:
            h = datetime.fromtimestamp(ts, timezone.utc).hour
            buckets[h].append(c["h"] - c["l"])
        except (ValueError, TypeError, KeyError):
            continue

    rows = []
    for h in range(24):
        vals = buckets[h]
        if not vals:
            continue
        rows.append({"symbol": symbol, "hour_utc": h, "avg_range": round(sum(vals) / len(vals), 6)})
    if verbose:
        covered = sum(1 for h in range(24) if buckets[h])
        print(f"  {symbol}: {covered}/24 часов покрыто ({len(candles)} свечей M30 в наличии)")
    return rows


def run(verbose: bool = False) -> int:
    con = sqlite3.connect(str(_BOT_DB))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS hourly_vol_profile(
          symbol TEXT, hour_utc INT, avg_range REAL, PRIMARY KEY(symbol, hour_utc));
    """)
    con.commit()

    now_ts = int(time.time())
    symbols = _price_bars.available_symbols("30m")

    written = 0
    for symbol in symbols:
        rows = compute_symbol(symbol, now_ts, verbose)
        if not rows:
            continue
        con.execute("DELETE FROM hourly_vol_profile WHERE symbol=?", (symbol,))
        for r in rows:
            con.execute(
                "INSERT INTO hourly_vol_profile(symbol, hour_utc, avg_range) VALUES(?,?,?)",
                (r["symbol"], r["hour_utc"], r["avg_range"]),
            )
            written += 1

    con.commit()
    con.close()
    if verbose:
        print(f"готово: {written} строк по {len(symbols)} символам")
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    run(verbose=args.verbose)
