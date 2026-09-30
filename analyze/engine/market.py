#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/engine/market.py — общий вид инструмента для любого транспорта.

ЗАЧЕМ. Риск-модуль считает объём, лимиты и барьеры. Ему нужно знать цену
пункта, шаг лота и минимальную дистанцию стопа — и ничего больше. Но у MT5
это `trade_tick_value/trade_tick_size/volume_step/trade_stops_level`, а у
cTrader — `lotSize/minVolume/stepVolume` плюс собственная арифметика цены
пункта. Если пустить эти объекты в `risk.py` напрямую, он обрастёт
условиями «если это MT5, то…», и любая третья площадка потребует править
логику риска — то есть самое опасное место в системе.

Поэтому транспорт обязан привести инструмент к `SymbolInfo`, а риск-модуль
знает только его. Переключение площадки становится конфигурацией, чем оно
и должно быть.

🔴 `money_per_unit` считает ТРАНСПОРТ, а не риск-модуль. У MT5 это готовое
поле терминала, у cTrader — вывод из `lotSize` с разной формулой для прямых
и обратных пар. Сводить эти два способа в одном месте значило бы завести
развилку ровно там, где ошибка тише всего: неверная цена пункта не падает,
она просто делает размер позиции не тем.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SymbolInfo:
    """Всё, что риск-модулю нужно знать об инструменте.

    `money_per_unit` — сколько денег даёт движение цены на 1.0 при объёме
    один лот, в валюте счёта. Единица объёма везде — ЛОТ: транспорт сам
    переводит лоты в свои внутренние единицы (у cTrader это `lotSize`,
    у MT5 лоты и есть родная единица).
    """
    name: str                 # брокерское имя
    canonical: str            # наше каноническое имя
    money_per_unit: float
    volume_min: float         # в лотах
    volume_step: float        # в лотах
    volume_max: float         # в лотах
    digits: int
    point: float
    stops_level: float        # минимальная дистанция барьеров, в цене

    def round_lots(self, lots: float) -> float:
        """Округление ВНИЗ до шага.

        Вниз, а не к ближайшему: округление вверх увеличивает риск, а весь
        смысл риск-модуля в том, что цена ошибки постоянна."""
        step = self.volume_step or self.volume_min or 0.01
        v = int(lots / step) * step
        return round(v, 8)


@dataclass(frozen=True)
class Quote:
    """Живая котировка. Барьеры считаются от неё, а не от закрытия бара.

    🔴 31.08 первый ордер на cTrader был отвергнут как `TRADING_BAD_STOPS`
    именно потому, что стоп посчитали от закрытия H1 (4420.15) при рынке
    4375.74 — расхождение ровно 1%. Бар не является ценой, по которой можно
    войти; между его закрытием и отправкой заявки лежит целый период."""
    bid: float
    ask: float

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    def entry(self, is_long: bool) -> float:
        return self.ask if is_long else self.bid
