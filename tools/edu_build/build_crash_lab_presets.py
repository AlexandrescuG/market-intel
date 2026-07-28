#!/usr/bin/env python3
"""
Build crash_lab_presets.json -- the data file driving the chapter-3 crash-lab
v2 (SPEC Level3 Capital Protection.md §3.3): real daily series for all 6
"arsenal" asset-slider buckets (sp500, bonds, gold, oil, btc, cash) across 4
crisis windows, so the frontend can compute a day-by-day weighted-equity
curve (and its running drawdown, not just the final number) for whatever
allocation the user picks.

Sources per preset (mixing local MT5 backfill where it covers the window,
external Yahoo Finance where it doesn't -- exact same discipline as every
other ch3/ch2 data file in this repo, documented per-preset in meta):

  inflation_2022 (2022 calendar year): SPX/GOLD/WTI/BTC local MT5 (covers,
    starts 2021-07-24/26); BONDS = AGG via Yahoo (local has no bond
    instrument at all).
  covid_2020 (2020-02-10..2020-08-31): SPX/GOLD/WTI via Yahoo (local doesn't
    cover 2020); BTC via Yahoo BTC-USD; BONDS = AGG via Yahoo.
  crypto_winytketer_2021_22 (2021-11-01..2022-12-30, BTC ATH to FTX-collapse
    trough): SPX/GOLD/WTI/BTC local MT5 (covers); BONDS = AGG via Yahoo.
  crisis_2008 (2007-10-01..2009-03-31): reuses edu_capsules/crisis_2008.json
    verbatim (SPX/GOLD/WTI/BONDS via Yahoo); no BTC column -- Bitcoin didn't
    exist yet, frontend must disable/grey the crypto slider for this preset.

cash is not fetched (by definition flat 0% nominal, every day, in every
preset -- that IS its story, not an omission).

Run: python3 build_crash_lab_presets.py
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _yahoo import fetch_daily, slice_range  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT_PATH = ROOT / "web" / "data" / "edu_capsules" / "crash_lab_presets.json"


def load_local(symbol, start, end):
    path = ROOT / "web" / "data" / f"ohlc_{symbol}_D1.json"
    candles = json.loads(path.read_text())["candles"]
    return [{"time": c["time"], "close": c["close"]} for c in candles if start <= c["time"] <= end]


def load_yahoo(ysym, start, end):
    candles = fetch_daily(ysym, start, end, pad_days=5)
    return [{"time": c["time"], "close": c["close"]} for c in slice_range(candles, start, end)]


def pct(a, b):
    return round((b - a) / a * 100, 1)


def stats_for(series):
    if not series:
        return None
    low = min(series, key=lambda c: c["close"])
    return {
        "start": series[0]["close"], "end": series[-1]["close"],
        "period_low": low["close"], "period_low_date": low["time"],
        "peak_to_trough_pct": pct(series[0]["close"], low["close"]),
        "full_window_pct": pct(series[0]["close"], series[-1]["close"]),
    }


def build_inflation_2022():
    start, end = "2022-01-03", "2022-12-30"
    series = {
        "sp500": load_local("SPX", start, end),
        "gold": load_local("GOLD", start, end),
        "oil": load_local("WTI", start, end),
        "btc": load_local("BTC", start, end),
        "bonds": load_yahoo("AGG", start, end),
    }
    return {
        "id": "inflation_2022", "label_key": "presetInflation2022",
        "range": [start, end], "months": 12,
        "source": "SPX/GOLD/WTI/BTC: local MT5 backfill (real). BONDS: Yahoo Finance AGG (real, no local bond instrument exists).",
        "reconstruction": False,
        "series": series,
        "stats": {k: stats_for(v) for k, v in series.items()},
    }


def build_covid_2020():
    start, end = "2020-02-10", "2020-08-31"
    series = {
        "sp500": load_yahoo("%5EGSPC", start, end),
        "gold": load_yahoo("GC=F", start, end),
        "oil": load_yahoo("CL=F", start, end),
        "btc": load_yahoo("BTC-USD", start, end),
        "bonds": load_yahoo("AGG", start, end),
    }
    return {
        "id": "covid_2020", "label_key": "presetCovid2020",
        "range": [start, end], "months": 2,
        "source": "All 5 series: Yahoo Finance (real, local MT5 backfill doesn't cover 2020).",
        "reconstruction": False,
        "series": series,
        "stats": {k: stats_for(v) for k, v in series.items()},
    }


def build_crypto_winter():
    start, end = "2021-11-01", "2022-12-30"
    series = {
        "sp500": load_local("SPX", start, end),
        "gold": load_local("GOLD", start, end),
        "oil": load_local("WTI", start, end),
        "btc": load_local("BTC", start, end),
        "bonds": load_yahoo("AGG", start, end),
    }
    return {
        "id": "crypto_winter_2022", "label_key": "presetCryptoWinter",
        "range": [start, end], "months": 14,
        "source": "SPX/GOLD/WTI/BTC: local MT5 backfill (real). BONDS: Yahoo Finance AGG (real).",
        "reconstruction": False,
        "series": series,
        "stats": {k: stats_for(v) for k, v in series.items()},
    }


def build_2008():
    cap = json.loads((ROOT / "web" / "data" / "edu_capsules" / "crisis_2008.json").read_text())
    s = cap["series"]
    series = {
        "sp500": s["SPX"], "gold": s["GOLD"], "oil": s["WTI"], "bonds": s["BONDS"],
        "btc": None,
    }
    return {
        "id": "crisis_2008", "label_key": "presetCrisis2008",
        "range": cap["meta"]["range"], "months": 17,
        "source": cap["meta"]["source"],
        "reconstruction": False,
        "no_btc": cap["meta"]["no_btc"],
        "series": series,
        "stats": {k: stats_for(v) if v else None for k, v in series.items()},
    }


def main():
    presets = {
        "inflation_2022": build_inflation_2022(),
        "covid_2020": build_covid_2020(),
        "crypto_winter_2022": build_crypto_winter(),
        "crisis_2008": build_2008(),
    }

    out = {
        "meta": {
            "assets": ["sp500", "bonds", "gold", "oil", "btc", "cash"],
            "cash_note": "Cash is not a fetched series -- flat 0% nominal every day in every preset by definition.",
            "note": "Real daily closes for all series (mix of local MT5 backfill and Yahoo Finance, documented per preset). Frontend computes weighted portfolio equity + running drawdown day-by-day from the user's allocation sliders.",
        },
        "presets": presets,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for pid, p in presets.items():
        print(f"--- {pid} ---")
        for k, v in p["stats"].items():
            print(" ", k, v)
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
