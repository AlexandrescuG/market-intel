#!/usr/bin/env python3
"""
Yahoo Finance загрузчик OHLCV баров → price_bars.

Использование:
  python3 yfinance_pull.py            # последние 90 дней, все символы из symbol_map
  python3 yfinance_pull.py --days 365
  python3 yfinance_pull.py --symbol EURUSD XAUUSD

Ключ не требуется.
"""
import sqlite3, sys, time, argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta

try:
    import yfinance as yf
except ImportError:
    print("Установите: pip install yfinance", file=sys.stderr)
    sys.exit(1)

_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")


def load(days: int, symbols: list[str] | None = None):
    con = sqlite3.connect(str(_DB))
    cur = con.cursor()

    q = "SELECT our_key, yahoo FROM symbol_map WHERE yahoo IS NOT NULL"
    if symbols:
        placeholders = ",".join("?" * len(symbols))
        q += f" AND our_key IN ({placeholders})"
        rows = cur.execute(q, symbols).fetchall()
    else:
        rows = cur.execute(q).fetchall()

    if not rows:
        print("Нет символов в symbol_map с yahoo-ключом.", file=sys.stderr)
        con.close()
        return

    period = f"{days}d"
    ok = 0
    for our_key, yf_sym in rows:
        print(f"  {our_key} ({yf_sym}) ...", end=" ", flush=True)
        try:
            ticker = yf.Ticker(yf_sym)
            hist = ticker.history(period=period, interval="1d", auto_adjust=True)
            if hist.empty:
                print("нет данных")
                continue

            cur.execute("DELETE FROM price_bars WHERE symbol=? AND tf=?", (our_key, '1d'))
            bars = []
            for dt, row in hist.iterrows():
                # нормализуем к 00:00:00 UTC того же дня (по дате DatetimeIndex)
                # это нужно для JOIN с econ_event_history по формуле ts/86400*86400
                try:
                    d = dt.date()
                    ts = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())
                except Exception:
                    ts = (int(dt.timestamp()) // 86400) * 86400
                o, h, l, c, v = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"]), float(row.get("Volume", 0) or 0)
                bars.append((our_key, "1d", ts, o, h, l, c, v))

            cur.executemany(
                "INSERT OR REPLACE INTO price_bars(symbol,tf,ts,o,h,l,c,v) VALUES(?,?,?,?,?,?,?,?)",
                bars
            )
            con.commit()
            print(f"{len(bars)} баров OK")
            ok += 1
        except Exception as e:
            print(f"ошибка: {e}")
        time.sleep(0.5)  # вежливая пауза

    con.close()
    print(f"\nГотово: {ok}/{len(rows)} символов загружены.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Yahoo Finance → price_bars")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--symbol", nargs="+", help="Символы из symbol_map (наш ключ, напр. EURUSD XAUUSD)")
    args = ap.parse_args()
    print(f"Загрузка за {args.days} дней...")
    load(args.days, args.symbol)
