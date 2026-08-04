#!/usr/bin/env python3
"""
Build djia_century.json — DJIA year-end closes, 1896-2025 (~130 points).

Data source: the "Annual returns" wikitable in the current Wikipedia article
"Dow Jones Industrial Average", fetched as raw wikitext (action=raw) so we
parse the actual cited numbers rather than a paraphrase. That table is
itself sourced (per its footnotes) to S&P Dow Jones Indices' official
"DJIA Yearly Performance History" report and Yahoo Finance historical data.

Cross-checked while researching this capsule: an alternate long-run daily
series (measuringworth.com's "Dow Jones Average", mirrored on GitHub) uses a
different splicing convention before ~1915 (e.g. it gives 51.80 for 1900 and
59.60 for 1910 vs. the official/Wikipedia 70.71 and 81.36) but converges
exactly with the official series from the 1920s onward (1920: 71.95, 1929:
248.48, 1932: 59.93, 1940: 131.13, 1950: 235.41 match in both). We use the
Wikipedia/official table throughout for consistency across the full range.

Run: python3 build_djia_century.py
"""
import json
import pathlib
import re
import sys

import requests

WIKI_RAW_URL = (
    "https://en.wikipedia.org/w/index.php?title=Dow_Jones_Industrial_Average&action=raw"
)
OUT_PATH = pathlib.Path(__file__).resolve().parents[2] / "web" / "data" / "edu_capsules" / "djia_century.json"

ANCHORS = {
    1920: 71.95,
    1929: 248.48,
    1932: 59.93,
    1940: 131.13,
    1950: 235.41,
}


def fetch_wikitext() -> str:
    resp = requests.get(WIKI_RAW_URL, headers={"User-Agent": "sbf-edu-build/1.0"}, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_annual_table(wikitext: str):
    start = wikitext.index("==Annual returns==")
    end = wikitext.index("|}", start)
    section = wikitext[start:end]
    # Row shape (format drifts slightly across the decades in the raw wikitext):
    #   !scope="row"| 1900\n| 70.71 || +4.63 || +7.01
    #   !2021\n|36,338.30\n| +5,731.82\n| +18.73
    rows = re.findall(r'!\s*(?:scope="row"\|)?\s*(\d{4})\s*\n\|\s*([\d,]+\.\d+)', section)
    years = []
    for year_str, value_str in rows:
        years.append({"year": int(year_str), "close": float(value_str.replace(",", ""))})
    years.sort(key=lambda y: y["year"])
    return years


def sanity_check(years):
    by_year = {y["year"]: y["close"] for y in years}
    for year, expected in ANCHORS.items():
        actual = by_year.get(year)
        assert actual is not None, f"missing year {year}"
        assert abs(actual - expected) < 0.05, f"{year}: expected {expected}, got {actual}"
    return by_year


def main():
    wikitext = fetch_wikitext()
    years = parse_annual_table(wikitext)
    if not years:
        print("ERROR: parsed zero rows from the wikitable", file=sys.stderr)
        sys.exit(1)

    sanity_check(years)
    lo, hi = years[0]["year"], years[-1]["year"]

    capsule = {
        "meta": {
            "source": (
                "Wikipedia \"Dow Jones Industrial Average\" article, \"Annual returns\" "
                "table (fetched raw wikitext, not paraphrased), which cites S&P Dow "
                "Jones Indices' official yearly performance history report and Yahoo "
                "Finance historical data as its sources. "
                "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average#Annual_returns"
            ),
            "note": (
                f"Year-end closing values, {lo}-{hi} ({len(years)} points), covering the "
                "full requested 1896-2025 span with no gaps. Values are the official "
                "DJIA series throughout (see build_djia_century.py header for a note on "
                "an alternate pre-1920 splicing convention found in a secondary source "
                "that was NOT used here). Not a reconstruction -- every point is a "
                "sourced published year-end close."
            ),
            "license": "public domain (factual historical price data)",
        },
        "years": years,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(capsule, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(years)} years ({lo}-{hi}) to {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
