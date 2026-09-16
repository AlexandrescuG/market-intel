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
  account TEXT NOT NULL DEFAULT 'demo',   -- какой счёт принимал это решение
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
  account TEXT NOT NULL DEFAULT 'demo',   -- на каком счёте стоит позиция
  signal_id INTEGER,
  strategy TEXT NOT NULL,
  symbol TEXT NOT NULL,
  broker_symbol TEXT,
  tf TEXT,
  direction TEXT NOT NULL,
  mode TEXT NOT NULL,               -- live | shadow
  volume REAL,
  risk_money REAL,                  -- риск НА МОМЕНТ ВХОДА, дальше не меняется
  risk_per_price REAL,              -- сколько денег стоит единица движения цены
  crosses_id INTEGER,               -- встречная позиция, с которой пересеклись
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
  -- 🔴 Ключ СОСТАВНОЙ: у каждого счёта своя кривая и свой стоп-кран. Общее
  -- состояние означало бы, что остановка на демо глушит стратегию и на
  -- реальных деньгах, а кривые R двух счетов складываются в одну.
  account TEXT NOT NULL DEFAULT 'demo',
  strategy TEXT NOT NULL,
  status TEXT NOT NULL,             -- live | shadow | halted
  cum_r REAL DEFAULT 0,             -- накопленный результат в R
  peak_r REAL DEFAULT 0,            -- максимум cum_r за всю историю
  n_closed INTEGER DEFAULT 0,
  halted_ts INTEGER,
  halt_reason TEXT,
  halt_threshold REAL,
  updated_ts INTEGER,
  PRIMARY KEY (account, strategy)
);
"""


def connect(timeout: float = 120.0) -> sqlite3.Connection:
    con = sqlite3.connect(str(BOT_DB), timeout=timeout)
    con.execute("PRAGMA busy_timeout=120000")
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    _migrate(con)
    con.commit()


def _migrate(con: sqlite3.Connection) -> None:
    """Добавить колонки, которых нет в уже созданной таблице.

    CREATE TABLE IF NOT EXISTS молча пропускает существующую таблицу со
    старым набором колонок — схема в коде и схема в базе расходятся, а
    ошибки нет до первого запроса к новой колонке."""
    for table in ("engine_trades", "engine_signals"):
        cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        if "account" not in cols:
            # DEFAULT 'demo': всё, что было до 16.09, торговалось на демо, и
            # приписывать старым строкам «неизвестный счёт» было бы неправдой.
            con.execute(f"ALTER TABLE {table} ADD COLUMN account TEXT "
                        f"NOT NULL DEFAULT 'demo'")

    # 🔴 Состояние стратегий — составной ключ (счёт, стратегия).
    #
    # Было PRIMARY KEY (strategy). С двумя счетами это значит: стоп-кран,
    # сработавший на демо, останавливает стратегию и на реальном счёте, а
    # кривые R двух счетов складываются в одну. То есть сравнение счетов,
    # ради которого второй счёт и заводится, становится невозможным.
    #
    # SQLite не меняет первичный ключ на месте — только перестройкой таблицы.
    # Делать при остановленном движке: между DROP и переименованием журнал
    # состояния не существует.
    st_cols = {r[1] for r in con.execute("PRAGMA table_info(engine_strategy_state)")}
    if st_cols and "account" not in st_cols:
        con.executescript("""
            CREATE TABLE engine_strategy_state_new (
              account TEXT NOT NULL DEFAULT 'demo',
              strategy TEXT NOT NULL,
              status TEXT NOT NULL,
              cum_r REAL DEFAULT 0, peak_r REAL DEFAULT 0,
              n_closed INTEGER DEFAULT 0,
              halted_ts INTEGER, halt_reason TEXT, halt_threshold REAL,
              updated_ts INTEGER,
              PRIMARY KEY (account, strategy)
            );
        """)
        old = ", ".join(sorted(st_cols))
        con.execute(f"INSERT INTO engine_strategy_state_new (account, {old}) "
                    f"SELECT 'demo', {old} FROM engine_strategy_state")
        con.executescript("""
            DROP TABLE engine_strategy_state;
            ALTER TABLE engine_strategy_state_new RENAME TO engine_strategy_state;
        """)

    have = {r[1] for r in con.execute("PRAGMA table_info(engine_trades)")}
    if "risk_per_price" not in have:
        con.execute("ALTER TABLE engine_trades ADD COLUMN risk_per_price REAL")
        # Задним числом: у старых сделок цена движения выводится из риска на
        # входе и ИСХОДНОГО стопа сигнала — текущий стоп уже подтянут, по нему
        # получилось бы не то число.
        con.execute("""
            UPDATE engine_trades SET risk_per_price = (
              SELECT engine_trades.risk_money / abs(engine_trades.req_price - s.stop)
              FROM engine_signals s WHERE s.id = engine_trades.signal_id
                AND abs(engine_trades.req_price - s.stop) > 1e-12)
            WHERE risk_per_price IS NULL""")
    if "crosses_id" not in have:
        con.execute("ALTER TABLE engine_trades ADD COLUMN crosses_id INTEGER")


# ─── сигналы ────────────────────────────────────────────────────────────────

def already_taken(con: sqlite3.Connection, dedup_key: str,
                  account: str = "demo") -> bool:
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
        "WHERE s.dedup_key=? AND t.account=? "
        "AND t.status IN ('pending','open','closed') LIMIT 1",
        (dedup_key, account)).fetchone()
    return row is not None


def record_decision(con: sqlite3.Connection, d: Decision,
                    account: str = "demo") -> int:
    s = d.signal
    cur = con.execute(
        "INSERT INTO engine_signals (account, ts, strategy, symbol, tf, direction, bar_ts, "
        "dedup_key, ref_price, stop, target, atr, rr, horizon_sec, accepted, reason, "
        "volume, risk_money, features) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (account, int(time.time()), s.strategy, s.symbol, s.tf, s.direction, s.bar_ts,
         s.dedup_key, s.ref_price, s.stop, s.target, s.atr, round(s.rr, 4),
         s.horizon_sec, int(d.accepted), d.reason, d.volume, d.risk_money,
         s.features_json()))
    con.commit()
    return int(cur.lastrowid)


# ─── сделки ─────────────────────────────────────────────────────────────────

def open_trade(con: sqlite3.Connection, signal_id: int, d: Decision, *,
               mode: str, broker_symbol: str, req_price: float,
               status: str = "pending", note: str = "",
               stop: float | None = None, target: float | None = None,
               account: str = "demo") -> int:
    """Строка заводится ДО отправки ордера.

    🔴 Порядок принципиален, это урок live_strategy от 19.08: ордер ушёл,
    позиция открылась, а INSERT упал с "database is locked" — получилась
    сделка, которой нет ни в журнале, ни под горизонтом. Позиция у брокера,
    не подтверждённая записью, хуже пропущенного входа."""
    s = d.signal
    now = int(time.time())
    # Цена единицы движения = объём × стоимость пункта. Храним её, а не только
    # риск на входе: стоп переносится (manage_open), и остаток риска считается
    # уже от нового стопа. Без этого числа пересчитать его не из чего.
    rpp = (d.risk_money / s.stop_distance) if s.stop_distance else None
    # С чем эта сделка пересеклась. Встречный вход больше не запрещён, но
    # обязан быть виден: без пометки выборку не разделить задним числом, и
    # вопрос «а не портят ли пересечения статистику» останется без ответа.
    from analyze.engine import risk as _risk
    crosses = (_risk.crossing_trade(con, s.symbol, s.is_long, account)
               if mode == "live" else None)
    cur = con.execute(
        "INSERT INTO engine_trades (account, signal_id, strategy, symbol, broker_symbol, tf, "
        "direction, mode, volume, risk_money, risk_per_price, crosses_id, atr, "
        "req_price, req_ts, stop, target, horizon_until, status, note) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (account, signal_id, s.strategy, s.symbol, broker_symbol, s.tf, s.direction, mode,
         d.volume, d.risk_money, rpp, crosses, s.atr, req_price, now,
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


def open_trades(con: sqlite3.Connection, strategy: str | None = None,
                account: str = "demo") -> list[dict]:
    q = ("SELECT id, strategy, symbol, broker_symbol, tf, direction, mode, volume, "
         "ticket, entry_price, stop, target, horizon_until, atr, req_ts "
         "FROM engine_trades WHERE status='open' AND account=?")
    args: tuple = (account,)
    if strategy:
        q += " AND strategy=?"
        args = args + (strategy,)
    cols = ["id", "strategy", "symbol", "broker_symbol", "tf", "direction", "mode",
            "volume", "ticket", "entry_price", "stop", "target", "horizon_until",
            "atr", "req_ts"]
    return [dict(zip(cols, r)) for r in con.execute(q, args).fetchall()]


# ─── состояние стратегий ────────────────────────────────────────────────────

def ensure_strategy(con: sqlite3.Connection, strategy: str, status: str,
                    account: str = "demo", create: bool = True) -> dict:
    """Состояние стратегии НА ЭТОМ СЧЁТЕ.

    🔴 Ключ составной с 16.09. Пока счёт был один, стратегия и её состояние
    совпадали; с двумя счетами общее состояние означало бы, что стоп-кран,
    сработавший на демо, глушит стратегию и на реальных деньгах, а кривые R
    двух счетов складываются в одну."""
    row = con.execute("SELECT strategy, status, cum_r, peak_r, n_closed, halt_reason "
                      "FROM engine_strategy_state WHERE account=? AND strategy=?",
                      (account, strategy)).fetchone()
    if row is None:
        # 🔴 16.09: create=False для сухого прогона. `--dry-run --account real`
        # завёл стратегии реального счёта со статусом shadow (у сухого прогона
        # default_status = shadow), и следующий БОЕВОЙ прогон с --live отправил
        # 8 сделок из 9 в тень: строки уже были, а --live существующие не
        # трогает. Тот же класс, что дедуп, отравленный dry-run 28.08:
        # репетиция не должна оставлять следов, по которым потом судят.
        if not create:
            return {"strategy": strategy, "status": status, "cum_r": 0.0,
                    "peak_r": 0.0, "n_closed": 0, "halt_reason": None}
        con.execute("INSERT INTO engine_strategy_state (account, strategy, status, "
                    "updated_ts) VALUES (?,?,?,?)",
                    (account, strategy, status, int(time.time())))
        con.commit()
        return {"strategy": strategy, "status": status, "cum_r": 0.0, "peak_r": 0.0,
                "n_closed": 0, "halt_reason": None}
    return dict(zip(["strategy", "status", "cum_r", "peak_r", "n_closed", "halt_reason"], row))


def apply_result(con: sqlite3.Connection, strategy: str, r: float,
                 account: str = "demo") -> dict:
    """Добавляет исход к кривой стратегии и двигает пик.

    Пик нужен именно здесь, а не в отчёте: стоп-кран меряет просадку ОТ ПИКА,
    и если пик считать на лету по журналу, он поедет каждый раз, когда часть
    сделок ещё не сведена."""
    st = ensure_strategy(con, strategy, ST_SHADOW, account)
    cum = (st["cum_r"] or 0.0) + r
    peak = max(st["peak_r"] or 0.0, cum)
    con.execute("UPDATE engine_strategy_state SET cum_r=?, peak_r=?, n_closed=n_closed+1, "
                "updated_ts=? WHERE account=? AND strategy=?",
                (cum, peak, int(time.time()), account, strategy))
    con.commit()
    st.update({"cum_r": cum, "peak_r": peak, "n_closed": st["n_closed"] + 1})
    return st


def halt(con: sqlite3.Connection, strategy: str, reason: str,
         threshold: float | None = None, account: str = "demo") -> None:
    """Остановить стратегию, запомнив ПОРОГ, по которому это сделано.

    🔴 Порог сохраняется не для истории, а чтобы остановку можно было
    отменить осмысленно. См. `resume_stale_halts`."""
    _ensure_threshold_column(con)
    now = int(time.time())
    con.execute("UPDATE engine_strategy_state SET status=?, halted_ts=?, halt_reason=?, "
                "halt_threshold=?, updated_ts=? WHERE account=? AND strategy=?",
                (ST_HALTED, now, reason, threshold, now, account, strategy))
    con.commit()


def _ensure_threshold_column(con: sqlite3.Connection) -> None:
    cols = {r[1] for r in con.execute("PRAGMA table_info(engine_strategy_state)")}
    if "halt_threshold" not in cols:
        con.execute("ALTER TABLE engine_strategy_state ADD COLUMN halt_threshold REAL")
        con.commit()


def resume_stale_halts(con: sqlite3.Connection, current_threshold: float,
                       account: str = "demo") -> list[tuple]:
    """Снять остановки, сделанные по УЖЕ НЕ ДЕЙСТВУЮЩЕМУ порогу.

    🔴 Найдено 11.09 на живом счёте. 07.09 порог подняли с 8 до 20 R —
    посчитали из распределения, потому что восьмёрка лежала внутри медианы
    нормальной просадки. Но стратегии, остановленные ДО правки, так и
    остались остановленными: правило изменилось, а его последствия нет.

    Цена ошибки: `pattern_break_retest` стоял шесть дней с просадкой -8.09R
    при новом пределе 20, будучи при этом в плюсе (+11.03 R за 60 сделок).
    За это время движок отверг **851 сигнал** с причиной «стратегия
    остановлена». Молчаливо: в журнале всё аккуратно записано, алерта нет,
    снаружи выглядит как «сигналов мало».

    Возобновляем ТОЛЬКО если просадка укладывается в нынешний порог — то
    есть по сегодняшнему правилу стратегия и не должна была быть
    остановлена. Если она пробила и новый порог, остановка остаётся:
    смягчение правила не должно воскрешать действительно сломанное."""
    _ensure_threshold_column(con)
    resumed = []
    rows = con.execute(
        "SELECT strategy, cum_r, peak_r, halt_threshold, halt_reason "
        "FROM engine_strategy_state WHERE status=? AND account=?",
        (ST_HALTED, account)).fetchall()
    for strategy, cum_r, peak_r, old_thr, reason in rows:
        dd = (cum_r or 0.0) - (peak_r or 0.0)
        if dd <= -current_threshold:
            continue                      # пробила и нынешний порог — пусть стоит
        # Порог мог не сохраниться (остановка до этой правки) — тогда
        # ориентируемся на сам факт: просадка внутри нынешнего предела.
        if old_thr is not None and old_thr >= current_threshold:
            continue                      # остановлена по такому же или более мягкому
        con.execute("UPDATE engine_strategy_state SET status=?, halted_ts=NULL, "
                    "halt_reason=NULL, halt_threshold=NULL, updated_ts=? "
                    "WHERE account=? AND strategy=?",
                    (ST_LIVE, int(time.time()), account, strategy))
        resumed.append((strategy, dd, old_thr, current_threshold))
    if resumed:
        con.commit()
    return resumed


def set_status(con: sqlite3.Connection, strategy: str, status: str,
               account: str = "demo") -> None:
    con.execute("UPDATE engine_strategy_state SET status=?, updated_ts=? "
                "WHERE account=? AND strategy=?",
                (status, int(time.time()), account, strategy))
    con.commit()


def strategy_report(con: sqlite3.Connection, account: str = "demo") -> list[dict]:
    """Сводка по стратегиям ОДНОГО счёта.

    🔴 16.09: подзапросы считали сделки по одной только стратегии, без счёта.
    После разделения на два счёта это дало строки-двойники: одна с реальными
    числами, вторая с нулями, и обе подписаны live. Отчёт, который показывает
    одну стратегию дважды с разными итогами, хуже отсутствующего отчёта —
    по нему принимают решения."""
    rows = con.execute("""
        SELECT s.strategy, s.status, s.cum_r, s.peak_r, s.n_closed, s.halt_reason,
               (SELECT count(*) FROM engine_trades t WHERE t.strategy=s.strategy
                  AND t.account=s.account AND t.status='open'),
               (SELECT count(*) FROM engine_trades t WHERE t.strategy=s.strategy
                  AND t.account=s.account AND t.status='closed' AND t.r_realized>0),
               (SELECT count(*) FROM engine_trades t WHERE t.strategy=s.strategy
                  AND t.account=s.account AND t.status='closed' AND t.r_realized<=0)
        FROM engine_strategy_state s WHERE s.account=? ORDER BY s.strategy""",
        (account,)).fetchall()
    cols = ["strategy", "status", "cum_r", "peak_r", "n_closed", "halt_reason",
            "open", "wins", "losses"]
    return [dict(zip(cols, r)) for r in rows]
