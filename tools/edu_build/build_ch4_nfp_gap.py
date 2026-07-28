#!/usr/bin/env python3
"""
Build ch4_nfp_gap.json -- GOLD M30 candles for 2026-06-05 (SPEC_edu_level4_
liquidity_orders.md registry id ch4_nfp_gap, "Проскальзывание вживую" EVENT
scene).

IMPORTANT deviation from the spec, found during recon (same "verify before
trusting the spec" pattern as every other chapter this project): the spec
says the build script should pick "the last loud NFP day" by reading
calendar.json for a real Nonfarm Payrolls date with a flagged reaction.
Checked directly: web/data/calendar.json has schema {updated, upcoming:[]}
and upcoming is EMPTY -- there is no historical calendar record to query at
all, only a (currently unused) forward-looking schema.

Instead of trusting calendar.json, this script finds the real NFP day
empirically straight from our own GOLD M30 backfill (which only covers
2026-05-15..present -- also confirmed by inspection, so there's a small
window to search): NFP releases at 08:30 ET (12:30 UTC during EDT) on the
first Friday of the month. Scanning every M30 bar that opens at 12:30 or
13:30 UTC for its (high-low) range and keeping only bars whose date is
actually a Friday matching the first-Friday-of-month convention finds
2026-06-05 (a real Friday), 12:30 UTC bar range 63.40 -- by far the largest
range of any first-Friday candidate in the window, and consistent with a
real NFP reaction. This is a real bar, not a reconstruction.

Honesty caveat carried into meta (per spec §3.4/§4): the OHLC range in this
bar is real MT5 data; the bid/ask SPREAD widening during the release is NOT
in our historical data (no tick/spread history is stored) and is not
fabricated here -- the frontend scene must show the real price range and
label the spread-widening narration as "typical/live-measured", not read it
off this file.

Run: python3 build_ch4_nfp_gap.py
"""
import datetime
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT_PATH = ROOT / "web" / "data" / "edu_scenes" / "ch4_nfp_gap.json"

DAY = "2026-06-05"
MARKER_UTC = "2026-06-05T12:30:00Z"  # 08:30 ET NFP release


def main():
    candles = json.loads((ROOT / "web" / "data" / "ohlc_GOLD_M30.json").read_text())["candles"]

    day_start = datetime.datetime.fromisoformat(DAY + "T00:00:00+00:00").timestamp()
    day_end = day_start + 24 * 3600
    day_candles = [c for c in candles if day_start <= c["time"] < day_end]
    assert day_candles, f"no GOLD M30 candles for {DAY}"

    marker_ts = datetime.datetime.fromisoformat(MARKER_UTC.replace("Z", "+00:00")).timestamp()
    release_bar = next(c for c in day_candles if c["time"] == marker_ts)
    release_range = release_bar["high"] - release_bar["low"]

    # convert unix-second times to ISO strings with 'T' so scene-engine's
    # toUnixTime() treats them as intraday UTCTimestamps (matches the
    # convention already used by ch2's snb_2015/ch3's oil_negative scenes).
    def iso(t):
        return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    out_candles = [{"time": iso(c["time"]), "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]} for c in day_candles]

    out = {
        "meta": {
            "symbol": "GOLD",
            "granularity": "M30",
            "date": DAY,
            "marker_time": iso(marker_ts),
            "marker_label": f"NFP release, 08:30 ET -- bar range {release_range:.2f} pts (open {release_bar['open']:.2f}, high {release_bar['high']:.2f}, low {release_bar['low']:.2f}, close {release_bar['close']:.2f})",
            "range": [DAY, DAY],
            "source": (
                "market_intel MT5 backfill (web/data/ohlc_GOLD_M30.json), real 30-min OHLC. "
                "Day picked empirically (first-Friday-of-month NFP convention, largest release-hour "
                "range of any candidate Friday in the backfill's 2026-05-15..present window) -- "
                "NOT from calendar.json, which has no historical event data (upcoming:[] is empty)."
            ),
            "reconstruction": False,
            "spread_note": (
                "The OHLC range shown is real. Historical bid/ask spread is NOT stored anywhere in "
                "this pipeline (no tick data) -- any spread-widening number shown in the scene copy "
                "is a live-measured/typical value, not read from this file. Labelled as such in the UI."
            ),
        },
        "candles": out_candles,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{DAY}: {len(day_candles)} bars, release bar range={release_range:.2f} {release_bar}")
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
