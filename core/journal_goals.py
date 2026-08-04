"""
journal_goals.py — Цели/Обязательства + Шкала XP (Part 9).

Таблицы (journal.db):
  goals              — процессные цели трейдера
  training_seasons   — сезоны (квартальные циклы)
  user_season_stats  — архив достижений по сезону
"""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

_DB = Path(__file__).parent.parent / "data" / "journal.db"

# ── XP rewards (§9.2) ─────────────────────────────────────────────────────────
XP_REWARDS: dict[str, int] = {
    "lesson_completed":       50,
    "module_completed":       200,
    "trade_logged":           10,
    "trade_metadata_filled":  15,
    "trade_disciplined":      100,   # Системная сделка: +100 XP
    "trade_undisciplined":    5,     # Нарушение плана: минимальный базис §9.2
    "flashcard_reviewed":     5,
    "checklist_passed":       20,
    "goal_achieved":          300,
    "streak_retained":        25,
    # Дополнительные (используются в journal_gamification)
    "chapter_complete":       50,    # alias для lesson_completed
    "all_chapters_done":      200,   # module_completed bonus
    "achievement_unlocked":   0,     # своё значение в achievements таблице
    "quest_complete":         0,     # своё значение в quests таблице
}

# ── Level titles (§9.4) ───────────────────────────────────────────────────────
_LEVEL_TITLES = [
    (1,  4,  "Новичок Процесса",       "Начинает путь построения системных торговых привычек."),
    (5,  9,  "Осознанный Трейдер",     "Стабильно заполняет дневник и контролирует эмоции."),
    (10, 19, "Мастер Риска",           "Продемонстрировал безупречное соблюдение стоп-лоссов."),
    (20, 34, "Хранитель Дисциплины",   "Прошёл полный академический курс, минимизировал тильт-факторы."),
    (35, 999,"Легенда SBF",            "Эталон системного подхода к управлению капиталом."),
]


def get_level_title(level: int) -> dict:
    for min_l, max_l, title, desc in _LEVEL_TITLES:
        if min_l <= level <= max_l:
            return {"title": title, "description": desc}
    return {"title": "Легенда SBF", "description": "Эталон системного подхода к управлению капиталом."}


# ── Level progression formula (§9.2) ─────────────────────────────────────────
# XP_req(L) = floor(100 × L^2.2) — XP от уровня L до L+1

def evaluate_level_progression(total_xp: int) -> dict:
    """
    XP_req(L) = floor(100 × L^2.2). Обновлено с 1.8 для более долгого прогресса.
    """
    total_xp = max(0, int(total_xp))
    level = 1
    accumulated = 0
    while True:
        next_level_xp = math.floor(100 * (level ** 2.2))
        if total_xp >= accumulated + next_level_xp:
            accumulated += next_level_xp
            level += 1
        else:
            xp_in = total_xp - accumulated
            pct = min(100, round(xp_in / next_level_xp * 100)) if next_level_xp > 0 else 100
            title_info = get_level_title(level)
            return {
                "level":        level,
                "xp":           total_xp,
                "xp_in_level":  xp_in,
                "xp_for_next":  next_level_xp - xp_in,
                "xp_to_next":   next_level_xp,
                "progress_pct": pct,
                "progress":     pct / 100,
                "title":        title_info["title"],
                "title_desc":   title_info["description"],
            }


# ── Goal presets (§9.3) ───────────────────────────────────────────────────────
VALID_GOAL_KINDS = (
    "journal_streak_days",
    "max_risk_per_trade",
    "complete_learning_chapters",
    "maintain_discipline_score",
)

GOAL_PRESETS: dict[str, dict] = {
    "iron_shield": {
        "kind":          "max_risk_per_trade",
        "target_value":  1.0,
        "deadline_days": 30,
        "label":         "Железный щит",
        "description":   "Риск не более 1% на одну сделку в течение 30 дней",
        "icon":          "🛡️",
    },
    "mindfulness_marathon": {
        "kind":          "journal_streak_days",
        "target_value":  30.0,
        "deadline_days": 45,
        "label":         "Марафон осознанности",
        "description":   "Ежедневное ведение дневника 30 дней подряд",
        "icon":          "🧘",
    },
    "academic_standard": {
        "kind":          "complete_learning_chapters",
        "target_value":  15.0,
        "deadline_days": 90,
        "label":         "Академический стандарт",
        "description":   "Изучить все 15 глав теоретического курса",
        "icon":          "🎓",
    },
}

GOAL_KIND_LABELS = {
    "journal_streak_days":       "Вести дневник N дней подряд",
    "max_risk_per_trade":        "Не превышать риск X% на сделку",
    "complete_learning_chapters":"Пройти N глав обучения",
    "maintain_discipline_score": "Удерживать балл дисциплины выше X%",
}


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
        CREATE TABLE IF NOT EXISTS goals (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       TEXT NOT NULL DEFAULT 'default',
            kind          TEXT NOT NULL,
            target_value  REAL NOT NULL,
            current_value REAL NOT NULL DEFAULT 0.0,
            deadline      TEXT NOT NULL,
            status        TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active','completed','failed')),
            preset_code   TEXT,
            label         TEXT NOT NULL DEFAULT '',
            icon          TEXT NOT NULL DEFAULT '🎯',
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_goals_user_status
            ON goals(user_id, status);

        CREATE TABLE IF NOT EXISTS training_seasons (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            title      TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date   TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS user_season_stats (
            user_id          TEXT NOT NULL DEFAULT 'default',
            season_id        INTEGER NOT NULL REFERENCES training_seasons(id) ON DELETE CASCADE,
            xp_earned        INTEGER NOT NULL DEFAULT 0,
            goals_completed  INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, season_id)
        );
    """)
    conn.commit()

    # Auto-create current season if none exists
    existing = conn.execute("SELECT COUNT(*) FROM training_seasons").fetchone()[0]
    if existing == 0:
        _create_current_season(conn)

    conn.close()


def _current_quarter_bounds() -> tuple[date, date]:
    today = date.today()
    q = (today.month - 1) // 3  # 0=Q1, 1=Q2, 2=Q3, 3=Q4
    start_month = q * 3 + 1
    end_month = start_month + 2
    start = date(today.year, start_month, 1)
    if end_month == 12:
        end = date(today.year, 12, 31)
    else:
        end = date(today.year, end_month + 1, 1) - timedelta(days=1)
    return start, end


def _create_current_season(conn: sqlite3.Connection) -> int:
    start, end = _current_quarter_bounds()
    q = (start.month - 1) // 3 + 1
    title = f"Q{q} {start.year}"
    cur = conn.execute(
        "INSERT OR IGNORE INTO training_seasons (title, start_date, end_date) VALUES (?,?,?)",
        (title, start.isoformat(), end.isoformat()),
    )
    conn.commit()
    return cur.lastrowid or 1


# ── Goals CRUD ────────────────────────────────────────────────────────────────

def add_goal(
    kind: str,
    target_value: float,
    deadline_days: int = 30,
    label: str = "",
    icon: str = "🎯",
    preset_code: str | None = None,
    user_id: str = "default",
) -> dict:
    """
    Создаёт новую цель. Запрещает финансовые/доходностные метрики (§9.5).
    """
    if kind not in VALID_GOAL_KINDS:
        return {"error": f"Invalid goal kind. Allowed: {VALID_GOAL_KINDS}"}
    if target_value <= 0:
        return {"error": "target_value must be > 0"}
    deadline = (
        datetime.now(timezone.utc) + timedelta(days=deadline_days)
    ).strftime("%Y-%m-%dT%H:%M:%S")
    if not label:
        label = GOAL_KIND_LABELS.get(kind, kind)

    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO goals (user_id, kind, target_value, deadline, label, icon, preset_code)
           VALUES (?,?,?,?,?,?,?)""",
        (user_id, kind, float(target_value), deadline, label, icon, preset_code),
    )
    goal_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {"id": goal_id, "kind": kind, "target_value": target_value, "deadline": deadline}


def add_goal_from_preset(preset_code: str, user_id: str = "default") -> dict:
    p = GOAL_PRESETS.get(preset_code)
    if not p:
        return {"error": f"Unknown preset: {preset_code}"}
    # Check if same preset+active already exists
    conn = _get_conn()
    existing = conn.execute(
        "SELECT id FROM goals WHERE user_id=? AND preset_code=? AND status='active'",
        (user_id, preset_code),
    ).fetchone()
    conn.close()
    if existing:
        return {"error": "Цель по этому пресету уже активна", "existing_id": existing["id"]}
    return add_goal(
        kind=p["kind"],
        target_value=p["target_value"],
        deadline_days=p["deadline_days"],
        label=p["label"],
        icon=p["icon"],
        preset_code=preset_code,
        user_id=user_id,
    )


def list_goals(user_id: str = "default", status: str | None = None) -> list[dict]:
    conn = _get_conn()
    query = "SELECT * FROM goals WHERE user_id=?"
    args: list = [user_id]
    if status:
        query += " AND status=?"
        args.append(status)
    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, args).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["progress_pct"] = round(
            min(d["current_value"] / d["target_value"] * 100, 100), 1
        ) if d["target_value"] > 0 else 0
        d["kind_label"] = GOAL_KIND_LABELS.get(d["kind"], d["kind"])
        result.append(d)
    return result


def delete_goal(goal_id: int, user_id: str = "default") -> bool:
    conn = _get_conn()
    cur = conn.execute(
        "DELETE FROM goals WHERE id=? AND user_id=?", (goal_id, user_id)
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# ── Goal Progress Engine (§9.3) ───────────────────────────────────────────────

def _update_single_goal(
    conn: sqlite3.Connection,
    goal: sqlite3.Row,
    update_data: dict,
) -> bool:
    """
    Точный порт TypeScript §9.3 updateGoalProgress.
    Возвращает True если статус изменился.
    """
    if goal["status"] != "active":
        return False

    kind = goal["kind"]
    current = float(goal["current_value"])
    target  = float(goal["target_value"])
    new_current = current
    new_status  = "active"

    if kind == "max_risk_per_trade":
        risk = update_data.get("lastTradeRiskPercent")
        if risk is not None:
            if float(risk) > target:
                # Превышение лимита = провал (§9.3, §9.5)
                new_status = "failed"
            else:
                new_current = float(risk)

    elif kind == "journal_streak_days":
        streak = update_data.get("currentStreak")
        if streak is not None:
            new_current = max(current, float(streak))
            if new_current >= target:
                new_status = "completed"

    elif kind == "complete_learning_chapters":
        chapters = update_data.get("totalChaptersRead")
        if chapters is not None:
            new_current = float(chapters)
            if new_current >= target:
                new_status = "completed"

    elif kind == "maintain_discipline_score":
        score = update_data.get("currentDisciplineScore")
        if score is not None:
            new_current = float(score)
            if new_current >= target:
                new_status = "completed"

    changed = (new_current != current or new_status != "active")
    if changed:
        conn.execute(
            "UPDATE goals SET current_value=?, status=? WHERE id=?",
            (new_current, new_status, goal["id"]),
        )
    return changed


def _gather_update_data(user_id: str, conn: sqlite3.Connection) -> dict:
    """Собирает актуальные данные для всех типов целей."""
    data: dict = {}

    # Journal streak
    streak_row = conn.execute(
        "SELECT current_streak FROM user_streaks WHERE user_id=? AND kind='journal_fill'",
        (user_id,),
    ).fetchone()
    if streak_row:
        data["currentStreak"] = streak_row["current_streak"]

    # Completed chapters
    ch_done = conn.execute(
        "SELECT COUNT(*) FROM user_course_progress WHERE user_id=? AND is_completed=1",
        (user_id,),
    ).fetchone()[0]
    data["totalChaptersRead"] = ch_done

    # Discipline score (last 5 trades)
    if _table_exists(conn, "trade_discipline_eval") and _table_exists(conn, "discipline_config"):
        try:
            disc_row = conn.execute(
                """SELECT SUM(dc.weight) as tw,
                          SUM(CASE WHEN te.passed=1 THEN dc.weight ELSE 0 END) as pw
                   FROM (SELECT id FROM trades WHERE user_id=? ORDER BY close_ts DESC LIMIT 5) t
                   JOIN trade_discipline_eval te ON t.id = te.trade_id
                   JOIN discipline_config dc ON dc.user_id=? AND dc.criterion=te.criterion AND dc.enabled=1""",
                (user_id, user_id),
            ).fetchone()
            if disc_row and disc_row["tw"]:
                data["currentDisciplineScore"] = round(disc_row["pw"] / disc_row["tw"] * 100, 1)
        except Exception:
            pass

    return data


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def update_all_goals(user_id: str = "default", extra: dict | None = None) -> list[dict]:
    """
    Обновляет все активные цели по текущему состоянию системы.
    extra — дополнительные данные (напр. lastTradeRiskPercent из новой сделки).
    Возвращает список только что выполненных/проваленных целей.
    """
    conn = _get_conn()
    active = conn.execute(
        "SELECT * FROM goals WHERE user_id=? AND status='active'", (user_id,)
    ).fetchall()
    if not active:
        conn.close()
        return []

    update_data = _gather_update_data(user_id, conn)
    if extra:
        update_data.update(extra)

    changed_goals = []
    for goal in active:
        if _update_single_goal(conn, goal, update_data):
            changed_goals.append({"id": goal["id"], "kind": goal["kind"], "new_status": update_data})

    conn.commit()

    # Re-read updated goals to get new status
    result = []
    for cg in changed_goals:
        row = conn.execute("SELECT id, kind, status, label, icon FROM goals WHERE id=?", (cg["id"],)).fetchone()
        if row:
            result.append(dict(row))

    conn.close()

    # Award XP for completed goals
    from . import journal_gamification as G
    for g in result:
        if g["status"] == "completed":
            G.award_xp("goal_achieved", XP_REWARDS["goal_achieved"], g["id"], user_id)

    return result


def update_goal_for_trade(user_id: str, pnl_r: float) -> list[dict]:
    """Вызывается после добавления сделки. pnl_r → risk proxy."""
    # pnl_r < 0 означает убыток; |pnl_r| = сколько R потеряли
    risk_pct_proxy = abs(pnl_r) if pnl_r < 0 else 0.0
    return update_all_goals(user_id, extra={"lastTradeRiskPercent": risk_pct_proxy})


# ── Seasons ───────────────────────────────────────────────────────────────────

def get_active_season(user_id: str = "default") -> dict | None:
    today = date.today().isoformat()
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM training_seasons WHERE start_date <= ? AND end_date >= ? ORDER BY id DESC LIMIT 1",
        (today, today),
    ).fetchone()
    if not row:
        conn.close()
        return None

    season_id = row["id"]
    # Get user's season stats
    stats = conn.execute(
        "SELECT * FROM user_season_stats WHERE user_id=? AND season_id=?",
        (user_id, season_id),
    ).fetchone()
    # Calculate XP earned this season on the fly
    season_xp = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM xp_events WHERE user_id=? AND ts >= ?",
        (user_id, row["start_date"]),
    ).fetchone()[0]
    season_goals_done = conn.execute(
        "SELECT COUNT(*) FROM goals WHERE user_id=? AND status='completed' AND created_at >= ?",
        (user_id, row["start_date"]),
    ).fetchone()[0]
    conn.close()

    return {
        **dict(row),
        "xp_earned": int(season_xp),
        "goals_completed": int(season_goals_done),
        "archived": dict(stats) if stats else None,
    }


def list_past_seasons(user_id: str = "default") -> list[dict]:
    today = date.today().isoformat()
    conn = _get_conn()
    rows = conn.execute(
        """SELECT ts.*, uss.xp_earned, uss.goals_completed
           FROM training_seasons ts
           LEFT JOIN user_season_stats uss ON ts.id=uss.season_id AND uss.user_id=?
           WHERE ts.end_date < ?
           ORDER BY ts.start_date DESC LIMIT 8""",
        (user_id, today),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def close_season(season_id: int, user_id: str = "default") -> dict:
    """Архивирует сезон: суммирует XP + завершённые цели (мягкий сброс §9.4)."""
    conn = _get_conn()
    season = conn.execute(
        "SELECT start_date FROM training_seasons WHERE id=?", (season_id,)
    ).fetchone()
    if not season:
        conn.close()
        return {"error": "season not found"}

    xp_earned = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM xp_events WHERE user_id=? AND ts >= ?",
        (user_id, season["start_date"]),
    ).fetchone()[0]
    goals_completed = conn.execute(
        "SELECT COUNT(*) FROM goals WHERE user_id=? AND status='completed' AND created_at >= ?",
        (user_id, season["start_date"]),
    ).fetchone()[0]

    conn.execute(
        """INSERT INTO user_season_stats (user_id, season_id, xp_earned, goals_completed)
           VALUES (?,?,?,?)
           ON CONFLICT(user_id, season_id) DO UPDATE SET xp_earned=?, goals_completed=?""",
        (user_id, season_id, int(xp_earned), int(goals_completed), int(xp_earned), int(goals_completed)),
    )
    conn.commit()
    conn.close()

    # Auto-create next season
    conn2 = _get_conn()
    _create_current_season(conn2)
    conn2.close()

    return {
        "ok": True,
        "xp_earned": int(xp_earned),
        "goals_completed": int(goals_completed),
    }


# ── Summary for UI ────────────────────────────────────────────────────────────

def get_goals_overview(user_id: str = "default") -> dict:
    return {
        "active":  list_goals(user_id, "active"),
        "completed": list_goals(user_id, "completed"),
        "failed":  list_goals(user_id, "failed"),
        "presets": [
            {**v, "code": k, "active": any(
                g.get("preset_code") == k
                for g in list_goals(user_id, "active")
            )}
            for k, v in GOAL_PRESETS.items()
        ],
        "season": get_active_season(user_id),
    }


ensure_schema()
