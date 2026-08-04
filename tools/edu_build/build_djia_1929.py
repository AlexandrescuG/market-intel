#!/usr/bin/env python3
"""
Build djia_1929.json — DJIA daily closes, 1929-08-01 .. 1929-12-31 (the crash).

Data source: measuringworth.com's "Dow Jones Average" daily series (extends the
DJIA/DJA back to 1885), as mirrored in the MIT-licensed GitHub repo
fja05680/dow-sp500-100-years (file DJA.csv, itself converted from
https://www.measuringworth.com/datasets/DJA/result.php).

This is REAL daily data, not a reconstruction. By 1929 the measuringworth
splice tracks the official DJIA exactly — verified below against four
independently-sourced anchor values from the spec (Wikipedia "Dow Jones
Industrial Average" article + Federal Reserve History / novelinvestor.com
crash timeline):
    1929-09-03  peak            381.17
    1929-10-28  "Black Monday"  -12.8% vs prior close
    1929-10-29  "Black Tuesday" -11.7% vs prior close
    1929-11-13  crash bottom    198.69
    1929-12-31  year-end close  248.48  (matches Wikipedia annual-returns table)

Run: python3 build_djia_1929.py
"""
import csv
import io
import json
import pathlib
import sys

import requests

SOURCE_URL = "https://raw.githubusercontent.com/fja05680/dow-sp500-100-years/master/DJA.csv"
OUT_PATH = pathlib.Path(__file__).resolve().parents[2] / "web" / "data" / "edu_capsules" / "djia_1929.json"

START = "1929-08-01"
END = "1929-12-31"

ANCHORS = {
    "1929-09-03": 381.17,
    "1929-11-13": 198.69,
    "1929-12-31": 248.48,
}


def fetch_csv() -> str:
    resp = requests.get(SOURCE_URL, headers={"User-Agent": "sbf-edu-build/1.0"}, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_candles(csv_text: str):
    reader = csv.DictReader(io.StringIO(csv_text))
    candles = []
    for row in reader:
        date = row[""] if "" in row else row.get("Date")
        if date is None:
            # first column has no header name in this file
            date = list(row.values())[0]
        if not (START <= date <= END):
            continue
        close = float(row["Close"])
        candles.append({"time": date, "close": round(close, 2)})
    candles.sort(key=lambda c: c["time"])
    return candles


def sanity_check(candles):
    by_date = {c["time"]: c["close"] for c in candles}
    for date, expected in ANCHORS.items():
        actual = by_date.get(date)
        assert actual is not None, f"missing anchor date {date}"
        assert abs(actual - expected) < 0.05, f"{date}: expected {expected}, got {actual}"

    # Black Monday / Black Tuesday are percentage-move anchors, not absolute
    # values (the two dow ticks differ slightly across sources) -- check the
    # percentage move instead of an exact close.
    d = by_date
    pct_1028 = (d["1929-10-28"] - d["1929-10-26"]) / d["1929-10-26"] * 100
    pct_1029 = (d["1929-10-29"] - d["1929-10-28"]) / d["1929-10-28"] * 100
    assert -13.5 < pct_1028 < -12.0, f"1929-10-28 move off: {pct_1028:.2f}%"
    assert -12.5 < pct_1029 < -11.0, f"1929-10-29 move off: {pct_1029:.2f}%"
    return pct_1028, pct_1029


def main():
    csv_text = fetch_csv()
    candles = parse_candles(csv_text)
    if not candles:
        print("ERROR: no candles parsed for the requested date range", file=sys.stderr)
        sys.exit(1)

    pct_1028, pct_1029 = sanity_check(candles)

    capsule = {
        "meta": {
            "source": (
                "measuringworth.com Dow Jones Average daily series "
                "(https://www.measuringworth.com/datasets/DJA/result.php), "
                "via MIT-licensed mirror "
                "https://github.com/fja05680/dow-sp500-100-years/blob/master/DJA.csv"
            ),
            "reconstruction": False,
            "note": (
                "Real daily closing values, not interpolated. Verified against "
                "independently-sourced anchors: peak 381.17 on 1929-09-03, "
                f"Black Monday move {pct_1028:.1f}% on 1929-10-28, "
                f"Black Tuesday move {pct_1029:.1f}% on 1929-10-29, bottom 198.69 on "
                "1929-11-13, year-end close 248.48 on 1929-12-31 (matches Wikipedia's "
                "sourced DJIA annual-returns table). This series only has close "
                "values (no separate OHLC in the source), covers NYSE trading days "
                "only (no weekends/holidays)."
            ),
            "license": "public domain (factual historical price data)",
        },
        "candles": candles,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(capsule, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(candles)} candles to {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
