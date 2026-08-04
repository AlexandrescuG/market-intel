"""
journal_tilt.py — Пре-трейд ритуал и детектор тильта (Part 7).

Таблицы (journal.db):
  checklist_items  — пункты чек-листа
  checklist_runs   — пройденные прогоны
  tilt_events      — лог срабатываний детектора
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DB = Path(__file__).parent.parent / "data" / "journal.db"

COOLDOWN_MINUTES = 60

REASON_NUDGES: dict[str, str] = {
    "loss_streak":          "Зафиксирована серия убыточных сделок. Рекомендуется сделать паузу и пересмотреть тезис.",
    "volume_escalation":    "Объём последней позиции значительно превысил средний. Позаботьтесь о своём капитале.",
    "high_frequency_frenzy":"Индикаторы фиксируют высокую частоту сделок. Позаботьтесь о своём капитале — сделайте короткую паузу.",
    "stop_revenge_reentry": "Зафиксирован быстрый повторный вход после закрытия позиции. Рекомендуется сделать паузу.",
}

DEFAULT_CHECKLIST = [
    "Есть чёткий тезис для входа в позицию",
    "Уровень стоп-лосса определён до открытия сделки",
    "Риск на сделку не превышает допустимый предел",
    "Вход соответствует торговому плану, не импульсу",
    "Проверен старший таймфрейм (H4 или выше)",
]


def _get_conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_schema() -> None:
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS checklist_items (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    TEXT NOT NULL DEFAULT 'default',
            text       TEXT NOT NULL,
            is_enabled INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_checklist_items_user
            ON checklist_items(user_id, is_enabled);

        CREATE TABLE IF NOT EXISTS checklist_runs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      TEXT NOT NULL DEFAULT 'default',
            passed       INTEGER NOT NULL DEFAULT 0,
            checked_ids  TEXT NOT NULL DEFAULT '[]',
            trade_id     INTEGER REFERENCES trades(id) ON DELETE SET NULL,
            completed_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_checklist_runs_user
            ON checklist_runs(user_id, completed_at);

        CREATE TABLE IF NOT EXISTS tilt_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT NOT NULL DEFAULT 'default',
            reason      TEXT NOT NULL,
            detected_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_tilt_events_user
            ON tilt_events(user_id, detected_at);
    """)
    conn.commit()

    # Seed default items for new users
    existing = conn.execute(
        "SELECT COUNT(*) FROM checklist_items WHERE user_id='default'"
    ).fetchone()[0]
    if existing == 0:
        for i, text in enumerate(DEFAULT_CHECKLIST):
            conn.execute(
                "INSERT INTO checklist_items (user_id, text, sort_order) VALUES ('default',?,?)",
                (text, i),
            )
        conn.commit()

    conn.close()


# ── Checklist CRUD ────────────────────────────────────────────────────────────

def get_checklist_items(user_id: str = "default") -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, text, is_enabled, sort_order FROM checklist_items WHERE user_id=? ORDER BY sort_order, id",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_checklist_item(text: str, user_id: str = "default") -> dict:
    conn = _get_conn()
    max_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) FROM checklist_items WHERE user_id=?", (user_id,)
    ).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO checklist_items (user_id, text, sort_order) VALUES (?,?,?)",
        (user_id, text[:200], max_order + 1),
    )
    conn.commit()
    item_id = cur.lastrowid
    conn.close()
    return {"id": item_id, "text": text, "is_enabled": 1, "sort_order": max_order + 1}


def toggle_checklist_item(item_id: int, user_id: str = "default") -> bool:
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE checklist_items SET is_enabled = 1 - is_enabled WHERE id=? AND user_id=?",
        (item_id, user_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def delete_checklist_item(item_id: int, user_id: str = "default") -> bool:
    conn = _get_conn()
    cur = conn.execute(
        "DELETE FROM checklist_items WHERE id=? AND user_id=?", (item_id, user_id)
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# ── Checklist Runs ────────────────────────────────────────────────────────────

def save_checklist_run(
    checked_ids: list[int],
    user_id: str = "default",
) -> dict:
    """Сохраняет прогон чек-листа. passed = True если все enabled-пункты отмечены."""
    import json

    conn = _get_conn()
    enabled_ids = [
        r["id"] for r in conn.execute(
            "SELECT id FROM checklist_items WHERE user_id=? AND is_enabled=1", (user_id,)
        ).fetchall()
    ]
    passed = bool(enabled_ids) and all(eid in checked_ids for eid in enabled_ids)

    cur = conn.execute(
        "INSERT INTO checklist_runs (user_id, passed, checked_ids) VALUES (?,?,?)",
        (user_id, int(passed), json.dumps(checked_ids)),
    )
    run_id = cur.lastrowid
    conn.commit()

    # XP: checklist_completed — пишем в xp_events если таблица существует
    try:
        if passed:
            conn.execute(
                "INSERT INTO xp_events (user_id, kind, amount, ref_id) VALUES (?,?,?,?)",
                (user_id, "checklist_completed", 15, run_id),
            )
            conn.commit()
    except Exception:
        pass

    conn.close()
    return {"id": run_id, "passed": passed, "checked_ids": checked_ids}


def get_recent_run(user_id: str = "default", within_minutes: int = 15) -> dict | None:
    """Последний прогон в пределах N минут — для автолинковки со сделкой."""
    cutoff = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    conn = _get_conn()
    row = conn.execute(
        """SELECT id, passed, completed_at FROM checklist_runs
           WHERE user_id=? AND completed_at >= datetime(?, '-' || ? || ' minutes')
           ORDER BY completed_at DESC LIMIT 1""",
        (user_id, cutoff, within_minutes),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)


def link_run_to_trade(run_id: int, trade_id: int, user_id: str = "default") -> bool:
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE checklist_runs SET trade_id=? WHERE id=? AND user_id=?",
        (trade_id, run_id, user_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# ── Tilt Detection Engine (§7.2) ──────────────────────────────────────────────

def _parse_ts_ms(s: str | None) -> float:
    """ISO/SQLite datetime → milliseconds. Returns 0 on failure."""
    if not s:
        return 0.0
    s = str(s).replace(" ", "T").rstrip("Z")
    if "+" in s:
        s = s.split("+")[0]
    fmts = ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d"]
    for fmt in fmts:
        try:
            return datetime.strptime(s[:len(fmt) + 4], fmt).replace(
                tzinfo=timezone.utc
            ).timestamp() * 1000
        except ValueError:
            continue
    return 0.0


def analyze_tilt_state(recent_trades: list[dict]) -> dict:
    """
    Точный порт алгоритма §7.2. recent_trades — хронологически любой порядок,
    сортируем внутри. Минимум 3 сделки для анализа.
    """
    if len(recent_trades) < 3:
        return {"is_tilt_detected": False, "reasons": []}

    sorted_t = sorted(recent_trades, key=lambda t: _parse_ts_ms(t.get("open_ts")))
    total = len(sorted_t)
    reasons: list[str] = []

    # 1. Loss streak — последние 3 в минус
    if all((t.get("pnl") or 0) < 0 for t in sorted_t[-3:]):
        reasons.append("loss_streak")

    # 2. Volume escalation — последняя сделка в убыток с объёмом > среднего × 1.5
    last_t = sorted_t[-1]
    prev_ts = sorted_t[:-1]
    sizes = [(t.get("size") or 0) for t in prev_ts]
    if sizes:
        avg_size = sum(sizes) / len(sizes)
        if (last_t.get("pnl") or 0) < 0 and (last_t.get("size") or 0) > avg_size * 1.5:
            reasons.append("volume_escalation")

    # 3. High frequency — ≥2 пар с интервалом close→open < 5 мин
    freq_matches = 0
    for i in range(1, total):
        gap_ms = _parse_ts_ms(sorted_t[i].get("open_ts")) - _parse_ts_ms(sorted_t[i - 1].get("close_ts"))
        gap_min = gap_ms / 60_000
        if 0 < gap_min < 5:
            freq_matches += 1
    if freq_matches >= 2:
        reasons.append("high_frequency_frenzy")

    # 4. Revenge reentry — тот же инструмент, вход < 3 мин после предыдущего стопа
    if total >= 2:
        prev_t = sorted_t[-2]
        if (prev_t.get("pnl") or 0) < 0 and last_t.get("symbol") == prev_t.get("symbol"):
            reentry_ms = _parse_ts_ms(last_t.get("open_ts")) - _parse_ts_ms(prev_t.get("close_ts"))
            reentry_min = reentry_ms / 60_000
            if 0 < reentry_min < 3:
                reasons.append("stop_revenge_reentry")

    return {"is_tilt_detected": len(reasons) > 0, "reasons": reasons}


def record_tilt_events(reasons: list[str], user_id: str = "default") -> None:
    if not reasons:
        return
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    conn = _get_conn()
    for reason in reasons:
        conn.execute(
            "INSERT INTO tilt_events (user_id, reason, detected_at) VALUES (?,?,?)",
            (user_id, reason, now),
        )
    conn.commit()
    conn.close()


def run_tilt_check(user_id: str = "default", window: int = 10) -> dict:
    """
    Загружает последние N закрытых сделок, запускает analyze_tilt_state,
    при обнаружении тильта пишет tilt_events. Возвращает результат + cooldown.
    """
    conn = _get_conn()
    rows = conn.execute(
        """SELECT symbol, size, pnl, open_ts, close_ts
           FROM trades WHERE user_id=?
           ORDER BY close_ts DESC LIMIT ?""",
        (user_id, window),
    ).fetchall()
    conn.close()

    trades = [dict(r) for r in rows]
    result = analyze_tilt_state(trades)

    if result["is_tilt_detected"]:
        record_tilt_events(result["reasons"], user_id)

    result["cooldown_remaining_min"] = get_cooldown_remaining(user_id)
    result["nudges"] = [REASON_NUDGES.get(r, r) for r in result["reasons"]]
    return result


def get_cooldown_remaining(user_id: str = "default") -> float:
    """Оставшееся время кулдауна в минутах (0 если не активен)."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT detected_at FROM tilt_events WHERE user_id=? ORDER BY detected_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    conn.close()
    if not row:
        return 0.0
    last_ms = _parse_ts_ms(row["detected_at"])
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    elapsed_min = (now_ms - last_ms) / 60_000
    return max(0.0, round(COOLDOWN_MINUTES - elapsed_min, 1))


# ── Tilt Heatmap (§7.4) ───────────────────────────────────────────────────────

_DAY_NAMES = ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"]
_SESSION_ORDER = ["Утро (EU)", "День (US)", "Вечер/Азия", "Ночь"]


def _session_bracket(hour: int) -> str:
    if 6 <= hour <= 12:
        return "Утро (EU)"
    if 13 <= hour <= 18:
        return "День (US)"
    if 19 <= hour <= 23:
        return "Вечер/Азия"
    return "Ночь"


def get_tilt_heatmap(user_id: str = "default") -> dict:
    """Распределение тильт-событий по дням недели и торговым сессиям."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT
               CAST(strftime('%w', detected_at) AS INTEGER) AS dow,
               CAST(strftime('%H', detected_at) AS INTEGER) AS hour,
               COUNT(*) AS cnt
           FROM tilt_events
           WHERE user_id=?
           GROUP BY dow, hour""",
        (user_id,),
    ).fetchall()
    conn.close()

    # Собираем матрицу day × session
    matrix: dict[str, dict[str, int]] = {
        day: {s: 0 for s in _SESSION_ORDER} for day in _DAY_NAMES
    }
    total = 0
    for r in rows:
        day = _DAY_NAMES[r["dow"]]
        session = _session_bracket(r["hour"])
        matrix[day][session] += r["cnt"]
        total += r["cnt"]

    return {"matrix": matrix, "days": _DAY_NAMES, "sessions": _SESSION_ORDER, "total": total}


def get_tilt_recent_events(user_id: str = "default", limit: int = 20) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, reason, detected_at FROM tilt_events WHERE user_id=? ORDER BY detected_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["nudge"] = REASON_NUDGES.get(r["reason"], r["reason"])
        result.append(d)
    return result


ensure_schema()
