#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
§3 и §5 SPEC_mt5_cost_calibration_2026-08-18.md.

Главное, что здесь проверяется, — отказ НИКОГДА не проходит молча.
Урок 17.08: run_cycle завершался sys.exit(0), алерт слался при коде 3,
автономный цикл стоял двое суток, systemd видел успех.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze.mt5_calibration import consecutive_failures, record
from analyze.mt5_safety import MAGIC
from core.db_migrations import apply_all


@pytest.fixture
def con():
    """apply_all() на пустой БД падает: миграции 1-17 — это ALTER TABLE по
    таблицам, которых в чистой базе нет (ограничение самого мигратора, не
    этой миграции). Помечаем их применёнными, чтобы apply_all выполнил
    ровно 18 и 19 — то есть проверяем реальную миграцию, а не обходим её
    ручным CREATE TABLE."""
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE IF NOT EXISTS schema_version "
              "(version INTEGER PRIMARY KEY, applied_ts INTEGER, description TEXT)")
    c.executemany("INSERT INTO schema_version VALUES (?,0,'pre-existing')",
                  [(v,) for v in range(1, 18)])
    c.commit()
    assert apply_all(c) == [18, 19], "миграция cost_observations не применилась"
    return c


def _obs(c, status, **kw):
    return record(c, forecast_id=kw.get("forecast_id"), account=101746781,
                  server="Ava-Demo 1-MT5", symbol="EURUSD", broker_symbol="EURUSD",
                  tf="H1", direction="bullish", volume=0.01, order_status=status,
                  note=kw.get("note"))


def test_таблица_создаётся_миграцией(con):
    cols = {r[1] for r in con.execute("PRAGMA table_info(cost_observations)")}
    assert {"commission", "swap", "slippage_entry", "order_status", "server", "account"} <= cols


def test_order_status_обязателен(con):
    """«Непонятно, что произошло» не должно быть представимо."""
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO cost_observations "
                    "(created_ts, account, server, symbol, broker_symbol, tf, direction, "
                    " volume, magic) VALUES (1,1,'s','E','E','H1','bullish',0.01,1)")


def test_отказ_пишется_строкой(con):
    _obs(con, "autotrading_off", note="AutoTrading выключен")
    row = con.execute("SELECT order_status, note, magic FROM cost_observations").fetchone()
    assert row[0] == "autotrading_off" and "AutoTrading" in row[1]
    assert row[2] == MAGIC, "magic должен проставляться сам"


def test_синтетическое_наблюдение_имеет_null_forecast_id(con):
    """Для комиссии и свопа такие наблюдения полноценны; смешивать их с
    сигнальными нельзя только при анализе проскальзывания."""
    _obs(con, "sent", forecast_id=None)
    assert con.execute("SELECT forecast_id FROM cost_observations").fetchone()[0] is None


# ─── §5: алерт на серию отказов ─────────────────────────────────────────────

def test_серия_отказов_поднимает_флаг(con):
    for _ in range(5):
        _obs(con, "order_rejected")
    assert consecutive_failures(con, 5)


def test_успех_сбрасывает_серию(con):
    for _ in range(4):
        _obs(con, "order_rejected")
    _obs(con, "sent")
    assert not consecutive_failures(con, 5)


def test_closed_тоже_успех(con):
    for _ in range(4):
        _obs(con, "bridge_down")
    _obs(con, "closed")
    assert not consecutive_failures(con, 5)


def test_мало_наблюдений_не_алертит(con):
    """Свежая таблица с двумя отказами — ещё не «систематически»."""
    _obs(con, "order_rejected")
    _obs(con, "order_rejected")
    assert not consecutive_failures(con, 5)


def test_разные_виды_отказов_считаются_вместе(con):
    """bridge_down, not_demo, order_rejected — все они «не отработало»."""
    for st in ("bridge_down", "not_demo", "order_rejected", "cap_reached", "error"):
        _obs(con, st)
    assert consecutive_failures(con, 5)
