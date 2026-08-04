"""Finnhub — фоллбек: общие новости, котировки акций/крипты (free tier).

Требует FINNHUB_API_KEY в .env (бесплатный: finnhub.io/dashboard).

⚠️ Проверено вживую 17.07.2026: форекс-котировки (`/quote?symbol=OANDA:...`),
экономический календарь (`/calendar/economic`) и news-sentiment на free tier
ЗАКРЫТЫ ("You don't have access to this resource") — вопреки тому, что
предполагал SBF_Free_Data_Sources.md. На free tier реально доступны только
акции/крипта (`/quote`) и общие новости (`/news`). Если форекс/календарь
понадобятся — нужен платный план Finnhub, это уже не «бесплатный источник».
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

log = logging.getLogger("finnhub")

_BASE = "https://finnhub.io/api/v1"


def _api_key() -> str | None:
    return os.getenv("FINNHUB_API_KEY")


def quote(symbol: str) -> dict:
    """Котировка акции/крипты. symbol: 'AAPL', 'BINANCE:BTCUSDT' и т.п.

    Returns: {price, change, change_pct, high, low, open, prev_close} или {} при ошибке/лимите.
    """
    key = _api_key()
    if not key:
        log.warning("FINNHUB_API_KEY не задан")
        return {}
    try:
        resp = httpx.get(f"{_BASE}/quote", params={"symbol": symbol, "token": key}, timeout=10)
        resp.raise_for_status()
        d = resp.json()
        if "c" not in d:
            return {}
        return {
            "price": d.get("c"), "change": d.get("d"), "change_pct": d.get("dp"),
            "high": d.get("h"), "low": d.get("l"), "open": d.get("o"), "prev_close": d.get("pc"),
        }
    except Exception as e:
        log.error("finnhub quote %s: %s", symbol, e)
        return {}


def general_news(limit: int = 20) -> list[dict]:
    """Общие рыночные новости (top news). Дублирует часть RSS-пула — доп. источник, не основной."""
    key = _api_key()
    if not key:
        log.warning("FINNHUB_API_KEY не задан")
        return []
    try:
        resp = httpx.get(f"{_BASE}/news", params={"category": "general", "token": key}, timeout=10)
        resp.raise_for_status()
        items = resp.json()
        return [
            {"headline": i.get("headline"), "source": i.get("source"),
             "url": i.get("url"), "datetime": i.get("datetime"), "summary": i.get("summary")}
            for i in items[:limit]
        ]
    except Exception as e:
        log.error("finnhub news: %s", e)
        return []
