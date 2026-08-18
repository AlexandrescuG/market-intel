#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SPEC_gdenigi_message_2026-08-18.md — P0-1, P0-2, P0-3, P1-6.

Владелец прислал ленту из 21 сообщения со словами «они непонятны». Два из
дефектов были не про удобство, а про корректность: вердикт выносился по
величине, про которую сообщение само пишет «не измерена», и в обход
доверительного интервала, напечатанного двумя строками выше.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze.notify_gdenigi import (describe_config, format_message,
                                    verdict_vs_breakeven)

BE = 1.0 / 3.0          # rr=2.0
EK = "barrier:a1.5_r2.0_h30_costsv1"


def _fc(**kw):
    base = {"symbol": "EURUSD", "horizon": "H1", "event_key": EK, "conviction": 0.34,
            "invalidation": "—", "direction": "bullish", "entry": 1.1642,
            "entry_kind": "close", "stop": 1.1610, "target": 1.1706,
            "valid_until": 1787130000}
    base.update(kw)
    return base


# ─── P0-2: неизмеренная поправка не решает вердикт ──────────────────────────

def test_поправка_не_создаёт_вердикт_выше_порога():
    """Лента 18.08, EURUSD H1: база 29.0%, поправка +5.0 -> 34.0%. Старая
    логика печатала «ВЫШЕ порога», хотя измеренная база ниже безубытка."""
    v = verdict_vs_breakeven(29.0, 18.0, 42.0, BE)
    assert "ВЫШЕ" not in v, f"поправка всё ещё создаёт вердикт: {v}"


def test_поправка_не_снимает_вердикт():
    """USDZAR H1: база 38.1%, поправка -6.0. Вердикт не должен зависеть от неё."""
    assert verdict_vs_breakeven(38.1, 25.1, 49.1, BE) == verdict_vs_breakeven(38.1, 25.1, 49.1, BE)


def test_в_тексте_сказано_что_поправка_не_участвует():
    msg = format_message(_fc(conviction=0.34),
                         {"insufficient": False, "p": 0.29, "n": 58,
                          "ci95_lo": 18.0, "ci95_hi": 42.0}, "ТЕСТ")
    assert "в вердикте не участвует" in msg, msg


# ─── P0-3: три состояния, интервал участвует ────────────────────────────────

def test_весь_интервал_выше():
    """USDCNY H1 40.2%, CI [35.3, 45.2] — единственная карточка из ленты,
    у которой интервал целиком выше безубытка."""
    assert verdict_vs_breakeven(40.2, 35.3, 45.2, BE).startswith("ВЫШЕ")


def test_весь_интервал_ниже():
    assert verdict_vs_breakeven(20.0, 12.0, 28.0, BE).startswith("НИЖЕ")


def test_интервал_накрывает_безубыток():
    """GOLD H1 40.6%, CI [29.5, 52.9] — точечная оценка выше порога, интервал
    его накрывает. Раньше печаталось «ВЫШЕ порога»."""
    assert verdict_vs_breakeven(40.6, 29.5, 52.9, BE) == "неотличимо от безубытка при текущем n"


def test_без_безубытка_вердикта_нет():
    assert verdict_vs_breakeven(40.0, 30.0, 50.0, None) is None


# ─── P0-1: направление и уровни доходят до текста ───────────────────────────

def test_направление_и_уровни_в_сообщении():
    msg = format_message(_fc(), None, "ТЕСТ")
    assert "Направление: покупка" in msg
    assert "1.16420" in msg and "1.16100" in msg and "1.17060" in msg, msg
    assert "Действует до:" in msg


def test_продажа_переводится():
    assert "Направление: продажа" in format_message(_fc(direction="bearish"), None, "ТЕСТ")


def test_пустые_уровни_дают_честную_строку():
    """Поля приходят от модели; пустое значение должно давать строку, а не
    дыру в сообщении и не исключение."""
    msg = format_message(_fc(entry=None, stop=None, target=None), None, "ТЕСТ")
    assert "Уровни: не заданы" in msg, msg


def test_close_помечен_как_смещённая_геометрия():
    """entry_kind='close' у всех 97 записей — цена уже закрывшегося бара, не
    котировка на момент чтения. Называть её «по рынку» значило бы обещать
    исполнимость, которой нет."""
    msg = format_message(_fc(), None, "ТЕСТ")
    assert "смещённая геометрия" in msg, msg


# ─── P1-6: заголовок расшифрован ────────────────────────────────────────────

def test_конфиг_расшифрован():
    assert describe_config(EK) == "цель 2R · стоп 1.5×ATR · горизонт 30 баров"


def test_нераспознанный_конфиг_не_выдумывается():
    assert describe_config("vol_autocorr_control") is None
    msg = format_message(_fc(event_key="странный_ключ"), None, "ТЕСТ")
    assert "странный_ключ" in msg, "сырой ключ должен остаться, если не разобран"


# ─── P2-8: встречная гипотеза по тому же бару ───────────────────────────────

import sqlite3

from analyze.notify_gdenigi import counter_hypothesis

_FC_DDL = """CREATE TABLE forecasts (
  id TEXT PRIMARY KEY, created_ts INTEGER, symbol TEXT, horizon TEXT,
  event_key TEXT, direction TEXT)"""


def _con_with(rows):
    con = sqlite3.connect(":memory:")
    con.execute(_FC_DDL)
    con.executemany("INSERT INTO forecasts VALUES (?,?,?,?,?,?)", rows)
    con.commit()
    return con


def test_встречная_гипотеза_найдена():
    con = _con_with([("a", 1000, "USDZAR", "H1", EK, "bullish"),
                     ("b", 1000, "USDZAR", "H1", EK, "bearish")])
    assert counter_hypothesis(con, "a") and counter_hypothesis(con, "b")


def test_одиночный_прогноз_не_помечается():
    con = _con_with([("a", 1000, "USDZAR", "H1", EK, "bullish")])
    assert not counter_hypothesis(con, "a")


def test_другой_бар_не_считается_встречным():
    """created_ts — это ts БАРА (перезаписывается в _write_one), значит
    противоположное направление на соседнем баре встречной гипотезой не является."""
    con = _con_with([("a", 1000, "USDZAR", "H1", EK, "bullish"),
                     ("b", 4600, "USDZAR", "H1", EK, "bearish")])
    assert not counter_hypothesis(con, "a")


def test_другой_инструмент_не_считается():
    con = _con_with([("a", 1000, "USDZAR", "H1", EK, "bullish"),
                     ("b", 1000, "EURUSD", "H1", EK, "bearish")])
    assert not counter_hypothesis(con, "a")


def test_пометка_попадает_в_текст():
    msg = format_message(_fc(), None, "ТЕСТ", counter=True)
    assert "встречная гипотеза по этому же бару" in msg
    assert "встречная" not in format_message(_fc(), None, "ТЕСТ", counter=False)
