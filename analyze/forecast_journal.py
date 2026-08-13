#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/forecast_journal.py — WP4.1 SPEC_alpha_engine_implementation.md.

Калибровочный журнал прогнозов агента (только барьерное семейство §3
проектной спеки — единственное с готовым резолвером). `forecasts`
иммутабельна после записи. Резолвер — та же механика, что WP2.2
(`analyze.labeler._walk_barriers`) — стопы/цели здесь явные (заданы при
создании прогноза), не выводятся из atr_mult/rr, поэтому вызывается
`_walk_barriers` напрямую, не `label_one`.

`event_key = f"barrier:{config_key}"` — `config_key` уже кодирует
atr_mult/rr/horizon_bars/costs_version, `horizon` (колонка forecasts) —
signal_tf ("H1"/"H4"/"D1"), дублировать tf внутри event_key не нужно.

Контракт LLM (§4.D проектной спеки) шире, чем DDL `forecasts` буквально —
поля `base_rate`/`base_n`/`base_backoff_level`/`adjustment`/`cited_factors`/
`novel_risk` не имеют отдельных колонок. Решение: не добавлять новые
колонки к зафиксированной в спеке DDL — переиспользовать существующий
generic shape `forecast_factors` (factor_key/value/weight): по строке на
каждое поле вектора состояния (`weight=1.0`, если процитировано моделью
в `cited_factors`, иначе `0.0` — ровно то, для чего этот столбец,
по-видимому, и задуман), плюс служебные `_meta.base_rate`/`_meta.base_n`/
`_meta.base_backoff_level`/`_meta.adjustment` тем же способом.
`conviction` = `final_p`. `thesis` = тезис + adjustment_reason + novel_risk
(проза, форматированно) — `run_analyst.py` собирает это, не этот модуль.
"""
from __future__ import annotations

import sqlite3
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze.labeler import RESOLUTION_TF, _walk_barriers, _mfe_mae
from core import costs as _costs
from core import db_migrations as _migrations
import core.price_bars as _price_bars

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS forecasts (
      id TEXT PRIMARY KEY, created_ts INTEGER, symbol TEXT, horizon TEXT,
      event_key TEXT, direction TEXT, conviction REAL,
      entry REAL, entry_kind TEXT, stop REAL, target REAL,
      valid_until INTEGER, invalidation TEXT, thesis TEXT, model_version TEXT,
      call_id TEXT
    );
    -- 🔴 REVIEW_wp4_cycle_2026-08-13.md §2: без этого один и тот же бар
    -- (created_ts) даёт до 5 прогнозов в сутки (частота цикла) с почти
    -- одинаковыми барьерами -- резолвер закроет их одинаково, n завышен,
    -- CI сужен (тот же класс ошибки, что WP0.2 дедупликация паттернов и
    -- поправка на корреляцию инструментов в report.py -- третий раз).
    -- Естественный ключ: один прогноз на (symbol, tf, bar_ts, event, direction).
    CREATE UNIQUE INDEX IF NOT EXISTS idx_forecasts_natural_key
      ON forecasts(symbol, horizon, event_key, direction, created_ts);
    CREATE TABLE IF NOT EXISTS forecast_factors (
      forecast_id TEXT, factor_key TEXT, value REAL, zscore REAL, weight REAL,
      PRIMARY KEY (forecast_id, factor_key)
    );
    CREATE TABLE IF NOT EXISTS forecast_outcomes (
      forecast_id TEXT PRIMARY KEY, status TEXT,
      r_realized REAL, mfe REAL, mae REAL, resolved_ts INTEGER
    );
    CREATE TABLE IF NOT EXISTS agent_calls (
      call_id TEXT PRIMARY KEY, ts INTEGER, symbol TEXT, tf TEXT, event_key TEXT,
      forecast_id TEXT, model_version TEXT, prompt TEXT, raw_response TEXT,
      tool_calls_json TEXT, duration_ms INTEGER, cost_usd REAL, exit_code INTEGER,
      validation_status TEXT, validation_reason TEXT
    );
"""


def init_schema(con: sqlite3.Connection) -> None:
    con.executescript(_SCHEMA)
    _migrations.apply_all(con)  # forecasts.call_id (WP4 continuous cycle, 13.08) --
    # таблица могла быть создана ДО появления этой колонки (CREATE TABLE IF
    # NOT EXISTS не трогает уже существующую таблицу).
    con.commit()


def write_forecast(con: sqlite3.Connection, forecast: dict, factors: list[dict]) -> str:
    """forecast: {symbol, horizon, event_key, direction, conviction, entry,
    entry_kind, stop, target, valid_until, invalidation, thesis, model_version}.
    factors: [{"factor_key":..., "value":..., "zscore":None, "weight":...}].
    Иммутабельна — только INSERT, никаких UPDATE на forecasts где-либо в модуле."""
    fid = str(uuid.uuid4())
    con.execute(
        """INSERT INTO forecasts (id, created_ts, symbol, horizon, event_key, direction,
                                   conviction, entry, entry_kind, stop, target, valid_until,
                                   invalidation, thesis, model_version, call_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (fid, int(time.time()), forecast["symbol"], forecast["horizon"], forecast["event_key"],
         forecast["direction"], forecast["conviction"], forecast["entry"], forecast["entry_kind"],
         forecast["stop"], forecast["target"], forecast["valid_until"], forecast.get("invalidation"),
         forecast.get("thesis"), forecast["model_version"], forecast.get("call_id")),
    )
    for f in factors:
        con.execute(
            "INSERT INTO forecast_factors (forecast_id, factor_key, value, zscore, weight) "
            "VALUES (?, ?, ?, ?, ?)",
            (fid, f["factor_key"], f.get("value"), f.get("zscore"), f.get("weight")),
        )
    con.commit()
    return fid


def _read_factor(con: sqlite3.Connection, forecast_id: str, factor_key: str) -> float | None:
    row = con.execute(
        "SELECT value FROM forecast_factors WHERE forecast_id=? AND factor_key=?",
        (forecast_id, factor_key),
    ).fetchone()
    return row[0] if row else None


def resolve_pending(con: sqlite3.Connection, verbose: bool = False) -> int:
    """Резолвит forecasts с истёкшим valid_until и без записи в
    forecast_outcomes. cost — из forecast_factors."_meta.atr_val"" (записан
    при создании, не пересчитывается — то же число, что видел агент)."""
    now_ts = int(time.time())
    con.row_factory = None
    pending = con.execute(
        """SELECT f.id, f.symbol, f.horizon, f.direction, f.entry, f.stop, f.target,
                  f.valid_until, f.created_ts
           FROM forecasts f LEFT JOIN forecast_outcomes o ON f.id = o.forecast_id
           WHERE o.forecast_id IS NULL AND f.valid_until <= ?""",
        (now_ts,),
    ).fetchall()

    n = 0
    for fid, symbol, tf, direction, entry, stop, target, valid_until, created_ts in pending:
        res_candles = _price_bars.load_candles(symbol, RESOLUTION_TF)
        if not res_candles:
            continue
        ts_to_idx = {c["ts"]: i for i, c in enumerate(res_candles)}
        i0 = ts_to_idx.get(created_ts)
        if i0 is None:
            i0 = next((i for i, c in enumerate(res_candles) if c["ts"] >= created_ts), None)
            if i0 is None or abs(res_candles[i0]["ts"] - created_ts) > 3 * 86400:
                if verbose:
                    print(f"  {fid}: нет честной резолюции (нет близкого {RESOLUTION_TF}-бара) — пропуск")
                continue

        upper = target if direction == "bullish" else stop
        lower = stop if direction == "bullish" else target
        risk = abs(entry - stop)
        walk = _walk_barriers(res_candles, i0, upper, lower, valid_until, direction)

        if walk["censored"]:
            mfe, mae = _mfe_mae(res_candles, i0, walk["last_i"], direction, entry, risk) if risk > 0 else (0.0, 0.0)
            status, r_realized = "censored", None
        else:
            gross = (walk["exit_price"] - entry) if direction == "bullish" else (entry - walk["exit_price"])
            atr_val = _read_factor(con, fid, "_meta.atr_val")
            cost = _costs.entry_cost_price(symbol, atr_val, tf) if atr_val else 0.0
            r_realized = round((gross - cost) / risk, 4) if risk > 0 else None
            mfe, mae = _mfe_mae(res_candles, i0, walk["last_i"], direction, entry, risk) if risk > 0 else (0.0, 0.0)
            status = "win" if walk["y"] == 1 else "loss"

        con.execute(
            "INSERT OR REPLACE INTO forecast_outcomes (forecast_id, status, r_realized, mfe, mae, resolved_ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (fid, status, r_realized, mfe, mae, now_ts),
        )
        n += 1
        if verbose:
            print(f"  {fid} {symbol} {tf}: {status} r={r_realized}")
    con.commit()
    return n
