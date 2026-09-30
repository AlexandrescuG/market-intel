#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/ctrader/bars.py — свечи из cTrader в наш формат.

🔴 ГЛАВНАЯ ЛОВУШКА ЭТОГО ФАЙЛА: ЦЕНЫ ПРИХОДЯТ НЕ ЦЕНАМИ.

`ProtoOATrendbar` не содержит четырёх цен. Он содержит `low` в целых
единицах 1/100000 и ТРИ ДЕЛЬТЫ от него — `deltaOpen`, `deltaHigh`,
`deltaClose`, тоже целые и тоже беззнаковые. То есть:

    open  = (low + deltaOpen)  / 100000
    high  = (low + deltaHigh)  / 100000
    close = (low + deltaClose) / 100000
    low   =  low               / 100000

Если прочитать поля «как есть», получится мусор, который при этом выглядит
правдоподобно: числа положительные, монотонные, похожи на цены другого
инструмента. Ровно так 45% трек-рекорда Signals оказались размечены по
чужому инструменту (17.08) — данные были неверные, но не пустые, и потому
никто не заметил. Поэтому здесь стоит проверка вменяемости на выходе.

Делитель 100000 одинаков для всех инструментов и НЕ равен `digits`
символа: у XAUUSD `digits=2`, но бары всё равно в стотысячных.
"""
from __future__ import annotations

import time

from ctrader_open_api.messages.OpenApiMessages_pb2 import *          # noqa: F403
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod

from analyze.ctrader.session import CTraderError, Session

SCALE = 100_000.0

# Наши обозначения ТФ -> периоды cTrader. Слева то, чем оперирует движок
# и `price_bars`, справа — протокол.
PERIODS = {
    "1m": ProtoOATrendbarPeriod.M1, "5m": ProtoOATrendbarPeriod.M5,
    "15m": ProtoOATrendbarPeriod.M15, "30m": ProtoOATrendbarPeriod.M30,
    "1h": ProtoOATrendbarPeriod.H1, "4h": ProtoOATrendbarPeriod.H4,
    "1d": ProtoOATrendbarPeriod.D1, "1w": ProtoOATrendbarPeriod.W1,
}
TF_SEC = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
          "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800}


def decode(tb) -> dict:
    """Одна свеча в наш формат: {"ts","o","h","l","c","v"}."""
    low = tb.low
    return {
        "ts": int(tb.utcTimestampInMinutes) * 60,
        "o": (low + tb.deltaOpen) / SCALE,
        "h": (low + tb.deltaHigh) / SCALE,
        "l": low / SCALE,
        "c": (low + tb.deltaClose) / SCALE,
        "v": int(tb.volume),
    }


def sane(candles: list[dict], name: str) -> None:
    """Проверка вменяемости расшифровки.

    Дешёвая, но ловит именно тот отказ, который иначе не виден: если
    делитель или порядок дельт перепутать, цены останутся положительными и
    гладкими, просто не теми. Здесь проверяется внутренняя согласованность
    свечи — high не ниже остальных, low не выше, — а не диапазон цен: он у
    каждого инструмента свой и жёстко зашивать его значило бы завести ещё
    одну таблицу, которая разойдётся с реальностью."""
    for c in candles[:200]:
        if not (c["l"] <= c["o"] <= c["h"] and c["l"] <= c["c"] <= c["h"]):
            raise CTraderError(
                "BAD_DECODE",
                f"{name}: свеча не согласована o={c['o']} h={c['h']} "
                f"l={c['l']} c={c['c']} — проверьте расшифровку дельт",
                "разбор баров")
        if c["h"] <= 0:
            raise CTraderError("BAD_DECODE", f"{name}: неположительная цена",
                               "разбор баров")


def fetch(session: Session, symbol: str, tf: str, count: int = 500,
          until: int | None = None) -> list[dict]:
    """Последние `count` баров по инструменту.

    Запрашиваем окном по времени, а не «последние N»: у протокола нет
    параметра количества, есть from/to в миллисекундах. Окно берём с
    запасом — брокер отдаёт только те бары, что у него есть, и выходные
    в форексе съедают заметную часть интервала."""
    if tf not in PERIODS:
        raise CTraderError("BAD_TF", f"неизвестный таймфрейм {tf}", "запрос баров")
    sid = session.symbol_id(symbol)
    to_ts = int(until or time.time())
    # ×3 на выходные, праздники и дыры в истории
    from_ts = to_ts - count * TF_SEC[tf] * 3

    req = ProtoOAGetTrendbarsReq()                                   # noqa: F405
    req.ctidTraderAccountId = session.account_id
    req.symbolId = sid
    req.period = PERIODS[tf]
    req.fromTimestamp = from_ts * 1000
    req.toTimestamp = to_ts * 1000
    r = session.request(req, f"бары {symbol}/{tf}")

    out = [decode(tb) for tb in r.trendbar]
    if not out:
        raise CTraderError("NO_BARS", f"{symbol}/{tf}: брокер вернул пусто",
                           "запрос баров")
    sane(out, f"{symbol}/{tf}")
    out.sort(key=lambda c: c["ts"])
    return out[-count:]
