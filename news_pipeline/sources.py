"""Базовый whitelist источников. seed() заполняет БД при первом старте."""
from __future__ import annotations

from news_pipeline.db import get_conn

# (kind, ref, category, lang, default_tags, trust)
_RSS = [
    # ── Центральные банки ──────────────────────────────────────────────────────
    ("rss", "https://www.federalreserve.gov/feeds/press_all.xml",
     "central_bank", "en", "#фрс #дкп", 10),
    ("rss", "https://www.ecb.europa.eu/rss/press.html",
     "central_bank", "en", "#есб #дкп", 10),
    ("rss", "https://www.bankofengland.co.uk/rss/publications",
     "central_bank", "en", "#банкангл #дкп", 9),
    ("rss", "https://www.boc-bce.gc.ca/rss/press-communiques-en.xml",
     "central_bank", "en", "#банккан #дкп", 9),

    # ── Макро-вайры ────────────────────────────────────────────────────────────
    ("rss", "https://feeds.reuters.com/reuters/businessNews",
     "macro_wire", "en", "#рейтерс #макро", 9),
    ("rss", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
     "macro_wire", "en", "#cnbc #рынки", 8),
    ("rss", "https://feeds.content.dowjones.io/public/rss/mw_topstories",
     "macro_wire", "en", "#marketwatch #рынки", 8),
    ("rss", "https://finance.yahoo.com/rss/topfinstories",
     "macro_wire", "en", "#yahoofinance #рынки", 7),
    ("rss", "https://www.ft.com/rss/home",
     "macro_wire", "en", "#ft #макро", 9),
    ("rss", "https://www.investing.com/rss/news_25.rss",
     "macro_wire", "en", "#investing #рынки", 7),

    # ── Крипто ────────────────────────────────────────────────────────────────
    ("rss", "https://coindesk.com/arc/outboundfeeds/rss/",
     "crypto", "en", "#крипто", 7),
    ("rss", "https://cointelegraph.com/rss",
     "crypto", "en", "#крипто", 7),

    # ── Геополитика ───────────────────────────────────────────────────────────
    ("rss", "https://www.aljazeera.com/xml/rss/all.xml",
     "geopolitics", "en", "#геополитика", 7),
    ("rss", "https://feeds.bbci.co.uk/news/world/rss.xml",
     "geopolitics", "en", "#bbc #мир", 8),

    # ── Молдова / нейтральные ─────────────────────────────────────────────────
    ("rss", "https://www.point.md/ru/rss/",
     "regional", "ru", "#молдова #экономика", 6),
    ("rss", "https://deschide.md/rss/",
     "regional", "ro", "#молдова", 5),
]

_TG = [
    # username без @
    ("tg", "markettwits",        "macro_wire",  "ru", "#макро #рынки",   8),
    ("tg", "Reuters",            "macro_wire",  "en", "#рейтерс",        9),
    ("tg", "BloombergMarkets",   "macro_wire",  "en", "#блумберг",       9),
    ("tg", "FinancialTimesNews", "macro_wire",  "en", "#ft",             9),
    ("tg", "coindesk_news",      "crypto",      "en", "#крипто",         7),
    ("tg", "lookonchain",        "crypto",      "en", "#крипто #ончейн", 7),
    ("tg", "Santimentfeed",      "crypto",      "en", "#крипто",         7),
]


def seed():
    """Добавляет источники в БД (пропускает уже существующие)."""
    with get_conn() as conn:
        for row in _RSS + _TG:
            conn.execute(
                "INSERT OR IGNORE INTO sources(kind, ref, category, lang, default_tags, trust) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                row,
            )
        conn.commit()


def get_active(kind: str | None = None) -> list[dict]:
    with get_conn() as conn:
        if kind:
            rows = conn.execute(
                "SELECT * FROM sources WHERE active=1 AND kind=?", (kind,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM sources WHERE active=1"
            ).fetchall()
    return [dict(r) for r in rows]
