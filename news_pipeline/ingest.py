"""Ингест из RSS и Telegram-каналов (whitelist). Пишет в raw_items."""
from __future__ import annotations

import logging
import re
import time

import feedparser

from news_pipeline.db import get_conn
from news_pipeline.sources import get_active

log = logging.getLogger("newspipe.ingest")

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


# ── RSS ────────────────────────────────────────────────────────────────────────

def _entry_id(entry, source_ref: str) -> str:
    base = entry.get("id") or entry.get("link") or entry.get("title", "")
    return f"{source_ref}:{base}"[:200]


def _entry_ts(entry) -> int:
    for k in ("published_parsed", "updated_parsed"):
        if entry.get(k):
            return int(time.mktime(entry[k]))
    return int(time.time())


def _entry_url(entry) -> str:
    return entry.get("link", "")


def _entry_title(entry) -> str:
    return (entry.get("title") or "").strip()


def ingest_rss() -> int:
    sources = get_active("rss")
    total = 0
    with get_conn() as conn:
        for src in sources:
            try:
                feed = feedparser.parse(src["ref"], agent=_UA)
                for entry in feed.entries:
                    ext_id = _entry_id(entry, src["ref"])
                    ts = _entry_ts(entry)
                    title = _entry_title(entry)
                    url = _entry_url(entry)
                    if not title:
                        continue
                    try:
                        conn.execute(
                            "INSERT OR IGNORE INTO raw_items "
                            "(source_id, ext_id, ts, title, body, url, lang, fetched_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (src["id"], ext_id, ts, title,
                             entry.get("summary", "")[:500],
                             url, src["lang"], int(time.time())),
                        )
                        if conn.execute("SELECT changes()").fetchone()[0]:
                            total += 1
                    except Exception as e:
                        log.debug("insert skip %s: %s", ext_id[:40], e)
                conn.commit()
                log.debug("RSS %s: %d entries", src["ref"][:60], len(feed.entries))
            except Exception as e:
                log.warning("RSS feed error %s: %s", src["ref"][:60], e)
    log.info("RSS ingest: +%d new items", total)
    return total


# ── Telegram (вызывается из run.py с готовым client) ──────────────────────────

async def ingest_tg_message(client, msg, source: dict) -> bool:
    """Сохраняет одно TG-сообщение в raw_items. Возвращает True если новое."""
    text = msg.text or ""
    if not text.strip():
        return False

    ext_id = str(msg.id)
    ts = int(msg.date.timestamp()) if msg.date else int(time.time())

    # первая ссылка из текста
    urls = re.findall(r"https?://\S+", text)
    url = urls[0].strip("()") if urls else ""

    title = text.splitlines()[0][:300]

    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO raw_items "
            "(source_id, ext_id, ts, title, body, url, lang, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (source["id"], ext_id, ts, title, text[:1000],
             url, source["lang"], int(time.time())),
        )
        changed = conn.execute("SELECT changes()").fetchone()[0]
        conn.commit()
    return bool(changed)


async def ingest_tg_history(client, source: dict, limit: int = 50) -> int:
    """Подгружает последние N сообщений из TG-канала whitelist."""
    total = 0
    try:
        async for msg in client.iter_messages(source["ref"], limit=limit, reverse=True):
            if await ingest_tg_message(client, msg, source):
                total += 1
    except Exception as e:
        log.warning("TG history error @%s: %s", source["ref"], e)
    return total
