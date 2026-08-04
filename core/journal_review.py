"""
journal_review.py — Еженедельный ревью (Weekly Review, §3).

Воскресный ритуал разбора недели. +75 XP за завершённое ревью.
Ревью открыто с пятницы 18:00 до конца вторника следующей недели.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DB = Path(__file__).parent.parent / "data" / "journal.db"

_MIN_REFLECTION_LEN = 20
_REVIEW_XP = 75
_REVIEW_STREAK_BADGE = "analyst_weekly"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_DB), timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def ensure_schema() -> None:
    c = _conn()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS weekly_reviews (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         TEXT NOT NULL DEFAULT 'default',
            week_iso        TEXT NOT NULL,
            best_trade_id   INTEGER,
            worst_trade_id  INTEGER,
            reflection      TEXT NOT NULL DEFAULT '',
            discipline_pct  REAL,
            tilt_episodes   INTEGER NOT NULL DEFAULT 0,
            trades_count    INTEGER NOT NULL DEFAULT 0,
            sum_r           REAL NOT NULL DEFAULT 0.0,
            created_ts      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
            UNIQUE(user_id, week_iso)
        );
    """)
    c.commit()
    c.close()


def _current_week_iso() -> str:
    """Текущая неделя в формате YYYY-Www."""
    now = datetime.now(timezone.utc)
    return now.strftime("%G-W%V")


def _week_bounds_utc(week_iso: str) -> tuple[datetime, datetime]:
    """Начало и конец недели (пн–вс) в UTC."""
    year, week = week_iso.split("-W")
    # ISO-неделя начинается с понедельника
    dt = datetime.strptime(f"{year}-W{week}-1", "%G-W%V-%u")
    start = dt.replace(tzinfo=timezone.utc)
    end   = start + timedelta(days=7)
    return start, end


def is_review_open(tz_offset_min: int = 120) -> bool:
    """
    Ревью открыто с пятницы 18:00 до конца вторника следующей недели.
    tz_offset_min — смещение пользователя от UTC (default UTC+2).
    """
    now_local = datetime.now(timezone.utc) + timedelta(minutes=tz_offset_min)
    dow = now_local.weekday()  # 0=пн, 4=пт, 5=сб, 6=вс, 1=вт
    hour = now_local.hour
    # Пятница 18:00+, суббота, воскресенье, понедельник, вторник
    if dow == 4 and hour >= 18:
        return True
    if dow in (5, 6, 0):
        return True
    if dow == 1:  # вторник — до конца дня
        return True
    return False


def get_auto_stats(user_id: str = "default", week_iso: str | None = None) -> dict:
    """Автозаполнение статистики за неделю."""
    if week_iso is None:
        week_iso = _current_week_iso()
    try:
        start, end = _week_bounds_utc(week_iso)
    except Exception:
        return {}

    start_s = start.strftime("%Y-%m-%dT%H:%M:%S")
    end_s   = end.strftime("%Y-%m-%dT%H:%M:%S")

    c = _conn()

    trades = c.execute(
        """SELECT id, pnl_r, close_ts FROM trades
           WHERE user_id=? AND close_ts >= ? AND close_ts < ?
           ORDER BY pnl_r""",
        (user_id, start_s, end_s),
    ).fetchall()

    # Лучшая/худшая по R
    best_id  = trades[-1]["id"] if trades else None
    worst_id = trades[0]["id"]  if trades else None
    sum_r    = sum(t["pnl_r"] for t in trades)
    count    = len(trades)

    # Тильт-эпизоды за неделю
    tilt_count = c.execute(
        "SELECT COUNT(*) FROM tilt_events WHERE user_id=? AND detected_at >= ? AND detected_at < ?",
        (user_id, start_s, end_s),
    ).fetchone()[0]

    # Дисциплина %
    disc_row = c.execute(
        """SELECT AVG(CASE WHEN passed=1 THEN 100.0 ELSE 0.0 END) AS pct
           FROM trade_discipline_eval tde
           JOIN trades t ON t.id = tde.trade_id
           WHERE t.user_id=? AND t.close_ts >= ? AND t.close_ts < ?""",
        (user_id, start_s, end_s),
    ).fetchone()
    disc_pct = round(disc_row["pct"] or 0, 1) if disc_row else None

    c.close()

    return {
        "week_iso":       week_iso,
        "trades_count":   count,
        "sum_r":          round(sum_r, 2),
        "best_trade_id":  best_id,
        "worst_trade_id": worst_id,
        "tilt_episodes":  tilt_count,
        "discipline_pct": disc_pct,
        "is_open":        is_review_open(),
    }


def get_this_week_review(user_id: str = "default") -> dict | None:
    """Вернуть ревью текущей недели если оно уже есть."""
    week_iso = _current_week_iso()
    c = _conn()
    row = c.execute(
        "SELECT * FROM weekly_reviews WHERE user_id=? AND week_iso=?",
        (user_id, week_iso),
    ).fetchone()
    c.close()
    return dict(row) if row else None


def submit_review(
    user_id: str = "default",
    week_iso: str | None = None,
    reflection: str = "",
    best_trade_id: int | None = None,
    worst_trade_id: int | None = None,
) -> dict:
    """Сохранить завершённое ревью. +75 XP. 409 если уже есть за эту неделю."""
    if week_iso is None:
        week_iso = _current_week_iso()
    reflection = (reflection or "").strip()
    if len(reflection) < _MIN_REFLECTION_LEN:
        return {
            "error": f"Рефлексия должна быть не менее {_MIN_REFLECTION_LEN} символов. "
                     f"Напиши что изменишь на этой неделе.",
            "status": 422,
        }

    stats = get_auto_stats(user_id, week_iso)

    c = _conn()
    try:
        c.execute(
            """INSERT INTO weekly_reviews
               (user_id, week_iso, best_trade_id, worst_trade_id, reflection,
                discipline_pct, tilt_episodes, trades_count, sum_r)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                user_id, week_iso,
                best_trade_id or stats.get("best_trade_id"),
                worst_trade_id or stats.get("worst_trade_id"),
                reflection,
                stats.get("discipline_pct"),
                stats.get("tilt_episodes", 0),
                stats.get("trades_count", 0),
                stats.get("sum_r", 0.0),
            ),
        )
        c.commit()
    except sqlite3.IntegrityError:
        c.close()
        return {"error": "Ревью за эту неделю уже существует", "status": 409}
    c.close()

    # XP
    try:
        from . import journal_gamification
        journal_gamification.award_xp("weekly_review", _REVIEW_XP, user_id=user_id)
    except Exception:
        pass

    # Обновить стрик ревью в user_prefs
    _update_review_streak(user_id)

    return {"ok": True, "week_iso": week_iso, "xp_awarded": _REVIEW_XP}


def _update_review_streak(user_id: str) -> None:
    """Проверить стрик ревью: 4 подряд → значок."""
    c = _conn()
    # Подсчитать подряд идущие недели с ревью
    rows = c.execute(
        "SELECT week_iso FROM weekly_reviews WHERE user_id=? ORDER BY week_iso DESC LIMIT 8",
        (user_id,),
    ).fetchall()
    c.close()

    streak = 0
    weeks = [r["week_iso"] for r in rows]
    for i, w in enumerate(weeks):
        if i == 0:
            streak = 1
            continue
        # Проверить что недели идут подряд
        try:
            y1, wn1 = weeks[i - 1].split("-W")
            y0, wn0 = w.split("-W")
            dt1 = datetime.strptime(f"{y1}-W{wn1}-1", "%G-W%V-%u")
            dt0 = datetime.strptime(f"{y0}-W{wn0}-1", "%G-W%V-%u")
            if (dt1 - dt0).days == 7:
                streak += 1
            else:
                break
        except Exception:
            break

    if streak >= 4:
        try:
            from . import journal_gamification
            journal_gamification.unlock_achievement(_REVIEW_STREAK_BADGE, user_id)
        except Exception:
            pass


def get_reviews(user_id: str = "default", limit: int = 52) -> list[dict]:
    """Список прошлых ревью."""
    c = _conn()
    rows = c.execute(
        "SELECT * FROM weekly_reviews WHERE user_id=? ORDER BY week_iso DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_prev_reflection(user_id: str = "default") -> str | None:
    """Рефлексия прошлой недели для отображения в начале нового ревью."""
    reviews = get_reviews(user_id, limit=2)
    if len(reviews) >= 2:
        return reviews[1].get("reflection")
    return None


ensure_schema()
