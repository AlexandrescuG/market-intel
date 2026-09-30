#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/mt5_safety.py — предохранители калибровочного контура издержек
(§2 SPEC_mt5_cost_calibration_2026-08-18.md).

Вынесены отдельным модулем и с собственными тестами намеренно: это
единственное, что стоит между исследовательским скриптом и реальными
ордерами. Их надо было проверить ДО первого order_send, а проверить
можно только то, что отделено от кода отправки.

Три требования, каждое блокирующее:
  2.1 только демо, и проверка запросом к терминалу перед КАЖДОЙ отправкой;
  2.2 свой magic на всех ордерах и во всех выборках;
  2.3 фиксированный минимальный объём и потолок открытых позиций.
"""
from __future__ import annotations

# Свой magic. В бутылке живёт торговый EA (докстринг mt5_bridge_pull.py),
# то есть на терминале есть ЧУЖИЕ сделки. Без фильтра по magic калибровка
# собрала бы их как свои, а в худшем случае контур закрыл бы позицию EA.
MAGIC = 20260818

MAX_OPEN_POSITIONS = 10   # потолок наших одновременных позиций
ACCOUNT_TRADE_MODE_DEMO = 0


class SafetyRefusal(RuntimeError):
    """Отказ предохранителя. Ловится вызывающим кодом и пишется в
    cost_observations строкой со статусом — молчаливый пропуск запрещён
    (§5 спеки, урок про sys.exit(0) от 17.08)."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def assert_demo(account_info) -> None:
    """2.1. Не конфигом, не флагом, не переменной окружения — состоянием,
    которое возвращает сам терминал. Конфиг можно перепутать, trade_mode
    врать не будет.

    account_info=None (мост упал, терминал закрыт) — тоже отказ: «не смог
    проверить» и «проверил, всё хорошо» не должны быть одним исходом."""
    if account_info is None:
        raise SafetyRefusal("bridge_down", "account_info() вернул None — счёт не подтверждён")
    mode = getattr(account_info, "trade_mode", None)
    if mode != ACCOUNT_TRADE_MODE_DEMO:
        raise SafetyRefusal(
            "not_demo",
            f"отказ: счёт {getattr(account_info, 'login', '?')} не демо (trade_mode={mode})")


def assert_autotrading(terminal_info) -> None:
    """Без AutoTrading order_send вернёт ошибку, и её надо отличать от
    прочих отказов — иначе выглядит как отказ брокера.

    На 18.08 у терминала именно это состояние: trade_allowed=False."""
    if terminal_info is None:
        raise SafetyRefusal("bridge_down", "terminal_info() вернул None")
    if not getattr(terminal_info, "trade_allowed", False):
        raise SafetyRefusal(
            "autotrading_off",
            "отказ: в терминале выключен AutoTrading (terminal_info().trade_allowed=False); "
            "включается только в GUI терминала")


def our_positions(positions) -> list:
    """2.2. ВСЕ выборки позиций фильтруются по нашему magic."""
    return [p for p in (positions or []) if getattr(p, "magic", None) == MAGIC]


def assert_capacity(positions) -> None:
    """2.3. Потолок считается по НАШИМ позициям — чужие в счёт не идут,
    но и закрывать их контур не имеет права."""
    n = len(our_positions(positions))
    if n >= MAX_OPEN_POSITIONS:
        raise SafetyRefusal(
            "cap_reached",
            f"отказ: открыто {n} наших позиций при потолке {MAX_OPEN_POSITIONS}")


def safe_volume(symbol_info) -> float:
    """2.3. Строго volume_min, не больше. Цель контура — измерить издержки,
    а не набрать экспозицию; на точность измерения комиссии за лот размер
    позиции не влияет."""
    if symbol_info is None:
        raise SafetyRefusal("bridge_down", "symbol_info() вернул None")
    vmin = getattr(symbol_info, "volume_min", None)
    if not vmin or vmin <= 0:
        raise SafetyRefusal("bad_symbol", f"volume_min не задан: {vmin!r}")
    return float(vmin)


def preflight(account_info, terminal_info, positions, symbol_info) -> float:
    """Все предохранители одним вызовом, в порядке возрастания стоимости
    ошибки. Возвращает разрешённый объём либо поднимает SafetyRefusal."""
    assert_demo(account_info)
    assert_autotrading(terminal_info)
    assert_capacity(positions)
    return safe_volume(symbol_info)
