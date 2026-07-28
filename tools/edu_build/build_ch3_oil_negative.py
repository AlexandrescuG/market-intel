#!/usr/bin/env python3
"""
Build ch3_oil_negative.json -- WTI daily OHLC, 2020-04-13..2020-04-24
(SPEC Level3 Capital Protection.md registry id ch3_oil_negative, "как цена
стала -$37" STORY scene).

IMPORTANT deviation from the spec, found during recon (same "verify before
trusting the spec" pattern as chapters 1 and 2): the spec's data column
claims this scene is "срез MT5 (есть!)" at M30 granularity. That is FALSE.
Checked directly: web/data/ohlc_WTI_M30.json only goes back to 2026-05-13
(broker keeps ~2.5 months of M30 history, same short retention already
documented for GOLD M30 in the chapter-2 memory). No free public source has
30-min WTI intraday from April 2020 either -- confirmed by hand: Yahoo
Finance's intraday endpoint rejects any interval finer than 1d once the
window is more than ~60 days in the past (tested directly against this exact
date, got "must be within the last 60 days"). Dukascopy's crude-oil CFD feed
(LIGHTCMDUSD) exists and has real ticks for this date, but it tracks the
front (next-month, June) contract and never goes negative that day --
because retail CFD/spot feeds roll ahead of expiry precisely to avoid this
kind of event, so it can't stand in for the actual May-contract print.
The negative settlement was a NYMEX May-2020 WTI futures (CLK20) event, and
free minute-level data for that specific contract isn't available anywhere.

So: this scene uses real DAILY OHLC only (Yahoo Finance CL=F, which mirrors
the real front-month print, including the 2020-04-20 negative close). The
STORY narration itself doesn't need sub-day resolution to explain WHY the
price went negative (contract expiry + physical delivery + storage) -- that
is conceptual, not chart-granularity-dependent.

Run: python3 build_ch3_oil_negative.py
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _yahoo import fetch_daily, slice_range  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT_PATH = ROOT / "web" / "data" / "edu_scenes" / "ch3_oil_negative.json"

START = "2020-04-13"
END = "2020-04-24"
MARKER_DATE = "2020-04-20"


def main():
    candles = fetch_daily("CL=F", START, END, pad_days=3)
    sliced = slice_range(candles, START, END)
    neg_day = next(c for c in sliced if c["time"] == MARKER_DATE)
    assert neg_day["low"] < -30, f"expected the well-known ~-$40 low on {MARKER_DATE}, got {neg_day}"
    next_day = next((c for c in sliced if c["time"] > MARKER_DATE), None)

    out = {
        "meta": {
            "symbol": "WTI",
            "granularity": "D1",
            "granularity_note": (
                "Spec asked for M30; no free intraday source exists this far back for the "
                "May-2020 WTI contract (see script docstring). Using real daily OHLC instead -- "
                "still 100% real, not reconstructed, just coarser resolution."
            ),
            "markers": [
                {"date": MARKER_DATE, "label": f"May WTI contract settles at ${neg_day['close']:.2f}, intraday low ${neg_day['low']:.2f}"}
            ],
            "range": [START, END],
            "source": "Yahoo Finance chart API, CL=F, interval=1d. Real fetched daily OHLC.",
            "reconstruction": False,
            "note": (
                f"Real values: {MARKER_DATE} open ${neg_day['open']:.2f}, low ${neg_day['low']:.2f}, "
                f"close ${neg_day['close']:.2f} (public record: settled at -$37.63; matches). "
                + (f"Next session ({next_day['time']}) opened at ${next_day['open']:.2f} as trading "
                   "rolled to the June contract, back in positive territory." if next_day else "")
            ),
        },
        "candles": sliced,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("neg day:", neg_day, "next day:", next_day)
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
