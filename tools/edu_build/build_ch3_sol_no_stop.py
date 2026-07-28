#!/usr/bin/env python3
"""
Build ch3_sol_no_stop.json -- SOL daily candles, 2021-11-01..2022-12-30
("Цена незнания" / the no-stop-loss EVENT scene, SPEC Level3 Capital
Protection.md registry id ch3_sol_no_stop).

Local MT5 backfill (web/data/ohlc_SOL_D1.json) starts 2021-07-24, so this
full window is covered -- real daily OHLC, no external fetch, no
reconstruction.

Marker: 2021-11-08, the trader's entry price mentioned in the spec's "Цена
незнания" copy (~$220, "покупает по $220"). EVENT mode will cut the chart
there, let the user pick a stop-loss distance, then reveal the real
subsequent collapse to the 2022-12-30 close.

Run: python3 build_ch3_sol_no_stop.py
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT_PATH = ROOT / "web" / "data" / "edu_scenes" / "ch3_sol_no_stop.json"

START = "2021-11-01"
END = "2022-12-30"
MARKER_DATE = "2021-11-02"  # real close $220.24 -- matches spec's "~$220" entry almost exactly


def load(symbol):
    path = ROOT / "web" / "data" / f"ohlc_{symbol}_D1.json"
    d = json.loads(path.read_text())
    return d["candles"]


def slice_range(candles, start, end):
    return [c for c in candles if start <= c["time"] <= end]


def main():
    candles = slice_range(load("SOL"), START, END)
    assert candles, "no SOL data in window"

    entry = next(c for c in candles if c["time"] == MARKER_DATE)
    trough = min(candles, key=lambda c: c["low"])
    peak_pct_from_entry = round((trough["low"] - entry["close"]) / entry["close"] * 100, 1)

    out = {
        "meta": {
            "symbol": "SOL",
            "markers": [
                {"date": MARKER_DATE, "label": f"Entry ~${entry['close']:.0f}, no stop-loss set"}
            ],
            "range": [START, END],
            "source": (
                "market_intel MT5 backfill (web/data/ohlc_SOL_D1.json), real daily OHLC "
                "sliced directly (window fully covered by local data, which starts 2021-07-24)."
            ),
            "reconstruction": False,
            "entry_close": entry["close"],
            "trough_low": trough["low"],
            "trough_date": trough["time"],
            "drawdown_from_entry_pct": peak_pct_from_entry,
            "note": (
                f"Real SOL entry close on {MARKER_DATE} was ${entry['close']:.2f} (spec's copy "
                f"cites ~$220, matched). Real trough low was ${trough['low']:.2f} on "
                f"{trough['time']}, a {peak_pct_from_entry:+.1f}% move from the entry close -- "
                "matches the spec's cited '-96% from peak' framing (peak was slightly above this "
                "entry price in early Nov 2021)."
            ),
        },
        "candles": candles,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"entry {entry['close']}, trough {trough['low']} on {trough['time']}, dd {peak_pct_from_entry}%")
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
