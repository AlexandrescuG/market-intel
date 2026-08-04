"""
journal_cooldown.py — Добровольный стоп-день после тильта (Cooldown, §4).

Механика harm reduction: предложение → пользователь выбирает → cooldown до полуночи.
Нарушенный cooldown — без штрафа XP и без стыдящих сообщений.
Lazy-проверка полуночи: при первом запросе нового дня.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DB = Path(__file__).parent.parent / "data" / "journal.db"

_COOLDOWN_XP = 150
_DEBRIEF_XP  = 30
_DEBRIEF_MIN_LEN = 10

_TILT_TRIGGERS = frozenset({"loss_streak", "stop_revenge_reentry"})

# Формулировки — наблюдательный тон, без осуждения
_TRIGGER_MSG = {
    "loss_streak":
        "Статистически зафиксирована серия сделок с отрицательным R. "
        "После таких серий паттерн ухудшения качества решений встречается чаще. "
        "Хочешь активировать стоп на сегодня?",
    "stop_revenge_reentry":
        "Зафиксирован повторный вход в рынок в течение короткого времени после закрытия позиции. "
        "Это паттерн, который статистически коррелирует со снижением качества решений. "
        "Хочешь активировать стоп на сегодня?",
}


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_DB), timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def ensure_schema() -> None:
    c = _conn()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS cooldowns (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       TEXT NOT NULL DEFAULT 'default',
            trigger_alert TEXT NOT NULL,
            started_ts    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
            until_ts      TEXT NOT NULL,
            status        TEXT NOT NULL DEFAULT 'active'
                          CHECK(status IN ('active','completed','broken')),
            debrief       TEXT,
            debrief_ts    TEXT
        );
        CREATE TABLE IF NOT EXISTS tilt_debriefs (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id  TEXT NOT NULL DEFAULT 'default',
            alert_id INTEGER,
            q1       TEXT NOT NULL DEFAULT '',
            q2       TEXT NOT NULL DEFAULT '',
            q3       TEXT NOT NULL DEFAULT '',
            ts       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_cooldowns_user ON cooldowns(user_id, status);
        CREATE INDEX IF NOT EXISTS idx_debriefs_user  ON tilt_debriefs(user_id);
    """)
    c.commit()
    c.close()


def _midnight_utc(tz_offset_min: int = 120) -> str:
    """Полночь по TZ пользователя (следующая, от сейчас), возвращает UTC ISO."""
    now_local = datetime.now(timezone.utc) + timedelta(minutes=tz_offset_min)
    midnight_local = (now_local + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    midnight_utc = midnight_local - timedelta(minutes=tz_offset_min)
    return midnight_utc.strftime("%Y-%m-%dT%H:%M:%S")


def accept_cooldown(
    user_id: str = "default",
    alert_id: int | None = None,
    trigger: str = "loss_streak",
    tz_offset_min: int = 120,
) -> dict:
    """Пользователь принял предложение стоп-дня."""
    if trigger not in _TILT_TRIGGERS:
        trigger = "loss_streak"
    until_ts = _midnight_utc(tz_offset_min)
    c = _conn()
    # Проверить нет ли уже активного
    existing = c.execute(
        "SELECT id FROM cooldowns WHERE user_id=? AND status='active'", (user_id,)
    ).fetchone()
    if existing:
        c.close()
        return {"ok": True, "existing": True, "cooldown_id": existing["id"]}
    cur = c.execute(
        "INSERT INTO cooldowns(user_id, trigger_alert, until_ts) VALUES(?,?,?)",
        (user_id, trigger, until_ts),
    )
    cid = cur.lastrowid
    c.commit()
    c.close()
    return {"ok": True, "cooldown_id": cid, "until_ts": until_ts}


def reject_cooldown(user_id: str = "default", alert_id: int | None = None) -> dict:
    """Пользователь отказался от стоп-дня — просто логируем."""
    # Не делаем ничего карательного — просто факт
    return {"ok": True, "accepted": False}


def get_active_cooldown(user_id: str = "default") -> dict | None:
    """Вернуть активный cooldown или None."""
    _lazy_complete_check(user_id)
    c = _conn()
    row = c.execute(
        "SELECT * FROM cooldowns WHERE user_id=? AND status='active' ORDER BY started_ts DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    c.close()
    return dict(row) if row else None


def mark_broken(user_id: str = "default") -> dict:
    """
    Сделка записана в период cooldown — помечаем как broken.
    Без штрафа XP. Без стыдящих сообщений.
    """
    c = _conn()
    c.execute(
        "UPDATE cooldowns SET status='broken' WHERE user_id=? AND status='active'",
        (user_id,),
    )
    c.commit()
    c.close()
    return {"ok": True, "status": "broken"}


def _lazy_complete_check(user_id: str) -> None:
    """
    Lazy-проверка: при запросе нового дня завершить активные cooldown
    которые прошли полночь (до них не записывали сделок → completed).
    """
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    c = _conn()
    to_complete = c.execute(
        "SELECT id FROM cooldowns WHERE user_id=? AND status='active' AND until_ts <= ?",
        (user_id, now_utc),
    ).fetchall()
    if to_complete:
        ids = [r["id"] for r in to_complete]
        c.execute(
            f"UPDATE cooldowns SET status='completed' WHERE id IN ({','.join('?'*len(ids))})",
            ids,
        )
        c.commit()
        # +150 XP за каждый соблюдённый cooldown
        for _ in to_complete:
            try:
                from . import journal_gamification
                journal_gamification.award_xp("cooldown_honored", _COOLDOWN_XP, user_id=user_id)
            except Exception:
                pass
        # Обновить счётчик
        c.execute(
            """UPDATE user_prefs
               SET cooldowns_honored = COALESCE(cooldowns_honored, 0) + ?
               WHERE user_id=?""",
            (len(to_complete), user_id),
        )
        c.commit()
    c.close()


def submit_debrief(
    user_id: str = "default",
    alert_id: int | None = None,
    q1: str = "",
    q2: str = "",
    q3: str = "",
) -> dict:
    """Сохранить дебрифинг тильт-эпизода. +30 XP. Минимум 10 символов на поле."""
    for field, value in [("q1", q1), ("q2", q2), ("q3", q3)]:
        if len((value or "").strip()) < _DEBRIEF_MIN_LEN:
            return {
                "error": f"Поле «{field}» должно содержать не менее {_DEBRIEF_MIN_LEN} символов",
                "status": 422,
            }
    c = _conn()
    c.execute(
        "INSERT INTO tilt_debriefs(user_id, alert_id, q1, q2, q3) VALUES(?,?,?,?,?)",
        (user_id, alert_id, q1.strip(), q2.strip(), q3.strip()),
    )
    c.commit()
    c.close()

    try:
        from . import journal_gamification
        journal_gamification.award_xp("tilt_debrief", _DEBRIEF_XP, user_id=user_id)
    except Exception:
        pass

    return {"ok": True, "xp_awarded": _DEBRIEF_XP}


def get_debriefs(user_id: str = "default", limit: int = 50) -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT * FROM tilt_debriefs WHERE user_id=? ORDER BY ts DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_cooldown_stats(user_id: str = "default") -> dict:
    """Статистика cooldown-ов: соблюдено / нарушено / всего."""
    c = _conn()
    rows = c.execute(
        "SELECT status, COUNT(*) AS cnt FROM cooldowns WHERE user_id=? GROUP BY status",
        (user_id,),
    ).fetchall()
    c.close()
    stats = {r["status"]: r["cnt"] for r in rows}
    total     = sum(stats.values())
    honored   = stats.get("completed", 0)
    broken    = stats.get("broken", 0)
    return {
        "total":   total,
        "honored": honored,
        "broken":  broken,
        "label":   f"Стоп-дней соблюдено: {honored} из {total}" if total else "Нет стоп-дней",
    }


def get_cooldown_prompt(trigger: str) -> str:
    """Текст предложения cooldown для фронтенда."""
    return _TRIGGER_MSG.get(trigger, _TRIGGER_MSG["loss_streak"])


# Добавить колонку cooldowns_honored в user_prefs если не существует
def _migrate() -> None:
    c = _conn()
    for ddl in [
        "ALTER TABLE user_prefs ADD COLUMN cooldowns_honored INTEGER NOT NULL DEFAULT 0",
    ]:
        try:
            c.execute(ddl)
            c.commit()
        except Exception:
            pass
    c.close()


ensure_schema()
_migrate()
