"""RSS-коллектор: что больше всего постят мировые и региональные СМИ.

Две функции:
  collect()        — тянет все ленты, скорит, пишет сигналы в БД
  media_agenda()   — частотный срез: какие темы/термины СМИ гонят чаще всего
                     за окно (для брифа — «повестка дня»)

Зависимость: feedparser. Без кредов, без браузера.
"""
from __future__ import annotations

import hashlib
import logging
import time
from collections import Counter
from datetime import datetime, timezone

import feedparser

from core import db, scoring
from core.config import (RSS_FEEDS, RSS_TREND_WINDOW_HOURS,
                         STORE_MIN_ECON_RELEVANCE, ALERT_MIN_RSS_RELEVANCE)

log = logging.getLogger("rss")

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# термины для частотного среза повестки (берём из лексиконов экономики/геополитики)
_AGENDA_TERMS: list[str] = []
for _dim in ("economy", "geopolitics"):
    for _cat in scoring.LEXICONS[_dim].values():
        _AGENDA_TERMS += [t.strip() for t, _w in _cat if len(t.strip()) > 3]
_AGENDA_TERMS = sorted(set(_AGENDA_TERMS))


def _guid(entry, feed_name: str) -> str:
    base = entry.get("id") or entry.get("link") or entry.get("title", "")
    return hashlib.sha1(f"{feed_name}:{base}".encode()).hexdigest()[:16]


def _entry_time(entry) -> float:
    for k in ("published_parsed", "updated_parsed"):
        if entry.get(k):
            return time.mktime(entry[k])
    return time.time()


def collect() -> tuple[int, list[dict]]:
    """Тянем все ленты, пишем релевантные сигналы.

    Возвращает (saved, alert_candidates) — новые важные статьи для Telegram.
    """
    db.init_db()
    saved = 0
    alerts: list[dict] = []

    for name, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url, agent=UA)
        except Exception as e:
            log.warning("RSS %s failed: %s", name, e)
            continue
        if feed.bozo and not feed.entries:
            log.warning("RSS %s empty/bozo: %s", name, getattr(feed, "bozo_exception", ""))
            continue

        cutoff = time.time() - 86400  # только за последние 24 часа
        for e in feed.entries[:40]:
            if _entry_time(e) < cutoff:
                continue
            title = (e.get("title") or "").strip()
            summary = (e.get("summary") or "").strip()
            text = summary[:600]
            # Google News ("Google News: EURUSD" и т.п.) — это агрегатор, а не
            # издание: каждый entry несёт свой <source> (реальный публикатор,
            # напр. "Reuters"), а title приходит вида "Заголовок - Publisher".
            # Показываем реального публикатора вместо "Google News: ..." и
            # убираем дублирующий суффикс из заголовка.
            source_hint = name
            gsrc = e.get("source")
            if gsrc and gsrc.get("title"):
                source_hint = gsrc["title"].strip()
                suffix = f" - {source_hint}"
                if title.endswith(suffix):
                    title = title[: -len(suffix)].strip()
            blob = f"{title}\n{text}"
            er = scoring.econ_relevance(blob)
            if er < STORE_MIN_ECON_RELEVANCE:
                continue
            res = db.upsert(
                source="rss",
                source_id=_guid(e, name),
                author=name,
                title=title,
                text=text,
                url=e.get("link", ""),
                engagement=0,
                topic_hint=source_hint,
                raw={"published": _entry_time(e)},
            )
            saved += 1
            if res["is_new"] and er >= ALERT_MIN_RSS_RELEVANCE:
                alerts.append({"source": name, "title": title,
                               "url": e.get("link", ""), "econ_relevance": er,
                               "dimension": res.get("dimension", "economy")})

        log.info("RSS %-16s %d entries → stored relevant", name, len(feed.entries))

    # топ-8 по релевантности, чтобы не спамить
    alerts.sort(key=lambda x: x["econ_relevance"], reverse=True)
    log.info("RSS collect done: %d signals, %d alerts", saved, len(alerts))
    return saved, alerts[:8]


def media_agenda(hours: int = RSS_TREND_WINDOW_HOURS, top: int = 20) -> list[tuple[str, int]]:
    """Частота терминов в заголовках RSS за окно → [(термин, упоминаний)]."""
    cutoff = (datetime.now(timezone.utc).timestamp()) - hours * 3600
    counter: Counter = Counter()
    for s in db.recent_since(hours):
        if s["source"] != "rss":
            continue
        lc = f"{s['title']} {s['text']}".lower()
        for term in _AGENDA_TERMS:
            if term in lc:
                counter[term.strip()] += 1
    return counter.most_common(top)


if __name__ == "__main__":
    from core.logging_setup import setup
    setup("rss")
    n = collect()
    print(f"\nСохранено сигналов: {n}")
    print("\nПовестка СМИ (топ терминов):")
    for term, c in media_agenda(top=15):
        print(f"  {c:3}×  {term}")
