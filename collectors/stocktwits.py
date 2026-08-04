"""StockTwits-коллектор: сентимент трейдеров по тикерам (замена Reddit).

Тянет символьные потоки, агрегирует bull/bear метки, объём сообщений (= внимание),
и сохраняет по сигналу на тикер. Плюс цепляет самое заметное сообщение для колорита.

Кандидаты-тикеры = watchlist из конфига ∪ кэштеги, всплывшие в свежих сигналах.
Без кредов. Лимит API ~200 запросов/час — держим watchlist умеренным.
"""
from __future__ import annotations

import json
import logging

import httpx

from core import db
from core.config import STOCKTWITS_WATCHLIST

log = logging.getLogger("stocktwits")
_BASE = "https://api.stocktwits.com/api/2"
UA = {"User-Agent": "Mozilla/5.0"}


async def _stream(client: httpx.AsyncClient, symbol: str) -> list[dict]:
    try:
        r = await client.get(f"{_BASE}/streams/symbol/{symbol}.json", headers=UA)
        if r.status_code != 200:
            log.debug("stocktwits %s: %s", symbol, r.status_code)
            return []
        return r.json().get("messages", [])
    except Exception as e:
        log.debug("stocktwits %s: %s", symbol, e)
        return []


def _candidates() -> list[str]:
    syms = set(s.upper() for s in STOCKTWITS_WATCHLIST)
    for sig in db.recent_since(24):
        for t in json.loads(sig["cashtags"] or "[]"):
            syms.add(t.upper())
    return sorted(syms)


async def collect() -> int:
    db.init_db()
    saved = 0
    async with httpx.AsyncClient(timeout=15) as client:
        for sym in _candidates():
            msgs = await _stream(client, sym)
            if not msgs:
                continue
            bull = bear = 0
            top = None
            for m in msgs:
                sent = ((m.get("entities") or {}).get("sentiment") or {}).get("basic")
                if sent == "Bullish":
                    bull += 1
                elif sent == "Bearish":
                    bear += 1
                # самое «заметное» — по лайкам, если есть
                likes = (m.get("likes") or {}).get("total", 0)
                if top is None or likes > top[0]:
                    top = (likes, m.get("body", ""), sent)
            total = len(msgs)
            ratio = round(bull / max(bull + bear, 1), 2)
            mood = ("🟢 bull" if ratio > 0.6 else "🔴 bear" if ratio < 0.4 else "⚪ mixed")
            color = f" · top: {top[1][:120]}" if top and top[1] else ""
            summary = (f"StockTwits ${sym}: {total} сообщ, "
                       f"{bull}🐂/{bear}🐻 (bull-ratio {ratio}, {mood}){color}")
            db.upsert(
                source="stocktwits",
                source_id=f"{sym}",                 # один агрегат на тикер/прогон
                author="stocktwits",
                title=f"${sym} sentiment",
                text=summary,
                url=f"https://stocktwits.com/symbol/{sym}",
                engagement=total,                   # объём = внимание
                replies=bull + bear,
                topic_hint=f"${sym}",
                raw={"bull": bull, "bear": bear, "ratio": ratio, "msgs": total},
            )
            saved += 1
            log.info("stocktwits $%-6s %d msgs %s", sym, total, mood)
    log.info("stocktwits collect done: %d tickers", saved)
    return saved


if __name__ == "__main__":
    import asyncio
    from core.logging_setup import setup
    setup("stocktwits")
    print("saved:", asyncio.run(collect()))
