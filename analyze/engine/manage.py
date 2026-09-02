#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/engine/manage.py — сопровождение открытой позиции.

Три правила, которых у нас не было: перевод стопа в безубыток, трейлинг и
досрочный выход. Все три СТАТИЧНЫ по отношению к рынку — они не пытаются
предсказать направление, а меняют форму выплаты уже открытой сделки. Это
важное отличие: предсказание требует преимущества, которого у нас нет,
а управление позицией — не требует.

🔴 НО ЭТО НЕ ЗНАЧИТ, ЧТО ОНО БЕСПЛАТНО. Перевод в безубыток срезает часть
проигрышей, но и превращает часть будущих выигрышей в нули: цена сходит
против на шум, выбивает стоп на входе, а потом идёт к цели без нас. Чистый
эффект на ожидание НЕ очевиден и обязан быть измерен, а не предположен.
Поэтому правила параметризованы и прогоняются через `analyze/engine/backtest.py`
теми же историческими данными, что и входы.

По умолчанию всё выключено (`Rules.off()`). Включать — только после того,
как исторический прогон покажет, что становится лучше.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rules:
    """Параметры сопровождения. Все пороги — в единицах R (риска сделки),
    чтобы правило одинаково работало на золоте и на евро."""

    # Перевод в безубыток: при каком ходе в плюс и куда именно ставить стоп.
    # `be_offset_r` > 0 оставляет запас на издержки: стоп ровно на входе
    # закрывается в минус на величину спреда.
    breakeven_at_r: float | None = None
    be_offset_r: float = 0.1

    # Трейлинг: после какого хода начинать и на каком расстоянии вести.
    trail_after_r: float | None = None
    trail_distance_r: float = 1.0

    # Досрочный выход по застою: если за N баров сделка не прошла и
    # `min_progress_r`, выйти по рынку. Смысл не в прогнозе, а в том, что
    # позиция занимает лимит портфеля и платит своп, ничего не делая.
    stagnation_bars: int | None = None
    min_progress_r: float = 0.3

    @staticmethod
    def off() -> "Rules":
        return Rules()

    @property
    def enabled(self) -> bool:
        return any((self.breakeven_at_r, self.trail_after_r, self.stagnation_bars))


def new_stop(rules: Rules, *, is_long: bool, entry: float, stop: float,
             best_price: float) -> float | None:
    """Куда переставить стоп, либо None если двигать не надо.

    `best_price` — максимум цены за время жизни сделки для лонга (минимум
    для шорта), а НЕ текущая цена. Стоп двигается только в сторону прибыли:
    правило, позволяющее отодвинуть стоп назад, — это не управление риском,
    а его отмена."""
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    moved_r = ((best_price - entry) if is_long else (entry - best_price)) / risk
    candidates: list[float] = []

    if rules.breakeven_at_r is not None and moved_r >= rules.breakeven_at_r:
        off = rules.be_offset_r * risk
        candidates.append(entry + off if is_long else entry - off)

    if rules.trail_after_r is not None and moved_r >= rules.trail_after_r:
        d = rules.trail_distance_r * risk
        candidates.append(best_price - d if is_long else best_price + d)

    if not candidates:
        return None
    want = max(candidates) if is_long else min(candidates)
    # только вперёд
    if (is_long and want > stop) or (not is_long and want < stop):
        return want
    return None


def should_exit(rules: Rules, *, is_long: bool, entry: float, stop: float,
                price: float, bars_held: int) -> str | None:
    """Причина досрочного выхода, либо None.

    Отдельно от `new_stop`, потому что это разные решения: подтянуть стоп —
    сузить риск, выйти — признать, что сделка не работает. Смешивать их в
    одной функции значит однажды закрыть позицию там, где хотели лишь
    подвинуть барьер."""
    if rules.stagnation_bars is None or bars_held < rules.stagnation_bars:
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    progress = ((price - entry) if is_long else (entry - price)) / risk
    if progress < rules.min_progress_r:
        return (f"застой: за {bars_held} баров пройдено {progress:+.2f}R "
                f"при пороге {rules.min_progress_r}R")
    return None


# Наборы для исторической проверки. Не «настройки на выбор», а гипотезы:
# каждая должна пройти прогон прежде, чем попасть в живой контур.
PRESETS = {
    "выключено": Rules.off(),
    "безубыток_1R": Rules(breakeven_at_r=1.0),
    "безубыток_0.5R": Rules(breakeven_at_r=0.5),
    "трейлинг_1R": Rules(trail_after_r=1.0, trail_distance_r=1.0),
    "безубыток+трейлинг": Rules(breakeven_at_r=1.0, trail_after_r=1.5,
                                trail_distance_r=1.0),
    "выход_по_застою_12": Rules(stagnation_bars=12, min_progress_r=0.3),
}
