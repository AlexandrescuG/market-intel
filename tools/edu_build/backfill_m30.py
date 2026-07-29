#!/usr/bin/env python3
"""
Bulk M30 historical backfill via free Dukascopy tick data -- SPEC_ch5_debug.md
§1.1. Extends the locally-covered MT5 window (~10 weeks) backward by years,
fixing the small-sample problem that chapters 5, 6, 7, 8 and 13 all hit.

Output goes to a SEPARATE file (ohlc_{ASSET}_M30_hist.json) -- the live
MT5-fed ohlc_{ASSET}_M30.json is never touched or overwritten.

Usage:
    python3 tools/edu_build/backfill_m30.py SYMBOL FROM_DATE TO_DATE
    python3 tools/edu_build/backfill_m30.py GOLD 2021-05-18 2026-05-18

Safety gate (the spec's own warning: a wrong Dukascopy symbol code or point
value makes "цены уедут на порядок и это заметят не сразу" -- prices land an
order of magnitude off and nobody notices right away): before fetching
anything else, pulls one real day that's also covered by the local MT5 file
and compares the resulting close against the MT5 close for the same bar.
Refuses to run the actual backfill if they disagree beyond a normal
spread-sized tolerance -- this is what makes it safe to add new SYMBOL_MAP
entries for instruments whose Dukascopy code isn't 100% certain.

Incremental / resumable: raw ticks are cached to disk per calendar day
(data/dukascopy_cache/{DUKASCOPY_CODE}/YYYY-MM-DD.json, including empty
weekend/holiday days so they aren't re-fetched either). Re-running the same
range after an interruption re-binds from cache instead of hitting the
network again. The output _hist.json is checkpointed periodically so a crash
mid-run loses at most a few days of binning (re-derivable from cache almost
instantly, not from the network).
"""
import datetime
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _dukascopy import BASE, POINT_VALUE  # noqa: E402

import lzma
import struct

import requests

# 2026-07-29 finding: the free Dukascopy datafeed rate-limits far more
# aggressively than SPEC_ch5_debug.md §1.1 assumed ("~0.2 sec/file" implied
# near-unrestricted access). A short burst of test requests (a handful of
# calls, a few seconds apart) was enough to get HTTP 429 with no
# Retry-After header. _dukascopy.fetch_hour_ticks's retry loop treats 429
# like any other transient error (short exponential backoff, ~1.5-7.5s across
# 5 attempts) which is nowhere near enough headroom and just burns the retry
# budget while still hammering a server that's already saying "slow down".
# This wrapper paces requests much more conservatively and gives 429
# specifically a long, escalating cooldown instead of the shared helper's
# generic backoff -- without touching _dukascopy.py itself, since 3 other
# scripts (build_ch2_*.py) already depend on its exact current behaviour for
# their own (much smaller, few-day) pulls that have never tripped this.
REQUEST_DELAY = 2.0  # seconds between successful requests -- conservative until proven safe
RATE_LIMIT_COOLDOWN = 60.0  # seconds to back off on a 429, escalating per consecutive hit


def fetch_hour_ticks_paced(symbol, dt_hour, session, state):
    """Same contract as _dukascopy.fetch_hour_ticks, but with 429-aware
    backoff and a fixed inter-request delay. `state` is a dict carrying
    `consecutive_429` across calls so cooldowns escalate on repeated hits."""
    url = (
        f"{BASE}/{symbol}/{dt_hour.year:04d}/{dt_hour.month - 1:02d}/"
        f"{dt_hour.day:02d}/{dt_hour.hour:02d}h_ticks.bi5"
    )
    while True:
        resp = session.get(url, headers={"User-Agent": "sbf-edu-build/1.0"}, timeout=20)
        if resp.status_code == 429:
            state["consecutive_429"] = state.get("consecutive_429", 0) + 1
            cooldown = RATE_LIMIT_COOLDOWN * state["consecutive_429"]
            print(f"    429 rate-limited (hit #{state['consecutive_429']}), cooling down {cooldown:.0f}s ...")
            time.sleep(cooldown)
            continue
        resp.raise_for_status()
        state["consecutive_429"] = 0
        time.sleep(REQUEST_DELAY)
        break
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


def fetch_range_ticks_paced(symbol, start, end, session, state):
    ticks = []
    h = start.replace(minute=0, second=0, microsecond=0)
    while h < end:
        ticks.extend(fetch_hour_ticks_paced(symbol, h, session, state))
        h += datetime.timedelta(hours=1)
    ticks = [(t, p) for (t, p) in ticks if start <= t < end]
    ticks.sort(key=lambda x: x[0])
    return ticks

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CACHE_ROOT = REPO_ROOT / "data" / "dukascopy_cache"
MT5_FILE_TPL = REPO_ROOT / "web" / "data" / "ohlc_{asset}_M30.json"
HIST_FILE_TPL = REPO_ROOT / "web" / "data" / "ohlc_{asset}_M30_hist.json"

# Our asset name -> (Dukascopy symbol code, price decimals). XAUUSD is
# already trusted -- used successfully by 3 live ch2 scene scripts
# (build_ch2_cpi_2022.py etc). EURUSD/GBPUSD/USDJPY are standard FX majors
# (Dukascopy codes them by the plain 6-letter pair, same convention as
# XAUUSD/EURCHF already in _dukascopy.POINT_VALUE) -- high confidence, but
# still gated by the self-check below before any real run.
SYMBOL_MAP = {
    "GOLD": ("XAUUSD", 2),
    "EURUSD": ("EURUSD", 5),
    "GBPUSD": ("GBPUSD", 5),
    "USDJPY": ("USDJPY", 3),
}
EXTRA_POINT_VALUE = {"GBPUSD": 100000.0, "USDJPY": 1000.0}
for _sym, _pv in EXTRA_POINT_VALUE.items():
    POINT_VALUE.setdefault(_sym, _pv)

BIN_MINUTES = 30
VERIFY_TOLERANCE_PCT = 0.01  # 1% -- generous for spread, catches order-of-magnitude errors


def cache_path(dukacode, day):
    d = CACHE_ROOT / dukacode
    d.mkdir(parents=True, exist_ok=True)
    return d / (day.strftime("%Y-%m-%d") + ".json")


def fetch_day_ticks_cached(dukacode, day, session, state):
    """One calendar day of ticks (UTC), cached to disk. Empty days (weekend/
    holiday) are cached too, so they short-circuit on re-runs instead of
    hitting the network again."""
    path = cache_path(dukacode, day)
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [
            (datetime.datetime.strptime(t, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=datetime.timezone.utc), p)
            for t, p in raw
        ]
    start = day
    end = day + datetime.timedelta(days=1)
    ticks = fetch_range_ticks_paced(dukacode, start, end, session, state)
    raw = [(t.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), p) for t, p in ticks]
    path.write_text(json.dumps(raw), encoding="utf-8")
    return ticks


def bin_candles_utc(ticks, decimals):
    """Bin ticks into M30 candles anchored to wall-clock UTC (:00/:30), not
    to the first tick's own offset -- matters because this backfill bins
    day-by-day across years and bin edges must line up consistently across
    every day, not drift depending on when the day's first tick happened to
    land. (_dukascopy.bin_candles anchors off ticks[0] instead; left
    untouched here since 3 other scripts already rely on its exact
    single-day behaviour.)"""
    if not ticks:
        return []
    bins = {}
    for t, p in ticks:
        key = t.replace(second=0, microsecond=0)
        key -= datetime.timedelta(minutes=key.minute % BIN_MINUTES)
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


def load_mt5_reference(asset):
    path = pathlib.Path(str(MT5_FILE_TPL).format(asset=asset))
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("candles", [])


def verify_against_mt5(asset, dukacode, decimals, session, state):
    mt5 = load_mt5_reference(asset)
    if not mt5:
        print(f"[{asset}] no local MT5 reference file -- skipping self-check (proceed with caution)")
        return
    ref = mt5[0]  # oldest MT5 bar: old enough to be in Dukascopy's archive, still MT5-covered
    t = datetime.datetime.fromtimestamp(ref["time"], tz=datetime.timezone.utc)
    day_start = t.replace(hour=0, minute=0, second=0, microsecond=0)
    ticks = fetch_range_ticks_paced(dukacode, day_start, day_start + datetime.timedelta(days=1), session, state)
    candles = bin_candles_utc(ticks, decimals)
    match = next((c for c in candles if c["time"] == t.strftime("%Y-%m-%dT%H:%M:%SZ")), None)
    if not match:
        raise RuntimeError(
            f"[{asset}] self-check FAILED: Dukascopy symbol '{dukacode}' returned no candle "
            f"for {t.isoformat()} (MT5 close was {ref['close']}). Wrong symbol code?"
        )
    diff = abs(match["close"] - ref["close"])
    tolerance = abs(ref["close"]) * VERIFY_TOLERANCE_PCT
    if diff > tolerance:
        raise RuntimeError(
            f"[{asset}] self-check FAILED: Dukascopy close {match['close']} vs MT5 close "
            f"{ref['close']} at {t.isoformat()} differ by {diff:.4f} (tolerance {tolerance:.4f}). "
            f"Wrong symbol code or point value -- do not trust this SYMBOL_MAP entry."
        )
    print(f"[{asset}] self-check OK: Dukascopy {match['close']} vs MT5 {ref['close']} at {t.isoformat()}")


def load_existing_hist(asset):
    path = pathlib.Path(str(HIST_FILE_TPL).format(asset=asset))
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"asset": asset, "interval": "M30", "candles": [], "_meta": {"source_periods": []}}


def save_hist(asset, doc):
    path = pathlib.Path(str(HIST_FILE_TPL).format(asset=asset))
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def backfill(asset, start, end):
    if asset not in SYMBOL_MAP:
        raise SystemExit(f"unknown asset '{asset}' -- add it to SYMBOL_MAP first (with a verified Dukascopy code)")
    dukacode, decimals = SYMBOL_MAP[asset]
    if dukacode not in POINT_VALUE:
        raise SystemExit(f"POINT_VALUE missing for '{dukacode}' -- add it before running")

    session = requests.Session()
    state = {}
    verify_against_mt5(asset, dukacode, decimals, session, state)

    doc = load_existing_hist(asset)
    existing_times = {c["time"] for c in doc["candles"]}

    print(f"[{asset}] backfilling {dukacode} {start.date()} -> {end.date()} ...")
    day = start
    days_since_checkpoint = 0
    total_new = 0
    while day < end:
        ticks = fetch_day_ticks_cached(dukacode, day, session, state)
        for c in bin_candles_utc(ticks, decimals):
            if c["time"] not in existing_times:
                doc["candles"].append(c)
                existing_times.add(c["time"])
                total_new += 1
        day += datetime.timedelta(days=1)
        days_since_checkpoint += 1
        if days_since_checkpoint >= 10:
            doc["candles"].sort(key=lambda c: c["time"])
            save_hist(asset, doc)
            print(f"  ... {day.date()} checkpointed, {total_new} new candles so far")
            days_since_checkpoint = 0

    doc["candles"].sort(key=lambda c: c["time"])
    period = {
        "from": start.strftime("%Y-%m-%d"),
        "to": end.strftime("%Y-%m-%d"),
        "source": "Dukascopy free historical tick data, real (not synthetic)",
    }
    if period not in doc["_meta"]["source_periods"]:
        doc["_meta"]["source_periods"].append(period)
    doc["_meta"]["updated"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_hist(asset, doc)
    print(f"[{asset}] done: {len(doc['candles'])} total candles, {total_new} new this run "
          f"-> {HIST_FILE_TPL.__str__().format(asset=asset)}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("usage: backfill_m30.py SYMBOL FROM_DATE TO_DATE  (dates YYYY-MM-DD, UTC)")
        sys.exit(1)
    asset_arg = sys.argv[1]
    start_arg = datetime.datetime.strptime(sys.argv[2], "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
    end_arg = datetime.datetime.strptime(sys.argv[3], "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
    backfill(asset_arg, start_arg, end_arg)
