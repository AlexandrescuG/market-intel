"""
journal_tradeplan.py — План сделки, записанный ДО открытия позиции (глава 13,
§3.6 SPEC_edu_level13_swing_pyramiding.md).

Отдельная таблица, а не journal_meta: journal_meta прикрепляется к уже
существующей сделке (обязательный trade_id), а план по определению пишется
раньше, чем сделка появляется в журнале.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

_DB = Path(__file__).parent.parent / "data" / "journal.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_DB), timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def ensure_schema() -> None:
    c = _conn()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS trade_plans (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    TEXT NOT NULL,
            plan_text  TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_tradeplans_user ON trade_plans(user_id, created_at DESC);
    """)
    c.commit()
    c.close()


def save_plan(user_id: str, plan_text: str) -> dict:
    plan_text = (plan_text or "").strip()
    if not plan_text:
        return {"ok": False, "error": "План не может быть пустым"}
    if len(plan_text) > 4000:
        return {"ok": False, "error": "Слишком длинный текст плана"}
    c = _conn()
    cur = c.execute(
        "INSERT INTO trade_plans(user_id, plan_text) VALUES(?,?)",
        (user_id, plan_text),
    )
    c.commit()
    c.close()
    return {"ok": True, "id": cur.lastrowid}


def list_plans(user_id: str, limit: int = 20) -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT id, plan_text, created_at FROM trade_plans WHERE user_id=? "
        "ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


ensure_schema()
