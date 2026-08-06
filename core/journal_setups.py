"""
journal_setups.py — Мои разборы и сетапы (Личный плейбук, Part 6).

Таблицы (journal.db):
  user_setups  — сохранённые сетапы с вектор-параметрами
  setup_tags   — теги для категоризации плейбука
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DB = Path(__file__).parent.parent / "data" / "journal.db"

VALID_STATUSES = ("pending", "executed", "invalidated", "expired")

PATTERN_KEYS: list[str] = [
    "head_and_shoulders", "inverse_head_and_shoulders",
    "double_top", "double_bottom",
    "triangle_ascending", "triangle_descending", "triangle_symmetrical",
    "wedge_rising", "wedge_falling",
    "flag_bull", "flag_bear",
    "pennant", "cup_and_handle",
    "support_level", "resistance_level",
    "fib_retracement", "fib_extension",
    "breakout", "breakdown", "range",
    "trend_continuation", "trend_reversal",
    "other",
]

PATTERN_LABELS: dict[str, str] = {
    "head_and_shoulders":         "Голова и плечи",
    "inverse_head_and_shoulders": "Перевёрнутые г/п",
    "double_top":                 "Двойная вершина",
    "double_bottom":              "Двойное дно",
    "triangle_ascending":         "Восходящий треугольник",
    "triangle_descending":        "Нисходящий треугольник",
    "triangle_symmetrical":       "Симметричный треугольник",
    "wedge_rising":               "Расширяющийся клин",
    "wedge_falling":              "Сужающийся клин",
    "flag_bull":                  "Бычий флаг",
    "flag_bear":                  "Медвежий флаг",
    "pennant":                    "Вымпел",
    "cup_and_handle":             "Чашка с ручкой",
    "support_level":              "Уровень поддержки",
    "resistance_level":           "Уровень сопротивления",
    "fib_retracement":            "Фибоначчи (откат)",
    "fib_extension":              "Фибоначчи (цель)",
    "breakout":                   "Пробой вверх",
    "breakdown":                  "Пробой вниз",
    "range":                      "Боковой диапазон",
    "trend_continuation":         "Продолжение тренда",
    "trend_reversal":             "Разворот тренда",
    "other":                      "Другое",
}


def _get_conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_schema() -> None:
    statuses_sql = ",".join(f"'{s}'" for s in VALID_STATUSES)
    conn = _get_conn()
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS user_setups (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       TEXT NOT NULL DEFAULT 'default',
            symbol        TEXT NOT NULL,
            timeframe     TEXT NOT NULL,
            pattern_key   TEXT NOT NULL,
            render_params TEXT NOT NULL DEFAULT '[]',
            levels        TEXT NOT NULL DEFAULT '[]',
            thesis        TEXT NOT NULL DEFAULT '',
            status        TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ({statuses_sql})),
            trade_id      INTEGER REFERENCES trades(id) ON DELETE SET NULL,
            review_at     TEXT NOT NULL,
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_user_setups_lookup
            ON user_setups(user_id, symbol, status);

        CREATE INDEX IF NOT EXISTS idx_user_setups_review
            ON user_setups(review_at, status);

        CREATE TABLE IF NOT EXISTS setup_tags (
            setup_id INTEGER NOT NULL REFERENCES user_setups(id) ON DELETE CASCADE,
            tag      TEXT NOT NULL,
            PRIMARY KEY (setup_id, tag)
        );
    """)
    conn.commit()
    conn.close()


# ── CRUD ──────────────────────────────────────────────────────────────────────
def add_setup(data: dict, user_id: str = "default") -> dict:
    """
    Создаёт новый сетап. review_at = now + review_in_weeks * 7 days.
    render_params и levels сериализуются в JSON.
    """
    review_weeks = int(data.get("review_in_weeks", 4))
    review_at = (
        datetime.now(timezone.utc) + timedelta(weeks=review_weeks)
    ).strftime("%Y-%m-%dT%H:%M:%S")

    render_params = json.dumps(data.get("render_params") or [], ensure_ascii=False)
    levels        = json.dumps(data.get("levels") or [],         ensure_ascii=False)
    tags          = data.get("tags") or []

    conn = _get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO user_setups
                   (user_id, symbol, timeframe, pattern_key,
                    render_params, levels, thesis, status, review_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                user_id,
                data["symbol"].upper(),
                data["timeframe"],
                data.get("pattern_key", "other"),
                render_params,
                levels,
                data.get("thesis", ""),
                "pending",
                review_at,
            ),
        )
        setup_id = cur.lastrowid
        for tag in [t.strip() for t in tags if t.strip()]:
            conn.execute(
                "INSERT OR IGNORE INTO setup_tags (setup_id, tag) VALUES (?,?)",
                (setup_id, tag[:32]),
            )
        conn.commit()
        return {"id": setup_id, "review_at": review_at}
    finally:
        conn.close()


def list_setups(
    user_id: str = "default",
    symbol: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    conn = _get_conn()
    query = """
        SELECT s.id, s.symbol, s.timeframe, s.pattern_key,
               s.levels, s.thesis, s.status, s.trade_id,
               s.review_at, s.created_at, s.updated_at,
               GROUP_CONCAT(t.tag, ',') AS tags
        FROM user_setups s
        LEFT JOIN setup_tags t ON s.id = t.setup_id
        WHERE s.user_id=?
    """
    args: list = [user_id]
    if symbol:
        query += " AND s.symbol=?"
        args.append(symbol.upper())
    if status and status in VALID_STATUSES:
        query += " AND s.status=?"
        args.append(status)
    query += " GROUP BY s.id ORDER BY s.created_at DESC LIMIT ? OFFSET ?"
    args.extend([limit, offset])
    rows = conn.execute(query, args).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def get_setup(setup_id: int, user_id: str = "default") -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        """SELECT s.*, GROUP_CONCAT(t.tag, ',') AS tags
           FROM user_setups s
           LEFT JOIN setup_tags t ON s.id = t.setup_id
           WHERE s.id=? AND s.user_id=?
           GROUP BY s.id""",
        (setup_id, user_id),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = _row_to_dict(row)
    # render_params already in SELECT *
    d["render_params"] = json.loads(row["render_params"] or "[]")
    return d


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    try:
        d["levels"] = json.loads(d.get("levels") or "[]")
    except Exception:
        d["levels"] = []
    d["tags"]   = [t for t in (d.get("tags") or "").split(",") if t]
    d["render_params"] = None  # omit heavy field from list view
    return d


def update_setup(setup_id: int, data: dict, user_id: str = "default") -> bool:
    conn = _get_conn()
    fields = []
    args   = []
    allowed = {
        "symbol":       lambda v: (v.upper(),),
        "timeframe":    lambda v: (str(v),),
        "pattern_key":  lambda v: (str(v),),
        "thesis":       lambda v: (str(v),),
        "levels":       lambda v: (json.dumps(v if isinstance(v, list) else [], ensure_ascii=False),),
        "render_params":lambda v: (json.dumps(v if isinstance(v, list) else [], ensure_ascii=False),),
        "status":       lambda v: (str(v),) if v in VALID_STATUSES else None,
    }
    for key, transform in allowed.items():
        if key in data:
            result = transform(data[key])
            if result is not None:
                fields.append(f"{key}=?")
                args.append(result[0])

    # Пересчёт review_at если изменено
    if "review_in_weeks" in data:
        weeks = int(data["review_in_weeks"])
        review_at = (
            datetime.now(timezone.utc) + timedelta(weeks=weeks)
        ).strftime("%Y-%m-%dT%H:%M:%S")
        fields.append("review_at=?")
        args.append(review_at)

    # Tags update
    new_tags = data.get("tags")

    if not fields and new_tags is None:
        conn.close()
        return False

    if fields:
        fields.append("updated_at=datetime('now')")
        args.extend([setup_id, user_id])
        cur = conn.execute(
            f"UPDATE user_setups SET {', '.join(fields)} WHERE id=? AND user_id=?",
            args,
        )
        if cur.rowcount == 0:
            conn.close()
            return False
        conn.commit()

    if new_tags is not None:
        conn.execute("DELETE FROM setup_tags WHERE setup_id=?", (setup_id,))
        for tag in [t.strip() for t in new_tags if t.strip()]:
            conn.execute(
                "INSERT OR IGNORE INTO setup_tags (setup_id, tag) VALUES (?,?)",
                (setup_id, tag[:32]),
            )
        conn.commit()

    conn.close()
    return True


def delete_setup(setup_id: int, user_id: str = "default") -> bool:
    conn = _get_conn()
    cur = conn.execute(
        "DELETE FROM user_setups WHERE id=? AND user_id=?", (setup_id, user_id)
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# ── Trade-to-Setup linking (§6.3) ─────────────────────────────────────────────
def link_trade(setup_id: int, trade_id: int, user_id: str = "default") -> bool:
    conn = _get_conn()
    cur = conn.execute(
        """UPDATE user_setups
           SET status='executed', trade_id=?, updated_at=datetime('now')
           WHERE id=? AND user_id=?""",
        (trade_id, setup_id, user_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def update_status(setup_id: int, status: str, user_id: str = "default") -> bool:
    if status not in VALID_STATUSES:
        return False
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE user_setups SET status=?, updated_at=datetime('now') WHERE id=? AND user_id=?",
        (status, setup_id, user_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# ── Плейбук: эффективность паттернов (§6.3) ──────────────────────────────────
def get_playbook_stats(user_id: str = "default") -> list[dict]:
    """
    Считает винрейт по паттернам: только исполненные сетапы с привязанной сделкой.
    Не содержит прогнозных суждений (§6.5).
    """
    conn = _get_conn()
    rows = conn.execute(
        """SELECT
               us.pattern_key,
               COUNT(us.id)                                          AS total_saved,
               COUNT(CASE WHEN us.status='executed' THEN 1 END)     AS executed_count,
               COUNT(CASE WHEN t.pnl > 0 THEN 1 END)               AS positive_pnl_count,
               ROUND(
                   COUNT(CASE WHEN t.pnl > 0 THEN 1 END) * 100.0
                   / NULLIF(COUNT(CASE WHEN us.status='executed' THEN 1 END), 0),
                   1
               )                                                     AS pattern_winrate
           FROM user_setups us
           LEFT JOIN trades t ON us.trade_id = t.id
           WHERE us.user_id=?
           GROUP BY us.pattern_key
           ORDER BY total_saved DESC""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [
        {
            "pattern_key":      r["pattern_key"],
            "label":            PATTERN_LABELS.get(r["pattern_key"], r["pattern_key"]),
            "total_saved":      r["total_saved"],
            "executed_count":   r["executed_count"],
            "positive_pnl_count": r["positive_pnl_count"],
            "pattern_winrate":  r["pattern_winrate"],
        }
        for r in rows
    ]


def count_setups(user_id: str = "default") -> int:
    conn = _get_conn()
    n = conn.execute(
        "SELECT COUNT(*) FROM user_setups WHERE user_id=?", (user_id,)
    ).fetchone()[0]
    conn.close()
    return n


# ── Review-alerts (§6.4) ──────────────────────────────────────────────────────
def get_overdue_reviews(user_id: str = "default") -> list[dict]:
    """Возвращает pending-сетапы с наступившим review_at."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    conn = _get_conn()
    rows = conn.execute(
        """SELECT id, symbol, timeframe, pattern_key, review_at
           FROM user_setups
           WHERE user_id=? AND status='pending' AND review_at <= ?
           ORDER BY review_at ASC LIMIT 10""",
        (user_id, now),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


ensure_schema()
