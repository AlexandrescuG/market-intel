#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/ctrader/execution.py — отправка ордеров через cTrader Open API.

Заменяет `analyze/engine/execution.py` в части транспорта. Риск-модуль,
журнал и стоп-краны не меняются: они считают в лотах и в R, и от площадки
не зависят.

🔴 ТРИ ЛОВУШКИ, ЗАМЕРЕННЫЕ НА ЖИВОМ СЧЁТЕ 31.08.

1. ОБЪЁМ НЕ В ЛОТАХ. Протокол принимает объём в единицах `lotSize` символа,
   а не в лотах:

       XAUUSD  lotSize=10 000       minVolume=100      -> 0.01 лота
       EURUSD  lotSize=10 000 000   minVolume=100 000  -> 0.01 лота

   То есть `volume = lots * lotSize`, округлённое до `stepVolume`. Отправить
   туда 0.01 значило бы попросить объём в тысячу раз меньше минимального —
   брокер отвергнет, и разбираться придётся по невнятному отказу.

2. ЦЕНА ПУНКТА СЧИТАЕТСЯ ПО-РАЗНОМУ У ПРЯМЫХ И ОБРАТНЫХ ПАР. В MT5 её давал
   сам терминал (`trade_tick_value/trade_tick_size`), здесь такого поля нет.
   Физический размер лота = `lotSize / 100` (объём в протоколе — сотые доли
   единицы базовой валюты). Дальше:

       котировка в USD (XAUUSD, EURUSD, GBPUSD):  деньги за 1.0 = lotSize/100
       база USD        (USDJPY, USDZAR, USDCHF):  деньги за 1.0 = (lotSize/100)/цена

   Формула сверена с независимыми замерами MT5 на тех же инструментах:
   USDZAR 6258.06 против расчётных 100000/15.98 = 6258, USDJPY 627.02
   против 100000/159.5 = 627.0, XAUUSD 100 против 100. Сходится.

   Всё, что не подходит под эти две формы (кроссы вроде EURGBP при
   долларовом счёте), — ОТКАЗ, а не догадка: там нужен третий курс, и
   ошибка в нём тихо исказит размер позиции.

3. ДЕМО ПРОВЕРЯЕТСЯ У API, А НЕ ПО КОНФИГУ. `isLive` приходит в списке
   счетов по токену. Конфиг можно перепутать, флаг брокера — нет. Та же
   логика, что в `analyze/mt5_safety.assert_demo`.
"""
from __future__ import annotations

from ctrader_open_api.messages.OpenApiMessages_pb2 import *          # noqa: F403
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAOrderType, ProtoOATradeSide)

from analyze.ctrader.session import CTraderError, Session

# Валюта счёта. Держим явно: расчёт цены пункта от неё зависит, а молчаливое
# допущение «у нас доллары» однажды разъедется с реальностью.
DEPOSIT_CURRENCY = "USD"

LABEL = "sbf_engine"


class Executor:
    """Тонкий слой над сессией: детали символов, объёмы, ордера."""

    def __init__(self, session: Session):
        self.s = session
        self._details: dict[int, object] = {}

    # ── предохранители ──────────────────────────────────────────────────

    def assert_demo(self) -> None:
        """Отказ, если счёт не демо ИЛИ если проверить не удалось.

        «Не смог проверить» и «проверил, всё хорошо» не должны быть одним
        исходом — тот же принцип, что в mt5_safety."""
        r = self.s.request(
            ProtoOAGetAccountListByAccessTokenReq(                   # noqa: F405
                accessToken=self.s.token), "список счетов")
        for a in r.ctidTraderAccount:
            if int(a.ctidTraderAccountId) == self.s.account_id:
                if getattr(a, "isLive", False):
                    raise CTraderError("NOT_DEMO",
                                       f"счёт {self.s.account_id} боевой",
                                       "предохранитель")
                return
        raise CTraderError("NO_ACCOUNT",
                           f"счёт {self.s.account_id} не покрыт токеном",
                           "предохранитель")

    # ── детали символов ─────────────────────────────────────────────────

    def details(self, symbol: str):
        sid = self.s.symbol_id(symbol)
        if sid not in self._details:
            req = ProtoOASymbolByIdReq(ctidTraderAccountId=self.s.account_id)  # noqa: F405
            req.symbolId.append(sid)
            r = self.s.request(req, f"детали {symbol}")
            if not r.symbol:
                raise CTraderError("NO_DETAILS", f"{symbol}: деталей нет",
                                   "детали символа")
            self._details[sid] = r.symbol[0]
        return self._details[sid]

    def money_per_price_unit(self, symbol: str, price: float) -> float:
        """Сколько денег даёт движение цены на 1.0 при объёме 1 лот."""
        d = self.details(symbol)
        contract = d.lotSize / 100.0          # физический размер лота
        base, quote = symbol[:3], symbol[3:6]
        if symbol.startswith("XAU") or symbol.startswith("XAG"):
            base, quote = symbol[:3], symbol[3:]
        if quote == DEPOSIT_CURRENCY:
            return contract
        if base == DEPOSIT_CURRENCY:
            if price <= 0:
                raise CTraderError("BAD_PRICE", f"{symbol}: цена {price}",
                                   "цена пункта")
            return contract / price
        raise CTraderError(
            "UNSUPPORTED_PAIR",
            f"{symbol}: ни база, ни котировка не {DEPOSIT_CURRENCY} — нужен "
            f"третий курс, угадывать нельзя", "цена пункта")

    def to_protocol_volume(self, symbol: str, lots: float) -> int:
        """Лоты -> объём протокола, с округлением вниз до шага.

        Вниз, а не к ближайшему: округление вверх увеличивает риск, а весь
        смысл риск-модуля в том, что цена ошибки постоянна."""
        d = self.details(symbol)
        raw = lots * d.lotSize
        step = d.stepVolume or d.minVolume or 1
        vol = int(raw // step) * step
        if vol < d.minVolume:
            raise CTraderError(
                "VOLUME_TOO_SMALL",
                f"{symbol}: {lots:.4f} лота = {int(raw)} < минимума "
                f"{d.minVolume} ({d.minVolume / d.lotSize:.4f} лота)",
                "объём")
        return min(vol, d.maxVolume) if d.maxVolume else vol

    def lots_of(self, symbol: str, protocol_volume: int) -> float:
        return protocol_volume / self.details(symbol).lotSize

    # ── торговые операции ───────────────────────────────────────────────

    def market_order(self, symbol: str, *, is_long: bool, lots: float,
                     stop: float, target: float, label: str = LABEL):
        """Рыночный ордер СО СТОПОМ И ЦЕЛЬЮ В САМОЙ ЗАЯВКЕ.

        Барьеры уходят вместе с ордером, а не «закроем потом сами»: без них
        позиция висит бесконечно, если наш процесс перезапустят. Барьеры на
        стороне брокера переживают всё, что происходит на нашей стороне."""
        d = self.details(symbol)
        vol = self.to_protocol_volume(symbol, lots)
        req = ProtoOANewOrderReq()                                   # noqa: F405
        req.ctidTraderAccountId = self.s.account_id
        req.symbolId = self.s.symbol_id(symbol)
        req.orderType = ProtoOAOrderType.MARKET
        req.tradeSide = ProtoOATradeSide.BUY if is_long else ProtoOATradeSide.SELL
        req.volume = vol
        req.stopLoss = round(stop, d.digits)
        req.takeProfit = round(target, d.digits)
        req.label = label
        return self.s.request(req, f"ордер {symbol}")

    def positions(self) -> list:
        """Только НАШИ позиции — по метке. Чужие не трогаем ни при каких
        обстоятельствах: на счёте могут быть ручные сделки владельца."""
        r = self.s.request(
            ProtoOAReconcileReq(ctidTraderAccountId=self.s.account_id),  # noqa: F405
            "открытые позиции")
        return [p for p in r.position
                if getattr(p.tradeData, "label", "") == LABEL]

    def close(self, position):
        req = ProtoOAClosePositionReq()                              # noqa: F405
        req.ctidTraderAccountId = self.s.account_id
        req.positionId = position.positionId
        req.volume = position.tradeData.volume
        return self.s.request(req, f"закрытие {position.positionId}")

    def deals(self, from_ts: int, to_ts: int) -> list:
        r = self.s.request(
            ProtoOADealListReq(ctidTraderAccountId=self.s.account_id,  # noqa: F405
                               fromTimestamp=from_ts * 1000,
                               toTimestamp=to_ts * 1000), "история сделок")
        return list(r.deal)
