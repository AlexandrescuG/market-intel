#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
§2 SPEC_mt5_cost_calibration_2026-08-18.md — предохранители.

Спека требует проверить их ДО первого ордера: «подсунуть заведомо не-демо
trade_mode и убедиться, что отказ срабатывает».
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze.mt5_safety import (MAGIC, MAX_OPEN_POSITIONS, SafetyRefusal,
                                assert_autotrading, assert_capacity, assert_demo,
                                our_positions, preflight, safe_volume)


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


DEMO = _Obj(trade_mode=0, login=101746781)
REAL = _Obj(trade_mode=2, login=999)
CONTEST = _Obj(trade_mode=1, login=888)
TERM_ON = _Obj(trade_allowed=True)
TERM_OFF = _Obj(trade_allowed=False)
SYM = _Obj(volume_min=0.01)


# ─── 2.1 только демо ────────────────────────────────────────────────────────

def test_демо_проходит():
    assert_demo(DEMO)


def test_реальный_счёт_отклонён():
    with pytest.raises(SafetyRefusal) as e:
        assert_demo(REAL)
    assert e.value.status == "not_demo"


def test_конкурсный_счёт_тоже_отклонён():
    """ACCOUNT_TRADE_MODE_CONTEST — не демо. Проверка на равенство нулю, а
    не на «!= REAL»."""
    with pytest.raises(SafetyRefusal) as e:
        assert_demo(CONTEST)
    assert e.value.status == "not_demo"


def test_нет_ответа_терминала_это_отказ():
    """«Не смог проверить» и «проверил, всё хорошо» не должны быть одним
    исходом."""
    with pytest.raises(SafetyRefusal) as e:
        assert_demo(None)
    assert e.value.status == "bridge_down"


# ─── AutoTrading ────────────────────────────────────────────────────────────

def test_autotrading_выключен_отклонён():
    """Реальное состояние терминала на 18.08."""
    with pytest.raises(SafetyRefusal) as e:
        assert_autotrading(TERM_OFF)
    assert e.value.status == "autotrading_off"


def test_autotrading_включён_проходит():
    assert_autotrading(TERM_ON)


# ─── 2.2 magic ──────────────────────────────────────────────────────────────

def test_чужие_позиции_не_наши():
    """В бутылке живёт торговый EA — его позиции контур не считает своими и
    не имеет права трогать."""
    pos = [_Obj(magic=MAGIC), _Obj(magic=12345), _Obj(magic=None), _Obj(magic=MAGIC)]
    assert len(our_positions(pos)) == 2


def test_пустой_список_позиций():
    assert our_positions(None) == [] and our_positions([]) == []


# ─── 2.3 потолок и объём ────────────────────────────────────────────────────

def test_потолок_считает_только_наши():
    """20 чужих позиций не должны блокировать наш контур."""
    assert_capacity([_Obj(magic=777) for _ in range(20)])


def test_потолок_срабатывает():
    with pytest.raises(SafetyRefusal) as e:
        assert_capacity([_Obj(magic=MAGIC) for _ in range(MAX_OPEN_POSITIONS)])
    assert e.value.status == "cap_reached"


def test_объём_строго_минимальный():
    assert safe_volume(SYM) == 0.01


def test_нулевой_volume_min_отклонён():
    with pytest.raises(SafetyRefusal):
        safe_volume(_Obj(volume_min=0))


# ─── preflight целиком ──────────────────────────────────────────────────────

def test_preflight_на_живом_состоянии_18_08():
    """Демо + AutoTrading выключен = отказ именно по autotrading, а не по
    чему-то другому: причина отказа должна быть различима."""
    with pytest.raises(SafetyRefusal) as e:
        preflight(DEMO, TERM_OFF, [], SYM)
    assert e.value.status == "autotrading_off"


def test_preflight_не_демо_отказывает_раньше_autotrading():
    """Порядок важен: самый опасный случай проверяется первым."""
    with pytest.raises(SafetyRefusal) as e:
        preflight(REAL, TERM_OFF, [], SYM)
    assert e.value.status == "not_demo"


def test_preflight_всё_хорошо_возвращает_объём():
    assert preflight(DEMO, TERM_ON, [], SYM) == 0.01
