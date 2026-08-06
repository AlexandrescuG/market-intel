"""
journal_gate.py — ступень 9 (глава 14, реальный счёт после арифметики).
SPEC_edu_level14_scalping_costs.md §3.7, состав условий — HANDOVER_SBF.md §7.2
(разрешение расхождения 1: четыре машинно-проверяемых условия, не декларация).

Условия:
  trades   — 50 сделок в активной серии главы 12 (journal_rules)
  weeks    — 4 различные ISO-недели среди сделок этой серии
  system   — правила серии записаны (есть активная серия)
  math     — калькулятор издержек §3.2 пройден до конца (флаг, эта таблица)

Ступень 9 НЕ раскрывает реального брокера при выполнении условий. На момент
написания partners.json не существовал (см. ch11 — ступень 6 отложена по той
же причине); с 06.08.2026 файл существует (927 строк, пять партнёров, страница
/brokers), но раскрытие `<PartnerBridge tier="live">` из родительской спеки
всё ещё не реализовано — ladder-инфраструктура отложена отдельным решением
владельца (см. project_edu_ladder_compliance_ch14_15 в координационном логе),
не техническим отсутствием данных. Честная заглушка остаётся намеренной.
Сама проверка условий, в отличие от брокерского раскрытия, не зависит от
партнёрских данных и потому реализована по-настоящему.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from core import journal_db, journal_rules

_DB = Path(__file__).parent.parent / "data" / "journal.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_DB), timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def ensure_schema() -> None:
    c = _conn()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS gate_flags (
            user_id  TEXT NOT NULL,
            flag_key TEXT NOT NULL,
            set_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
            PRIMARY KEY (user_id, flag_key)
        );
    """)
    c.commit()
    c.close()


def set_flag(user_id: str, flag_key: str) -> dict:
    c = _conn()
    c.execute(
        "INSERT OR REPLACE INTO gate_flags(user_id, flag_key) VALUES(?,?)",
        (user_id, flag_key),
    )
    c.commit()
    c.close()
    return {"ok": True}


def get_flag(user_id: str, flag_key: str) -> bool:
    c = _conn()
    row = c.execute(
        "SELECT 1 FROM gate_flags WHERE user_id=? AND flag_key=?",
        (user_id, flag_key),
    ).fetchone()
    c.close()
    return row is not None


def _weeks_active(user_id: str, started_at: str) -> int:
    c = _conn()
    rows = c.execute(
        "SELECT DISTINCT strftime('%Y-%W', close_ts) AS wk FROM trades "
        "WHERE user_id=? AND close_ts >= ?",
        (user_id, started_at),
    ).fetchall()
    c.close()
    return len(rows)


def get_gate_status(user_id: str = "default") -> dict:
    series = journal_rules.get_series_progress(user_id)
    has_series = series.get("series_no") is not None

    trades_n = series.get("trade_count", 0)
    weeks_n = _weeks_active(user_id, series["started_at"]) if has_series else 0
    system_ok = has_series
    math_ok = get_flag(user_id, "risk_math_completed")

    conditions = {
        "trades": {"need": 50, "have": trades_n, "ok": trades_n >= 50},
        "weeks": {"need": 4, "have": weeks_n, "ok": weeks_n >= 4},
        "system": {"need": 1, "have": int(system_ok), "ok": system_ok},
        "math": {"need": 1, "have": int(math_ok), "ok": math_ok},
    }
    all_ok = all(c["ok"] for c in conditions.values())
    return {"conditions": conditions, "all_ok": all_ok}


ensure_schema()
