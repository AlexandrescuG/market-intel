#!/usr/bin/env python3
"""
Build nikkei_bubble.json — Nikkei 225 monthly closes, 1985-01 .. 2024-12.

Data source: Yahoo Finance chart API for ^N225, interval=1mo (real fetched
data, not a reconstruction).

Quirk handled below: Yahoo's monthly bar timestamps for a Tokyo-listed index
are the *start* of the bar given as a UTC instant, which lands on the
previous UTC calendar day/month relative to Tokyo time (JST = UTC+9). E.g.
the bar timestamped "1989-11-30 15:00 UTC" is actually "1989-12-01 00:00
JST" and its close (38915.87) is the real December 1989 month-end close --
not November's. We add 9h before taking (year, month) so bars line up with
the calendar month they actually close.

Anchor check against the spec:
    1989-12 close   38,915.87  (closing-basis bubble peak; matches known
                                 1989-12-29 closing record)
    2008-2009 low   nearest MONTHLY close is 2009-02 = 7,568.42. The
                                 widely-cited 6,994.90 figure was an
                                 INTRADAY low on 2008-10-28, not a month-end
                                 close, so it cannot land on a monthly point
                                 -- documented in meta.note instead.
    2024-02-22      new all-time closing high 39,098.68 (verified via a
                                 separate daily fetch); Feb-2024 MONTHLY
                                 close is 39,166.19, also above the 1989
                                 peak, consistent with the spec's anchor.

Run: python3 build_nikkei_bubble.py
"""
import datetime
import json
import pathlib
import sys

import requests

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%5EN225"
OUT_PATH = pathlib.Path(__file__).resolve().parents[2] / "web" / "data" / "edu_capsules" / "nikkei_bubble.json"

START_YM = (1985, 1)
END_YM = (2024, 12)
JST_OFFSET = 9 * 3600


def fetch_monthly():
    resp = requests.get(
        CHART_URL,
        params={"period1": 0, "period2": 9999999999, "interval": "1mo"},
        headers={"User-Agent": "sbf-edu-build/1.0"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    result = data["chart"]["result"][0]
    timestamps = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]
    return timestamps, closes


def to_months(timestamps, closes):
    months = {}
    for t, c in zip(timestamps, closes):
        if c is None:
            continue
        dt = datetime.datetime.utcfromtimestamp(t + JST_OFFSET)
        ym = (dt.year, dt.month)
        if START_YM <= ym <= END_YM:
            months[ym] = round(float(c), 2)
    return months


def sanity_check(months):
    peak = months.get((1989, 12))
    assert peak is not None and abs(peak - 38915.87) < 1.0, f"1989-12 peak off: {peak}"

    feb2024 = months.get((2024, 2))
    assert feb2024 is not None and feb2024 > 38957, f"2024-02 not above old peak: {feb2024}"

    low_ym = min(
        ((ym, v) for ym, v in months.items() if (2008, 1) <= ym <= (2009, 12)),
        key=lambda kv: kv[1],
    )
    return peak, feb2024, low_ym


def main():
    timestamps, closes = fetch_monthly()
    months = to_months(timestamps, closes)
    if not months:
        print("ERROR: no monthly points parsed in the requested range", file=sys.stderr)
        sys.exit(1)

    peak, feb2024, (low_ym, low_val) = sanity_check(months)

    ordered = sorted(months.items())
    months_list = [{"time": f"{y:04d}-{m:02d}", "close": v} for (y, m), v in ordered]

    capsule = {
        "meta": {
            "source": "Yahoo Finance chart API, ^N225, interval=1mo (query1.finance.yahoo.com/v8/finance/chart/%5EN225)",
            "note": (
                f"Real fetched monthly closes, {months_list[0]['time']}..{months_list[-1]['time']} "
                f"({len(months_list)} points), not interpolated. Bubble closing peak "
                f"38,915.87 on 1989-12-29 (JST) is the 1989-12 point ({peak}); the widely "
                "quoted 38,957 figure is that day's INTRADAY high, close was 38,915.87. "
                "2008-2009 crisis: the famous 6,994.90 low was an INTRADAY print on "
                "2008-10-28, not a month-end close, so it is not literally a point in "
                f"this monthly series -- the lowest MONTHLY close in the series is "
                f"{low_val} in {low_ym[0]:04d}-{low_ym[1]:02d}. New all-time closing high: "
                f"verified via a separate daily fetch at 39,098.68 on 2024-02-22; the "
                f"2024-02 monthly close is {feb2024}, also above the old 1989 peak."
            ),
            "license": "public domain (factual historical price data)",
        },
        "months": months_list,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(capsule, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(months_list)} months to {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
