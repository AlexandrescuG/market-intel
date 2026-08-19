#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Правила остановки форвард-проверки (§3 pregeg 2026-08-19_forward_stopping.md).

Эти правила — единственное, что стоит между «система учится» и «система
крутит параметры, пока не понравится». Они заданы до первой закрытой сделки
и проверяются здесь на синтетике, чтобы не выяснять их поведение на живых
деньгах.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze.strategy_monitor import (MAX_DRAWDOWN_ATR, PLANKA_ATR, apply_rules,
                                      metrics)


def _t(vals):
    return [{"r_atr": v, "divergence": False, "id": i, "closed_ts": i} for i, v in enumerate(vals)]


def test_мало_сделок_правила_молчат():
    v, _ = apply_rules(metrics(_t([0.5] * 10)))
    assert v == "накопление"


def test_стоп_убыток_при_явном_минусе():
    """30 сделок с отрицательным и тесным результатом: верх CI ниже планки."""
    v, why = apply_rules(metrics(_t([-0.1, -0.12, -0.08] * 10)))
    assert v == "СТОП-УБЫТОК", (v, why)


def test_стоп_просадка_срабатывает_независимо_от_n():
    """Крупный убыток должен останавливать, даже если n мало для CI-правила."""
    v, _ = apply_rules(metrics(_t([-1.0] * 20)))
    assert v == "СТОП-ПРОСАДКА"


def test_подтверждение_требует_50_сделок():
    """Уверенный плюс, но n=30 — рано подтверждать."""
    v, _ = apply_rules(metrics(_t([0.5, 0.6, 0.4] * 10)))
    assert v == "продолжать", v
    v2, _ = apply_rules(metrics(_t([0.5, 0.6, 0.4] * 20)))
    assert v2 == "ПОДТВЕРЖДЁН", v2


def test_планка_не_ноль():
    """Стратегия, которая в среднем даёт ноль, НЕ подтверждается: спред реален.
    Это главное отличие от наивного «лишь бы не минус»."""
    m = metrics(_t([0.001, -0.001] * 30))
    v, _ = apply_rules(m)
    assert v != "ПОДТВЕРЖДЁН"
    assert PLANKA_ATR > 0


def test_остановка_раньше_подтверждения():
    """Если сработали оба условия, приоритет у остановки."""
    vals = [-1.0] * 30 + [0.5] * 30
    v, _ = apply_rules(metrics(_t(vals)))
    assert v.startswith("СТОП")


def test_метрики_считаются():
    m = metrics(_t([1.0, -2.0, 1.0]))
    assert m["n"] == 3 and abs(m["total"]) < 1e-9 and m["wins"] == 2
