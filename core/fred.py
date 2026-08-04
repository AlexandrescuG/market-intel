"""WP9 — FRED (официальная макроэкономика).

Требует FRED_API_KEY в .env (бесплатный: fred.stlouisfed.org/docs/api/).
Без ключа — возвращает пустые данные с предупреждением.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

log = logging.getLogger("fred")

_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Ключевые ряды
KEY_SERIES = {
    "CPIAUCSL":  "CPI (All Urban)",
    "UNRATE":    "Unemployment Rate",
    "DFF":       "Fed Funds Rate",
    "T10Y2Y":    "10y-2y Spread",
    "T10YIE":    "10y Breakeven Inflation",
    "DCOILWTICO": "WTI Oil Price",
    "DTWEXBGS":  "Trade-Weighted USD",
}


def _api_key() -> str | None:
    return os.getenv("FRED_API_KEY")


def series(code: str, n: int = 12) -> list[dict]:
    """Вернуть последние n наблюдений для FRED-ряда.

    Returns: [{"date": "YYYY-MM-DD", "value": float}, ...]
    """
    key = _api_key()
    if not key:
        log.warning("FRED_API_KEY не задан — данные FRED недоступны")
        return []

    try:
        resp = httpx.get(
            _BASE,
            params={"series_id": code, "api_key": key, "file_type": "json",
                    "sort_order": "desc", "limit": n},
            timeout=10,
        )
        resp.raise_for_status()
        obs = resp.json().get("observations", [])
        result = []
        for o in obs:
            try:
                result.append({"date": o["date"], "value": float(o["value"])})
            except (ValueError, KeyError):
                pass
        return list(reversed(result))
    except Exception as e:
        log.error("FRED %s: %s", code, e)
        return []


def macro_snapshot() -> dict:
    """Последние значения ключевых рядов."""
    out = {}
    for code, label in KEY_SERIES.items():
        data = series(code, n=2)
        if data:
            latest = data[-1]
            prev = data[-2] if len(data) >= 2 else None
            delta = None
            if prev:
                try:
                    delta = round(latest["value"] - prev["value"], 3)
                except Exception:
                    pass
            out[code] = {
                "label": label,
                "value": latest["value"],
                "date": latest["date"],
                "delta": delta,
            }
    out["_updated"] = datetime.now(timezone.utc).isoformat()
    return out
