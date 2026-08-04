"""
journal_discipline.py — Оценка дисциплины трейдера (Part 3).

Взвешенная оценка по настраиваемым критериям, стрики, детектор «тильта».
§3.5: балл не зависит от P&L; XP не списывается — только прирост замораживается.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DB = Path(__file__).parent.parent / "data" / "journal.db"

# ── Справочники ────────────────────────────────────────────────────────────────
CRITERIA = [
    {"key": "sl_used",               "ico": "🛡️", "label": "Жёсткий Stop Loss выставлен",         "auto": True},
    {"key": "mental_stop_respected", "ico": "🧠", "label": "Ментальный стоп соблюдён",             "auto": False},
    {"key": "no_averaging_down",     "ico": "🚫", "label": "Нет усреднения в убыток",              "auto": False},
    {"key": "allowed_time_window",   "ico": "🕐", "label": "Торговля в разрешённые часы",          "auto": False},
    {"key": "position_size_limit",   "ico": "📏", "label": "Объём не превышает лимит",             "auto": False},
    {"key": "journal_completed_24h", "ico": "📓", "label": "Дневник заполнен за 24 ч",            "auto": True},
]
CRITERION_KEYS = tuple(c["key"] for c in CRITERIA)

PRESETS: dict[str, list[dict]] = {
    "conservative": [
        {"criterion": "sl_used",               "enabled": True,  "weight": 2.0},
        {"criterion": "mental_stop_respected",  "enabled": False, "weight": 0.0},
        {"criterion": "no_averaging_down",      "enabled": True,  "weight": 1.5},
        {"criterion": "allowed_time_window",    "enabled": True,  "weight": 1.0},
        {"criterion": "position_size_limit",    "enabled": True,  "weight": 2.0},
        {"criterion": "journal_completed_24h",  "enabled": True,  "weight": 1.0},
    ],
    "scalper": [
        {"criterion": "sl_used",               "enabled": False, "weight": 0.0},
        {"criterion": "mental_stop_respected",  "enabled": True,  "weight": 2.0},
        {"criterion": "no_averaging_down",      "enabled": True,  "weight": 1.5},
        {"criterion": "allowed_time_window",    "enabled": True,  "weight": 1.0},
        {"criterion": "position_size_limit",    "enabled": True,  "weight": 1.5},
        {"criterion": "journal_completed_24h",  "enabled": True,  "weight": 0.5},
    ],
    "investor": [
        {"criterion": "sl_used",               "enabled": False, "weight": 0.0},
        {"criterion": "mental_stop_respected",  "enabled": True,  "weight": 1.0},
        {"criterion": "no_averaging_down",      "enabled": False, "weight": 0.0},
        {"criterion": "allowed_time_window",    "enabled": False, "weight": 0.0},
        {"criterion": "position_size_limit",    "enabled": True,  "weight": 2.0},
        {"criterion": "journal_completed_24h",  "enabled": True,  "weight": 1.0},
    ],
}


# ── Соединение ────────────────────────────────────────────────────────────────
def _get_conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── Схема (§3.1) ──────────────────────────────────────────────────────────────
def ensure_schema() -> None:
    ck = "(" + ",".join(f"'{k}'" for k in CRITERION_KEYS) + ")"
    conn = _get_conn()
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS discipline_config (
            user_id   TEXT NOT NULL DEFAULT 'default',
            criterion TEXT NOT NULL CHECK(criterion IN {ck}),
            enabled   INTEGER NOT NULL DEFAULT 1,
            weight    REAL    NOT NULL DEFAULT 1.0
                CHECK(weight >= 0.0 AND weight <= 3.0),
            PRIMARY KEY (user_id, criterion)
        );

        CREATE TABLE IF NOT EXISTS trade_discipline_eval (
            trade_id     INTEGER NOT NULL
                REFERENCES trades(id) ON DELETE CASCADE,
            criterion    TEXT NOT NULL CHECK(criterion IN {ck}),
            passed       INTEGER NOT NULL CHECK(passed IN (0,1)),
            evaluated_at TEXT    NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (trade_id, criterion)
        );
        CREATE INDEX IF NOT EXISTS idx_disc_criterion_passed
            ON trade_discipline_eval(criterion, passed);

        CREATE TABLE IF NOT EXISTS user_settings (
            user_id       TEXT PRIMARY KEY,
            advanced_mode INTEGER NOT NULL DEFAULT 0
        );
    """)
    conn.commit()
    conn.close()


# ── Конфиг ────────────────────────────────────────────────────────────────────
def get_config(user_id: str = "default") -> list[dict]:
    """Возвращает список критериев. Если не настроен — инициализирует conservative."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT criterion, enabled, weight FROM discipline_config WHERE user_id=?",
        (user_id,),
    ).fetchall()
    conn.close()

    if not rows:
        _apply_preset(user_id, "conservative")
        return get_config(user_id)

    config_map = {r["criterion"]: dict(r) for r in rows}
    # Гарантируем все критерии присутствуют
    result = []
    default_cfg = {c["criterion"]: c for c in PRESETS["conservative"]}
    for c in CRITERIA:
        k = c["key"]
        if k in config_map:
            row = config_map[k]
            result.append({
                "criterion": k,
                "enabled":   bool(row["enabled"]),
                "weight":    row["weight"],
                "ico":       c["ico"],
                "label":     c["label"],
                "auto":      c["auto"],
            })
        else:
            d = default_cfg.get(k, {"enabled": True, "weight": 1.0})
            result.append({
                "criterion": k,
                "enabled":   d["enabled"],
                "weight":    d["weight"],
                "ico":       c["ico"],
                "label":     c["label"],
                "auto":      c["auto"],
            })
    return result


def _apply_preset(user_id: str, preset_name: str) -> None:
    preset = PRESETS.get(preset_name, PRESETS["conservative"])
    conn = _get_conn()
    conn.executemany(
        """INSERT OR REPLACE INTO discipline_config(user_id, criterion, enabled, weight)
           VALUES(?,?,?,?)""",
        [(user_id, p["criterion"], 1 if p["enabled"] else 0, p["weight"]) for p in preset],
    )
    conn.commit()
    conn.close()


def save_config(
    user_id: str,
    config_list: list[dict],
    advanced_mode: bool = False,
) -> dict:
    """Сохраняет конфиг. Возвращает {ok, error?}."""
    validation = validate_config(config_list, advanced_mode)
    if not validation["valid"]:
        return {"ok": False, "error": validation["error"]}

    conn = _get_conn()
    conn.executemany(
        """INSERT OR REPLACE INTO discipline_config(user_id, criterion, enabled, weight)
           VALUES(?,?,?,?)""",
        [
            (user_id, c["criterion"], 1 if c.get("enabled") else 0, float(c.get("weight", 1.0)))
            for c in config_list if c["criterion"] in CRITERION_KEYS
        ],
    )
    conn.execute(
        "INSERT OR REPLACE INTO user_settings(user_id, advanced_mode) VALUES(?,?)",
        (user_id, 1 if advanced_mode else 0),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


def get_advanced_mode(user_id: str = "default") -> bool:
    conn = _get_conn()
    row = conn.execute(
        "SELECT advanced_mode FROM user_settings WHERE user_id=?", (user_id,)
    ).fetchone()
    conn.close()
    return bool(row["advanced_mode"]) if row else False


def validate_config(config_list: list[dict], advanced_mode: bool = False) -> dict:
    """§3.2 Wellbeing: нельзя отключить оба вида стопа без продвинутого режима."""
    sl      = next((c for c in config_list if c["criterion"] == "sl_used"),               None)
    mental  = next((c for c in config_list if c["criterion"] == "mental_stop_respected"),  None)
    sl_on      = sl     and sl.get("enabled")
    mental_on  = mental and mental.get("enabled")
    if not sl_on and not mental_on and not advanced_mode:
        return {
            "valid": False,
            "error": (
                "Запрещено одновременное отключение жёсткого и ментального "
                "стоп-лосса. Активируйте «Продвинутый режим» в настройках."
            ),
        }
    return {"valid": True}


# ── Оценки по сделкам ─────────────────────────────────────────────────────────
def save_eval(trade_id: int, evaluations: list[dict]) -> None:
    """
    evaluations: [{"criterion": "sl_used", "passed": True}, ...]
    §3.5: оценка не зависит от P&L — не проверяем знак pnl.
    """
    conn = _get_conn()
    conn.executemany(
        """INSERT OR REPLACE INTO trade_discipline_eval
           (trade_id, criterion, passed, evaluated_at)
           VALUES(?,?,?,datetime('now'))""",
        [
            (trade_id, e["criterion"], 1 if e["passed"] else 0)
            for e in evaluations if e["criterion"] in CRITERION_KEYS
        ],
    )
    conn.commit()
    conn.close()


def get_trade_eval(trade_id: int) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT criterion, passed FROM trade_discipline_eval WHERE trade_id=?",
        (trade_id,),
    ).fetchall()
    conn.close()
    return [{"criterion": r["criterion"], "passed": bool(r["passed"])} for r in rows]


def auto_eval_sl_used(trade_id: int) -> bool | None:
    """True если stop_loss выставлен, False если нет, None если trade не найдена."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT stop_loss FROM trades WHERE id=?", (trade_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return row["stop_loss"] is not None and row["stop_loss"] > 0


def auto_eval_journal_24h(trade_id: int) -> bool:
    """True если meta создана в течение 24ч после close_ts."""
    conn = _get_conn()
    row = conn.execute(
        """SELECT t.close_ts, jm.updated_at
           FROM trades t
           LEFT JOIN journal_meta jm ON t.id = jm.trade_id
           WHERE t.id=?""",
        (trade_id,),
    ).fetchone()
    conn.close()
    if not row or not row["updated_at"]:
        return False
    try:
        close = datetime.fromisoformat(row["close_ts"].replace(" ", "T"))
        updated = datetime.fromisoformat(row["updated_at"].replace(" ", "T"))
        return (updated - close).total_seconds() <= 86400
    except Exception:
        return False


# ── Расчёт балла (§3.3) ───────────────────────────────────────────────────────
def _compute_score_for_slice(
    trade_slice: list[dict],
    enabled_weights: dict[str, float],
) -> float:
    total_possible = total_passed = 0.0
    for trade in trade_slice:
        for ev in trade["evaluations"]:
            w = enabled_weights.get(ev["criterion"])
            if w is not None:
                total_possible += w
                if ev["passed"]:
                    total_passed += w
    return (total_passed / total_possible * 100) if total_possible > 0 else 100.0


def calculate_score(user_id: str = "default", window: int = 20) -> dict:
    config = get_config(user_id)
    enabled_weights = {c["criterion"]: c["weight"] for c in config if c["enabled"]}

    if not enabled_weights:
        return {"current_score": 100, "trend": "stable", "worst_criterion": None, "evaluated": 0}

    conn = _get_conn()
    trade_rows = conn.execute(
        """SELECT DISTINCT t.id, t.close_ts
           FROM trades t
           JOIN trade_discipline_eval te ON t.id = te.trade_id
           WHERE t.user_id=?
           ORDER BY t.close_ts DESC LIMIT ?""",
        (user_id, window),
    ).fetchall()

    history: list[dict] = []
    for tr in trade_rows:
        evals = conn.execute(
            "SELECT criterion, passed FROM trade_discipline_eval WHERE trade_id=?",
            (tr["id"],),
        ).fetchall()
        history.append({
            "trade_id":    tr["id"],
            "evaluations": [{"criterion": e["criterion"], "passed": bool(e["passed"])} for e in evals],
        })
    conn.close()

    if not history:
        return {"current_score": 100, "trend": "stable", "worst_criterion": None, "evaluated": 0}

    half = (len(history) + 1) // 2
    recent_score = _compute_score_for_slice(history[:half],  enabled_weights)
    older_score  = _compute_score_for_slice(history[half:],  enabled_weights) if history[half:] else recent_score

    trend: str = "stable"
    if recent_score > older_score + 2:
        trend = "up"
    elif recent_score < older_score - 2:
        trend = "down"

    # Критерий с наибольшим весом провалов (§3.3)
    failure_weights: dict[str, float] = {}
    for trade in history:
        for ev in trade["evaluations"]:
            w = enabled_weights.get(ev["criterion"])
            if w is not None and not ev["passed"]:
                failure_weights[ev["criterion"]] = failure_weights.get(ev["criterion"], 0.0) + w

    worst = max(failure_weights, key=lambda k: failure_weights[k]) if failure_weights else None

    return {
        "current_score": round(recent_score),
        "trend":         trend,
        "worst_criterion": worst,
        "evaluated":     len(history),
    }


# ── Стрики (§3.4.1) ───────────────────────────────────────────────────────────
def get_streak(user_id: str, criterion: str) -> int:
    conn = _get_conn()
    rows = conn.execute(
        """SELECT te.passed
           FROM trade_discipline_eval te
           JOIN trades t ON te.trade_id = t.id
           WHERE t.user_id=? AND te.criterion=?
           ORDER BY t.close_ts DESC""",
        (user_id, criterion),
    ).fetchall()
    conn.close()
    streak = 0
    for row in rows:
        if row["passed"]:
            streak += 1
        else:
            break
    return streak


def get_all_streaks(user_id: str = "default") -> dict[str, int]:
    return {c: get_streak(user_id, c) for c in CRITERION_KEYS}


# ── Дисциплинарный пробой / тильт (§3.4.2) ────────────────────────────────────
def check_breakout(user_id: str = "default") -> dict:
    """
    avg(last 20 evaluated trades) ≥ 85% И last_trade score < 40% → пробой.
    """
    config = get_config(user_id)
    enabled_weights = {c["criterion"]: c["weight"] for c in config if c["enabled"]}

    conn = _get_conn()
    trade_rows = conn.execute(
        """SELECT DISTINCT t.id, t.close_ts
           FROM trades t
           JOIN trade_discipline_eval te ON t.id = te.trade_id
           WHERE t.user_id=?
           ORDER BY t.close_ts DESC LIMIT 21""",
        (user_id,),
    ).fetchall()
    conn.close()

    if len(trade_rows) < 5:
        return {"detected": False, "avg_score": None, "last_score": None}

    def load_evals(tid: int) -> list[dict]:
        c = _get_conn()
        rows = c.execute(
            "SELECT criterion, passed FROM trade_discipline_eval WHERE trade_id=?", (tid,)
        ).fetchall()
        c.close()
        return [{"criterion": r["criterion"], "passed": bool(r["passed"])} for r in rows]

    last_trade = {"evaluations": load_evals(trade_rows[0]["id"])}
    history    = [{"evaluations": load_evals(r["id"])} for r in trade_rows[1:]]

    last_score = _compute_score_for_slice([last_trade], enabled_weights)
    avg_score  = _compute_score_for_slice(history,      enabled_weights)

    detected = avg_score >= 85.0 and last_score < 40.0

    return {
        "detected":   detected,
        "avg_score":  round(avg_score, 1),
        "last_score": round(last_score, 1),
    }


# ── Агрегированный ответ для API ──────────────────────────────────────────────
def get_discipline_data(user_id: str = "default") -> dict:
    score   = calculate_score(user_id)
    streaks = get_all_streaks(user_id)
    breakout = check_breakout(user_id)
    config   = get_config(user_id)
    adv_mode = get_advanced_mode(user_id)

    conn = _get_conn()
    total_eval = conn.execute(
        """SELECT COUNT(DISTINCT t.id) FROM trades t
           JOIN trade_discipline_eval te ON t.id = te.trade_id
           WHERE t.user_id=?""",
        (user_id,),
    ).fetchone()[0]
    conn.close()

    return {
        "score":          score,
        "streaks":        streaks,
        "breakout":       breakout,
        "config":         config,
        "presets":        list(PRESETS.keys()),
        "advanced_mode":  adv_mode,
        "total_evaluated": total_eval,
    }


ensure_schema()
