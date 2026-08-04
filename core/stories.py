"""WP1 — Истории (нарративы). Кластеризует сигналы в живые нарративы.

Уровень 1 (детерминированный): группировка по пересечению кэштегов + ключевых
терминов из LEXICONS. Уровень 2 (эмбеддинги) — опционален, включается если
sentence-transformers установлен.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from core.config import DB_PATH
from core import scoring

# ── Термины для сущностей (редкие → вес выше) ──────────────────────────────────
_ACTORS = [t for cat in scoring.LEXICONS.get("geopolitics", {}).values()
           for t, _ in cat]
_ECON   = [t for cat in scoring.LEXICONS.get("economy", {}).values()
           for t, _ in cat if len(t) > 5]

# Только значимые (длинные) термины для кластеризации
_CLUSTER_TERMS: list[str] = list({
    t.strip().lower() for t in _ACTORS + _ECON
    if len(t.strip()) >= 6
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_entities(text: str) -> set[str]:
    tl = text.lower()
    found: set[str] = set()
    for term in _CLUSTER_TERMS:
        if term in tl:
            found.add(term)
    return found


def _story_id(entities: set[str]) -> str:
    key = "-".join(sorted(entities)[:4])
    return hashlib.md5(key.encode()).hexdigest()[:12]


# ─── DB helpers ────────────────────────────────────────────────────────────────

def _db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


# ─── Публичный API ─────────────────────────────────────────────────────────────

def rebuild_stories(hours: int = 48) -> int:
    """Пересобрать кластеры историй из последних сигналов. Возвращает кол-во историй."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    now = _now()

    with _db() as db:
        signals = _rows(db.execute(
            "SELECT uid, title, text, cashtags, first_seen FROM signals WHERE last_seen >= ?",
            (cutoff,)
        ))

    # Извлечь сущности для каждого сигнала
    sig_entities: dict[str, set[str]] = {}
    sig_tags: dict[str, set[str]] = {}
    for s in signals:
        blob = f"{s['title']} {s['text']}"
        sig_entities[s["uid"]] = _extract_entities(blob)
        try:
            tags = set(json.loads(s["cashtags"] or "[]"))
        except Exception:
            tags = set()
        sig_tags[s["uid"]] = tags

    # Уровень 1: кластеризация по пересечению сущностей + кэштегов
    clusters: dict[str, set[str]] = {}  # story_id -> set[uid]
    uid_to_story: dict[str, str] = {}

    for uid, entities in sig_entities.items():
        tags = sig_tags[uid]
        best_story: str | None = None
        best_overlap = 0

        for sid, members in clusters.items():
            # Собрать все сущности и теги историй
            story_entities: set[str] = set()
            story_tags: set[str] = set()
            for m in members:
                story_entities |= sig_entities.get(m, set())
                story_tags |= sig_tags.get(m, set())

            overlap = len(entities & story_entities) + len(tags & story_tags) * 2
            if overlap >= 2 and overlap > best_overlap:
                best_overlap = overlap
                best_story = sid

        if best_story:
            clusters[best_story].add(uid)
            uid_to_story[uid] = best_story
        else:
            if entities or tags:
                sid = _story_id(entities | tags)
                clusters[sid] = {uid}
                uid_to_story[uid] = sid

    # Уровень 2: попробовать семантические эмбеддинги (опционально)
    try:
        from sentence_transformers import SentenceTransformer, util
        _apply_embeddings(signals, sig_entities, sig_tags, clusters, uid_to_story)
    except ImportError:
        pass

    # Записать историй в БД
    with _db() as db:
        # Сбросить привязки сигналов
        db.execute("DELETE FROM story_signals WHERE 1=1")

        for sid, members in clusters.items():
            if len(members) < 2:
                continue  # одиночные сигналы не делают историю

            # Авто-заголовок из общих терминов
            all_entities: set[str] = set()
            all_tags: set[str] = set()
            for m in members:
                all_entities |= sig_entities.get(m, set())
                all_tags |= sig_tags.get(m, set())

            top_terms = sorted(all_entities, key=len, reverse=True)[:3]
            auto_title = " · ".join(top_terms) if top_terms else sid

            # Посчитать momentum (сигналов за последние 6ч vs 24ч)
            dates = [s["first_seen"] for s in signals if s["uid"] in members]
            cutoff6 = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
            recent6 = sum(1 for d in dates if d and d >= cutoff6)
            momentum = round(recent6 / 6.0, 3)

            # Уникальные источники
            src_cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
            tickers_json = json.dumps(list(all_tags)[:6])

            # Статус lifecycle
            if momentum > 0.5:
                status = "peak"
            elif momentum > 0.1:
                status = "emerging"
            elif recent6 == 0:
                status = "dormant"
            else:
                status = "fading"

            existing = db.execute(
                "SELECT id, title FROM stories WHERE id=?", (sid,)
            ).fetchone()

            if existing:
                db.execute(
                    """UPDATE stories SET momentum=?, status=?, last_seen=?,
                       market_tickers=?, source_diversity=? WHERE id=?""",
                    (momentum, status, now, tickers_json,
                     len({s["uid"].split(":")[0] for s in signals if s["uid"] in members}),
                     sid)
                )
            else:
                db.execute(
                    """INSERT INTO stories
                       (id, title, status, momentum, source_diversity,
                        first_seen, last_seen, market_tickers)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (sid, auto_title, status, momentum,
                     len({s["uid"].split(":")[0] for s in signals if s["uid"] in members}),
                     now, now, tickers_json)
                )

            # Привязать сигналы
            for uid in members:
                db.execute(
                    "INSERT OR IGNORE INTO story_signals (story_id, signal_uid, added) VALUES (?,?,?)",
                    (sid, uid, now)
                )

        db.commit()

    return len([s for s in clusters.values() if len(s) >= 2])


def _apply_embeddings(signals, sig_entities, sig_tags, clusters, uid_to_story):
    """Склеить кластеры по косинусному сходству (если sentence-transformers доступен)."""
    from sentence_transformers import SentenceTransformer, util
    model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

    uid_to_text = {s["uid"]: f"{s['title']} {s['text']}" for s in signals}
    story_ids = list(clusters.keys())
    story_texts = [
        " ".join(sorted(sig_entities.get(m, set()))[:5] +
                 list(sig_tags.get(m, set()))[:3])
        for sid in story_ids
        for m in list(clusters[sid])[:1]
    ]
    if len(story_texts) < 2:
        return

    embeddings = model.encode(story_texts, convert_to_tensor=True)
    cos_scores = util.cos_sim(embeddings, embeddings)

    merged: dict[str, str] = {}
    for i in range(len(story_ids)):
        for j in range(i + 1, len(story_ids)):
            if float(cos_scores[i][j]) > 0.55:
                keep, drop = story_ids[i], story_ids[j]
                merged[drop] = keep

    for drop, keep in merged.items():
        if drop in clusters:
            clusters[keep] |= clusters.pop(drop)


def story_momentum(story_id: str) -> float:
    with _db() as db:
        row = db.execute("SELECT momentum FROM stories WHERE id=?", (story_id,)).fetchone()
    return float(row["momentum"]) if row else 0.0


def story_timeline(story_id: str) -> list[dict]:
    with _db() as db:
        return _rows(db.execute(
            """SELECT s.uid, s.author, s.title, s.text, s.first_seen, s.importance, s.source
               FROM signals s JOIN story_signals ss ON s.uid=ss.signal_uid
               WHERE ss.story_id=? ORDER BY s.first_seen""",
            (story_id,)
        ))


def active_stories(limit: int = 12) -> list[dict]:
    with _db() as db:
        return _rows(db.execute(
            """SELECT * FROM stories WHERE status != 'dormant'
               ORDER BY momentum * source_diversity DESC LIMIT ?""",
            (limit,)
        ))


def attach_market(story: dict) -> dict:
    from core.market import snapshot, reaction_around
    tickers = json.loads(story.get("market_tickers") or "[]")
    if tickers:
        story["market_snap"] = snapshot(tickers)
    else:
        story["market_snap"] = {}
    return story
