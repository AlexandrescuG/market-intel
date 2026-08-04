"""
journal_meta.py — Поведенческое зеркало трейдера (Part 2).

Расширяет trades таблицей journal_meta (1:1).
Содержит: смарт-очередь, детекторы девиаций, движок инсайтов.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

_DB = Path(__file__).parent.parent / "data" / "journal.db"

EMOTIONS = ('calmness', 'fomo', 'revenge', 'confidence', 'fear', 'greed', 'impatience')
SMART_QUEUE_N = 5   # порог переключения на аномальную сортировку


# ── Соединение ────────────────────────────────────────────────────────────────
def _get_conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── Схема (§2.1) ──────────────────────────────────────────────────────────────
def ensure_schema() -> None:
    emo_check = "(" + ",".join(f"'{e}'" for e in EMOTIONS) + ")"
    conn = _get_conn()
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS journal_meta (
            trade_id   INTEGER PRIMARY KEY
                REFERENCES trades(id) ON DELETE CASCADE,
            setup_tag  TEXT NOT NULL DEFAULT '',
            emo_open   TEXT NOT NULL DEFAULT 'calmness'
                CHECK(emo_open  IN {emo_check}),
            emo_close  TEXT NOT NULL DEFAULT 'calmness'
                CHECK(emo_close IN {emo_check}),
            followed_plan INTEGER NOT NULL DEFAULT 1,
            note       TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_journal_meta_setup
            ON journal_meta(setup_tag);
    """)
    conn.commit()
    conn.close()


# ── CRUD ──────────────────────────────────────────────────────────────────────
def save_meta(
    trade_id: int,
    setup_tag: str,
    emo_open: str,
    emo_close: str,
    followed_plan: bool,
    note: str = "",
) -> None:
    if emo_open not in EMOTIONS or emo_close not in EMOTIONS:
        raise ValueError(f"Неверная эмоция. Допустимо: {EMOTIONS}")
    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO journal_meta
           (trade_id, setup_tag, emo_open, emo_close, followed_plan, note, updated_at)
           VALUES (?,?,?,?,?,?,datetime('now'))""",
        (trade_id, setup_tag.strip(), emo_open, emo_close,
         1 if followed_plan else 0, note),
    )
    conn.commit()
    conn.close()


def get_meta(trade_id: int) -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM journal_meta WHERE trade_id=?", (trade_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_unjournaled(user_id: str = "default") -> list[dict]:
    """Сделки без записи в journal_meta."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT t.id, t.symbol, t.dir, t.size, t.pnl, t.pnl_r,
                  t.entry_price, t.exit_price, t.open_ts, t.close_ts
           FROM trades t
           LEFT JOIN journal_meta jm ON t.id = jm.trade_id
           WHERE t.user_id=? AND jm.trade_id IS NULL
           ORDER BY t.close_ts DESC""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── SmartJournalQueue (§2.2) ──────────────────────────────────────────────────
def sort_smart_queue(trades: list[dict]) -> list[dict]:
    """
    Если незаполненных > N: сортируем по аномальному весу (z-score size×1.5 + pnl×2.0).
    Иначе: хронологически (новые первыми).
    """
    if not trades:
        return []
    if len(trades) <= SMART_QUEUE_N:
        return sorted(trades, key=lambda t: t.get("close_ts", ""), reverse=True)

    sizes = [t["size"]       for t in trades]
    pnls  = [abs(t["pnl"])   for t in trades]
    n     = len(trades)

    mean_sz = sum(sizes) / n
    mean_pn = sum(pnls)  / n
    std_sz  = (sum((s - mean_sz) ** 2 for s in sizes) / n) ** 0.5 or 1.0
    std_pn  = (sum((p - mean_pn) ** 2 for p in pnls)  / n) ** 0.5 or 1.0

    def weight(t: dict) -> float:
        z_sz = abs(t["size"]       - mean_sz) / std_sz
        z_pn = abs(abs(t["pnl"])   - mean_pn) / std_pn
        return z_sz * 1.5 + z_pn * 2.0

    return sorted(trades, key=weight, reverse=True)


# ── Behavioral Metrics (§2.3) ─────────────────────────────────────────────────
def get_setup_emotion_metrics(user_id: str = "default") -> list[dict]:
    """
    Математическое ожидание и win rate по сетапам и эмоциям.
    Только группы с ≥3 сделками.
    """
    conn = _get_conn()
    rows = conn.execute(
        """SELECT
               jm.setup_tag,
               jm.emo_open,
               COUNT(t.id) AS total_trades,
               ROUND(100.0 * COUNT(CASE WHEN t.pnl > 0 THEN 1 END)
                     / COUNT(t.id), 2)            AS winrate_percent,
               ROUND(AVG(t.pnl_r), 4)             AS mathematical_expectancy_r,
               ROUND(AVG(CASE WHEN t.pnl > 0  THEN t.pnl_r END), 2) AS avg_win_r,
               ROUND(AVG(CASE WHEN t.pnl <= 0 THEN t.pnl_r END), 2) AS avg_loss_r
           FROM trades t
           JOIN journal_meta jm ON t.id = jm.trade_id
           WHERE t.user_id = ?
           GROUP BY jm.setup_tag, jm.emo_open
           HAVING COUNT(t.id) >= 3
           ORDER BY mathematical_expectancy_r DESC""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_emotion_metrics(user_id: str = "default") -> list[dict]:
    """Агрегация по каждой эмоции входа (все сетапы вместе)."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT
               jm.emo_open,
               COUNT(t.id) AS total_trades,
               ROUND(100.0 * COUNT(CASE WHEN t.pnl > 0 THEN 1 END)
                     / COUNT(t.id), 2) AS winrate_percent,
               ROUND(AVG(t.pnl_r), 4) AS mathematical_expectancy_r
           FROM trades t
           JOIN journal_meta jm ON t.id = jm.trade_id
           WHERE t.user_id = ?
           GROUP BY jm.emo_open
           ORDER BY mathematical_expectancy_r DESC""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Revenge Cluster Detector (§2.4.1) ─────────────────────────────────────────
def _parse_ts(s: str) -> float:
    try:
        return datetime.fromisoformat(s.replace(" ", "T")).timestamp()
    except Exception:
        return 0.0


def detect_revenge_clusters(user_id: str = "default") -> dict:
    """
    Выявляет серийные сделки после убытка: интервал ≤30 мин, лот ≥ предыдущего.
    Кластер засчитывается при ≥3 сделках.
    """
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, open_ts, close_ts, pnl, size FROM trades "
        "WHERE user_id=? ORDER BY open_ts ASC",
        (user_id,),
    ).fetchall()
    conn.close()

    trades = [dict(r) for r in rows]
    cluster_ids: set[int] = set()

    for i in range(1, len(trades)):
        prev = trades[i - 1]
        curr = trades[i]
        if prev["pnl"] < 0:
            prev_close = _parse_ts(prev["close_ts"])
            curr_open  = _parse_ts(curr["open_ts"])
            diff_min   = (curr_open - prev_close) / 60
            if 0 < diff_min <= 30 and curr["size"] >= prev["size"]:
                cluster_ids.add(prev["id"])
                cluster_ids.add(curr["id"])

    cluster_list = sorted(cluster_ids)
    return {
        "is_revenge_cluster": len(cluster_list) >= 3,
        "trade_ids": cluster_list,
    }


# ── Holding Duration Analysis (§2.4.2) ───────────────────────────────────────
def analyze_holding_duration(user_id: str = "default") -> dict:
    """
    Сравнивает среднее время удержания прибыльных vs убыточных позиций.
    Флаг «пересиживание» если avg_loss > avg_win * 1.4.
    """
    conn = _get_conn()
    rows = conn.execute(
        "SELECT pnl, open_ts, close_ts FROM trades WHERE user_id=?",
        (user_id,),
    ).fetchall()
    conn.close()

    win_dur:  list[float] = []
    loss_dur: list[float] = []

    for r in rows:
        try:
            open_dt  = datetime.fromisoformat(r["open_ts"].replace(" ", "T"))
            close_dt = datetime.fromisoformat(r["close_ts"].replace(" ", "T"))
            dur_min  = (close_dt - open_dt).total_seconds() / 60
            if dur_min > 0:
                (win_dur if r["pnl"] > 0 else loss_dur).append(dur_min)
        except Exception:
            pass

    avg_win  = sum(win_dur)  / len(win_dur)  if win_dur  else 0.0
    avg_loss = sum(loss_dur) / len(loss_dur) if loss_dur else 0.0
    overstay = avg_win > 0 and avg_loss > avg_win * 1.4

    return {
        "avg_win_min":    round(avg_win, 1),
        "avg_loss_min":   round(avg_loss, 1),
        "overstaying":    overstay,
        "ratio":          round(avg_loss / avg_win, 2) if avg_win > 0 else None,
    }


# ── Последовательности (after-loss / after-win) ───────────────────────────────
def get_winrate_sequences(user_id: str = "default") -> dict:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT pnl FROM trades WHERE user_id=? ORDER BY close_ts ASC",
        (user_id,),
    ).fetchall()
    conn.close()

    al_wins = al_total = aw_wins = aw_total = 0
    pnls = [r["pnl"] for r in rows]

    for i in range(1, len(pnls)):
        if pnls[i - 1] < 0:
            al_total += 1
            if pnls[i] > 0:
                al_wins += 1
        else:
            aw_total += 1
            if pnls[i] > 0:
                aw_wins += 1

    return {
        "after_loss": round(al_wins / al_total * 100, 1) if al_total else 0.0,
        "after_win":  round(aw_wins / aw_total * 100, 1) if aw_total else 0.0,
    }


def get_revenge_expectancy(user_id: str = "default") -> float:
    """Среднее pnl_r для сделок с emo_open='revenge'."""
    conn = _get_conn()
    row = conn.execute(
        """SELECT AVG(t.pnl_r) FROM trades t
           JOIN journal_meta jm ON t.id = jm.trade_id
           WHERE t.user_id=? AND jm.emo_open='revenge'""",
        (user_id,),
    ).fetchone()
    conn.close()
    val = row[0]
    return round(val, 4) if val is not None else 0.0


# ── Insight Engine (§2.5) ─────────────────────────────────────────────────────
def generate_insights(metrics: dict) -> list[str]:
    """
    Детерминированный генератор инсайтов.
    Только прошедшее время. Без предиктивных рекомендаций (§2.6).
    """
    insights: list[str] = []

    after_loss = metrics.get("winrate_after_loss", 0.0)
    after_win  = metrics.get("winrate_after_win",  0.0)
    revenge_r  = metrics.get("revenge_expectancy_r", 0.0)
    best_setup = metrics.get("best_setup", "")
    best_exp   = metrics.get("best_setup_expectancy", 0.0)
    overstay   = metrics.get("overstaying", False)
    ratio      = metrics.get("holding_ratio")

    if after_win > 0 and after_loss < after_win * 0.8:
        diff = round(after_win - after_loss, 1)
        insights.append(
            f"После фиксации убытка ваш винрейт падал на {diff}% "
            f"({after_loss:.1f}% vs {after_win:.1f}% после прибыли)."
        )

    if revenge_r < 0:
        insights.append(
            f"Сделки с эмоцией «Месть» принесли средний убыток "
            f"{abs(revenge_r):.2f} R на сделку."
        )

    if best_setup and best_exp > 0:
        insights.append(
            f"Лучший исторический сетап: «{best_setup}» — "
            f"мат. ожидание +{best_exp:.2f} R."
        )

    if overstay and ratio:
        insights.append(
            f"Убыточные позиции удерживались в {ratio:.1f}× дольше прибыльных "
            f"(признак пересиживания убытков)."
        )

    return insights


# ── Агрегированный ответ для API ──────────────────────────────────────────────
def get_behavioral_data(user_id: str = "default") -> dict:
    unjournaled    = list_unjournaled(user_id)
    smart_queue    = sort_smart_queue(unjournaled)
    setup_metrics  = get_setup_emotion_metrics(user_id)
    emotion_metrics = get_emotion_metrics(user_id)
    revenge        = detect_revenge_clusters(user_id)
    holding        = analyze_holding_duration(user_id)
    sequences      = get_winrate_sequences(user_id)
    revenge_r      = get_revenge_expectancy(user_id)

    best = max(setup_metrics, key=lambda x: x["mathematical_expectancy_r"], default=None)

    insights = generate_insights({
        "winrate_after_loss":     sequences["after_loss"],
        "winrate_after_win":      sequences["after_win"],
        "revenge_expectancy_r":   revenge_r,
        "best_setup":             best["setup_tag"]               if best else "",
        "best_setup_expectancy":  best["mathematical_expectancy_r"] if best else 0.0,
        "overstaying":            holding["overstaying"],
        "holding_ratio":          holding["ratio"],
    })

    return {
        "queue_count":    len(unjournaled),
        "queue_trades":   smart_queue[:10],
        "setup_metrics":  setup_metrics,
        "emotion_metrics": emotion_metrics,
        "revenge_clusters": revenge,
        "holding_duration": holding,
        "sequences":       sequences,
        "insights":        insights,
    }


ensure_schema()
