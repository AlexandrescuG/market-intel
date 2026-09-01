#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты клиента cTrader. Каждый назван по дефекту, который не даёт вернуть.

Живого соединения не требуют: проверяется расшифровка баров и устройство
сессии. Интеграционная проверка — `ops/check_ctrader.sh` и
`ops/compare_bars.py`, они ходят в сеть.
"""
from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, "/mnt/sbfdata/sbf-platform/market_intel")

from analyze.ctrader import bars                                     # noqa: E402
from analyze.ctrader.session import CTraderError                     # noqa: E402


def tb(low, d_open, d_high, d_close, minutes=29_000_000, volume=10):
    """Свеча в том виде, в каком её присылает протокол: целые сотые тысячных
    и три дельты от `low`."""
    return SimpleNamespace(low=low, deltaOpen=d_open, deltaHigh=d_high,
                           deltaClose=d_close, utcTimestampInMinutes=minutes,
                           volume=volume)


class Decode(unittest.TestCase):
    """🔴 Цены в ProtoOATrendbar приходят НЕ ценами: есть `low` в единицах
    1/100000 и три БЕЗЗНАКОВЫЕ дельты от него. Прочитать поля «как есть» —
    получить мусор, который выглядит правдоподобно: положительный, гладкий,
    похожий на цену другого инструмента. Ровно так 45% трек-рекорда Signals
    оказались размечены по чужому инструменту (17.08)."""

    def test_дельты_складываются_с_low(self):
        c = bars.decode(tb(low=460_000_000, d_open=50_000,
                           d_high=120_000, d_close=30_000))
        self.assertAlmostEqual(c["l"], 4600.00, places=5)
        self.assertAlmostEqual(c["o"], 4600.50, places=5)
        self.assertAlmostEqual(c["h"], 4601.20, places=5)
        self.assertAlmostEqual(c["c"], 4600.30, places=5)

    def test_делитель_не_зависит_от_digits(self):
        """У XAUUSD digits=2, у EURUSD 5 — но бары у обоих в стотысячных.
        Соблазн поделить на 10**digits закончился бы ценой в 46 миллионов."""
        eur = bars.decode(tb(low=115_900, d_open=10, d_high=40, d_close=25))
        self.assertAlmostEqual(eur["l"], 1.15900, places=6)
        self.assertAlmostEqual(eur["h"], 1.15940, places=6)

    def test_метка_времени_в_минутах(self):
        c = bars.decode(tb(460_000_000, 0, 0, 0, minutes=29_000_000))
        self.assertEqual(c["ts"], 29_000_000 * 60)


class Sanity(unittest.TestCase):
    def test_несогласованная_свеча_отвергается(self):
        """Если перепутать порядок дельт, high окажется ниже close —
        и это единственный дешёвый признак, по которому видно ошибку
        расшифровки. Цены при этом остаются положительными."""
        broken = [{"ts": 0, "o": 5.0, "h": 1.0, "l": 0.5, "c": 4.0, "v": 1}]
        with self.assertRaises(CTraderError) as e:
            bars.sane(broken, "TEST")
        self.assertEqual(e.exception.code, "BAD_DECODE")

    def test_корректная_свеча_проходит(self):
        ok = [{"ts": 0, "o": 1.1, "h": 1.3, "l": 1.0, "c": 1.2, "v": 1}]
        bars.sane(ok, "TEST")

    def test_неположительная_цена_отвергается(self):
        with self.assertRaises(CTraderError):
            bars.sane([{"ts": 0, "o": 0, "h": 0, "l": 0, "c": 0, "v": 1}], "TEST")


class SessionShape(unittest.TestCase):
    def test_выход_не_останавливает_реактор(self):
        """🔴 Регрессия на живой дефект 31.08. Первая версия крутила
        `reactor.run()` до ответа и гасила его — это работает ровно один
        раз, второй запрос падает с `ReactorNotRestartable`. Я сам описал
        это ограничение в докстринге модуля и всё равно написал код,
        который на него наступает."""
        import inspect

        from analyze.ctrader import session as s
        src = inspect.getsource(s.Session.__exit__)
        self.assertNotIn("reactor.stop", src,
                         "__exit__ не имеет права гасить реактор: он один "
                         "на процесс и переживает сессию")
        self.assertIn("stopService", src)

    def test_запрос_имеет_таймаут(self):
        """Без таймаута зависший ответ вешает юнит навсегда, а systemd
        показывает `active` — так мост MT5 простоял 26.08 семь часов."""
        import inspect

        from analyze.ctrader import session as s
        self.assertIn("addTimeout", inspect.getsource(s.Session.request))

    def test_отказ_определяется_по_errorCode_а_не_по_типу(self):
        """🔴 Регрессия на живой дефект 31.08. `request` знал одну форму
        неудачи — `ProtoOAErrorRes`, — а отвергнутый ордер вернулся как
        `ProtoOAOrderErrorEvent`. Проверка его пропустила, скрипт напечатал
        «ордер принят», позиции при этом не было. Третий раз за день один и
        тот же класс: проверка знает одну форму отказа и молча пропускает
        остальные. Поэтому теперь признак, а не перечень типов."""
        import inspect

        from analyze.ctrader import session as s
        src = inspect.getsource(s.Session.request)
        self.assertIn('getattr(r, "errorCode", None)', src)
        self.assertNotIn('== "ProtoOAErrorRes"', src,
                         "нельзя опираться на конкретный тип: форм отказа больше одной")

    def test_есть_живая_котировка_а_не_только_бары(self):
        """Барьеры обязаны считаться от рыночной цены. Первая попытка
        отправить ордер взяла закрытие H1 (4420.15) при рынке 4375.74 —
        расхождение ровно 1%, и брокер отверг заявку как TRADING_BAD_STOPS:
        стоп для покупки оказался выше цены входа."""
        from analyze.ctrader import session as s
        self.assertTrue(hasattr(s.Session, "spot"))

    def test_неизвестный_символ_это_отказ(self):
        """Без тихого фолбэка: у Ava золото `GOLD`, у FxPro `XAUUSD`,
        и «вернём имя как есть» дало бы пустые данные, неотличимые от
        «рынок молчит»."""
        import inspect

        from analyze.ctrader import session as s
        src = inspect.getsource(s.Session.symbol_id)
        self.assertIn("NO_SYMBOL", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
