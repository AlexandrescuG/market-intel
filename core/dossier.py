"""WP6 — Досье-движок. Мгновенный срез всего что система знает про тикер/тему."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from core.config import DB_PATH


def _db():
    return sqlite3.connect(DB_PATH)


def dossier(query: str) -> dict:
    """Собрать полное досье по тикеру или ключевому слову."""
    from core.market import snapshot, to_ticker
    from core.technical import analyze

    ticker = to_ticker(query.strip().upper())
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()

    # Технический анализ
    tech = None
    try:
        tech = analyze(ticker)
    except Exception:
        pass

    # Сигналы с упоминанием
    with _db() as db:
        signals_raw = db.execute(
            """SELECT uid, source, author, title, text, url, importance,
                      crowd_intensity, engagement, first_seen
               FROM signals
               WHERE last_seen >= ? AND (
                   cashtags LIKE ? OR text LIKE ? OR title LIKE ?
               )
               ORDER BY importance DESC LIMIT 20""",
            (cutoff, f'%"{query.upper()}"%', f"%{query}%", f"%{query}%")
        ).fetchall()
        sig_cols = ["uid", "source", "author", "title", "text", "url",
                    "importance", "crowd_intensity", "engagement", "first_seen"]
        signals = [dict(zip(sig_cols, r)) for r in signals_raw]

        # Истории с этим тикером
        stories_raw = db.execute(
            "SELECT id, title, status, momentum FROM stories WHERE market_tickers LIKE ?",
            (f'%"{query.upper()}"%',)
        ).fetchall()
        stories = [{"id": r[0], "title": r[1], "status": r[2], "momentum": r[3]}
                   for r in stories_raw]

        # StockTwits sentiment
        st_rows = db.execute(
            """SELECT AVG(crowd_intensity), COUNT(*) FROM signals
               WHERE source='stocktwits' AND last_seen >= ? AND cashtags LIKE ?""",
            (cutoff, f'%"{query.upper()}"%')
        ).fetchone()
        st_sentiment = {"avg_crowd": round(st_rows[0] or 0, 3), "count": st_rows[1]}

    # Рыночный снимок
    market_snap = {}
    try:
        snap = snapshot([ticker])
        market_snap = snap.get(ticker, {})
    except Exception:
        pass

    return {
        "query": query,
        "ticker": ticker,
        "technical": tech,
        "market": market_snap,
        "signals": signals,
        "stories": stories,
        "stocktwits_sentiment": st_sentiment,
        "updated": datetime.now(timezone.utc).isoformat(),
    }


def publish_dossiers(watchlist: list[str] | None = None) -> dict[str, dict]:
    """Собрать досье для всех тикеров из watchlist."""
    from core.config import STOCKTWITS_WATCHLIST
    tickers = watchlist or STOCKTWITS_WATCHLIST[:10]
    return {t: dossier(t) for t in tickers}
