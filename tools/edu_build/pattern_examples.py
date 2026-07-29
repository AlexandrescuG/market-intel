#!/usr/bin/env python3
"""
pattern_examples.py — chapter 10 "Психология и Паттерны", PatternBehaviorScreens
(SPEC_charts_and_interactivity_standard.md re-audit, 29.07).

The chapter's own debug spec (SPEC_ch10_debug.md §2/§6) required a real chart
with the pattern marked and a visible date for each of the 4 pattern screens;
that never got built (text cards with pooled stats only). This script finds
ONE real, recent occurrence of each of the 7 pattern keys used by those 4
screens on USDJPY H1 (same instrument already used for the chapter's "open
on chart" links -- highest n across all four pairs) using the platform's own
existing detector (core.patterns.detect(), the identical function
pattern_stats_job.py already runs weekly for the pooled stats), and writes a
windowed real-candle scene per pattern.

Not new pattern-recognition logic: this reuses the detector as-is and just
keeps one instance per key instead of only aggregating all of them.

Run: python3 tools/edu_build/pattern_examples.py
Output: web/data/edu_scenes/ch10_patterns.json
"""
import datetime
import json
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pattern_stats_job import _load_candles, _load_levels  # noqa: E402
from core.patterns import detect  # noqa: E402

OUT_PATH = ROOT / "web" / "data" / "edu_scenes" / "ch10_patterns.json"
BOT_DB = pathlib.Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
SYMBOL = "USDJPY"
TF = "H1"
BEFORE, AFTER = 24, 16  # candles of real context on each side of the pattern bar

PATTERN_KEYS = [
    "double_top", "double_bottom",
    "bullish_engulfing", "bearish_engulfing",
    "pin_bar_top", "pin_bar_bottom",
    "break_retest",
]


def main():
    candles = _load_candles(SYMBOL, TF)
    if not candles:
        raise SystemExit(f"no candles for {SYMBOL} {TF}")
    con = sqlite3.connect(BOT_DB)
    levels = _load_levels(con, SYMBOL)
    events = detect(candles, levels)

    ts_to_idx = {c["ts"]: i for i, c in enumerate(candles)}
    by_key = {}
    for e in events:
        by_key.setdefault(e["pattern_key"], []).append(e)

    out = {"_meta": {
        "symbol": SYMBOL, "tf": TF,
        "source": "core.patterns.detect() -- same function pattern_stats_job.py runs weekly for the pooled stats",
        "built": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }, "patterns": {}}

    missing = []
    for key in PATTERN_KEYS:
        occs = by_key.get(key, [])
        # most recent occurrence with enough real candles on both sides
        chosen = None
        for e in reversed(occs):
            idx = ts_to_idx.get(e["ts"])
            if idx is None:
                continue
            if idx - BEFORE >= 0 and idx + AFTER < len(candles):
                chosen = (e, idx)
                break
        if not chosen:
            missing.append(key)
            continue
        e, idx = chosen
        window = candles[idx - BEFORE: idx + AFTER + 1]
        out["patterns"][key] = {
            "direction": e["direction"],
            "date": datetime.datetime.fromtimestamp(e["ts"], tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "marker_time": e["ts"],
            "candles": [
                {"time": c["ts"], "open": c["o"], "high": c["h"], "low": c["l"], "close": c["c"]}
                for c in window
            ],
        }
        print(f"{key}: {out['patterns'][key]['date']}, {len(window)} candles")

    if missing:
        print("WARNING: no usable occurrence found for:", missing)

    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"-> {OUT_PATH} ({len(out['patterns'])} patterns)")


if __name__ == "__main__":
    main()
