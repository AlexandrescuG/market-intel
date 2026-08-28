#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/engine/contracts.py — общий словарь движка.

Одна структура `Signal` на все источники. Смысл в том, что источник обязан
досчитать за себя всё, что нужно для решения: цену-основание, стоп, цель,
ATR и горизонт. Если источник не может назвать стоп — он не выдаёт сигнал,
а не оставляет это исполнителю. Иначе риск-модуль пришлось бы учить
особенностям каждого источника, и «сколько мы рискуем» перестало бы быть
одним числом.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

# Свой magic, отдельно от калибровочного 20260818 — иначе движок собирал бы
# позиции старого контура как свои, а close_aged() мог бы их закрыть.
ENGINE_MAGIC = 20260827

LONG, SHORT = "long", "short"

# Статусы стратегии в engine_strategy_state.
ST_LIVE = "live"        # шлёт живые ордера
ST_SHADOW = "shadow"    # считается, но не торгует
ST_HALTED = "halted"    # остановлена стоп-краном, руками не трогать до разбора


@dataclass(frozen=True)
class Signal:
    """Кандидат на сделку. Полностью самодостаточен для исполнения.

    `dedup_key` — то, чем сигнал отличается от повторного взгляда на ту же
    ситуацию. Обязан включать метку бара-основания: без неё стратегия,
    условие которой держится неделями (как gold_oil), войдёт на каждом тике
    планировщика и превратит один эпизод режима в сотню «наблюдений».
    """
    strategy: str
    symbol: str            # каноническое имя (XAUUSD, EURUSD…), не брокерское
    tf: str                # 1h | 4h | 1d
    direction: str         # LONG | SHORT
    bar_ts: int            # закрытие бара-основания, UTC
    ref_price: float       # цена основания (для контроля сноса)
    stop: float            # абсолютная цена
    target: float          # абсолютная цена
    atr: float
    horizon_sec: int
    dedup_key: str
    features: dict = field(default_factory=dict)
    confidence: float = 1.0

    @property
    def is_long(self) -> bool:
        return self.direction == LONG

    @property
    def stop_distance(self) -> float:
        return abs(self.ref_price - self.stop)

    @property
    def rr(self) -> float:
        d = self.stop_distance
        return abs(self.target - self.ref_price) / d if d > 0 else 0.0

    def validate(self) -> str | None:
        """Причина, по которой сигнал нельзя исполнять, либо None.

        Проверяется до всякого риска: геометрия, вывернутая наизнанку,
        отвергается брокером как invalid stops, и в журнале копились бы
        order_rejected без внятной причины (тот же урок, что в live_strategy
        19.08 про снос цены)."""
        if self.direction not in (LONG, SHORT):
            return f"неизвестное направление {self.direction!r}"
        if self.atr is None or self.atr <= 0:
            return "ATR не положителен"
        if self.stop_distance <= 0:
            return "стоп совпадает с ценой основания"
        if self.is_long and not (self.stop < self.ref_price < self.target):
            return (f"геометрия лонга нарушена: стоп {self.stop:.5f} / вход "
                    f"{self.ref_price:.5f} / цель {self.target:.5f}")
        if not self.is_long and not (self.target < self.ref_price < self.stop):
            return (f"геометрия шорта нарушена: цель {self.target:.5f} / вход "
                    f"{self.ref_price:.5f} / стоп {self.stop:.5f}")
        if self.horizon_sec <= 0:
            return "горизонт не положителен"
        return None

    def features_json(self) -> str:
        return json.dumps(self.features, ensure_ascii=False, sort_keys=True)


@dataclass
class Decision:
    """Что движок решил по сигналу и почему. Пишется ВСЕГДА, в том числе на
    отказ: журнал, в котором видны только исполненные сделки, не позволяет
    отличить «источник молчал» от «риск-модуль всё отклонил»."""
    signal: Signal
    accepted: bool
    reason: str
    volume: float = 0.0
    risk_money: float = 0.0
