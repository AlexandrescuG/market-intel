#!/usr/bin/env python3
"""
Build ch2_cpi_2022.json -- GOLD (XAUUSD) intraday candles, 2022-11-09..2022-11-11,
around the 2022-11-10 13:30 UTC US CPI print (inflation came in cooler than
expected -> one of gold's biggest single-day rallies of the year).

Data source: Dukascopy free historical tick data (datafeed.dukascopy.com), real
tick-by-tick bid/ask, binned into 30-minute OHLC candles using mid price
(bid+ask)/2. This is REAL intraday data, not a reconstruction -- Dukascopy
retains full tick history back to the early 2000s for major instruments.

Cross-check against Yahoo Finance daily GC=F candle for 2022-11-10:
    open 1708.2  high 1750.3  low 1708.2  close 1750.3
    (prior close 2022-11-09: 1710.1)
    -> daily move ~2.35% close/close, ~2.46% low/high -- consistent with the
       "roughly 2.5-3%" figure the spec anchored on (a bit under the top of
       that range, but same event, same direction, same order of magnitude).

Run: python3 build_ch2_cpi_2022.py
"""
import datetime
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _dukascopy import fetch_range_ticks, bin_candles  # noqa: E402

OUT_PATH = pathlib.Path(__file__).resolve().parents[2] / "web" / "data" / "edu_scenes" / "ch2_cpi_2022.json"

SYMBOL = "XAUUSD"
START = datetime.datetime(2022, 11, 9, 0, 0, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2022, 11, 12, 0, 0, tzinfo=datetime.timezone.utc)  # exclusive
MARKER = "2022-11-10T13:30:00Z"
BIN_MINUTES = 30
DECIMALS = 2

# Yahoo Finance daily GC=F anchors (fetched separately, see docstring) used to
# sanity-check the Dukascopy-derived candles.
DAILY_ANCHORS = {
    "2022-11-09": {"open": 1707.4, "high": 1720.2, "low": 1706.0, "close": 1710.1},
    "2022-11-10": {"open": 1708.2, "high": 1750.3, "low": 1708.2, "close": 1750.3},
    "2022-11-11": {"open": 1763.8, "high": 1766.0, "low": 1757.6, "close": 1766.0},
}


def sanity_check(candles):
    by_day = {}
    for c in candles:
        day = c["time"][:10]
        by_day.setdefault(day, []).append(c)
    for day, anchor in DAILY_ANCHORS.items():
        day_candles = by_day.get(day)
        assert day_candles, f"no candles for {day}"
        lo = min(c["low"] for c in day_candles)
        hi = max(c["high"] for c in day_candles)
        # tick-derived intraday range should roughly bracket the daily OHLC
        # anchor (allow a little slack -- Dukascopy mid vs Yahoo settlement
        # price can differ slightly)
        assert lo <= anchor["high"] * 1.01 and hi >= anchor["low"] * 0.99, (
            f"{day}: tick range [{lo},{hi}] doesn't line up with daily anchor {anchor}"
        )
    # confirm the CPI spike is visible: price ~30-60min after 13:30 UTC should
    # be meaningfully higher than right before it
    before = [c for c in candles if c["time"] <= "2022-11-10T13:30:00Z" and c["time"] >= "2022-11-10T13:00:00Z"]
    after = [c for c in candles if "2022-11-10T14:00:00Z" <= c["time"] <= "2022-11-10T15:00:00Z"]
    assert before and after, "missing candles around the CPI marker"
    move_pct = (after[-1]["close"] - before[0]["open"]) / before[0]["open"] * 100
    assert move_pct > 1.0, f"CPI spike not visible in tick data: {move_pct:.2f}%"
    return move_pct


def main():
    ticks = fetch_range_ticks(SYMBOL, START, END)
    if not ticks:
        print("ERROR: no ticks fetched", file=sys.stderr)
        sys.exit(1)
    candles = bin_candles(ticks, BIN_MINUTES, DECIMALS)
    move_pct = sanity_check(candles)

    out = {
        "meta": {
            "symbol": "GOLD (XAUUSD)",
            "marker_time": MARKER,
            "marker_label": "US CPI release (Oct data), cooler than expected",
            "range": [START.strftime("%Y-%m-%d"), (END - datetime.timedelta(days=1)).strftime("%Y-%m-%d")],
            "bin_minutes": BIN_MINUTES,
            "source": (
                "Dukascopy free historical tick data (datafeed.dukascopy.com/datafeed/XAUUSD/...), "
                "real bid/ask ticks binned into 30-min OHLC via mid price (bid+ask)/2. "
                "Cross-checked against Yahoo Finance daily GC=F OHLC for 2022-11-09/10/11."
            ),
            "reconstruction": False,
            "note": (
                "REAL intraday data, not interpolated -- Dukascopy retains tick-level "
                "history for XAUUSD back to the early 2000s, so no reconstruction was "
                "needed for this event (unlike the spec's fallback plan). Prices are "
                "mid = (bid+ask)/2 from real ticks, binned into 30-minute candles. "
                f"The CPI-driven jump from just before 13:30 UTC to the following hour "
                f"is ~{move_pct:.1f}% in this tick series. Daily reference (Yahoo GC=F, "
                "2022-11-10): open 1708.2, high 1750.3, low 1708.2, close 1750.3 "
                "(prior close 1710.1), i.e. ~2.3-2.5% on the day -- same event, same "
                "direction as the commonly cited 'roughly 2.5-3%' figure, slightly "
                "under the top of that range depending on which reference close/high "
                "is used."
            ),
        },
        "candles": candles,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(candles)} candles to {OUT_PATH} ({OUT_PATH.stat().st_size} bytes), CPI move ~{move_pct:.2f}%")


if __name__ == "__main__":
    main()
