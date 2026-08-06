"""
journal_gamification.py — Путь обучения + Геймификация (Part 8).

Таблицы (journal.db):
  xp_events              — лог всех начислений XP
  user_course_progress   — прогресс по 15 главам
  flashcards             — глоссарий флешкарт
  user_flashcards        — SM-2 состояние повторений
  user_streaks           — серии ежедневной активности
  achievements           — определения значков
  user_achievements      — разблокированные значки
  daily_quests           — определения квестов
  user_daily_quests      — прогресс квестов за сегодня
  user_cosmetic_unlocks  — косметические анлоки (только за XP, §8.5)
  academy_quiz_attempt   — попытки теста на воспроизведение (SPEC_academy_level1_interactivity.md)
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

_DB = Path(__file__).parent.parent / "data" / "journal.db"

TOTAL_CHAPTERS = 15

# XP за действия
# XP amounts — из справочника §9.2 (journal_goals.XP_REWARDS — единый источник правды)
XP_CHAPTER_COMPLETE    = 50   # lesson_completed
XP_ALL_CHAPTERS_DONE   = 200  # module_completed bonus
XP_FLASHCARD_SESSION   = 5    # flashcard_reviewed
XP_STREAK_7_DAYS       = 25   # streak_retained × 7
XP_QUEST_COMPLETE      = 0    # задаётся в таблице quests
XP_TRADE_LOGGED        = 10   # trade_logged
XP_TRADE_META_FILLED   = 15   # trade_metadata_filled
XP_TRADE_DISCIPLINED   = 100  # trade_disciplined
XP_TRADE_UNDISCIPLINED = 5    # trade_undisciplined (базовый минимум §9.2)
XP_CHECKLIST_PASSED    = 20   # checklist_passed

# Заморозки стрика: начисляются при level-up и раз в 7 дней
STREAK_FREEZE_ON_LEVELUP = 1

STREAK_KINDS = ("daily_login", "journal_fill", "lesson_read")

# Косметика (анлоки только за достижения, §8.5 — никаких покупок)
COSMETIC_ITEMS = [
    {"item_key": "theme_nordic",    "description": "Нордическая тема интерфейса", "unlock_xp": 750},
    {"item_key": "theme_tokyo",     "description": "Tokyo Blue тема",             "unlock_xp": 2000},
    {"item_key": "theme_classic",   "description": "Classic Dark тема",            "unlock_xp": 3500},
    {"item_key": "candle_hollow",   "description": "Полые свечи на графике",       "unlock_xp": 300},
    {"item_key": "chart_grid_fine", "description": "Мелкая сетка на графике",      "unlock_xp": 600},
]

DEFAULT_FLASHCARDS = [
    ("Stop Loss",             "Ордер для ограничения убытка при достижении заданного ценового уровня."),
    ("Take Profit",           "Ордер для фиксации прибыли при достижении целевого уровня цены."),
    ("R-Мультипликатор",      "Отношение результата сделки к начальному риску; 1R = размер стоп-лосса."),
    ("Win Rate",              "Доля прибыльных сделок от общего числа закрытых позиций (в процентах)."),
    ("Risk/Reward Ratio",     "Соотношение потенциальной прибыли к потенциальному убытку сделки."),
    ("ATR",                   "Average True Range — средний истинный диапазон; показатель волатильности за N свечей."),
    ("Drawdown",              "Снижение торгового капитала от максимального значения до текущего."),
    ("Equity Curve",          "График изменения торгового счёта во времени."),
    ("Position Sizing",       "Расчёт объёма позиции на основе допустимого риска и размера стоп-лосса."),
    ("Revenge Trading",       "Импульсивные сделки с целью «отыграть» убыток; характерная форма тильта."),
    ("FOMO",                  "Fear Of Missing Out — страх пропустить движение; приводит к импульсивным входам."),
    ("Support Level",         "Ценовой уровень, где покупательское давление исторически превышало продающее."),
    ("Resistance Level",      "Ценовой уровень, где продающее давление исторически превышало покупательское."),
    ("Breakout",              "Пробой ценой значимого уровня поддержки или сопротивления."),
    ("Fibonacci Retracement", "Уровни коррекции на основе чисел Фибоначчи: 23.6%, 38.2%, 50%, 61.8%."),
    ("Head and Shoulders",    "Паттерн разворота тренда: левое плечо → голова → правое плечо."),
    ("Double Top",            "Паттерн разворота: два последовательных максимума на одном ценовом уровне."),
    ("Тильт",                 "Эмоциональное состояние, при котором нарушается торговая дисциплина и план."),
    ("Backtesting",           "Тестирование стратегии на исторических данных для оценки её эффективности."),
    ("Scalping",              "Торговый стиль с удержанием позиции от нескольких секунд до нескольких минут."),
    ("Swing Trading",         "Торговля с удержанием позиции от нескольких дней до нескольких недель."),
    ("Volume",                "Объём торгов за период; подтверждает силу ценового движения."),
    ("Liquidity",             "Ликвидность — возможность быстро войти/выйти из позиции без заметного проскальзывания."),
    ("Spread",                "Разница между ценой покупки (Ask) и ценой продажи (Bid)."),
    ("Pip",                   "Минимальный шаг изменения цены на форекс (обычно 0.0001 для пар с USD)."),
]

DEFAULT_ACHIEVEMENTS = [
    ("first_trade",         50,  "Первая сделка в журнале",             "📝"),
    ("trades_10",           75,  "10 сделок в журнале",                  "📊"),
    ("trades_50",           150, "50 сделок в журнале",                  "🏆"),
    ("streak_7_days",       100, "7 дней подряд в системе",              "🔥"),
    ("streak_30_days",      300, "30 дней подряд в системе",             "⚡"),
    ("disciplined_week",    150, "Средний балл дисциплины >80% за 5 сделок", "🎯"),
    ("chapter_complete",    75,  "Завершить первую главу курса",         "📚"),
    ("all_chapters_done",   500, "Завершить все 15 глав курса",          "🎓"),
    ("flashcard_10",        50,  "Повторить 10 флешкарт",                "🃏"),
    ("flashcard_50",        200, "Повторить 50 флешкарт",                "🧠"),
    ("quest_streak_7",      100, "Выполнить ежедневный квест 7 дней подряд", "⭐"),
    ("checklist_10",        100, "Пройти пре-трейд чек-лист 10 раз",    "✅"),
    ("setup_playbook_10",   75,  "Сохранить 10 сетапов в плейбук",       "📐"),
]

DEFAULT_QUESTS = [
    ("trade_and_emotion", "Добавить сделку с заполненными эмоциями",   1, 25),
    ("repeat_5_cards",    "Повторить 5 флешкарт",                       5, 20),
    ("read_1_chapter",    "Прочитать 1 главу курса",                    1, 30),
    ("run_checklist",     "Пройти пре-трейд ритуал",                    1, 15),
    ("add_setup",         "Добавить 1 сетап в плейбук",                 1, 20),
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
        CREATE TABLE IF NOT EXISTS xp_events (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    TEXT NOT NULL DEFAULT 'default',
            kind       TEXT NOT NULL,
            amount     INTEGER NOT NULL,
            ref_id     INTEGER,
            ts         TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_xp_events_user
            ON xp_events(user_id, ts);

        CREATE TABLE IF NOT EXISTS user_course_progress (
            user_id        TEXT NOT NULL DEFAULT 'default',
            chapter_number INTEGER NOT NULL CHECK(chapter_number BETWEEN 1 AND 15),
            is_completed   INTEGER NOT NULL DEFAULT 0,
            completed_at   TEXT,
            PRIMARY KEY (user_id, chapter_number)
        );

        CREATE TABLE IF NOT EXISTS flashcards (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            term       TEXT NOT NULL,
            definition TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS user_flashcards (
            user_id       TEXT NOT NULL DEFAULT 'default',
            card_id       INTEGER NOT NULL REFERENCES flashcards(id) ON DELETE CASCADE,
            repetitions   INTEGER NOT NULL DEFAULT 0,
            ease_factor   REAL NOT NULL DEFAULT 2.50,
            interval_days INTEGER NOT NULL DEFAULT 0,
            next_review_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, card_id)
        );

        CREATE INDEX IF NOT EXISTS idx_user_flashcards_review
            ON user_flashcards(user_id, next_review_at);

        CREATE TABLE IF NOT EXISTS user_streaks (
            user_id            TEXT NOT NULL DEFAULT 'default',
            kind               TEXT NOT NULL CHECK(kind IN ('daily_login','journal_fill','lesson_read')),
            current_streak     INTEGER NOT NULL DEFAULT 0,
            max_streak         INTEGER NOT NULL DEFAULT 0,
            freeze_count       INTEGER NOT NULL DEFAULT 0,
            last_activity_date TEXT NOT NULL DEFAULT (date('now')),
            PRIMARY KEY (user_id, kind)
        );

        CREATE TABLE IF NOT EXISTS achievements (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            code        TEXT UNIQUE NOT NULL,
            xp_reward   INTEGER NOT NULL DEFAULT 0,
            description TEXT NOT NULL DEFAULT '',
            icon        TEXT NOT NULL DEFAULT '🏅',
            metadata    TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS user_achievements (
            user_id        TEXT NOT NULL DEFAULT 'default',
            achievement_id INTEGER NOT NULL REFERENCES achievements(id) ON DELETE CASCADE,
            unlocked_at    TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, achievement_id)
        );

        CREATE TABLE IF NOT EXISTS daily_quests (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            code         TEXT UNIQUE NOT NULL,
            description  TEXT NOT NULL,
            target_count INTEGER NOT NULL DEFAULT 1,
            xp_reward    INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS user_daily_quests (
            user_id       TEXT NOT NULL DEFAULT 'default',
            quest_id      INTEGER NOT NULL REFERENCES daily_quests(id) ON DELETE CASCADE,
            quest_date    TEXT NOT NULL DEFAULT (date('now')),
            current_count INTEGER NOT NULL DEFAULT 0,
            is_completed  INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, quest_id, quest_date)
        );

        CREATE TABLE IF NOT EXISTS user_cosmetic_unlocks (
            user_id    TEXT NOT NULL DEFAULT 'default',
            item_key   TEXT NOT NULL,
            unlocked_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, item_key)
        );

        CREATE TABLE IF NOT EXISTS academy_quiz_attempt (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT NOT NULL DEFAULT 'default',
            level_id    TEXT NOT NULL,
            question_id TEXT NOT NULL,
            correct     INTEGER NOT NULL,
            attempt_ts  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_quiz_attempt_user
            ON academy_quiz_attempt(user_id, level_id);
    """)
    conn.commit()

    # Seed flashcards
    existing_fc = conn.execute("SELECT COUNT(*) FROM flashcards").fetchone()[0]
    if existing_fc == 0:
        conn.executemany(
            "INSERT INTO flashcards (term, definition) VALUES (?, ?)",
            DEFAULT_FLASHCARDS,
        )
        conn.commit()

    # Init user_flashcards for default user
    _init_user_flashcards(conn, "default")

    # Seed achievements
    existing_ach = conn.execute("SELECT COUNT(*) FROM achievements").fetchone()[0]
    if existing_ach == 0:
        conn.executemany(
            "INSERT INTO achievements (code, xp_reward, description, icon) VALUES (?,?,?,?)",
            DEFAULT_ACHIEVEMENTS,
        )
        conn.commit()

    # Seed daily quests
    existing_q = conn.execute("SELECT COUNT(*) FROM daily_quests").fetchone()[0]
    if existing_q == 0:
        conn.executemany(
            "INSERT INTO daily_quests (code, description, target_count, xp_reward) VALUES (?,?,?,?)",
            DEFAULT_QUESTS,
        )
        conn.commit()

    # Init streaks
    for kind in STREAK_KINDS:
        conn.execute(
            "INSERT OR IGNORE INTO user_streaks (user_id, kind) VALUES ('default', ?)", (kind,)
        )
    conn.commit()
    conn.close()


def _init_user_flashcards(conn: sqlite3.Connection, user_id: str) -> None:
    """Создаёт записи SM-2 для всех карточек без записи."""
    card_ids = [r[0] for r in conn.execute("SELECT id FROM flashcards").fetchall()]
    for cid in card_ids:
        conn.execute(
            "INSERT OR IGNORE INTO user_flashcards (user_id, card_id) VALUES (?,?)",
            (user_id, cid),
        )
    conn.commit()


# ── XP ────────────────────────────────────────────────────────────────────────

def award_xp(kind: str, amount: int, ref_id: int | None = None, user_id: str = "default") -> int:
    """Записывает XP-событие. Возвращает новый суммарный XP."""
    if amount <= 0:
        return get_xp_total(user_id)
    conn = _get_conn()
    conn.execute(
        "INSERT INTO xp_events (user_id, kind, amount, ref_id) VALUES (?,?,?,?)",
        (user_id, kind, amount, ref_id),
    )
    conn.commit()
    total = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM xp_events WHERE user_id=?", (user_id,)
    ).fetchone()[0]
    conn.close()
    return total


def get_xp_total(user_id: str = "default") -> int:
    conn = _get_conn()
    n = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM xp_events WHERE user_id=?", (user_id,)
    ).fetchone()[0]
    conn.close()
    return int(n)


def get_xp_weekly(user_id: str = "default") -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
    conn = _get_conn()
    n = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM xp_events WHERE user_id=? AND ts >= ?",
        (user_id, cutoff),
    ).fetchone()[0]
    conn.close()
    return int(n)


def calc_level(xp: int) -> dict:
    """Делегирует в journal_goals.evaluate_level_progression (§9.2: XP_req(L) = floor(100 × L^2.2)).

    Показатель степени в докстринге был 1.8 — устаревшее значение, не совпадавшее
    с реальной формулой в journal_goals.py:65. Исправлено 06.08.2026 вместе
    со сведением фронта (web/assets/sbf-profile.js) к этой же формуле.
    """
    from .journal_goals import evaluate_level_progression
    return evaluate_level_progression(xp)


# ── SM-2 Algorithm (§8.2) ──────────────────────────────────────────────────────

def sm2_calculate(
    repetitions: int,
    ease_factor: float,
    interval_days: int,
    quality: int,
) -> dict:
    """Точный порт алгоритма §8.2 (TypeScript calculateNextReview)."""
    quality = max(0, min(5, int(quality)))

    if quality < 3:
        repetitions = 0
        interval_days = 1
    else:
        if repetitions == 0:
            interval_days = 1
        elif repetitions == 1:
            interval_days = 6
        else:
            interval_days = math.ceil(interval_days * ease_factor)
        repetitions += 1

    new_ef = ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ease_factor = max(1.3, round(new_ef, 2))

    return {
        "repetitions": repetitions,
        "ease_factor": ease_factor,
        "interval_days": interval_days,
        "next_review_in_hours": interval_days * 24,
    }


def get_due_flashcards(user_id: str = "default", limit: int = 20) -> list[dict]:
    """Возвращает карточки, подошедшие к дате повторения."""
    _init_user_flashcards(_get_conn(), user_id)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    conn = _get_conn()
    rows = conn.execute(
        """SELECT f.id, f.term, f.definition,
                  uf.repetitions, uf.ease_factor, uf.interval_days, uf.next_review_at
           FROM user_flashcards uf
           JOIN flashcards f ON uf.card_id = f.id
           WHERE uf.user_id=? AND uf.next_review_at <= ?
           ORDER BY uf.next_review_at ASC
           LIMIT ?""",
        (user_id, now, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_flashcards(user_id: str = "default") -> list[dict]:
    """Все карточки с текущим SM-2 состоянием."""
    _init_user_flashcards(_get_conn(), user_id)
    conn = _get_conn()
    rows = conn.execute(
        """SELECT f.id, f.term, f.definition,
                  uf.repetitions, uf.ease_factor, uf.interval_days, uf.next_review_at
           FROM user_flashcards uf
           JOIN flashcards f ON uf.card_id = f.id
           WHERE uf.user_id=?
           ORDER BY uf.next_review_at ASC""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def review_flashcard(card_id: int, quality: int, user_id: str = "default") -> dict:
    """Обновляет SM-2 состояние после ответа. Начисляет XP при quality >= 3."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT repetitions, ease_factor, interval_days FROM user_flashcards WHERE user_id=? AND card_id=?",
        (user_id, card_id),
    ).fetchone()
    if not row:
        conn.execute(
            "INSERT OR IGNORE INTO user_flashcards (user_id, card_id) VALUES (?,?)", (user_id, card_id)
        )
        conn.commit()
        row = conn.execute(
            "SELECT repetitions, ease_factor, interval_days FROM user_flashcards WHERE user_id=? AND card_id=?",
            (user_id, card_id),
        ).fetchone()

    new_state = sm2_calculate(
        int(row["repetitions"]),
        float(row["ease_factor"]),
        int(row["interval_days"]),
        quality,
    )
    next_review = (
        datetime.now(timezone.utc) + timedelta(hours=new_state["next_review_in_hours"])
    ).strftime("%Y-%m-%dT%H:%M:%S")

    conn.execute(
        """UPDATE user_flashcards SET repetitions=?, ease_factor=?, interval_days=?, next_review_at=?
           WHERE user_id=? AND card_id=?""",
        (
            new_state["repetitions"],
            new_state["ease_factor"],
            new_state["interval_days"],
            next_review,
            user_id,
            card_id,
        ),
    )
    conn.commit()
    conn.close()

    xp_this = 0
    if quality >= 3:
        xp_this = XP_FLASHCARD_SESSION
        award_xp("flashcard_review", xp_this, card_id, user_id)
        process_quest_event(user_id, "card_reviewed")
        check_achievements(user_id)

    new_state["next_review_at"] = next_review
    new_state["xp_awarded"] = xp_this
    new_state["total_xp"] = get_xp_total(user_id)
    return new_state


def get_quiz_cards(user_id: str = "default", count: int = 5) -> list[dict]:
    """Выбирает N случайных карточек для практики."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT f.id, f.term, f.definition
           FROM flashcards f
           ORDER BY RANDOM()
           LIMIT ?""",
        (count,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Course Progress ───────────────────────────────────────────────────────────

def get_course_progress(user_id: str = "default") -> dict:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT chapter_number, is_completed, completed_at FROM user_course_progress WHERE user_id=?",
        (user_id,),
    ).fetchall()
    conn.close()
    chapters = {r["chapter_number"]: dict(r) for r in rows}
    total_done = sum(1 for c in chapters.values() if c["is_completed"])
    return {
        "chapters": chapters,
        "total_chapters": TOTAL_CHAPTERS,
        "completed_count": total_done,
        "progress_pct": round(total_done / TOTAL_CHAPTERS * 100, 1),
    }


def complete_chapter(chapter_number: int, user_id: str = "default") -> dict:
    """Отмечает главу пройденной, начисляет XP. Idempotent."""
    if not (1 <= chapter_number <= TOTAL_CHAPTERS):
        return {"error": "chapter_number out of range"}

    conn = _get_conn()
    existing = conn.execute(
        "SELECT is_completed FROM user_course_progress WHERE user_id=? AND chapter_number=?",
        (user_id, chapter_number),
    ).fetchone()
    conn.close()

    if existing and existing["is_completed"]:
        return {"ok": True, "xp_awarded": 0, "already_done": True}

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    conn = _get_conn()
    conn.execute(
        """INSERT INTO user_course_progress (user_id, chapter_number, is_completed, completed_at)
           VALUES (?,?,1,?)
           ON CONFLICT(user_id, chapter_number) DO UPDATE SET is_completed=1, completed_at=?""",
        (user_id, chapter_number, now, now),
    )
    conn.commit()

    total_done = conn.execute(
        "SELECT COUNT(*) FROM user_course_progress WHERE user_id=? AND is_completed=1",
        (user_id,),
    ).fetchone()[0]
    conn.close()

    xp_awarded = award_xp("chapter_complete", XP_CHAPTER_COMPLETE, chapter_number, user_id)
    if total_done == TOTAL_CHAPTERS:
        xp_awarded = award_xp("all_chapters_done", XP_ALL_CHAPTERS_DONE, None, user_id)

    update_streak(user_id, "lesson_read")
    process_quest_event(user_id, "chapter_read")
    check_achievements(user_id)

    return {
        "ok": True,
        "xp_awarded": xp_awarded,
        "all_done": total_done == TOTAL_CHAPTERS,
    }


def reset_course_progress(user_id: str) -> dict:
    """Ручной сброс прогресса по главам (кнопка "сбросить" в /edu — раньше
    висела на мёртвом localStorage-ключе sbf_edu_done, теперь на реальных
    данных, см. SPEC_chart_fixes_and_staged_signup.md §5 п.7)."""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM user_course_progress WHERE user_id=?", (user_id,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


def migrate_anon_progress(anon_id: str, user_id: str) -> None:
    """SPEC_chart_fixes_and_staged_signup.md §5, Этап 0: переносит прогресс
    анонимного читателя (anon_id — токен из web/assets/sbf-anon.js, до этого
    момента жил в user_course_progress как обычный user_id) на настоящего
    пользователя при регистрации. INSERT OR IGNORE — если реальный юзер уже
    сам отмечал главы (например, читал раньше залогиненным с другого
    устройства), эта, более ранняя, запись не затирается анонимной."""
    if not anon_id or not user_id or anon_id == user_id:
        return
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO user_course_progress
               (user_id, chapter_number, is_completed, completed_at)
               SELECT ?, chapter_number, is_completed, completed_at
               FROM user_course_progress WHERE user_id=?""",
            (user_id, anon_id),
        )
        conn.execute("DELETE FROM user_course_progress WHERE user_id=?", (anon_id,))
        conn.commit()
    finally:
        conn.close()


def record_quiz_attempt(level_id: str, question_id: str, correct: bool, user_id: str = "default") -> dict:
    """Пишет одну попытку теста на воспроизведение (SPEC_academy_level1_interactivity.md
    §1.4). Каждая попытка — новая строка, ничего не перезаписывается (задел
    на будущую аналитику "в чём чаще ошибаются")."""
    conn = _get_conn()
    conn.execute(
        """INSERT INTO academy_quiz_attempt (user_id, level_id, question_id, correct)
           VALUES (?,?,?,?)""",
        (user_id, level_id, question_id, 1 if correct else 0),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# ── Streaks ───────────────────────────────────────────────────────────────────

def get_streaks(user_id: str = "default") -> dict:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM user_streaks WHERE user_id=?", (user_id,)
    ).fetchall()
    conn.close()
    return {r["kind"]: dict(r) for r in rows}


def update_streak(user_id: str, kind: str) -> dict:
    """
    Обновляет стрик за сегодня. Если последняя активность была вчера — +1.
    Если старше — сброс (с заморозкой если есть).
    """
    if kind not in STREAK_KINDS:
        return {}
    today = date.today().isoformat()
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM user_streaks WHERE user_id=? AND kind=?", (user_id, kind)
    ).fetchone()

    if not row:
        conn.execute(
            "INSERT INTO user_streaks (user_id, kind, current_streak, max_streak, last_activity_date) VALUES (?,?,1,1,?)",
            (user_id, kind, today),
        )
        conn.commit()
        conn.close()
        return {"current_streak": 1, "max_streak": 1}

    last = row["last_activity_date"]
    if last == today:
        conn.close()
        return dict(row)

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    current = int(row["current_streak"])
    max_s = int(row["max_streak"])
    freeze = int(row["freeze_count"])

    if last == yesterday:
        current += 1
    elif last < yesterday and freeze > 0:
        # Заморозка: сохраняем стрик, тратим заморозку (§8.5 compliance)
        freeze -= 1
        current += 1
    else:
        # Сброс
        current = 1

    max_s = max(max_s, current)

    # Бонус за 7-дневный стрик
    if current % 7 == 0:
        award_xp("streak_milestone", XP_STREAK_7_DAYS * (current // 7), None, user_id)
        freeze = min(freeze + 1, 3)  # Award freeze, cap at 3
        check_achievements(user_id)

    conn.execute(
        """UPDATE user_streaks SET current_streak=?, max_streak=?, freeze_count=?, last_activity_date=?
           WHERE user_id=? AND kind=?""",
        (current, max_s, freeze, today, user_id, kind),
    )
    conn.commit()
    conn.close()
    return {"current_streak": current, "max_streak": max_s, "freeze_count": freeze}


def use_streak_freeze(user_id: str, kind: str) -> dict:
    """Вручную применяет заморозку стрика."""
    if kind not in STREAK_KINDS:
        return {"error": "unknown kind"}
    conn = _get_conn()
    row = conn.execute(
        "SELECT freeze_count FROM user_streaks WHERE user_id=? AND kind=?", (user_id, kind)
    ).fetchone()
    if not row or row["freeze_count"] <= 0:
        conn.close()
        return {"error": "no freezes available"}
    conn.execute(
        "UPDATE user_streaks SET freeze_count=freeze_count-1, last_activity_date=? WHERE user_id=? AND kind=?",
        (date.today().isoformat(), user_id, kind),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "freeze_used": True}


# ── Quests (§8.3) ─────────────────────────────────────────────────────────────

def _ensure_today_quests(user_id: str, conn: sqlite3.Connection) -> None:
    today = date.today().isoformat()
    quests = conn.execute("SELECT id FROM daily_quests").fetchall()
    for q in quests:
        conn.execute(
            "INSERT OR IGNORE INTO user_daily_quests (user_id, quest_id, quest_date) VALUES (?,?,?)",
            (user_id, q["id"], today),
        )
    conn.commit()


def get_active_quests(user_id: str = "default") -> list[dict]:
    today = date.today().isoformat()
    conn = _get_conn()
    _ensure_today_quests(user_id, conn)
    rows = conn.execute(
        """SELECT udq.quest_id, dq.code, dq.description, dq.target_count, dq.xp_reward,
                  udq.current_count, udq.is_completed
           FROM user_daily_quests udq
           JOIN daily_quests dq ON udq.quest_id = dq.id
           WHERE udq.user_id=? AND udq.quest_date=?
           ORDER BY udq.quest_id""",
        (user_id, today),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def process_quest_event(
    user_id: str,
    event_type: str,
    meta: dict | None = None,
) -> list[dict]:
    """
    Обрабатывает событие (§8.3 processQuestEvent).
    event_type: 'trade_logged' | 'card_reviewed' | 'chapter_read' | 'checklist_run' | 'setup_added'
    """
    meta = meta or {}
    today = date.today().isoformat()
    conn = _get_conn()
    _ensure_today_quests(user_id, conn)

    rows = conn.execute(
        """SELECT udq.rowid, udq.quest_id, dq.code, dq.target_count, dq.xp_reward,
                  udq.current_count, udq.is_completed
           FROM user_daily_quests udq
           JOIN daily_quests dq ON udq.quest_id = dq.id
           WHERE udq.user_id=? AND udq.quest_date=? AND udq.is_completed=0""",
        (user_id, today),
    ).fetchall()

    newly_completed = []
    pending_xp = []  # (kind, amount, ref_id) — начисляем после закрытия соединения
    for row in rows:
        increment = 0
        code = row["code"]
        if code == "trade_and_emotion" and event_type == "trade_logged" and meta.get("hasEmotions"):
            increment = 1
        elif code == "repeat_5_cards" and event_type == "card_reviewed":
            increment = 1
        elif code == "read_1_chapter" and event_type == "chapter_read":
            increment = 1
        elif code == "run_checklist" and event_type == "checklist_run":
            increment = 1
        elif code == "add_setup" and event_type == "setup_added":
            increment = 1

        if increment > 0:
            new_count = min(row["current_count"] + increment, row["target_count"])
            completed = int(new_count >= row["target_count"])
            conn.execute(
                "UPDATE user_daily_quests SET current_count=?, is_completed=? WHERE rowid=?",
                (new_count, completed, row["rowid"]),
            )
            if completed:
                newly_completed.append({"code": code, "xp_reward": row["xp_reward"]})
                pending_xp.append(("quest_complete", row["xp_reward"], row["quest_id"]))

    if newly_completed:
        conn.commit()

    conn.close()

    for kind_, amount_, ref_ in pending_xp:
        award_xp(kind_, amount_, ref_, user_id)

    return newly_completed


# ── Achievements ──────────────────────────────────────────────────────────────

def get_achievements(user_id: str = "default") -> dict:
    conn = _get_conn()
    unlocked = {
        r["achievement_id"]
        for r in conn.execute(
            "SELECT achievement_id FROM user_achievements WHERE user_id=?", (user_id,)
        ).fetchall()
    }
    all_ach = conn.execute(
        "SELECT id, code, xp_reward, description, icon FROM achievements ORDER BY xp_reward ASC"
    ).fetchall()
    conn.close()
    return {
        "unlocked": [
            dict(a) | {"unlocked": True}
            for a in all_ach
            if a["id"] in unlocked
        ],
        "locked": [
            dict(a) | {"unlocked": False}
            for a in all_ach
            if a["id"] not in unlocked
        ],
    }


def unlock_achievement(code: str, user_id: str = "default") -> dict:
    conn = _get_conn()
    ach = conn.execute("SELECT * FROM achievements WHERE code=?", (code,)).fetchone()
    if not ach:
        conn.close()
        return {"error": "unknown achievement"}
    already = conn.execute(
        "SELECT 1 FROM user_achievements WHERE user_id=? AND achievement_id=?",
        (user_id, ach["id"]),
    ).fetchone()
    if already:
        conn.close()
        return {"ok": True, "already_unlocked": True}
    conn.execute(
        "INSERT INTO user_achievements (user_id, achievement_id) VALUES (?,?)",
        (user_id, ach["id"]),
    )
    conn.commit()
    conn.close()
    award_xp("achievement_unlocked", ach["xp_reward"], ach["id"], user_id)
    return {
        "ok": True,
        "code": code,
        "xp_awarded": ach["xp_reward"],
        "description": ach["description"],
        "icon": ach["icon"],
    }


def check_achievements(user_id: str = "default") -> list[str]:
    """Автопроверка условий. Возвращает коды только что разблокированных значков."""
    newly = []
    conn = _get_conn()

    # Считаем факты для проверки условий
    trade_count = conn.execute(
        "SELECT COUNT(*) FROM trades WHERE user_id=?", (user_id,)
    ).fetchone()[0]

    chapters_done = conn.execute(
        "SELECT COUNT(*) FROM user_course_progress WHERE user_id=? AND is_completed=1", (user_id,)
    ).fetchone()[0]

    fc_reviewed = conn.execute(
        "SELECT COALESCE(SUM(amount)/5,0) FROM xp_events WHERE user_id=? AND kind='flashcard_review'",
        (user_id,),
    ).fetchone()[0]

    checklist_runs = conn.execute(
        "SELECT COUNT(*) FROM checklist_runs WHERE user_id=? AND passed=1", (user_id,)
    ).fetchone()[0] if _table_exists(conn, "checklist_runs") else 0

    setup_count = conn.execute(
        "SELECT COUNT(*) FROM user_setups WHERE user_id=?", (user_id,)
    ).fetchone()[0] if _table_exists(conn, "user_setups") else 0

    streak_row = conn.execute(
        "SELECT MAX(current_streak) FROM user_streaks WHERE user_id=?", (user_id,)
    ).fetchone()[0] or 0

    # Дисциплина за последние 5 сделок
    disc_avg = _calc_avg_discipline(conn, user_id, last_n=5)

    conn.close()

    conditions = {
        "first_trade":      trade_count >= 1,
        "trades_10":        trade_count >= 10,
        "trades_50":        trade_count >= 50,
        "streak_7_days":    streak_row >= 7,
        "streak_30_days":   streak_row >= 30,
        "disciplined_week": disc_avg is not None and disc_avg >= 80,
        "chapter_complete": chapters_done >= 1,
        "all_chapters_done":chapters_done >= TOTAL_CHAPTERS,
        "flashcard_10":     fc_reviewed >= 10,
        "flashcard_50":     fc_reviewed >= 50,
        "checklist_10":     checklist_runs >= 10,
        "setup_playbook_10":setup_count >= 10,
    }

    for code, met in conditions.items():
        if met:
            result = unlock_achievement(code, user_id)
            if result.get("ok") and not result.get("already_unlocked"):
                newly.append(code)

    return newly


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _calc_avg_discipline(conn: sqlite3.Connection, user_id: str, last_n: int = 5) -> float | None:
    if not _table_exists(conn, "trade_discipline_eval"):
        return None
    rows = conn.execute(
        """SELECT SUM(dc.weight) as tw,
                  SUM(CASE WHEN te.passed=1 THEN dc.weight ELSE 0 END) as pw
           FROM (SELECT id FROM trades WHERE user_id=? ORDER BY close_ts DESC LIMIT ?) t
           JOIN trade_discipline_eval te ON t.id = te.trade_id
           JOIN discipline_config dc ON dc.user_id=? AND dc.criterion = te.criterion AND dc.enabled=1""",
        (user_id, last_n, user_id),
    ).fetchone()
    if not rows or not rows["tw"]:
        return None
    return round(rows["pw"] / rows["tw"] * 100, 1)


# ── Cosmetics (§8.5 — строго за XP, не за деньги) ────────────────────────────

def get_cosmetics(user_id: str = "default") -> dict:
    total_xp = get_xp_total(user_id)
    conn = _get_conn()
    unlocked_keys = {
        r["item_key"]
        for r in conn.execute(
            "SELECT item_key FROM user_cosmetic_unlocks WHERE user_id=?", (user_id,)
        ).fetchall()
    }
    conn.close()

    # Авто-разблокировка по порогу XP
    newly_unlocked = []
    conn = _get_conn()
    for item in COSMETIC_ITEMS:
        key = item["item_key"]
        if key not in unlocked_keys and total_xp >= item["unlock_xp"]:
            conn.execute(
                "INSERT OR IGNORE INTO user_cosmetic_unlocks (user_id, item_key) VALUES (?,?)",
                (user_id, key),
            )
            unlocked_keys.add(key)
            newly_unlocked.append(key)
    if newly_unlocked:
        conn.commit()
    conn.close()

    items_with_status = [
        {**item, "unlocked": item["item_key"] in unlocked_keys}
        for item in COSMETIC_ITEMS
    ]
    return {
        "items": items_with_status,
        "newly_unlocked": newly_unlocked,
        "total_xp": total_xp,
    }


# ── Leaderboard (§8.4.1) — opt-in, только дисциплина, без финансовых данных ──

def get_leaderboard(user_id: str = "default") -> dict:
    """
    В одиночном режиме возвращает только данные текущего пользователя.
    Финансовые показатели (PnL, баланс) не передаются — только дисциплина и XP (§8.4.1).
    """
    conn = _get_conn()
    disc_score = _calc_avg_discipline(conn, user_id, last_n=20)
    weekly_xp = get_xp_weekly(user_id)
    trade_count = conn.execute(
        "SELECT COUNT(*) FROM trades WHERE user_id=? AND close_ts >= datetime('now','-7 days')",
        (user_id,),
    ).fetchone()[0]
    conn.close()

    own_entry = {
        "user_id": user_id,
        "username_masked": "Вы",
        "avg_discipline_score": disc_score,
        "weekly_xp_gained": weekly_xp,
        "trade_count_week": trade_count,
        "eligible": trade_count >= 5,
    }
    return {
        "leaderboard": [own_entry] if own_entry["eligible"] else [],
        "own_stats": own_entry,
        "mode": "single_user",
        "note": "Публичный рейтинг доступен в сетевом режиме (§8.4.1)",
    }


# ── All-in-one overview ───────────────────────────────────────────────────────

def get_overview(user_id: str = "default") -> dict:
    """Все данные геймификации одним запросом для начальной загрузки."""
    xp = get_xp_total(user_id)
    level_info = calc_level(xp)
    return {
        "xp": level_info,
        "streaks": get_streaks(user_id),
        "quests": get_active_quests(user_id),
        "achievements": get_achievements(user_id),
        "course": get_course_progress(user_id),
        "due_flashcards_count": len(get_due_flashcards(user_id, limit=100)),
        "cosmetics": get_cosmetics(user_id),
    }



# ── Event hooks (вызываются из serve.py после ключевых действий) ──────────────

def on_trade_added(trade_id: int, pnl_r: float = 0.0, user_id: str = "default") -> dict:
    """
    Начисляет XP за факт записи сделки (trade_logged = 10 XP).
    PnL не влияет на XP (§9.2).
    Обновляет journal_fill стрик, квесты, цели.
    """
    award_xp("trade_logged", XP_TRADE_LOGGED, trade_id, user_id)
    update_streak(user_id, "journal_fill")
    update_streak(user_id, "daily_login")
    process_quest_event(user_id, "trade_logged")
    check_achievements(user_id)
    # Обновляем цели (в т.ч. max_risk_per_trade)
    try:
        from .journal_goals import update_goal_for_trade
        update_goal_for_trade(user_id, pnl_r)
    except Exception:
        pass
    return {"xp_awarded": XP_TRADE_LOGGED}


def on_meta_saved(
    trade_id: int,
    followed_plan: bool,
    has_emotions: bool = True,
    user_id: str = "default",
) -> dict:
    """
    Начисляет XP за заполнение мета-данных (15 XP) и за дисциплину.
    trade_disciplined = 100 XP если followed_plan=True,
    trade_undisciplined = 5 XP если нарушение (§9.2 compliance rule).
    """
    xp_meta = XP_TRADE_META_FILLED
    award_xp("trade_metadata_filled", xp_meta, trade_id, user_id)

    if followed_plan:
        award_xp("trade_disciplined", XP_TRADE_DISCIPLINED, trade_id, user_id)
        disc_xp = XP_TRADE_DISCIPLINED
    else:
        award_xp("trade_undisciplined", XP_TRADE_UNDISCIPLINED, trade_id, user_id)
        disc_xp = XP_TRADE_UNDISCIPLINED

    if has_emotions:
        process_quest_event(user_id, "trade_logged", {"hasEmotions": True})

    check_achievements(user_id)
    try:
        from .journal_goals import update_all_goals
        update_all_goals(user_id)
    except Exception:
        pass

    return {"xp_meta": xp_meta, "xp_discipline": disc_xp}


def on_checklist_passed(run_id: int, user_id: str = "default") -> dict:
    """Начисляет XP за пройденный чек-лист (checklist_passed = 20 XP)."""
    award_xp("checklist_passed", XP_CHECKLIST_PASSED, run_id, user_id)
    process_quest_event(user_id, "checklist_run")
    check_achievements(user_id)
    return {"xp_awarded": XP_CHECKLIST_PASSED}


ensure_schema()
