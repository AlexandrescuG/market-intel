"""WP7 — Экономический календарь. FOMC, CPI, NFP, ECB, PMI.

Источник: Investing.com scrape (fallback) или FMP free API.

🔴 DEPRECATED (СПЕКА_календарь_и_движения_рынка.md §2): не канонично и не
вызывается ниоткуда в проекте. Таблица `calendar` (signals.db), которую пишет
collect_calendar(), пуста и не читается — реальный календарь живёт в таблице
econ_events (SBFAcademy_bot/bot.db), наполняется calendar_pull.py
(Forexfactory + TradingView, работает непрерывным потоком внутри
sbf-web.service) и отдаётся через core/calendar_api.py (/api/calendar/events)
и build_brief_v2.py. _fetch_scrape() ниже к тому же никогда не работал —
возвращает [] безусловно. Файл оставлен как есть (не удалён) на случай, если
FMP-ключ появится и понадобится альтернативный источник — но перед
использованием сверить с econ_events, не подключать вслепую.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone

import httpx

from core.config import DB_PATH

log = logging.getLogger("calendar")

_FMP_BASE = "https://financialmodelingprep.com/api/v3"

# Ключевые события для фильтра
_KEYWORDS = {
    "fomc", "federal reserve", "cpi", "ppi", "nonfarm", "nfp", "gdp",
    "unemployment", "ecb", "boe", "boj", "pmi", "retail sales", "jobless",
    "fed", "interest rate", "inflation", "payroll",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    return sqlite3.connect(DB_PATH)


def _is_important(name: str) -> bool:
    nl = name.lower()
    return any(k in nl for k in _KEYWORDS)


def collect_calendar(days_ahead: int = 7) -> int:
    """Обновить события на ближайшие days_ahead дней. Вернуть кол-во добавленных."""
    import os
    fmp_key = os.getenv("FMP_API_KEY", "")
    events = []

    if fmp_key:
        events = _fetch_fmp(fmp_key, days_ahead)
    else:
        events = _fetch_scrape(days_ahead)

    if not events:
        log.warning("calendar: нет данных")
        return 0

    added = 0
    with _db() as db:
        for e in events:
            eid = hashlib.md5(f"{e['date']}{e['name']}".encode()).hexdigest()[:16]
            try:
                db.execute(
                    """INSERT OR IGNORE INTO calendar
                       (id, event_date, name, importance, forecast, previous,
                        actual, country, currency, url, resolved)
                       VALUES (?,?,?,?,?,?,?,?,?,?,0)""",
                    (eid, e["date"], e["name"], e.get("importance", 1),
                     e.get("forecast"), e.get("previous"), e.get("actual"),
                     e.get("country", ""), e.get("currency", ""), e.get("url", ""))
                )
                if db.execute("SELECT changes()").fetchone()[0]:
                    added += 1
            except Exception as ex:
                log.debug("calendar insert: %s", ex)
        db.commit()

    return added


def _fetch_fmp(api_key: str, days: int) -> list[dict]:
    today = datetime.now(timezone.utc).date()
    end = today + timedelta(days=days)
    try:
        resp = httpx.get(
            f"{_FMP_BASE}/economic_calendar",
            params={"from": today.isoformat(), "to": end.isoformat(), "apikey": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        raw = resp.json()
        return [
            {
                "date": e.get("date", "")[:16],
                "name": e.get("event", ""),
                "importance": {"High": 3, "Medium": 2, "Low": 1}.get(e.get("impact", ""), 1),
                "forecast": e.get("estimate"),
                "previous": e.get("previous"),
                "actual": e.get("actual"),
                "country": e.get("country", ""),
                "currency": e.get("currency", ""),
            }
            for e in raw if _is_important(e.get("event", ""))
        ]
    except Exception as e:
        log.warning("FMP calendar: %s", e)
        return []


def _fetch_scrape(days: int) -> list[dict]:
    """Fallback: Investing.com economic calendar (упрощённый)."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; SBFBot/1.0)"}
        resp = httpx.get(
            "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData",
            data={"timeZone": "55", "dateFrom": "", "dateTo": "", "currentTab": "thisWeek"},
            headers=headers, timeout=15,
        )
        # Investing.com возвращает HTML — только базовые события из RSS как fallback
        return []
    except Exception:
        return []


def upcoming(hours: int = 72) -> list[dict]:
    cutoff = datetime.now(timezone.utc).isoformat()
    horizon = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    with _db() as db:
        try:
            cur = db.execute(
                """SELECT id, event_date, name, importance, forecast, previous,
                          actual, country, currency
                   FROM calendar WHERE event_date >= ? AND event_date <= ?
                   AND importance >= 2
                   ORDER BY event_date""",
                (cutoff[:16], horizon[:16])
            )
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        except Exception:
            return []


def resolve_past_events() -> int:
    """Пометить прошедшие события; добавить реакцию рынка где возможно."""
    now = datetime.now(timezone.utc).isoformat()[:16]
    resolved = 0
    with _db() as db:
        try:
            past = db.execute(
                "SELECT id, event_date, name FROM calendar WHERE event_date < ? AND resolved=0",
                (now,)
            ).fetchall()
            for eid, edate, name in past:
                # Попытаться получить реакцию рынка (S&P 500 вокруг события)
                market_move = None
                try:
                    from core.market import reaction_around
                    when = datetime.fromisoformat(edate)
                    r = reaction_around("^GSPC", when, window_min=120)
                    if r:
                        market_move = r.get("move_pct")
                except Exception:
                    pass
                db.execute(
                    "UPDATE calendar SET resolved=1, market_move=? WHERE id=?",
                    (market_move, eid)
                )
                resolved += 1
            db.commit()
        except Exception as e:
            log.debug("resolve_past_events: %s", e)
    return resolved
