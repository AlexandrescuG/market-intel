#!/usr/bin/env python3
"""
Build ch2_carry_2024.json -- USDJPY daily candles, 2024-07-15..2024-08-20
(SPEC_edu_level2_central_banks.md registry id ch2_carry_2024, the August 2024
yen carry-trade unwind).

Real MT5 backfill (web/data/ohlc_USDJPY_D1.json) covers this window in full
(full stack back to 2018-01-02, confirmed by inspection). No Nikkei 225
instrument exists in our backfill at all -- USDJPY is used instead as the
direct, real proxy for the same carry-trade-unwind story (BOJ hiking +
carry-trade unwound the yen directly; Nikkei's crash on 2024-08-05 was a
second-order consequence of the same unwind, not a separate driver), per the
substitution already decided during chapter-2 planning.

Real events on the real chart:
  2024-07-31: BOJ raises rate to 0.25% (largest hike since 2007)
  2024-08-02: weak US jobs report (NFP miss) revives US recession fears
  2024-08-05: Nikkei 225 falls 12.4% intraday -- its worst day since 1987
              ("Black Monday" Japan) -- carry trades unwind violently
USDJPY itself: 157.42 (2024-07-21) -> 145.60 (2024-08-04), a real ~7.5% move
in two weeks -- the currency pair IS the carry trade, no reconstruction
needed for this scene at all.

Run: python3 build_ch2_carry_2024.py
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT_PATH = ROOT / "web" / "data" / "edu_scenes" / "ch2_carry_2024.json"

START = "2024-07-15"
END = "2024-08-20"

MARKERS = [
    {"date": "2024-07-31", "label": "BOJ raises its policy rate to 0.25% -- the largest hike since 2007"},
    {"date": "2024-08-02", "label": "Weak US jobs report revives US recession fears"},
    {"date": "2024-08-05", "label": "Nikkei 225 falls 12.4% intraday -- worst day since 1987 -- carry trades unwind violently"},
]


def main():
    candles = json.loads((ROOT / "web" / "data" / "ohlc_USDJPY_D1.json").read_text())["candles"]
    sliced = [c for c in candles if START <= c["time"] <= END]
    assert sliced, "no USDJPY data in window"

    out_candles = [{"time": c["time"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]} for c in sliced]
    peak = max(out_candles, key=lambda c: c["close"])
    trough_after_peak = min((c for c in out_candles if c["time"] >= peak["time"]), key=lambda c: c["close"])
    move_pct = round((trough_after_peak["close"] - peak["close"]) / peak["close"] * 100, 1)

    out = {
        "meta": {
            "symbols": ["USDJPY"],
            "substitution_note": (
                "No Nikkei 225 instrument exists in our MT5 backfill. USDJPY is used directly, "
                "not as a stand-in but as the real, primary instrument of the carry-trade unwind "
                "itself -- the Nikkei crash on 2024-08-05 was a downstream consequence of the same "
                "yen move, not an independent data point."
            ),
            "markers": MARKERS,
            "range": [START, END],
            "source": "market_intel MT5 backfill (web/data/ohlc_USDJPY_D1.json), real daily closes, full coverage of this window.",
            "reconstruction": False,
            "note": (
                f"Real move: USDJPY {peak['close']} ({peak['time']}) -> {trough_after_peak['close']} "
                f"({trough_after_peak['time']}), {move_pct:+.1f}% -- the yen carry-trade unwind, "
                "not a reconstruction."
            ),
        },
        "candles": out_candles,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"peak {peak}, trough {trough_after_peak}, move {move_pct}%")
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
