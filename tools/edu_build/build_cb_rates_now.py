#!/usr/bin/env python3
"""
Build cb_rates_now.json -- current-snapshot file for the "3 central banks
pulling in different directions" widget. No fetching: values were supplied
pre-verified by the spec author. This script just transcribes them into the
documented shape and writes the file (kept as a script, like the other
build_*.py files, for consistency/reproducibility, even though it has no
network calls).

Run: python3 build_cb_rates_now.py
"""
import json
import pathlib

OUT = pathlib.Path(__file__).resolve().parents[2] / "web" / "data" / "edu_capsules" / "cb_rates_now.json"

DATA = {
    "updated": "2026-07-23",
    "fed": {
        "rate": 3.63,
        "as_of": "2026-07-21",
        "source": "Federal Reserve H.15",
    },
    "ecb": {
        "rate": 2.25,
        "as_of": "2026-06-11",
        "note": "first hike in 3 years",
        "source": "ECB",
    },
    "boj": {
        "rate": 1.00,
        "as_of": "2026-06-16",
        "note": "highest since 1995",
        "source": "Bank of Japan",
    },
}


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(DATA, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
