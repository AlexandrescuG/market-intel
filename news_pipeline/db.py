"""SQLite схема и хелперы для news_pipeline."""
from __future__ import annotations

import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "news_pipeline.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    kind           TEXT NOT NULL,       -- 'rss' | 'tg'
    ref            TEXT NOT NULL,       -- URL (rss) или username без @ (tg)
    category       TEXT DEFAULT 'general',
    lang           TEXT DEFAULT 'en',
    default_tags   TEXT DEFAULT '',
    trust          INTEGER DEFAULT 5,
    active         INTEGER DEFAULT 1,
    UNIQUE(kind, ref)
);

CREATE TABLE IF NOT EXISTS raw_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id  INTEGER NOT NULL,
    ext_id     TEXT NOT NULL,
    ts         INTEGER NOT NULL,
    title      TEXT DEFAULT '',
    body       TEXT DEFAULT '',
    url        TEXT DEFAULT '',
    lang       TEXT DEFAULT 'en',
    fetched_at INTEGER NOT NULL,
    UNIQUE(source_id, ext_id)
);
CREATE INDEX IF NOT EXISTS idx_raw_ts ON raw_items(ts DESC);

CREATE TABLE IF NOT EXISTS posts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    type         TEXT NOT NULL,          -- 'free_text'|'econ_release'|'upcoming'|'price_move'
    text         TEXT NOT NULL,
    source_id    INTEGER,
    url          TEXT DEFAULT '',
    content_hash TEXT UNIQUE,
    created_ts   INTEGER NOT NULL,
    posted_ts    INTEGER,
    status       TEXT DEFAULT 'queued'   -- 'queued'|'posted'|'skipped'
);
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);

CREATE TABLE IF NOT EXISTS price_triggers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument   TEXT NOT NULL,
    kind         TEXT NOT NULL,          -- 'round'|'week_hi'|'week_lo'|'pct'
    param        REAL NOT NULL,
    cooldown_min INTEGER DEFAULT 60
);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)
