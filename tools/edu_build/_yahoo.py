"""Shared helper: fetch real daily OHLC from Yahoo Finance's public chart API.
Used by chapter-3 build scripts for windows the local MT5 backfill doesn't
cover (MT5 D1 for SPX/NASDAQ/GOLD/WTI/DXY only starts 2021-07-23..26; BTC/ETH/
SOL D1 only starts 2021-07-24 -- verified by inspecting web/data/ohlc_*.json
directly before writing any of this). No API key needed, no auth.
"""
import datetime
import time

import requests

BASE = "https://query1.finance.yahoo.com/v8/finance/chart"


def fetch_daily(yahoo_symbol: str, start: str, end: str, pad_days: int = 5):
    """Fetch real daily OHLC for `yahoo_symbol` between ISO dates start/end
    (inclusive-ish; padded by `pad_days` on both sides so edge dates aren't
    clipped by timezone rounding). Returns a list of
    {time:'YYYY-MM-DD', open, high, low, close} dicts, real values only."""
    start_dt = datetime.datetime.strptime(start, "%Y-%m-%d") - datetime.timedelta(days=pad_days)
    end_dt = datetime.datetime.strptime(end, "%Y-%m-%d") + datetime.timedelta(days=pad_days)
    p1 = int(start_dt.replace(tzinfo=datetime.timezone.utc).timestamp())
    p2 = int(end_dt.replace(tzinfo=datetime.timezone.utc).timestamp())
    last_exc = None
    for attempt in range(5):
        try:
            resp = requests.get(
                f"{BASE}/{yahoo_symbol}",
                params={"period1": p1, "period2": p2, "interval": "1d"},
                headers={"User-Agent": "sbf-edu-build/1.0"}, timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            last_exc = None
            break
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            time.sleep(2)
    if last_exc is not None:
        raise last_exc

    result = data["chart"]["result"]
    if not result:
        raise ValueError(f"Yahoo returned no data for {yahoo_symbol}: {data['chart'].get('error')}")
    result = result[0]
    ts = result["timestamp"]
    q = result["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(ts):
        c = q["close"][i]
        if c is None:
            continue
        dt = datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
        out.append({
            "time": dt.strftime("%Y-%m-%d"),
            "open": round(float(q["open"][i]), 4) if q["open"][i] is not None else round(float(c), 4),
            "high": round(float(q["high"][i]), 4) if q["high"][i] is not None else round(float(c), 4),
            "low": round(float(q["low"][i]), 4) if q["low"][i] is not None else round(float(c), 4),
            "close": round(float(c), 4),
        })
    return out


def slice_range(candles, start, end):
    return [c for c in candles if start <= c["time"] <= end]
