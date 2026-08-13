#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/agent/attention_trigger.py — WP4.4 SPEC_alpha_engine_implementation.md,
расширено 13.08 для SPEC_alpha_engine_wp4_continuous_cycle.md §WP4.2.

ТОЛЬКО чистые функции скоринга. Порог калибруется от бюджета вызовов
("N в сутки" -> перцентиль), не от интуиции. Сознательно НЕ входит:
main()/цикл/автоматический вызов агента — это теперь `analyze/gate.py`
(WP4.2), который зовёт эти функции и владеет systemd-интеграцией. Раньше
здесь было явное решение не включать автономный цикл до появления числа
"N вызовов в сутки" от Георгия — `SPEC_alpha_engine_wp4_continuous_cycle.md`
даёт это число (частота 5 циклов/сутки = верхняя граница вызовов), решение
принято.
"""
from __future__ import annotations


def attention_score(move_atr: float, news_burst_z: float | None,
                     calendar_prox_minutes: float | None, base_rate_shift: float,
                     level_break: float = 0.0) -> float:
    """Скаляр "насколько состояние изменилось против ожидаемого". Выше —
    больше причин звать analyst. Физически отсутствующие компоненты
    (news_burst_z сейчас всегда None — см. state_vector.py) входят с
    вкладом 0, НЕ как измеренный ноль, а как "этот компонент сейчас не
    участвует в решении" — разница явно закомментирована, чтобы её не
    перепутали при появлении реальных данных.

    level_break — [0,1], 1.0 если пробой уровня (break_retest) сработал на
    последнем баре (WP4.2: "движение в ATR + news_burst_z + близость релиза
    + сдвиг базовой ставки + пробой уровня/зоны"). Дефолт 0.0 -- обратно
    совместим с вызовами до 13.08."""
    score = abs(move_atr)
    if news_burst_z is not None:
        score += max(0.0, news_burst_z)  # отсутствие -- НЕ вклад 0.0 "измеренного" всплеска
    if calendar_prox_minutes is not None:
        score += max(0.0, 60.0 - calendar_prox_minutes) / 60.0  # ближе часа к релизу -- растущий вклад
    score += abs(base_rate_shift) * 2.0  # сдвиг самой базовой ставки -- сильный сигнал
    score += max(0.0, min(1.0, level_break))
    return round(score, 4)


def calibrate_threshold(scores: list[float], target_calls_per_day: int, bars_per_day: float) -> float:
    """Порог = перцентиль на готовом списке ИСТОРИЧЕСКИХ scores,
    соответствующий target_calls_per_day. Чистая статистика — не вызывает
    claude, не трогает systemd."""
    if not scores or bars_per_day <= 0:
        return float("inf")
    target_share = min(1.0, target_calls_per_day / bars_per_day)
    if target_share <= 0:
        return float("inf")
    idx = max(0, min(len(scores) - 1, int(round((1 - target_share) * (len(scores) - 1)))))
    return sorted(scores)[idx]


def would_trigger(score: float, threshold: float) -> bool:
    return score >= threshold
