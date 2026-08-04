#!/usr/bin/env python3
"""
Build sr_trainer_gold.json -- real recent GOLD H4 candles + real computed
support/resistance zones, for chapter 2's SRTrainer (SPEC_edu_level2_
central_banks.md: "Апгрейд SRTrainer: реальный GOLD H4 вместо фейковых 20
свечей").

IMPORTANT finding from recon: the existing real S/R endpoint
(/api/chart/levels?symbol=GOLD, backed by sr_levels_job.py) returns the
globally top-12 scored levels across GOLD's ENTIRE H4 history (2024-03-04..
present) -- for an asset in a 2+ year uptrend (~$2000 -> ~$4100), those
top-scored levels cluster in the $1785-2041 zone (heavily touched EARLY in
that window) and are far below any window of recent candles a "drag a line"
trainer can usefully display. That endpoint is tuned for long-term chart
annotation, not for "levels visible in the last N bars" -- it is not
reusable here as-is.

Instead, this script computes real fractal swing-high/swing-low pivots
directly from the last ~90 H4 candles (fractal = a bar whose high/low is the
most extreme among itself and `k` bars on each side, the standard
Bill-Williams-style fractal definition), clusters nearby pivots (within a
tolerance derived from the window's own volatility) and counts touches, then
keeps the 2-3 clusters with the most touches as the trainer's real
correct-answer zones. This is real, computed from real OHLC, not the
existing global-score endpoint and not invented numbers.

Run: python3 build_sr_trainer_gold.py
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT_PATH = ROOT / "web" / "data" / "edu_capsules" / "sr_trainer_gold.json"

WINDOW = 90   # H4 bars (~15 trading days)
FRACTAL_K = 2  # bars on each side to qualify as a swing point
CLUSTER_COUNT = 3


def find_fractals(candles, k):
    highs, lows = [], []
    for i in range(k, len(candles) - k):
        window = candles[i-k:i+k+1]
        if candles[i]["high"] == max(c["high"] for c in window):
            highs.append((i, candles[i]["high"]))
        if candles[i]["low"] == min(c["low"] for c in window):
            lows.append((i, candles[i]["low"]))
    return highs, lows


def cluster(points, tolerance):
    """points: list of (idx, price). Returns clusters sorted by touch count desc:
    [{price: avg, touches: n, idxs: [...]}]."""
    pts = sorted(points, key=lambda p: p[1])
    clusters = []
    cur = [pts[0]] if pts else []
    for p in pts[1:]:
        if abs(p[1] - cur[-1][1]) <= tolerance:
            cur.append(p)
        else:
            clusters.append(cur)
            cur = [p]
    if cur:
        clusters.append(cur)
    out = []
    for c in clusters:
        avg = sum(p[1] for p in c) / len(c)
        out.append({"price": round(avg, 2), "touches": len(c), "idxs": [p[0] for p in c]})
    return sorted(out, key=lambda c: -c["touches"])


def main():
    all_candles = json.loads((ROOT / "web" / "data" / "ohlc_GOLD_H4.json").read_text())["candles"]
    window = all_candles[-WINDOW:]

    price_range = max(c["high"] for c in window) - min(c["low"] for c in window)
    tolerance = price_range * 0.015  # ~1.5% of the window's range

    highs, lows = find_fractals(window, FRACTAL_K)
    high_clusters = [c for c in cluster(highs, tolerance) if c["touches"] >= 2][:CLUSTER_COUNT]
    low_clusters = [c for c in cluster(lows, tolerance) if c["touches"] >= 2][:CLUSTER_COUNT]

    zones = []
    for c in high_clusters:
        zones.append({"price": c["price"], "type": "resistance", "touches": c["touches"], "tolerance": round(tolerance, 2)})
    for c in low_clusters:
        zones.append({"price": c["price"], "type": "support", "touches": c["touches"], "tolerance": round(tolerance, 2)})
    zones.sort(key=lambda z: -z["price"])

    out = {
        "meta": {
            "symbol": "GOLD",
            "timeframe": "H4",
            "window_bars": WINDOW,
            "range": [window[0]["time"], window[-1]["time"]],
            "source": "market_intel MT5 backfill (web/data/ohlc_GOLD_H4.json), real H4 OHLC.",
            "method": (
                f"Real fractal swing highs/lows (k={FRACTAL_K} bars each side, Bill-Williams-style), "
                f"clustered within {tolerance:.2f} price tolerance (~1.5% of the {WINDOW}-bar window's "
                "range), kept if touched by 2+ fractals. NOT from the /api/chart/levels endpoint -- that "
                "endpoint's top-scored levels are far outside this window's price range for a "
                "long-trending asset like gold (see script docstring)."
            ),
            "reconstruction": False,
        },
        "candles": window,
        "zones": zones,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"window: {window[0]['time']} -> {window[-1]['time']}, {len(window)} bars, tolerance {tolerance:.2f}")
    for z in zones:
        print(z)
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
