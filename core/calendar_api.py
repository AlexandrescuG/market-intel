"""core/calendar_api.py — запросы к econ_events (bot.db), общие для /api/calendar/events
и build_brief_v2.py.

Вынесено из serve.py::_handle_calendar_api (SPEC_morning_brief_v2.md, Этап 0):
логика фильтрации не менялась, только параметризован лимит (был захардкожен
LIMIT 2000) и вызов стал переиспользуемым вне HTTP-хендлера.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")


def query_events(
    date: str | None = None,
    from_d: str | None = None,
    to_d: str | None = None,
    impact: str | None = None,
    country: str | None = None,
    symbols: str | None = None,
    limit: int = 2000,
) -> list[dict]:
    con = sqlite3.connect(str(_BOT_DB))
    con.row_factory = sqlite3.Row
    try:
        query = "SELECT * FROM econ_events WHERE 1=1"
        args: list = []
        if date:
            try:
                day_start = int(_dt.strptime(date, "%Y-%m-%d").replace(tzinfo=_tz.utc).timestamp())
                query += " AND (scheduled_ts >= ? AND scheduled_ts < ?" \
                         " OR scheduled_ts IS NULL AND ts_utc LIKE ?)"
                args.extend([day_start, day_start + 86400, f"{date}%"])
            except ValueError:
                query += " AND ts_utc LIKE ?"
                args.append(f"{date}%")
        elif from_d or to_d:
            if from_d:
                try:
                    ts = int(_dt.strptime(from_d, "%Y-%m-%d").replace(tzinfo=_tz.utc).timestamp())
                    query += " AND (scheduled_ts >= ? OR scheduled_ts IS NULL AND ts_utc >= ?)"
                    args.extend([ts, f"{from_d}T00:00:00"])
                except ValueError:
                    query += " AND ts_utc >= ?"
                    args.append(f"{from_d}T00:00:00")
            if to_d:
                try:
                    ts = int(_dt.strptime(to_d, "%Y-%m-%d").replace(tzinfo=_tz.utc).timestamp()) + 86400
                    query += " AND (scheduled_ts < ? OR scheduled_ts IS NULL AND ts_utc <= ?)"
                    args.extend([ts, f"{to_d}T23:59:59"])
                except ValueError:
                    query += " AND ts_utc <= ?"
                    args.append(f"{to_d}T23:59:59")
        if impact:
            query += " AND impact = ?"
            args.append(impact)
        if country:
            query += " AND country = ?"
            args.append(country)
        if symbols:
            syms = [s.upper().strip() for s in symbols.split(",") if s.strip()]
            if syms:
                placeholders = ",".join("?" * len(syms))
                query += f" AND country IN (SELECT country FROM event_instrument_map WHERE symbol IN ({placeholders}))"
                args.extend(syms)
        query += " ORDER BY COALESCE(scheduled_ts, 0) ASC LIMIT ?"
        args.append(int(limit))
        return [dict(r) for r in con.execute(query, args).fetchall()]
    finally:
        con.close()


def instruments_for_country(country: str, min_weight: int = 1) -> list[str]:
    """Символы, на которые влияет страна события, при заданном пороге weight
    (weight=2 — прямая FX-пара, weight=1 — косвенное влияние, см. serve.py:116-117)."""
    con = sqlite3.connect(str(_BOT_DB))
    try:
        rows = con.execute(
            "SELECT symbol FROM event_instrument_map WHERE country = ? AND weight >= ?",
            (country, min_weight),
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()
