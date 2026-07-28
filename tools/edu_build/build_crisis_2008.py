#!/usr/bin/env python3
"""
Build crisis_2008.json -- daily closes for SPX, GOLD, WTI, DXY and a bonds
proxy (AGG, iShares Core U.S. Aggregate Bond ETF -- inception 2003, so it
covers 2008; the standard real-world proxy for "US aggregate bonds" that the
60/40-portfolio literature the spec cites (~-13% bonds in 2022) also uses),
2007-10-01..2009-03-31 -- peak (2007-10-09 S&P all-time high before the GFC)
to trough (2009-03-09 S&P bear-market bottom).

Local MT5 backfill doesn't cover 2008 at all (starts 2021-07-24/26) -- this
whole capsule is external, real, from Yahoo Finance's chart API.
No BTC column: Bitcoin didn't exist yet (launched Jan 2009), so the
crash-lab UI must grey out / zero the crypto slider for this preset rather
than show a fabricated 2008 "crypto" return -- handled in the frontend, not
faked here.

Run: python3 build_crisis_2008.py
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _yahoo import fetch_daily, slice_range  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT_PATH = ROOT / "web" / "data" / "edu_capsules" / "crisis_2008.json"

START = "2007-10-01"
END = "2009-03-31"

SYMBOLS = {"SPX": "%5EGSPC", "GOLD": "GC=F", "WTI": "CL=F", "DXY": "DX-Y.NYB", "BONDS": "AGG"}


def pct(a, b):
    return round((b - a) / a * 100, 1)


def main():
    series = {}
    stats = {}
    for label, ysym in SYMBOLS.items():
        candles = fetch_daily(ysym, START, END, pad_days=5)
        sliced = slice_range(candles, START, END)
        series[label] = [{"time": c["time"], "close": c["close"]} for c in sliced]
        low = min(sliced, key=lambda c: c["close"])
        stats[label] = {
            "start": sliced[0]["close"], "end": sliced[-1]["close"],
            "period_low": low["close"], "period_low_date": low["time"],
            "peak_to_trough_pct": pct(sliced[0]["close"], low["close"]),
            "full_window_pct": pct(sliced[0]["close"], sliced[-1]["close"]),
        }

    spx_bottom_date = stats["SPX"]["period_low_date"]

    out = {
        "meta": {
            "symbols": list(SYMBOLS.keys()),
            "range": [START, END],
            "spx_peak_date": series["SPX"][0]["time"],
            "spx_bottom_date": spx_bottom_date,
            "source": (
                "Yahoo Finance chart API, interval=1d: ^GSPC (SPX), GC=F (GOLD), CL=F (WTI), "
                "DX-Y.NYB (DXY), AGG (bonds proxy -- iShares Core U.S. Aggregate Bond ETF, "
                "the standard real-world 'aggregate bonds' benchmark). Real fetched daily "
                "closes, not interpolated. Local MT5 backfill doesn't cover 2008 at all."
            ),
            "reconstruction": False,
            "no_btc": "Bitcoin did not exist yet (launched Jan 2009) -- crypto slider must be disabled/zeroed for this preset, not faked.",
            "stats": stats,
            "note": (
                f"Real peak-to-trough ({series['SPX'][0]['time']} -> {spx_bottom_date}): "
                + ", ".join(f"{k} {v['peak_to_trough_pct']:+.1f}%" for k, v in stats.items())
            ),
        },
        "series": series,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for k, v in stats.items():
        print(k, v)
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
