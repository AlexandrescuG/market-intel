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


# ── перекрытие сделок (25.08) ───────────────────────────────────────────────

def _overlapping(vals, hold=12 * 3600, step=3600):
    """Вход раз в час, горизонт 12 часов — как у живой стратегии."""
    return [{"r_atr": v, "divergence": False, "id": i,
             "open_ts": i * step, "closed_ts": i * step + hold}
            for i, v in enumerate(vals)]


def _sequential(vals, hold=3600):
    """Сделки встык, без перекрытия — эталон независимости."""
    return [{"r_atr": v, "divergence": False, "id": i,
             "open_ts": i * hold, "closed_ts": (i + 1) * hold}
            for i, v in enumerate(vals)]


def test_перекрытие_расширяет_интервал():
    """Одна и та же цена входит в исход нескольких сделок сразу — считать их
    независимыми значит сузить интервал и подтвердить признак раньше срока."""
    vals = [0.3, -0.1, 0.5, 0.2] * 15
    m_seq = metrics(_sequential(vals))
    m_ovl = metrics(_overlapping(vals))
    assert m_ovl["overlap"] > 3, m_ovl["overlap"]
    assert m_ovl["n_eff"] < m_seq["n"] / 3
    width_seq = m_seq["ci_hi"] - m_seq["ci_lo"]
    width_ovl = m_ovl["ci_hi"] - m_ovl["ci_lo"]
    assert width_ovl > width_seq * 1.5, (width_seq, width_ovl)


def test_перекрытие_не_даёт_ложного_подтверждения():
    """Живой случай 25.08: n=73, EV=+0.3027, наивный CI95 нижней границей
    +0.0295 — разошёлся с планкой 0.036 всего на 0.007 ATR. С поправкой на
    перекрытие 3.9x ноль оказывается внутри интервала."""
    # Форма реального журнала: 54 сделки по цели (+1 ATR минус издержки) и
    # 19 по стопу (-2 ATR, часть закрылась раньше горизонтом). Даёт
    # EV=+0.30 при большом разбросе — ровно тот случай, где наивный
    # интервал узок настолько, что вот-вот подтвердит.
    vals = [0.97] * 54 + [-1.60] * 19
    m = metrics(_overlapping(vals))
    assert m["ci_lo_naive"] > 0, "иначе случай не тот: наивный интервал должен быть в плюсе"
    assert m["ci_lo_naive"] > m["ci_lo"], "поправка обязана СНИЖАТЬ нижнюю границу"
    v, why = apply_rules(m)
    assert v != "ПОДТВЕРЖДЁН", (v, why)


def test_поправка_только_ужесточает():
    """Интервал шире в обе стороны: подтвердить труднее И остановить по
    убытку труднее. Создать ложную остановку поправка не может."""
    vals = [-0.2, -0.15, -0.25] * 12
    m = metrics(_overlapping(vals))
    assert m["ci_hi"] > m["ci_hi_naive"], "верхняя граница обязана расти"
    assert m["ci_lo"] < m["ci_lo_naive"], "нижняя граница обязана падать"
