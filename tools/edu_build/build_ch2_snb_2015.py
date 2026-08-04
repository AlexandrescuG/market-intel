#!/usr/bin/env python3
"""
Build ch2_snb_2015.json -- EURCHF intraday candles, 2015-01-14..2015-01-16,
around the SNB's 2015-01-15 shock removal of the 1.20 EUR/CHF floor -- one of
the most famous single events in FX history (franc spiked as much as ~30%
against the euro within minutes).

Data source: Dukascopy free historical tick data (datafeed.dukascopy.com), real
tick-by-tick bid/ask, binned into 5-minute OHLC candles using mid price
(bid+ask)/2. REAL intraday data, not a reconstruction (Dukascopy tick history
goes back to the early 2000s, well before 2015).

Timing correction found while building this file: the spec's working guess was
"announcement 09:30 CET / 08:30 UTC". The REAL tick data shows EUR/CHF pinned
dead flat at ~1.2010 through the whole 08h and most of the 09h UTC hour, then
the first violent tick-by-tick break happens at 09:30:46 UTC on 2015-01-15 --
i.e. 10:30 CET (CET = UTC+1 in January, no DST), matching "9:30am GMT" as
reported by several contemporary outlets (GMT ~= UTC in January). We use the
tick-verified 09:30 UTC as the marker, not the spec's initial 08:30 UTC guess.

Anchor cross-check against 2-3 independent public sources for the day's low/close
(both corroborate the same order of magnitude; exact tick lows vary slightly by
venue/feed during this famously chaotic, liquidity-gapped session):
  - forex.in.rs / Nasdaq / FXSSI writeups: intraday low ~0.8204, close ~1.0279
    (-14.4% on the day)
  - Widely repeated round-number description: "fell from 1.20 to as low as 0.85
    within minutes" (order of magnitude match; exact print differs by feed)
  - This Dukascopy tick series' own low is reported in meta.note below -- it is
    close to, but not necessarily bit-for-bit identical to, other brokers' feeds,
    which is expected and documented for this event (many brokers' feeds gapped
    or froze differently during the liquidity vacuum).

Also builds a `daily` array (2015-01-14/15/16) aggregated directly from this
same real tick data (00:00-24:00 UTC per day) rather than from Yahoo Finance's
daily EURCHF=X series -- Yahoo's 2015-01-15 daily bar has a visibly corrupted
`close` field (identical to `open`, 1.2008, which cannot be right given the
day's well-documented ~14% net move); using tick-derived daily bars avoids
propagating that glitch.

Run: python3 build_ch2_snb_2015.py
"""
import datetime
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _dukascopy import fetch_range_ticks, bin_candles  # noqa: E402

OUT_PATH = pathlib.Path(__file__).resolve().parents[2] / "web" / "data" / "edu_scenes" / "ch2_snb_2015.json"

SYMBOL = "EURCHF"
START = datetime.datetime(2015, 1, 14, 0, 0, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2015, 1, 17, 0, 0, tzinfo=datetime.timezone.utc)  # exclusive
MARKER = "2015-01-15T09:30:00Z"
BIN_MINUTES = 5
DECIMALS = 5


def sanity_check(candles, daily):
    # pre-shock peg should hold ~1.20 on 01-14 and early 01-15
    pre_shock = [c for c in candles if c["time"] < "2015-01-15T09:30:00Z"]
    assert pre_shock, "no pre-shock candles"
    for c in pre_shock[-20:]:
        assert 1.195 < c["close"] < 1.205, f"peg not holding just before shock: {c}"

    # the shock itself: massive intraday range on 01-15
    d15 = daily.get("2015-01-15")
    assert d15 is not None
    drop_pct = (d15["low"] - 1.20) / 1.20 * 100
    assert drop_pct < -20, f"01-15 low doesn't show the shock: {d15} ({drop_pct:.1f}%)"

    # post-shock: 01-16 should be trading meaningfully below the old 1.20 peg,
    # broadly in the 0.95-1.05 chaos band widely reported for the days after
    d16 = daily.get("2015-01-16")
    assert d16 is not None
    assert 0.90 < d16["close"] < 1.10, f"01-16 close outside expected post-shock band: {d16}"
    return drop_pct


def daily_from_ticks(ticks):
    by_day = {}
    for t, p in ticks:
        day = t.strftime("%Y-%m-%d")
        by_day.setdefault(day, []).append(p)
    out = {}
    for day, prices in by_day.items():
        out[day] = {
            "time": day,
            "open": round(prices[0], DECIMALS),
            "high": round(max(prices), DECIMALS),
            "low": round(min(prices), DECIMALS),
            "close": round(prices[-1], DECIMALS),
        }
    return out


def main():
    ticks = fetch_range_ticks(SYMBOL, START, END)
    if not ticks:
        print("ERROR: no ticks fetched", file=sys.stderr)
        sys.exit(1)
    candles = bin_candles(ticks, BIN_MINUTES, DECIMALS)
    daily = daily_from_ticks(ticks)
    drop_pct = sanity_check(candles, daily)

    d15 = daily["2015-01-15"]

    out = {
        "meta": {
            "symbol": "EURCHF",
            "marker_time": MARKER,
            "marker_label": "SNB abandons the 1.20 EUR/CHF floor (tick-verified break time; see note)",
            "range": [START.strftime("%Y-%m-%d"), (END - datetime.timedelta(days=1)).strftime("%Y-%m-%d")],
            "bin_minutes": BIN_MINUTES,
            "source": (
                "Dukascopy free historical tick data (datafeed.dukascopy.com/datafeed/EURCHF/...), "
                "real bid/ask ticks binned into 5-min OHLC via mid price (bid+ask)/2. "
                "Cross-checked against public writeups of the day (forex.in.rs, Nasdaq, FXSSI) "
                "citing an intraday low near 0.82 and a day close near 1.03, and against Yahoo "
                "Finance's daily EURCHF=X series for the surrounding days (2015-01-14 and "
                "2015-01-16, which are not corrupted)."
            ),
            "reconstruction": False,
            "note": (
                "REAL intraday tick data, not interpolated -- Dukascopy retains tick-level "
                "history for EURCHF back well before 2015. Timing correction: the peg holds "
                "dead flat at ~1.2010 through 2015-01-14 and into the morning of 2015-01-15; "
                "the first violent break in this tick feed is at 09:30:46 UTC on 2015-01-15 "
                "(10:30 CET, since CET=UTC+1 in January) -- NOT 08:30 UTC as an initial working "
                "guess assumed; 09:30 UTC matches 'around 9:30am GMT' as reported by several "
                f"outlets. This series' own 2015-01-15 tick-derived day range: open {d15['open']}, "
                f"high {d15['high']}, low {d15['low']}, close {d15['close']} "
                f"({drop_pct:.1f}% from the 1.20 peg to the day's low). Independent public "
                "writeups (forex.in.rs, Nasdaq) cite an intraday low near 0.8204 and an end-of-day "
                "print near 1.0279 (-14.4%); this tick feed's own low/close are in the same "
                "neighborhood but not bit-for-bit identical -- expected and documented for this "
                "event, since order flow, liquidity, and quoting froze/gapped differently across "
                "brokers and feeds during the ~20-minute vacuum (this is one of the most "
                "notorious 'my broker's price differs from another broker's price' events in FX "
                "history). The `daily` array below is built directly from this same real tick "
                "data (00:00-24:00 UTC per day), not from Yahoo Finance, because Yahoo's own "
                "2015-01-15 daily EURCHF=X bar has a corrupted `close` field (identical to "
                "`open`, 1.2008) that cannot be right given the well-documented ~14% net move -- "
                "flagged here rather than silently used."
            ),
        },
        "candles": candles,
        "daily": [daily[d] for d in sorted(daily)],
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(candles)} candles + {len(daily)} daily bars to {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")
    print("daily:", json.dumps(daily, indent=2))


if __name__ == "__main__":
    main()
