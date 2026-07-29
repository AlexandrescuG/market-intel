"""Единая БД сигналов. Все коллекторы пишут сюда, оба потребителя читают отсюда.

Сигнал = одна запись из любого источника (twitter/reddit/rss), нормализованная
и проскоренная. uid = '{source}:{source_id}' — глобально уникален.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from core import scoring
from core.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    uid              TEXT PRIMARY KEY,   -- 'twitter:123', 'reddit:abc', 'rss:<hash>'
    source           TEXT NOT NULL,      -- twitter | reddit | rss
    source_id        TEXT NOT NULL,
    dimension        TEXT,               -- economy | geopolitics | crowd
    topic_hint       TEXT,               -- запрос/сабреддит/лента, откуда пришёл
    author           TEXT,
    title            TEXT DEFAULT '',
    text             TEXT DEFAULT '',
    url              TEXT,
    lang             TEXT DEFAULT '',
    engagement       INTEGER DEFAULT 0,  -- likes+rt | reddit score | 0 для rss
    replies          INTEGER DEFAULT 0,
    econ_relevance   REAL DEFAULT 0,
    crowd_intensity  REAL DEFAULT 0,
    importance       REAL DEFAULT 0,
    cashtags         TEXT DEFAULT '[]',  -- json list
    raw              TEXT DEFAULT '{}',  -- json, источник-специфичное
    first_seen       TEXT,
    last_seen        TEXT,
    last_alerted_eng INTEGER DEFAULT 0,
    alerted          INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_signals_seen ON signals(last_seen);
CREATE INDEX IF NOT EXISTS idx_signals_dim  ON signals(dimension);
CREATE INDEX IF NOT EXISTS idx_signals_imp  ON signals(importance);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as db:
        db.executescript(SCHEMA)
        db.commit()


def _rss_cross_coverage(db: sqlite3.Connection, ctags: list[str], author: str, hours: int = 6) -> int:
    """Число ДРУГИХ RSS-изданий (author != этот), у которых за последние `hours`
    есть сигнал хотя бы с одним общим кэштегом -- прокси "сколько изданий уже
    написали о том же" (SPEC_site_fixes_2026-07-29 §6 п.3). Без кэштегов
    сравнивать не с чем -- 0, не гадаем по тексту."""
    if not ctags:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = db.execute(
        "SELECT author, cashtags FROM signals WHERE source='rss' AND last_seen >= ?",
        (cutoff,),
    ).fetchall()
    tagset = set(ctags)
    authors = set()
    for a, cj in rows:
        if a == author:
            continue
        try:
            other_tags = set(json.loads(cj or "[]"))
        except (json.JSONDecodeError, TypeError):
            continue
        if tagset & other_tags:
            authors.add(a)
    return len(authors)


def upsert(
    *,
    source: str,
    source_id: str,
    author: str = "",
    title: str = "",
    text: str = "",
    url: str = "",
    engagement: int = 0,
    replies: int = 0,
    topic_hint: str = "",
    lang: str = "",
    raw: dict | None = None,
) -> dict:
    """Вставить/обновить сигнал. Скоринг считается тут.

    Возвращает dict с ключами: is_new, growth, и всеми score-метриками.
    """
    uid = f"{source}:{source_id}"
    blob = f"{title}\n{text}".strip()
    now = _now()

    with sqlite3.connect(DB_PATH) as db:
        row = db.execute(
            "SELECT engagement, last_alerted_eng FROM signals WHERE uid=?", (uid,)
        ).fetchone()

        is_new = row is None
        prev_alerted = 0 if is_new else row[1]
        growth = engagement - prev_alerted

        # SPEC_site_fixes_2026-07-29 §6 п.3: RSS всегда приходит с engagement=0
        # (нет лайков/RT у заголовка СМИ) -- считать importance общей формулой
        # значит гарантированно проигрывать твитам. cross_coverage считаем тут
        # (не в scoring.py -- та не обязана знать про БД): сколько ДРУГИХ
        # изданий уже писали с тем же кэштегом за последние часы.
        if source == "rss":
            ctags = scoring.cashtags(blob)
            published_ts = (raw or {}).get("published")
            cross_coverage = _rss_cross_coverage(db, ctags, author)
            sc = scoring.rss_importance(blob, author, published_ts, cross_coverage)
        else:
            sc = scoring.importance(
                blob, engagement=engagement, replies=replies, virality=max(growth, 0)
            )

        if is_new:
            db.execute(
                """INSERT INTO signals
                   (uid, source, source_id, dimension, topic_hint, author, title,
                    text, url, lang, engagement, replies, econ_relevance,
                    crowd_intensity, importance, cashtags, raw, first_seen, last_seen)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (uid, source, source_id, sc["dimension"], topic_hint, author, title,
                 text, url, lang, engagement, replies, sc["econ_relevance"],
                 sc["crowd_intensity"], sc["importance"], json.dumps(sc["cashtags"]),
                 json.dumps(raw or {}), now, now),
            )
        else:
            # SPEC_site_fixes_2026-07-29 §6 п.4: раньше raw не обновлялся на
            # повторном upsert того же uid -- значит новое поле raw.domain
            # (резолвится в rss.py из entry.source.href) никогда не доходило
            # до уже виденных статей, только до по-настоящему новых uid.
            # RSS-агрегаторы (Google News) отдают одни и те же топ-статьи по
            # несколько циклов сбора подряд -- без этого фикса домен молчал
            # бы неделями. topic_hint/title/url не трогаем -- у них риск
            # перезаписать не изменившееся значение выше цены починки.
            db.execute(
                """UPDATE signals SET engagement=?, replies=?, dimension=?,
                   econ_relevance=?, crowd_intensity=?, importance=?, cashtags=?,
                   raw=?, last_seen=? WHERE uid=?""",
                (engagement, replies, sc["dimension"], sc["econ_relevance"],
                 sc["crowd_intensity"], sc["importance"], json.dumps(sc["cashtags"]),
                 json.dumps(raw or {}), now, uid),
            )
        db.commit()

    return {"uid": uid, "is_new": is_new, "growth": growth, **sc}


def mark_alerted(uid: str, engagement: int) -> None:
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            "UPDATE signals SET last_alerted_eng=?, alerted=1 WHERE uid=?",
            (engagement, uid),
        )
        db.commit()


# ─── Запросы для дайджеста ──────────────────────────────────────────────────────

def _rows(cur) -> list[dict]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def recent_since(hours: int = 24) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with sqlite3.connect(DB_PATH) as db:
        return _rows(db.execute(
            "SELECT * FROM signals WHERE last_seen >= ? ORDER BY importance DESC",
            (cutoff,),
        ))


def top_by_dimension(hours: int, dimension: str, limit: int = 15) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with sqlite3.connect(DB_PATH) as db:
        return _rows(db.execute(
            """SELECT * FROM signals
               WHERE last_seen >= ? AND dimension = ?
               ORDER BY importance DESC LIMIT ?""",
            (cutoff, dimension, limit),
        ))


def top_by_crowd(hours: int, limit: int = 15, min_intensity: float = 0.45) -> list[dict]:
    """Самые «эмоциональные» сигналы независимо от темы — для секции психологии толпы."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with sqlite3.connect(DB_PATH) as db:
        return _rows(db.execute(
            """SELECT * FROM signals
               WHERE last_seen >= ? AND crowd_intensity >= ?
               ORDER BY crowd_intensity DESC, importance DESC LIMIT ?""",
            (cutoff, min_intensity, limit),
        ))


def cashtag_heatmap(hours: int, limit: int = 20) -> list[tuple[str, int, float]]:
    """[(ticker, mentions, avg_importance)] — что обсуждают трейдеры по тикерам."""
    from collections import defaultdict
    counts: dict[str, int] = defaultdict(int)
    imp: dict[str, float] = defaultdict(float)
    for s in recent_since(hours):
        for t in json.loads(s["cashtags"] or "[]"):
            counts[t] += 1
            imp[t] += s["importance"]
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [(t, c, round(imp[t] / c, 3)) for t, c in ranked]


if __name__ == "__main__":
    init_db()
    print("DB initialised at", DB_PATH)
