#!/usr/bin/env python3
"""
Twelve Data adapter — загружает дневные OHLCV бары в price_bars.

Использование:
  TD_KEY=ваш_ключ python3 twelvedata_pull.py        # последние 90 дней
  TD_KEY=ваш_ключ python3 twelvedata_pull.py --days 365

Получить ключ: https://twelvedata.com/  (free: ~800 req/day, 8 req/min).
Free tier покрывает мажоры (EURUSD, USDJPY, GBP/USD, XAUUSD).
USDRUB/USDCNY/USDKZT/USDAED — на free могут быть недоступны, добавить через MT5 позже.
"""
import sqlite3, json, os, sys, time, argparse
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError
from datetime import datetime, timezone

_DB  = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
_API = "https://api.twelvedata.com"

def _key():
    k = os.environ.get("TD_KEY", "").strip()
    if not k:
        print("Ошибка: TD_KEY не задан. export TD_KEY=ваш_ключ", file=sys.stderr)
        sys.exit(1)
    return k

def _fetch(sym_td: str, outputsize: int, apikey: str):
    url = (f"{_API}/time_series?symbol={sym_td}&interval=1day"
           f"&outputsize={outputsize}&timezone=UTC&apikey={apikey}")
    try:
        with urlopen(url, timeout=30) as r:
            data = json.loads(r.read())
    except HTTPError as e:
        print(f"  HTTP {e.code} для {sym_td}", file=sys.stderr)
        return None
    if data.get("status") == "error":
        print(f"  API ошибка {sym_td}: {data.get('message')}", file=sys.stderr)
        return None
    values = data.get("values", [])
    if not values:
        print(f"  Нет данных для {sym_td}", file=sys.stderr)
        return None
    return values

def _ts_of(date_str: str) -> int:
    # "2024-05-23 00:00:00" → Unix timestamp UTC
    dt = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())

def pull(days: int = 90):
    apikey = _key()
    con = sqlite3.connect(str(_DB))

    # Получаем список символов из symbol_map (только у которых есть twelvedata)
    symbols = con.execute(
        "SELECT our_key, twelvedata FROM symbol_map WHERE twelvedata IS NOT NULL"
    ).fetchall()

    total_inserted = 0
    for our_key, td_sym in symbols:
        print(f"  {our_key} ({td_sym}) ...", end=" ", flush=True)
        values = _fetch(td_sym, days, apikey)
        if not values:
            continue

        rows = []
        for v in values:
            try:
                rows.append((
                    our_key, "1d", _ts_of(v["datetime"]),
                    float(v["open"]), float(v["high"]),
                    float(v["low"]),  float(v["close"]),
                    float(v.get("volume") or 0),
                ))
            except (KeyError, ValueError):
                continue

        con.executemany(
            "INSERT OR REPLACE INTO price_bars(symbol,tf,ts,o,h,l,c,v) VALUES(?,?,?,?,?,?,?,?)",
            rows,
        )
        con.commit()
        print(f"{len(rows)} баров записано")
        total_inserted += len(rows)

        # rate limit: 8 req/min free tier
        time.sleep(8)

    con.close()
    print(f"\nГотово. Итого записей: {total_inserted}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90, help="Глубина истории в днях")
    args = ap.parse_args()
    print(f"Загружаем {args.days} дней из Twelve Data...")
    pull(args.days)
