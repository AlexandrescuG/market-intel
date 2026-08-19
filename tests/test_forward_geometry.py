#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Три дефекта форвард-проверки, найденные 19.08 на первой же сделке.

Общее у них одно: каждый оставлял контур внешне работающим. Сделки шли,
журнал наполнялся, правила §3 применялись — просто измерялась не та
стратегия, которую пререгистрировали. Такой отказ не виден по логам, его
можно поймать только тестом на условие, а не на работоспособность.
"""
import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze.live_strategy import ATR_MULT, MAX_SIGNAL_LAG_SEC, RR, evaluate, geometry
from analyze.mt5_calibration import close_aged, record
from analyze.mt5_safety import MAGIC
from core.db_migrations import apply_all


@pytest.fixture
def con():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE IF NOT EXISTS schema_version "
              "(version INTEGER PRIMARY KEY, applied_ts INTEGER, description TEXT)")
    c.executemany("INSERT INTO schema_version VALUES (?,0,'pre-existing')",
                  [(v,) for v in range(1, 18)])
    c.commit()
    apply_all(c)
    return c


class _Pos:
    def __init__(self, ticket, age_sec):
        self.ticket, self.magic = ticket, MAGIC
        self.time = int(time.time()) - age_sec
        self.symbol, self.volume, self.type = "GOLD", 0.01, 0


class _FakeMT5:
    """Позиции отдаёт, закрыть ничего не даст: если close_aged дойдёт до
    отправки встречной сделки, тест упадёт с AttributeError, а не молча."""
    def __init__(self, positions):
        self._p = positions

    def positions_get(self):
        return self._p


# ── 1. сборщик по возрасту не трогает стратегию ────────────────────────────

def test_сборщик_по_возрасту_не_закрывает_сделку_стратегии(con):
    """🔴 Главный дефект: sbf-strategy-monitor вызывает mt5_calibration
    --collect-only каждые 15 минут, а close_aged отбирал позиции по
    `forecast_id IS NULL` — под это условие подпадают и сделки стратегии.
    Горизонт 12 часов схлопывался бы до 15 минут, и §3 остановил бы
    гипотезу, которую ни разу не проверил."""
    record(con, forecast_id=None, account=1, server="Ava-Demo 1-MT5", symbol="XAUUSD",
           broker_symbol="GOLD", tf="H1", direction="bullish", volume=0.01,
           ticket=111, order_status="sent",
           note="strategy=gold_oil oil_rising=1 atr=13.9 horizon_bars=12")
    n = close_aged(_FakeMT5([_Pos(111, age_sec=3600)]), None, con, max_age_sec=900)
    assert n == 0, "позиция стратегии закрыта чужим таймером"


def test_сборщик_по_возрасту_по_прежнему_закрывает_синтетику(con):
    """Обратная сторона: исключение не должно отключить сам сборщик —
    синтетические позиции копились бы до потолка в 10 штук."""
    record(con, forecast_id=None, account=1, server="Ava-Demo 1-MT5", symbol="EURUSD",
           broker_symbol="EURUSD", tf="H1", direction="bullish", volume=0.01,
           ticket=222, order_status="sent", note="deal=1")
    with pytest.raises(AttributeError):
        close_aged(_FakeMT5([_Pos(222, age_sec=3600)]), None, con, max_age_sec=900)


# ── 2. барьеры считаются от входа ──────────────────────────────────────────

def test_геометрия_от_цены_входа_а_не_от_закрытия_бара():
    """Числа — с первой реальной сделки: бар закрылся на 4367.22, вход
    прошёл по 4369.73, ATR 13.9014. Барьеры от закрытия бара дали риск
    2.18 ATR при награде 0.82 ATR — RR 0.38 вместо 0.5."""
    atr, fill = 13.9014, 4369.73
    stop, target = geometry(fill, atr)
    assert (fill - stop) / atr == pytest.approx(ATR_MULT)
    assert (target - fill) / atr == pytest.approx(ATR_MULT * RR)


def test_разрыв_бар_вход_не_искажает_rr():
    """Устойчивость к самому разрыву: как бы далеко цена ни ушла от
    сигнального бара, отношение риска к награде обязано остаться 0.5."""
    atr = 10.0
    for fill in (4000.0, 4050.0, 3950.0):
        stop, target = geometry(fill, atr)
        assert (target - fill) / (fill - stop) == pytest.approx(RR)


# ── 3. отказ входить по устаревшим барам ───────────────────────────────────

def _candles(last_ts, n=200, price=4000.0):
    return [{"ts": last_ts - (n - 1 - k) * 3600, "o": price, "h": price + 5,
             "l": price - 5, "c": price} for k in range(n)]


def test_устаревшие_бары_отменяют_вход(monkeypatch, con):
    """19.08 доливка баров встала на один прогон (symbol_select('GOLD')
    вернул False у Ava). Молча войти по бару трёхчасовой давности значит
    поставить барьеры вокруг цены, которой уже нет."""
    import analyze.live_strategy as ls
    now = int(time.time())
    stale = now - MAX_SIGNAL_LAG_SEC - 3600 * 3
    monkeypatch.setattr(ls._pb, "load_candles", lambda *a, **k: _candles(stale))
    s = evaluate(con)
    assert s["ok"] is False and "устарели" in s["reason"], s


def test_свежие_бары_вход_разрешают(monkeypatch, con):
    import analyze.live_strategy as ls
    now = int(time.time())
    monkeypatch.setattr(ls._pb, "load_candles", lambda *a, **k: _candles(now - 60))
    monkeypatch.setattr(ls, "_macro_at",
                        lambda c, code, ts, back=0: 70.0 if back == 0 else 65.0)
    s = evaluate(con)
    assert s["ok"] is True and s["signal"] is True, s
    assert s["lag_sec"] < MAX_SIGNAL_LAG_SEC


# ── 4. отказ входить, когда цена ушла от сигнального бара ──────────────────

def test_предел_сноса_равен_расстоянию_до_цели():
    """Порог не самостоятельное число, а сама геометрия: уйди цена дальше —
    и движение, ради которого бралась сделка, уже случилось до входа."""
    from analyze.live_strategy import MAX_ENTRY_DRIFT_ATR
    assert MAX_ENTRY_DRIFT_ATR == ATR_MULT * RR


def test_снос_делает_цель_ниже_входа():
    """Живой случай 19.08 16:02: бар закрылся на 4365.95, рынок ушёл на
    4438.93 (+5.4 ATR при ATR=13.4471). Барьеры от закрытия бара дали бы
    покупку с целью ниже цены входа — заявка невыполнима в принципе."""
    from analyze.live_strategy import MAX_ENTRY_DRIFT_ATR
    bar_close, ask, atr = 4365.95, 4438.93, 13.4471
    drift = abs(ask - bar_close) / atr
    assert drift > MAX_ENTRY_DRIFT_ATR, drift
    _, target_from_bar = geometry(bar_close, atr)
    assert target_from_bar < ask, "цель должна оказаться ниже входа — ради этого и предохранитель"
    _, target_from_fill = geometry(ask, atr)
    assert target_from_fill > ask, "от цены входа цель обязана быть выше"
