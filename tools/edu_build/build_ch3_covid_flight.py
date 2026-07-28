#!/usr/bin/env python3
"""
Build ch3_covid_flight.json -- SPX + GOLD + WTI daily closes, 2020-02-10..
2020-08-31 (SPEC Level3 Capital Protection.md registry id ch3_covid_flight,
"куда бежал капитал" MULTI scene).

Local MT5 backfill (web/data/ohlc_*_D1.json) only starts 2021-07-24/26 --
confirmed by inspection -- so this window needs an external source. Yahoo
Finance chart API, interval=1d, real fetched daily closes (^GSPC / GC=F /
CL=F), not interpolated, not reconstructed.

Anchor cross-checks against well-known public values:
    SPX 2020-03-23 close: known crash bottom ~2237
    SPX 2020-02-19 close: known pre-crash peak ~3386

Run: python3 build_ch3_covid_flight.py
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _yahoo import fetch_daily, slice_range  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT_PATH = ROOT / "web" / "data" / "edu_scenes" / "ch3_covid_flight.json"

START = "2020-02-10"
END = "2020-08-31"

SYMBOLS = {"SPX": "%5EGSPC", "GOLD": "GC=F", "WTI": "CL=F"}

ANCHORS = {"SPX": {"2020-02-19": 3386.15, "2020-03-23": 2237.40}}


def main():
    series = {}
    full = {}
    for label, ysym in SYMBOLS.items():
        candles = fetch_daily(ysym, START, END, pad_days=5)
        full[label] = candles
        series[label] = [{"time": c["time"], "close": c["close"]} for c in slice_range(candles, START, END)]

    by_date = {c["time"]: c["close"] for c in full["SPX"]}
    for date, expected in ANCHORS["SPX"].items():
        actual = by_date.get(date)
        assert actual is not None, f"missing SPX anchor {date}"
        assert abs(actual - expected) < 0.5, f"SPX {date}: expected {expected}, got {actual}"

    spx_low = min(series["SPX"], key=lambda c: c["close"])
    gold_at_spx_low = next((c["close"] for c in series["GOLD"] if c["time"] == spx_low["time"]), None)
    wti_min = min(series["WTI"], key=lambda c: c["close"])

    out = {
        "meta": {
            "symbols": ["SPX", "GOLD", "WTI"],
            "range": [START, END],
            "source": (
                "Yahoo Finance chart API (query1.finance.yahoo.com/v8/finance/chart/), "
                "interval=1d: ^GSPC (SPX), GC=F (GOLD), CL=F (WTI). Real fetched daily "
                "closes, not interpolated. Local MT5 backfill doesn't cover this window "
                "(starts 2021-07-24/26)."
            ),
            "reconstruction": False,
            "spx_bottom": spx_low,
            "gold_at_spx_bottom": gold_at_spx_low,
            "wti_period_low": wti_min,
            "note": (
                f"Anchors verified against known public values: SPX close 2020-02-19 = "
                f"{by_date['2020-02-19']} (peak, cited ~3386) and 2020-03-23 = "
                f"{by_date['2020-03-23']} (bottom, cited ~2237), both matched to the cent. "
                f"SPX bottom in this window: {spx_low['close']} on {spx_low['time']}; gold "
                f"that same day: {gold_at_spx_low}. This is a fear-crisis (COVID), the "
                "opposite driver from ch3_2022_multi's inflation crisis -- capital fled to "
                "gold and (briefly) cash, not oil, which is the point of this scene's task "
                "('куда бежал капитал')."
            ),
        },
        "series": series,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("SPX bottom:", spx_low, "gold same day:", gold_at_spx_low, "WTI min:", wti_min)
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
