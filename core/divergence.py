"""WP11 — Расхождение сентимента/цены и «Что изменилось»."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from core.config import DB_PATH


def _db():
    return sqlite3.connect(DB_PATH)


def sentiment_price_divergence() -> list[dict]:
    """Найти тикеры где StockTwits bull-ratio расходится с движением цены."""
    from core.market import snapshot, to_ticker

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    with _db() as db:
        rows = db.execute(
            """SELECT cashtags, crowd_intensity, raw FROM signals
               WHERE last_seen >= ? AND source='stocktwits'""",
            (cutoff,)
        ).fetchall()

    # Накопить bull_count / total по тикеру из raw StockTwits
    ticker_bull: dict[str, list[float]] = {}
    for cashtags_json, crowd, raw_json in rows:
        try:
            raw = json.loads(raw_json or "{}")
            bull = raw.get("bull_pct")
            if bull is None:
                continue
            for tag in json.loads(cashtags_json or "[]"):
                if tag not in ticker_bull:
                    ticker_bull[tag] = []
                ticker_bull[tag].append(float(bull))
        except Exception:
            continue

    if not ticker_bull:
        return []

    # Получить цены
    tickers = list(ticker_bull)[:12]
    yf_tickers = [to_ticker(t) for t in tickers]
    try:
        snap = snapshot(yf_tickers)
    except Exception:
        return []

    result = []
    for tag, bulls in ticker_bull.items():
        yf_t = to_ticker(tag)
        price_data = snap.get(yf_t, {})
        change_pct = price_data.get("change_pct")
        if change_pct is None:
            continue
        avg_bull = sum(bulls) / len(bulls)
        # Дивергенция: ритейл бычий (>0.65), цена падает; или ритейл медвежий (<0.35), цена растёт
        divergence = None
        if avg_bull > 0.65 and change_pct < -1.0:
            divergence = "bearish_divergence"  # толпа быкует — рынок падает
        elif avg_bull < 0.35 and change_pct > 1.0:
            divergence = "bullish_divergence"  # толпа медвежит — рынок растёт
        if divergence:
            result.append({
                "tag": tag,
                "bull_pct": round(avg_bull, 3),
                "change_pct": round(change_pct, 2),
                "divergence": divergence,
                "price": price_data.get("price"),
            })

    return result


def changes_since(prev_snapshot: dict | None = None) -> dict:
    """День-к-дню: новые тикеры в Buzz, развороты сентимента."""
    cutoff24 = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    cutoff48 = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()

    def _tags_in_window(start: str, end: str) -> set[str]:
        with _db() as db:
            rows = db.execute(
                "SELECT cashtags FROM signals WHERE last_seen >= ? AND last_seen < ?",
                (start, end)
            ).fetchall()
        tags: set[str] = set()
        for (cj,) in rows:
            try:
                tags |= set(json.loads(cj or "[]"))
            except Exception:
                pass
        return tags

    now_iso = datetime.now(timezone.utc).isoformat()
    recent = _tags_in_window(cutoff24, now_iso)
    older = _tags_in_window(cutoff48, cutoff24)

    new_tickers = sorted(recent - older)
    dropped_tickers = sorted(older - recent)

    return {
        "new_tickers": new_tickers[:10],
        "dropped_tickers": dropped_tickers[:10],
        "updated": now_iso,
    }
