#!/usr/bin/env python3
"""
Build ch3_2022_multi.json -- SPX + NASDAQ + GOLD + WTI daily closes for 2022,
plus DXY (for the meta stats only, not a rendered pane) -- the chapter-3
cold-open's MULTI scene ("find what survived 2022").

All 5 symbols come from the local MT5 backfill (web/data/ohlc_*_D1.json),
which starts 2021-07-24/26 -- confirmed by inspection, so full calendar-year
2022 is covered. Real daily closes, no external fetch needed, no reconstruction.

Also computes the real full-year % change per symbol (open of first trading
day of 2022 -> close of last trading day of 2022) and DXY's real peak gain
from its Jan-2022 low to its Sept-2022 high, to replace the spec's
"ориентировочные" placeholder numbers with our own verified values (SPEC
Level3 Capital Protection.md instructs to do this in the build step, and the
same "run the eras" ("ориентировочные" -> real) fix was needed in chapter 2).

Run: python3 build_ch3_2022_multi.py
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT_PATH = ROOT / "web" / "data" / "edu_scenes" / "ch3_2022_multi.json"

START = "2022-01-01"
END = "2022-12-31"

SYMBOLS = ["SPX", "NASDAQ", "GOLD", "WTI", "DXY"]
PANE_SYMBOLS = ["SPX", "NASDAQ", "GOLD", "WTI"]  # DXY used for meta stat only


def load(symbol):
    path = ROOT / "web" / "data" / f"ohlc_{symbol}_D1.json"
    d = json.loads(path.read_text())
    return d["candles"]


def slice_range(candles, start, end):
    return [c for c in candles if start <= c["time"] <= end]


def pct(a, b):
    return round((b - a) / a * 100, 1)


def main():
    series = {}
    year_change = {}
    full = {}
    for sym in SYMBOLS:
        candles = slice_range(load(sym), START, END)
        assert candles, f"no {sym} data in {START}..{END}"
        full[sym] = candles
        year_change[sym] = pct(candles[0]["close"], candles[-1]["close"])
        if sym in PANE_SYMBOLS:
            series[sym] = [{"time": c["time"], "close": c["close"]} for c in candles]

    dxy_low = min(c["close"] for c in full["DXY"])
    dxy_low_date = next(c["time"] for c in full["DXY"] if c["close"] == dxy_low)
    dxy_high = max(c["close"] for c in full["DXY"])
    dxy_high_date = next(c["time"] for c in full["DXY"] if c["close"] == dxy_high)
    dxy_peak_gain = pct(dxy_low, dxy_high)

    out = {
        "meta": {
            "symbols": PANE_SYMBOLS,
            "range": [START, END],
            "source": (
                "market_intel MT5 backfill (web/data/ohlc_{SPX,NASDAQ,GOLD,WTI,DXY}_D1.json), "
                "real daily closes sliced directly for calendar year 2022 (fully covered by "
                "local data, which starts 2021-07-24/26)."
            ),
            "reconstruction": False,
            "year_change_pct": year_change,
            "dxy_year_low": {"date": dxy_low_date, "close": dxy_low},
            "dxy_year_high": {"date": dxy_high_date, "close": dxy_high},
            "dxy_peak_gain_pct": dxy_peak_gain,
            "note": (
                "Real verified 2022 figures from our own data (not the spec's placeholder "
                "estimates): " + ", ".join(f"{k} {v:+.1f}%" for k, v in year_change.items()) +
                f". DXY's intra-year peak gain from its {dxy_low_date} low ({dxy_low}) to its "
                f"{dxy_high_date} high ({dxy_high}) was {dxy_peak_gain:+.1f}%."
            ),
        },
        "series": series,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Year change %:", year_change)
    print("DXY low", dxy_low_date, dxy_low, "high", dxy_high_date, dxy_high, "peak gain", dxy_peak_gain)
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
