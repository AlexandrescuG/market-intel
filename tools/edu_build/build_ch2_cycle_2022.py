#!/usr/bin/env python3
"""
Build ch2_cycle_2022.json -- SPX + GOLD + EURUSD daily closes, 2022-03-01..2023-07-31
(the fastest Fed hiking cycle in 40 years), plus the real FOMC meeting dates and
rate decisions for that cycle as annotations.

Price data source: local MT5 backfill (web/data/ohlc_{SPX,GOLD,EURUSD,DXY}_D1.json).
Verified these files cover 2022-03-01..2023-07-31 in full before writing this
script (D1 files start 2021-07-23) -- real data, sliced directly, no external
fetch needed for the price series.

FOMC meeting dates/decisions: taken from the Federal Reserve's own published
"Open Market Operations" historical page (federalreserve.gov/monetarypolicy/openmarket.htm),
which lists every federal funds rate target change with its date and resulting
range. Cross-checked against contemporary reporting (CNBC/Reuters/NAFCU) for
the "four consecutive 75bp hikes" characterization (Jun/Jul/Sep/Nov 2022).

SPEC_ch2_debug_and_chart_engine.md §4 update: added DXY (§4.5 wants GOLD ·
EURUSD · SPX · DXY, the original build only had 3 of the 4) and full OHLC
under a new "candles" key (§4.4 wants real candlesticks -- the old "series"
key only carried closes). "series" (closes-only) is kept alongside "candles"
so nothing that already reads this file's old shape breaks; mountReplay in
scene-engine.js is the only planned consumer of "candles" and treats it as
{symbol: [...]}, a schema mountEvent's flat single-instrument "candles" array
never used, so there's no collision between the two modes' conventions.

Run: python3 build_ch2_cycle_2022.py
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "web" / "data" / "edu_scenes" / "ch2_cycle_2022.json"

START, END = "2022-03-01", "2023-07-31"

SOURCES = {
    "SPX": ROOT / "web/data/ohlc_SPX_D1.json",
    "GOLD": ROOT / "web/data/ohlc_GOLD_D1.json",
    "EURUSD": ROOT / "web/data/ohlc_EURUSD_D1.json",
    "DXY": ROOT / "web/data/ohlc_DXY_D1.json",
}

# Federal funds rate target changes, 2022-03..2023-07, per federalreserve.gov's
# own historical open-market-operations table (date = decision/announcement
# date, decision_bp = size of the move, rate_after = resulting target range).
FOMC_MEETINGS = [
    {"date": "2022-03-16", "decision_bp": 25, "rate_after": "0.25-0.50%"},
    {"date": "2022-05-04", "decision_bp": 50, "rate_after": "0.75-1.00%"},
    {"date": "2022-06-15", "decision_bp": 75, "rate_after": "1.50-1.75%"},
    {"date": "2022-07-27", "decision_bp": 75, "rate_after": "2.25-2.50%"},
    {"date": "2022-09-21", "decision_bp": 75, "rate_after": "3.00-3.25%"},
    {"date": "2022-11-02", "decision_bp": 75, "rate_after": "3.75-4.00%"},
    {"date": "2022-12-14", "decision_bp": 50, "rate_after": "4.25-4.50%"},
    {"date": "2023-02-01", "decision_bp": 25, "rate_after": "4.50-4.75%"},
    {"date": "2023-03-22", "decision_bp": 25, "rate_after": "4.75-5.00%"},
    {"date": "2023-05-03", "decision_bp": 25, "rate_after": "5.00-5.25%"},
    {"date": "2023-06-14", "decision_bp": 0, "rate_after": "5.00-5.25%"},
    {"date": "2023-07-26", "decision_bp": 25, "rate_after": "5.25-5.50%"},
]


def slice_window(path, start, end):
    data = json.loads(path.read_text())
    candles = data["candles"]
    idx_start = next(i for i, c in enumerate(candles) if c["time"] == start)
    idx_end = next(i for i, c in enumerate(candles) if c["time"] == end)
    return candles[idx_start:idx_end + 1]


def slice_series(path, start, end):
    window = slice_window(path, start, end)
    return [{"time": c["time"], "close": c["close"]} for c in window]


def slice_candles(path, start, end):
    window = slice_window(path, start, end)
    return [{"time": c["time"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]} for c in window]


def sanity_check(series, meetings):
    # first hike total move should land right at 0.25-0.50%, last hike at 5.25-5.50%
    assert meetings[0]["rate_after"] == "0.25-0.50%"
    assert meetings[-1]["rate_after"] == "5.25-5.50%"
    hikes = [m for m in meetings if m["decision_bp"] > 0]
    assert len(hikes) == 11, f"expected 11 hike meetings (Mar22..Jul23 excl. Jun23 hold), got {len(hikes)}"
    total_bp = sum(m["decision_bp"] for m in meetings)
    assert total_bp == 525, f"expected +525bp total (0 -> 5.25-5.50%), got {total_bp}"
    # four consecutive 75bp hikes: Jun, Jul, Sep, Nov 2022
    seventy_fives = [m["date"] for m in meetings if m["decision_bp"] == 75]
    assert seventy_fives == ["2022-06-15", "2022-07-27", "2022-09-21", "2022-11-02"], seventy_fives
    # every meeting date must fall inside the price window
    for m in meetings:
        assert START <= m["date"] <= END, m
    # SPX should be in a plausible 2022-2023 bear-market-to-recovery range
    for c in series["SPX"]:
        assert 3400 < c["close"] < 4700, c
    # DXY (dollar index) plausible range for the same window
    for c in series["DXY"]:
        assert 90 < c["close"] < 120, c


def main():
    series = {sym: slice_series(path, START, END) for sym, path in SOURCES.items()}
    candles = {sym: slice_candles(path, START, END) for sym, path in SOURCES.items()}
    sanity_check(series, FOMC_MEETINGS)
    for sym, c in candles.items():
        assert len(c) == len(series[sym]), (sym, "candles/series length mismatch")

    out = {
        "meta": {
            "symbols": list(SOURCES.keys()),
            "range": [START, END],
            "source": (
                "Price series: market_intel MT5 backfill (web/data/ohlc_{SPX,GOLD,EURUSD,DXY}_D1.json), "
                "real daily OHLC sliced directly (window fully covered by local data). "
                "FOMC meetings/decisions: Federal Reserve's own historical Open Market "
                "Operations table (federalreserve.gov/monetarypolicy/openmarket.htm)."
            ),
            "reconstruction": False,
            "note": (
                "Real daily closes, not interpolated. This is the fastest Fed hiking cycle "
                "in ~40 years: 11 rate hikes totalling +525bp from 2022-03-16 (+25bp, first "
                "hike of the cycle) to 2023-07-26 (+25bp, final hike, to 5.25-5.50%), including "
                "four consecutive +75bp hikes (2022-06-15, 07-27, 09-21, 11-02) -- unprecedented "
                "in the modern inflation-targeting era -- then stepping down to +50bp "
                "(2022-12-14) and +25bp hikes through mid-2023, plus one hold "
                "(2023-06-14, no change, included here for calendar completeness)."
            ),
        },
        "series": series,
        "candles": candles,
        "fomc_meetings": FOMC_MEETINGS,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for k, v in series.items():
        print(f"{k}: {len(v)} points")
    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes), {len(FOMC_MEETINGS)} FOMC meetings")


if __name__ == "__main__":
    main()
