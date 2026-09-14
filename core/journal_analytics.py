"""
journal_analytics.py — Аналитика: «Цена недисциплины» + разбор по сетапам.

Все цифры — R-кратные, % дисциплины. Никаких слов «прибыль/доход/сигнал».
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DB = Path(__file__).parent.parent / "data" / "journal.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_DB), timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def ensure_schema() -> None:
    c = _conn()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS trade_violations (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
            rule_key TEXT NOT NULL,
            ts       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_tv_trade ON trade_violations(trade_id);
    """)
    c.commit()
    c.close()


def log_violation(trade_id: int, rule_key: str) -> None:
    """Зафиксировать нарушение правила для сделки."""
    c = _conn()
    c.execute(
        "INSERT OR IGNORE INTO trade_violations(trade_id, rule_key) VALUES(?,?)",
        (trade_id, rule_key),
    )
    c.commit()
    c.close()


def _period_where(period: str) -> tuple[str, list]:
    """Вернуть SQL-фрагмент WHERE и аргументы для фильтра периода."""
    period = period.lower().strip()
    now = datetime.now(timezone.utc)
    if period.endswith("d") and period[:-1].isdigit():
        days = int(period[:-1])
        since = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        return "AND t.close_ts >= ?", [since]
    if period == "month":
        since = now.replace(day=1, hour=0, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%S")
        return "AND t.close_ts >= ?", [since]
    if period.endswith("q") or period in ("quarter", "q"):
        month = ((now.month - 1) // 3) * 3 + 1
        since = now.replace(month=month, day=1, hour=0, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%S")
        return "AND t.close_ts >= ?", [since]
    # 'all' или неизвестный — без ограничения
    return "", []


def get_discipline_cost(user_id: str = "default", period: str = "90d") -> dict:
    """
    Отчёт «Цена недисциплины».

    Источник «нарушений»: trade_violations ИЛИ trade_discipline_eval (passed=0).
    Возвращает trades_clean/violated + discipline_cost_r.
    """
    where, args = _period_where(period)
    c = _conn()

    # Сделки с хотя бы одним нарушением по discipline eval
    violated_ids_q = c.execute(
        f"""SELECT DISTINCT t.id, t.pnl_r
            FROM trades t
            LEFT JOIN trade_discipline_eval tde ON t.id = tde.trade_id AND tde.passed = 0
            LEFT JOIN trade_violations tv ON t.id = tv.trade_id
            WHERE t.user_id = ?
              AND (tde.trade_id IS NOT NULL OR tv.trade_id IS NOT NULL)
              {where}""",
        [user_id] + args,
    ).fetchall()

    # 🔴 Псевдоним t обязателен: _period_where отдаёт «AND t.close_ts >= ?».
    # Без него запрос падал с «no such column: t.close_ts», исключение
    # уходило из обработчика наружу и рвало соединение — снаружи это 502.
    # Найдено обходом сайта на живом телефоне 14.09.2026: /journal стабильно
    # получал 502 на discipline-cost и setups. В браузере разработчика этого
    # не видно, пока в дневнике нет ни одной сделки: при user_id без записей
    # до этого запроса дело доходит всё равно, а вот заметить 502 в консоли
    # на десктопе было некому — страница молча показывала пустой блок.
    all_trades_q = c.execute(
        f"SELECT t.id, t.pnl_r FROM trades t WHERE t.user_id=? {where}",
        [user_id] + args,
    ).fetchall()

    violated_ids = {r["id"] for r in violated_ids_q}
    violated_pnl = [r["pnl_r"] for r in violated_ids_q]
    clean_pnl    = [r["pnl_r"] for r in all_trades_q if r["id"] not in violated_ids]

    # Топ нарушенных правил
    top_rules_q = c.execute(
        f"""SELECT rule_key, COUNT(*) AS cnt, SUM(t.pnl_r) AS sum_r
            FROM trade_violations tv
            JOIN trades t ON t.id = tv.trade_id AND t.user_id = ?
            WHERE 1=1
            {where}
            GROUP BY rule_key ORDER BY cnt DESC LIMIT 5""",
        [user_id] + args,
    ).fetchall()

    c.close()

    n_clean    = len(clean_pnl)
    n_violated = len(violated_pnl)

    if n_clean < 10:
        return {
            "period": period,
            "insufficient_data": True,
            "clean_count": n_clean,
            "note": "Нужно ≥10 дисциплинированных сделок для отчёта",
        }

    avg_r_clean = sum(clean_pnl) / n_clean
    sum_r_violated = sum(violated_pnl)
    # discipline_cost_r = sum_r_violated_actual − n_violated × avg_r_clean
    discipline_cost_r = round(sum_r_violated - n_violated * avg_r_clean, 2)

    return {
        "period": period,
        "insufficient_data": False,
        "trades_clean": {
            "count":  n_clean,
            "sum_r":  round(sum(clean_pnl), 2),
            "avg_r":  round(avg_r_clean, 3),
        },
        "trades_violated": {
            "count":  n_violated,
            "sum_r":  round(sum_r_violated, 2),
            "avg_r":  round(sum_r_violated / n_violated, 3) if n_violated else 0.0,
        },
        "discipline_cost_r": discipline_cost_r,
        "top_rules_broken": [
            {"rule": r["rule_key"], "count": r["cnt"], "sum_r": round(r["sum_r"] or 0, 2)}
            for r in top_rules_q
        ],
        "note": "Статистика твоих сделок — не прогноз и не оценка качества решений.",
    }


_DOW_NAMES = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}
_HOUR_BUCKETS = [("00-08", 0, 8), ("08-12", 8, 12), ("12-16", 12, 16), ("16-24", 16, 24)]


def get_setup_analytics(user_id: str = "default", period: str = "90d") -> list[dict]:
    """
    Агрегация по сетапам: win_rate, avg_r, sum_r + разрезы по дням недели и часам.
    Ячейки < 8 сделок — скрыты (не включаются).
    """
    where, args = _period_where(period)
    c = _conn()

    rows = c.execute(
        # Псевдоним t — по той же причине, что и выше: фрагмент периода
        # приходит из _period_where уже с «t.».
        f"""SELECT t.setup_tag,
                   CAST(strftime('%w', t.close_ts) AS INTEGER) AS dow,
                   CAST(strftime('%H', t.close_ts) AS INTEGER) AS hour,
                   t.pnl_r,
                   CASE WHEN t.pnl_r > 0 THEN 1 ELSE 0 END AS win
            FROM trades t
            WHERE t.user_id=? AND t.setup_tag IS NOT NULL AND t.setup_tag != ''
            {where}
            ORDER BY t.setup_tag, t.close_ts""",
        [user_id] + args,
    ).fetchall()
    c.close()

    from collections import defaultdict

    # setup → all trades
    setups: dict[str, list] = defaultdict(list)
    for r in rows:
        setups[r["setup_tag"]].append(dict(r))

    result = []
    for setup, trades in sorted(setups.items()):
        n = len(trades)
        wins = sum(1 for t in trades if t["win"])
        sum_r = sum(t["pnl_r"] for t in trades)
        avg_r = sum_r / n if n else 0

        # DoW разрез
        by_dow: dict[str, dict] = {}
        dow_groups: dict[int, list] = defaultdict(list)
        for t in trades:
            dow_groups[t["dow"]].append(t["pnl_r"])
        for dow_num, pnl_list in dow_groups.items():
            if len(pnl_list) >= 8:
                by_dow[_DOW_NAMES.get(dow_num, str(dow_num))] = {
                    "count": len(pnl_list),
                    "avg_r": round(sum(pnl_list) / len(pnl_list), 3),
                }

        # Часовой разрез
        by_hour: dict[str, dict] = {}
        for bucket_name, h_start, h_end in _HOUR_BUCKETS:
            bucket = [t["pnl_r"] for t in trades if h_start <= t["hour"] < h_end]
            if len(bucket) >= 8:
                by_hour[bucket_name] = {
                    "count": len(bucket),
                    "avg_r": round(sum(bucket) / len(bucket), 3),
                }

        result.append({
            "setup":    setup,
            "count":    n,
            "win_rate": round(wins / n, 3) if n else 0,
            "avg_r":    round(avg_r, 3),
            "sum_r":    round(sum_r, 2),
            "by_dow":   by_dow,
            "by_hour_bucket": by_hour,
        })

    # Сортировка по sum_r DESC
    result.sort(key=lambda x: x["sum_r"], reverse=True)
    return result


ensure_schema()
