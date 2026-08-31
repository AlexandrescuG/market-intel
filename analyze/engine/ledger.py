#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/engine/ledger.py — журнал движка и состояние стратегий.

Живёт в той же `bot.db`, что и остальной альфа-контур: заводить вторую базу
значило бы, что «сколько мы потеряли» считается в двух местах и рано или
поздно разойдётся.

🔴 `busy_timeout` здесь не косметика. Разбор 27.08 показал, что
`OperationalError: database is locked` ронял сведение в strategy_monitor, и
закрытые стопы не попадали в метрику, по которой считаются правила
остановки: прибыли успевали свестись, свежие убытки — нет. Смещение было
систематическим и в опасную сторону. Поэтому все подключения движка идут
через `connect()` с длинным таймаутом ожидания блокировки.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from analyze.engine.contracts import Decision, Signal, ST_HALTED, ST_LIVE, ST_SHADOW

BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS engine_signals (
  id INTEGER PRIMARY KEY,
  ts INTEGER NOT NULL,
  strategy TEXT NOT NULL,
  symbol TEXT NOT NULL,
  tf TEXT NOT NULL,
  direction TEXT NOT NULL,
  bar_ts INTEGER NOT NULL,
  dedup_key TEXT NOT NULL,
  ref_price REAL, stop REAL, target REAL, atr REAL, rr REAL,
  horizon_sec INTEGER,
  accepted INTEGER NOT NULL,
  reason TEXT,
  volume REAL, risk_money REAL,
  features TEXT
);
CREATE INDEX IF NOT EXISTS idx_eng_sig_dedup ON engine_signals(dedup_key);
CREATE INDEX IF NOT EXISTS idx_eng_sig_strat ON engine_signals(strategy, ts);

CREATE TABLE IF NOT EXISTS engine_trades (
  id INTEGER PRIMARY KEY,
  signal_id INTEGER,
  strategy TEXT NOT NULL,
  symbol TEXT NOT NULL,
  broker_symbol TEXT,
  tf TEXT,
  direction TEXT NOT NULL,
  mode TEXT NOT NULL,               -- live | shadow
  volume REAL,
  risk_money REAL,
  atr REAL,
  req_price REAL, req_ts INTEGER,
  stop REAL, target REAL,
  horizon_until INTEGER,
  ticket INTEGER,
  entry_price REAL, exit_price REAL,
  profit REAL, commission REAL, swap REAL,
  r_realized REAL,                  -- итог в единицах риска
  status TEXT NOT NULL,             -- pending|open|closed|rejected
  closed_ts INTEGER,
  close_reason TEXT,
  note TEXT
);
CREATE INDEX IF NOT EXISTS idx_eng_tr_open ON engine_trades(status, ticket);
CREATE INDEX IF NOT EXISTS idx_eng_tr_strat ON engine_trades(strategy, status);

CREATE TABLE IF NOT EXISTS engine_strategy_state (
  strategy TEXT PRIMARY KEY,
  status TEXT NOT NULL,             -- live | shadow | halted
  cum_r REAL DEFAULT 0,             -- накопленный результат в R
  peak_r REAL DEFAULT 0,            -- максимум cum_r за всю историю
  n_closed INTEGER DEFAULT 0,
  halted_ts INTEGER,
  halt_reason TEXT,
  updated_ts INTEGER
);
"""


def connect(timeout: float = 120.0) -> sqlite3.Connection:
    con = sqlite3.connect(str(BOT_DB), timeout=timeout)
    con.execute("PRAGMA busy_timeout=120000")
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    con.commit()


# ─── сигналы ────────────────────────────────────────────────────────────────

def already_taken(con: sqlite3.Connection, dedup_key: str) -> bool:
    """Брали ли уже сделку по этому основанию.

    Отклонённый риск-модулем сигнал обязан получить второй шанс на следующем
    прогоне (лимит мог освободиться), а исполненный — нет.

    🔴 28.08: сначала здесь стояло `accepted=1` по engine_signals, и первый же
    `--dry-run` заблокировал последующий боевой прогон целиком: dry-run писал
    решения как «принято», ордеров не слал, а дедуп считал их состоявшимися
    входами. 16 сигналов из 21 отвалились с «уже входили», движок отчитался
    «взято сделок: 0» и выглядел работающим.

    Поэтому дедуп привязан к РЕАЛЬНОЙ сделке, а не к намерению. Строка в
    engine_trades заводится до отправки ордера, в том же цикле — гонки нет,
    зато «решили войти» и «вошли» перестали быть одним и тем же."""
    row = con.execute(
        "SELECT 1 FROM engine_signals s JOIN engine_trades t ON t.signal_id = s.id "
        "WHERE s.dedup_key=? AND t.status IN ('pending','open','closed') LIMIT 1",
        (dedup_key,)).fetchone()
    return row is not None


def record_decision(con: sqlite3.Connection, d: Decision) -> int:
    s = d.signal
    cur = con.execute(
        "INSERT INTO engine_signals (ts, strategy, symbol, tf, direction, bar_ts, "
        "dedup_key, ref_price, stop, target, atr, rr, horizon_sec, accepted, reason, "
        "volume, risk_money, features) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (int(time.time()), s.strategy, s.symbol, s.tf, s.direction, s.bar_ts,
         s.dedup_key, s.ref_price, s.stop, s.target, s.atr, round(s.rr, 4),
         s.horizon_sec, int(d.accepted), d.reason, d.volume, d.risk_money,
         s.features_json()))
    con.commit()
    return int(cur.lastrowid)


# ─── сделки ─────────────────────────────────────────────────────────────────

def open_trade(con: sqlite3.Connection, signal_id: int, d: Decision, *,
               mode: str, broker_symbol: str, req_price: float,
               status: str = "pending", note: str = "",
               stop: float | None = None, target: float | None = None) -> int:
    """Строка заводится ДО отправки ордера.

    🔴 Порядок принципиален, это урок live_strategy от 19.08: ордер ушёл,
    позиция открылась, а INSERT упал с "database is locked" — получилась
    сделка, которой нет ни в журнале, ни под горизонтом. Позиция у брокера,
    не подтверждённая записью, хуже пропущенного входа."""
    s = d.signal
    now = int(time.time())
    cur = con.execute(
        "INSERT INTO engine_trades (signal_id, strategy, symbol, broker_symbol, tf, "
        "direction, mode, volume, risk_money, atr, req_price, req_ts, stop, target, "
        "horizon_until, status, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (signal_id, s.strategy, s.symbol, broker_symbol, s.tf, s.direction, mode,
         d.volume, d.risk_money, s.atr, req_price, now,
         s.stop if stop is None else stop,
         s.target if target is None else target,
         now + s.horizon_sec, status, note))
    con.commit()
    return int(cur.lastrowid)


def mark_sent(con: sqlite3.Connection, trade_id: int, ticket: int,
              entry_price: float) -> None:
    con.execute("UPDATE engine_trades SET status='open', ticket=?, entry_price=? "
                "WHERE id=?", (ticket, entry_price, trade_id))
    con.commit()


def mark_rejected(con: sqlite3.Connection, trade_id: int, reason: str) -> None:
    con.execute("UPDATE engine_trades SET status='rejected', close_reason=?, "
                "closed_ts=? WHERE id=?", (reason, int(time.time()), trade_id))
    con.commit()


def close_trade(con: sqlite3.Connection, trade_id: int, *, exit_price: float,
                profit: float, commission: float, swap: float,
                reason: str) -> float:
    """Закрывает сделку и возвращает результат в R.

    R считается по ЦЕНЕ, а не по деньгам: деньги зависят от объёма, который
    у нас плавает вместе с волатильностью, и сравнивать такие исходы между
    собой нельзя. Единица риска — расстояние вход-стоп."""
    row = con.execute("SELECT entry_price, stop, direction FROM engine_trades "
                      "WHERE id=?", (trade_id,)).fetchone()
    r = None
    if row and row[0] is not None and row[1] is not None:
        entry, stop, direction = row
        risk = abs(entry - stop)
        if risk > 0:
            move = (exit_price - entry) if direction == "long" else (entry - exit_price)
            r = move / risk
    con.execute(
        "UPDATE engine_trades SET status='closed', exit_price=?, profit=?, "
        "commission=?, swap=?, r_realized=?, closed_ts=?, close_reason=? WHERE id=?",
        (exit_price, profit, commission, swap, r, int(time.time()), reason, trade_id))
    con.commit()
    return r if r is not None else 0.0


def open_trades(con: sqlite3.Connection, strategy: str | None = None) -> list[dict]:
    q = ("SELECT id, strategy, symbol, broker_symbol, tf, direction, mode, volume, "
         "ticket, entry_price, stop, target, horizon_until, atr, req_ts "
         "FROM engine_trades WHERE status='open'")
    args: tuple = ()
    if strategy:
        q += " AND strategy=?"
        args = (strategy,)
    cols = ["id", "strategy", "symbol", "broker_symbol", "tf", "direction", "mode",
            "volume", "ticket", "entry_price", "stop", "target", "horizon_until",
            "atr", "req_ts"]
    return [dict(zip(cols, r)) for r in con.execute(q, args).fetchall()]


# ─── состояние стратегий ────────────────────────────────────────────────────

def ensure_strategy(con: sqlite3.Connection, strategy: str, status: str) -> dict:
    row = con.execute("SELECT strategy, status, cum_r, peak_r, n_closed, halt_reason "
                      "FROM engine_strategy_state WHERE strategy=?",
                      (strategy,)).fetchone()
    if row is None:
        con.execute("INSERT INTO engine_strategy_state (strategy, status, updated_ts) "
                    "VALUES (?,?,?)", (strategy, status, int(time.time())))
        con.commit()
        return {"strategy": strategy, "status": status, "cum_r": 0.0, "peak_r": 0.0,
                "n_closed": 0, "halt_reason": None}
    return dict(zip(["strategy", "status", "cum_r", "peak_r", "n_closed", "halt_reason"], row))


def apply_result(con: sqlite3.Connection, strategy: str, r: float) -> dict:
    """Добавляет исход к кривой стратегии и двигает пик.

    Пик нужен именно здесь, а не в отчёте: стоп-кран меряет просадку ОТ ПИКА,
    и если пик считать на лету по журналу, он поедет каждый раз, когда часть
    сделок ещё не сведена."""
    st = ensure_strategy(con, strategy, ST_SHADOW)
    cum = (st["cum_r"] or 0.0) + r
    peak = max(st["peak_r"] or 0.0, cum)
    con.execute("UPDATE engine_strategy_state SET cum_r=?, peak_r=?, n_closed=n_closed+1, "
                "updated_ts=? WHERE strategy=?",
                (cum, peak, int(time.time()), strategy))
    con.commit()
    st.update({"cum_r": cum, "peak_r": peak, "n_closed": st["n_closed"] + 1})
    return st


def halt(con: sqlite3.Connection, strategy: str, reason: str) -> None:
    con.execute("UPDATE engine_strategy_state SET status=?, halted_ts=?, halt_reason=?, "
                "updated_ts=? WHERE strategy=?",
                (ST_HALTED, int(time.time()), reason, int(time.time()), strategy))
    con.commit()


def set_status(con: sqlite3.Connection, strategy: str, status: str) -> None:
    con.execute("UPDATE engine_strategy_state SET status=?, updated_ts=? WHERE strategy=?",
                (status, int(time.time()), strategy))
    con.commit()


def strategy_report(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute("""
        SELECT s.strategy, s.status, s.cum_r, s.peak_r, s.n_closed, s.halt_reason,
               (SELECT count(*) FROM engine_trades t WHERE t.strategy=s.strategy AND t.status='open'),
               (SELECT count(*) FROM engine_trades t WHERE t.strategy=s.strategy AND t.status='closed' AND t.r_realized>0),
               (SELECT count(*) FROM engine_trades t WHERE t.strategy=s.strategy AND t.status='closed' AND t.r_realized<=0)
        FROM engine_strategy_state s ORDER BY s.strategy""").fetchall()
    cols = ["strategy", "status", "cum_r", "peak_r", "n_closed", "halt_reason",
            "open", "wins", "losses"]
    return [dict(zip(cols, r)) for r in rows]
