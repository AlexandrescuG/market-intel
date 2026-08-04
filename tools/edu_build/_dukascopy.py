"""Shared helper: fetch + decode Dukascopy historical tick data (.bi5 files) and
bin into OHLC candles. Used by build_ch2_cpi_2022.py, build_ch2_ecb_2022.py and
build_ch2_snb_2015.py to get REAL intraday price action for single-day central
bank / data-release events that predate the local MT5 backfill and are too old
for Yahoo Finance's intraday (60m) history (~2 years lookback only).

Dukascopy publishes free historical tick data per symbol/year/month/day/hour at
https://datafeed.dukascopy.com/datafeed/{SYMBOL}/{YYYY}/{MM}/{DD}/{HH}h_ticks.bi5
Note: month is ZERO-INDEXED (January = "00", November = "10").

Each decompressed .bi5 file is a sequence of 20-byte records:
    >iiiff  = (ms_since_hour_start, ask*point_value, bid*point_value, ask_vol, bid_vol)

This is real historical tick data (not synthetic) -- used here to build genuine
intraday candles for specific historical dates, not a reconstruction.
"""
import datetime
import lzma
import struct
import time

import requests

BASE = "https://datafeed.dukascopy.com/datafeed"

# Dukascopy price point divisors per symbol (raw integer -> float price).
POINT_VALUE = {
    "XAUUSD": 1000.0,
    "EURUSD": 100000.0,
    "EURCHF": 100000.0,
}


def fetch_hour_ticks(symbol: str, dt_hour: datetime.datetime):
    """Fetch and decode one hour of ticks for `symbol` at UTC hour `dt_hour`
    (a datetime truncated to the hour). Returns list of
    (datetime_utc, mid_price) tuples, or [] if that hour has no data
    (e.g. weekend / market closed -- Dukascopy returns an empty/tiny body)."""
    url = (
        f"{BASE}/{symbol}/{dt_hour.year:04d}/{dt_hour.month - 1:02d}/"
        f"{dt_hour.day:02d}/{dt_hour.hour:02d}h_ticks.bi5"
    )
    last_exc = None
    for attempt in range(5):
        try:
            resp = requests.get(url, headers={"User-Agent": "sbf-edu-build/1.0"}, timeout=20)
            resp.raise_for_status()
            last_exc = None
            break
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            time.sleep(1.5 * (attempt + 1))
    if last_exc is not None:
        raise last_exc
    if len(resp.content) < 20:
        return []
    raw = lzma.decompress(resp.content)
    pv = POINT_VALUE[symbol]
    n = len(raw) // 20
    out = []
    for i in range(n):
        ms, ask, bid, _av, _bv = struct.unpack(">iiiff", raw[i * 20:(i + 1) * 20])
        t = dt_hour + datetime.timedelta(milliseconds=ms)
        mid = (ask + bid) / 2.0 / pv
        out.append((t, mid))
    return out


def fetch_range_ticks(symbol: str, start: datetime.datetime, end: datetime.datetime):
    """Fetch all ticks for `symbol` between UTC datetimes start (inclusive) and
    end (exclusive), hour by hour. Silently skips hours with no data."""
    ticks = []
    h = start.replace(minute=0, second=0, microsecond=0)
    while h < end:
        ticks.extend(fetch_hour_ticks(symbol, h))
        h += datetime.timedelta(hours=1)
        time.sleep(0.2)
    ticks = [(t, p) for (t, p) in ticks if start <= t < end]
    ticks.sort(key=lambda x: x[0])
    return ticks


def bin_candles(ticks, bin_minutes: int, decimals: int):
    """Bin a sorted list of (datetime, price) ticks into OHLC candles of
    `bin_minutes` width, keyed by bin start time. Empty bins are skipped
    (no fabricated fill)."""
    if not ticks:
        return []
    bins = {}
    delta = datetime.timedelta(minutes=bin_minutes)
    epoch = ticks[0][0].replace(second=0, microsecond=0)
    epoch -= datetime.timedelta(minutes=epoch.minute % bin_minutes)
    for t, p in ticks:
        offset = int((t - epoch) / delta)
        key = epoch + offset * delta
        bins.setdefault(key, []).append(p)
    out = []
    for key in sorted(bins):
        prices = bins[key]
        out.append({
            "time": key.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "open": round(prices[0], decimals),
            "high": round(max(prices), decimals),
            "low": round(min(prices), decimals),
            "close": round(prices[-1], decimals),
        })
    return out
