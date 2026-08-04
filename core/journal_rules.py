"""
journal_rules.py — Хранилище правил серии (ступень 7, глава 12, SPEC_edu_level12).

Правила фиксируются ДО начала счёта и неизменяемы внутри активной серии:
таблица не поддерживает UPDATE текста — единственный способ «изменить»
правила это start_series() заново, который деактивирует текущую строку и
вставляет новую с series_no+1 (счётчик обнуляется вместе с серией).
Подтверждение «ты точно хочешь начать заново» — забота фронтенда, делается
ДО вызова этой функции, не после.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from core import journal_db

_DB = Path(__file__).parent.parent / "data" / "journal.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_DB), timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def ensure_schema() -> None:
    c = _conn()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS system_rules (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      TEXT NOT NULL,
            series_no    INTEGER NOT NULL,
            rules_text   TEXT NOT NULL,
            started_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
            active       INTEGER NOT NULL DEFAULT 1,
            predict_pct  REAL,
            manual_count INTEGER NOT NULL DEFAULT 0,
            UNIQUE(user_id, series_no)
        );
        CREATE INDEX IF NOT EXISTS idx_rules_user_active ON system_rules(user_id, active);
    """)
    # Миграция для БД, где таблица уже была создана до появления manual_count.
    cols = {row["name"] for row in c.execute("PRAGMA table_info(system_rules)")}
    if "manual_count" not in cols:
        c.execute("ALTER TABLE system_rules ADD COLUMN manual_count INTEGER NOT NULL DEFAULT 0")
    c.commit()
    c.close()


def get_active_series(user_id: str) -> dict | None:
    c = _conn()
    row = c.execute(
        "SELECT * FROM system_rules WHERE user_id=? AND active=1 "
        "ORDER BY series_no DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    c.close()
    return dict(row) if row else None


def start_series(user_id: str, rules_text: str, predict_pct: float | None = None) -> dict:
    rules_text = (rules_text or "").strip()
    if not rules_text:
        return {"ok": False, "error": "Правила не могут быть пустыми"}
    if len(rules_text) > 2000:
        return {"ok": False, "error": "Слишком длинный текст правил"}

    c = _conn()
    c.execute("UPDATE system_rules SET active=0 WHERE user_id=? AND active=1", (user_id,))
    max_no = c.execute(
        "SELECT COALESCE(MAX(series_no),0) FROM system_rules WHERE user_id=?", (user_id,)
    ).fetchone()[0]
    new_no = max_no + 1
    c.execute(
        "INSERT INTO system_rules(user_id, series_no, rules_text, active, predict_pct) "
        "VALUES(?,?,?,1,?)",
        (user_id, new_no, rules_text, predict_pct),
    )
    c.commit()
    c.close()
    return {"ok": True, "series_no": new_no}


def tick_manual(user_id: str) -> dict:
    """Ручной счёт для «бумажной версии» (нет демо-счёта — §3.7 blocked)."""
    active = get_active_series(user_id)
    if not active:
        return {"ok": False, "error": "Нет активной серии"}
    c = _conn()
    c.execute(
        "UPDATE system_rules SET manual_count = manual_count + 1 WHERE user_id=? AND active=1",
        (user_id,),
    )
    c.commit()
    c.close()
    return {"ok": True}


def get_series_progress(user_id: str) -> dict:
    """
    §4.1/§4.3: автоматический счётчик считает только сделки close_ts >=
    started_at активной серии — импортированная задним числом история
    физически не может в него попасть, это следует из самого WHERE, а не
    из отдельной проверки.

    Без демо-счёта (has_account=False) автоматических сделок не бывает по
    определению — используется manual_count («бумажная версия», §3.7).
    """
    active = get_active_series(user_id)
    has_account = len(journal_db.list_investor_accounts(user_id)) > 0

    if not active:
        return {
            "status": "blocked" if not has_account else "not_yet",
            "series_no": None,
            "trade_count": 0,
            "target": 50,
            "has_account": has_account,
            "paper_mode": not has_account,
        }

    paper_mode = not has_account
    c = _conn()
    if paper_mode:
        trade_count = active["manual_count"]
    else:
        trade_count = c.execute(
            "SELECT COUNT(*) FROM trades WHERE user_id=? AND close_ts >= ?",
            (user_id, active["started_at"]),
        ).fetchone()[0]

    disc_rows = c.execute(
        """SELECT tde.criterion, tde.passed
           FROM trade_discipline_eval tde
           JOIN trades t ON t.id = tde.trade_id
           WHERE t.user_id=? AND t.close_ts >= ?""",
        (user_id, active["started_at"]),
    ).fetchall()
    c.close()

    discipline = None
    if disc_rows:
        total = len(disc_rows)
        passed = sum(1 for r in disc_rows if r["passed"])
        discipline = {
            "evaluated": total,
            "passed": passed,
            "off_system_pct": round((total - passed) / total * 100, 1),
        }

    status = "done" if trade_count >= 50 else "in_progress"
    return {
        "status": status,
        "series_no": active["series_no"],
        "rules_text": active["rules_text"],
        "started_at": active["started_at"],
        "predict_pct": active["predict_pct"],
        "trade_count": trade_count,
        "target": 50,
        "discipline": discipline,
        "has_account": has_account,
        "paper_mode": paper_mode,
    }


ensure_schema()
