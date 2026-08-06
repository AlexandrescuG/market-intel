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

from core.event_types import normalize_event_type

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
        # source='recognia_via_avatrade' — разовый бэкфилл 28 событий
        # (СПЕКА_календарь_и_движения_рынка.md §0/§2.3), только для внутренней
        # сверки методики (compare_recognia.py), не для показа. Их страны (BR,
        # MX, TR, KR, IE, HU, CZ) не входят ни в _TV_COUNTRIES (обычный сборщик
        # никогда их не подхватит), ни в event_instrument_map — то есть история
        # (event_key завязан на русский заголовок с зашитым месяцем, никогда не
        # повторится), волатильность и влияние для них физически недостижимы
        # НАВСЕГДА, не «пока нет данных». Показывать такую строку в общем
        # календаре — гарантированно сломанный UX, а не временная пустота.
        # is_primary — дедуп между источниками (СПЕКА_графики_и_починка_
        # календаря.md §3, calendar_pull.py::recompute_primary_flags). NULL
        # = ещё не пересчитано (до первого forward-цикла после миграции) —
        # показываем, а не прячем, честнее оставить дубль временно видимым,
        # чем спрятать событие, которое ещё не успели разметить.
        query = "SELECT * FROM econ_events WHERE source != 'recognia_via_avatrade' AND (is_primary IS NULL OR is_primary = 1)"
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
        rows = [dict(r) for r in con.execute(query, args).fetchall()]
        # event_type — та же нормализация, что уже отдаёт _handle_chart_events
        # для chart.html (не дублировать regex по-разному в двух местах);
        # calendar.html использует его для /api/chart/event-reaction (Волатильность/Влияние).
        for r in rows:
            r["event_type"] = normalize_event_type(r.get("indicator") or r.get("title") or "")
        return rows
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
