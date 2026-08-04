"""Slice 30 daily GOLD candles for edu chapter 1, interactive B (5 eras of chart drawing).
Window chosen for a visible story: drift down -> sharp selloff -> V-reversal (2026-02-20..2026-04-02),
swing low 2026-03-23 (intraday 4100.80) / 2026-03-24 close 4399.30.
Source: web/data/ohlc_GOLD_D1.json (MT5 backfill, GC=F daily).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "web/data/ohlc_GOLD_D1.json"
OUT = ROOT / "web/data/edu_scenes/gold_30d.json"

START, END = "2026-02-20", "2026-04-02"

def main():
    data = json.loads(SRC.read_text())
    candles = data["candles"]
    idx_start = next(i for i, c in enumerate(candles) if c["time"] == START)
    idx_end = next(i for i, c in enumerate(candles) if c["time"] == END)
    window = candles[idx_start:idx_end + 1]
    assert len(window) == 30, f"expected 30 bars, got {len(window)}"

    lows = [c["low"] for c in window]
    reversal_idx = min(range(len(window)), key=lambda i: lows[i])
    reversal_day = window[reversal_idx]["time"]

    out = {
        "meta": {
            "ticker": "GC=F",
            "label": "GOLD",
            "source": "market_intel MT5 backfill (web/data/ohlc_GOLD_D1.json)",
            "range": [START, END],
            "note": "30 дневных баров, реальный ряд (не синтетика). Видимая история: снижение -> резкая распродажа 18-23.03 -> V-разворот.",
            "reversal_day": reversal_day
        },
        "candles": [
            {"time": c["time"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]}
            for c in window
        ]
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes), reversal_day={reversal_day}")

if __name__ == "__main__":
    main()
