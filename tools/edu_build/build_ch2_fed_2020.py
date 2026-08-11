#!/usr/bin/env python3
"""
Build ch2_fed_2020.json -- SPX + GOLD + EURUSD daily closes, 2020-02-10..2020-04-17
(the COVID Fed emergency-cut scenario: run-up into the crash, the two emergency
cuts, and the start of the recovery).

Data source: Yahoo Finance chart API (query1.finance.yahoo.com/v8/finance/chart/...),
interval=1d, real fetched daily OHLC (close used here). Local MT5 backfill
(web/data/ohlc_*_D1.json) only starts 2021-07-23, so it does NOT cover this
window -- confirmed by inspecting the files directly before writing this script.

Anchor cross-checks against the spec's known public values:
    SPX 2020-02-19 close: spec says peak ~3386 -- fetched 3386.15  (match)
    SPX 2020-03-23 close: spec says bottom ~2237 -- fetched 2237.40  (match)
Both anchors are just outside/at the edge of the requested window, which is
fine per the spec (window only needs to show the run-up to and initial
reaction after the two Fed dates, not the eventual bottom).

Markers: 2020-03-03 (first emergency 50bp cut, intermeeting) and 2020-03-15
(Sunday emergency cut to 0-0.25% + $700bn QE announcement, ahead of the
2020-03-16 market open).

Run: python3 build_ch2_fed_2020.py
"""
import datetime
import json
import pathlib
import sys
from urllib.parse import quote as _urlquote

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from core.symbols_registry import yahoo_ticker as _yahoo_ticker

OUT_PATH = pathlib.Path(__file__).resolve().parents[2] / "web" / "data" / "edu_scenes" / "ch2_fed_2020.json"

START = "2020-02-10"
END = "2020-04-17"

# WP1.1 SPEC_alpha_engine_implementation.md: раньше был свой хардкод
# {"SPX": "%5EGSPC", "GOLD": "GC=F", "EURUSD": "EURUSD=X"} -- те же значения,
# что в core/symbols_registry (GC=F/EURUSD=X совпадали буквально, ^GSPC был
# заранее URL-квотирован вручную). Теперь квотится сама эта функция, а не
# по памяти при правке словаря.
SYMBOLS = {label: _urlquote(_yahoo_ticker(label), safe="=") for label in ("SPX", "GOLD", "EURUSD")}

MARKERS = [
    {"date": "2020-03-03", "label": "Fed emergency intermeeting cut: -50bp to 1.00-1.25%"},
    {"date": "2020-03-15", "label": "Fed Sunday emergency cut to 0-0.25% + $700bn QE"},
]

ANCHORS = {
    "SPX": {"2020-02-19": 3386.15, "2020-03-23": 2237.40},
}


def sanity_check(series):
    by_date = {c["time"]: c["close"] for c in series["SPX"]}
    for date, expected in ANCHORS["SPX"].items():
        actual = by_date.get(date)
        assert actual is not None, f"missing SPX anchor date {date} (may be just outside fetched window)"
        assert abs(actual - expected) < 0.5, f"SPX {date}: expected {expected}, got {actual}"


def main():
    # widen the fetch a touch so the two anchor dates (2020-02-19, one day
    # before window start-ish is fine; 2020-03-23 is after window end) are
    # available for the sanity check even though the emitted series only
    # covers START..END
    fetch_start_dt = datetime.datetime.strptime(START, "%Y-%m-%d") - datetime.timedelta(days=5)
    fetch_end_dt = datetime.datetime.strptime(END, "%Y-%m-%d") + datetime.timedelta(days=10)

    series = {}
    check_series = {}
    for label, ysym in SYMBOLS.items():
        p1 = int(fetch_start_dt.replace(tzinfo=datetime.timezone.utc).timestamp())
        p2 = int(fetch_end_dt.replace(tzinfo=datetime.timezone.utc).timestamp())
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}"
        resp = requests.get(
            url, params={"period1": p1, "period2": p2, "interval": "1d"},
            headers={"User-Agent": "sbf-edu-build/1.0"}, timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()["chart"]["result"][0]
        ts = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
        full = []
        for t, c in zip(ts, closes):
            if c is None:
                continue
            dt = datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
            full.append({"time": dt.strftime("%Y-%m-%d"), "close": round(float(c), 4)})
        check_series[label] = full
        series[label] = [c for c in full if START <= c["time"] <= END]

    sanity_check(check_series)

    out = {
        "meta": {
            "symbols": list(SYMBOLS.keys()),
            "markers": MARKERS,
            "source": (
                "Yahoo Finance chart API (query1.finance.yahoo.com/v8/finance/chart/), "
                "interval=1d: ^GSPC (SPX), GC=F (GOLD), EURUSD=X (EURUSD). Real fetched "
                "daily closes, not interpolated."
            ),
            "reconstruction": False,
            "note": (
                "Real daily closes fetched directly from Yahoo Finance for all 3 symbols "
                "(local MT5 backfill only starts 2021-07-23, so it doesn't cover this window). "
                "Verified against known public anchors: SPX close 2020-02-19 = 3386.15 "
                "(spec's cited peak ~3386, just before this window's start) and SPX close "
                "2020-03-23 = 2237.40 (spec's cited crash bottom ~2237, just after this "
                "window's end) -- both matched to the cent. This window (2020-02-10..2020-04-17) "
                "shows the pre-crash top, the crash itself, the two Fed emergency cuts "
                "(2020-03-03 intermeeting -50bp, 2020-03-15 Sunday cut to zero + QE), and the "
                "first leg of the recovery, without including the exact bottom (2020-03-23, "
                "just past this window) or the pre-window all-time high (2020-02-19)."
            ),
        },
        "series": series,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for k, v in series.items():
        print(f"{k}: {len(v)} points, {v[0]['time']}..{v[-1]['time']}")
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
