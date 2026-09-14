#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты движка. Проверяется ровно то, что стоит между источником и ордером:
геометрия, размер от риска, портфельные лимиты и стоп-кран по просадке.

Каждый тест назван по дефекту, который он не даёт вернуть. Все четыре
пункта — из разбора просадки 26-27.08.2026.
"""
from __future__ import annotations

import sqlite3
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, "/mnt/sbfdata/sbf-platform/market_intel")

from analyze.engine import ledger, risk                       # noqa: E402
from analyze.engine.contracts import LONG, SHORT, Signal, ST_HALTED, ST_LIVE  # noqa: E402


def sig(**kw) -> Signal:
    base = dict(strategy="t", symbol="XAUUSD", tf="1h", direction=LONG,
                bar_ts=1000, ref_price=4600.0, stop=4570.0, target=4660.0,
                atr=20.0, horizon_sec=3600, dedup_key="t:1")
    base.update(kw)
    return Signal(**base)


SI = SimpleNamespace(trade_tick_value=1.0, trade_tick_size=0.01,
                     volume_min=0.01, volume_max=100.0, volume_step=0.01, digits=2)


class Geometry(unittest.TestCase):
    def test_вывернутый_лонг_отвергается(self):
        """Цель ниже входа -> брокер вернёт invalid stops, и в журнале
        копились бы order_rejected без внятной причины (урок 19.08)."""
        with self.assertRaises(risk.RiskRefusal) as c:
            risk.geometry_gate(sig(target=4500.0))
        self.assertEqual(c.exception.status, "bad_geometry")

    def test_шорт_с_правильной_геометрией_проходит(self):
        risk.geometry_gate(sig(direction=SHORT, stop=4630.0, target=4540.0))

    def test_слишком_тесный_стоп_отвергается(self):
        with self.assertRaises(risk.RiskRefusal) as c:
            risk.geometry_gate(sig(stop=4599.0))     # 0.05 ATR
        self.assertEqual(c.exception.status, "stop_too_tight")

    def test_слишком_широкий_стоп_отвергается(self):
        with self.assertRaises(risk.RiskRefusal) as c:
            risk.geometry_gate(sig(stop=4400.0, target=5000.0))   # 10 ATR
        self.assertEqual(c.exception.status, "stop_too_wide")


class Sizing(unittest.TestCase):
    def test_объём_обратно_пропорционален_ширине_стопа(self):
        """🔴 Главная правка. В старом контуре объём был volume_min всегда,
        и при расширении ATR стоп дорожал с -31 до -45 USD — риск рос сам.
        Здесь цена ошибки постоянна, а меняется объём."""
        eq = 1_000_000.0        # крупный счёт, чтобы округление до шага лота не мешало
        v_narrow, r_narrow = risk.position_volume(sig(stop=4570.0), eq, SI)
        v_wide, r_wide = risk.position_volume(sig(stop=4540.0, target=4720.0), eq, SI)
        self.assertGreater(v_narrow, v_wide)
        self.assertAlmostEqual(r_narrow, r_wide, delta=r_narrow * 0.05)

    def test_риск_держится_около_заданной_доли(self):
        eq = 1_000_000.0
        _, rm = risk.position_volume(sig(), eq, SI)
        self.assertAlmostEqual(rm, eq * risk.RISK_PER_TRADE, delta=eq * 0.0002)

    def test_отказ_вместо_округления_риска_вверх(self):
        """Если минимальный лот дороже разрешённого риска — не берём сделку,
        а не округляем вверх. На мелком счёте движок обязан молчать.

        Замерено на живом терминале: по золоту минимальный лот при стопе
        1.5 ATR стоит ~23.5 USD, то есть нижний предел риска задаёт брокер,
        а не мы."""
        with self.assertRaises(risk.RiskRefusal) as c:
            risk.position_volume(sig(), 100.0, SI)
        self.assertEqual(c.exception.status, "risk_too_small")

    def test_золото_проходит_при_текущем_счёте(self):
        """Регрессия на выбор RISK_PER_TRADE: если однажды его снизят до
        0.25%, золото начнёт отказываться молча, и это будет выглядеть как
        «сигналов нет»."""
        gold = SimpleNamespace(trade_tick_value=0.01, trade_tick_size=0.01,
                               volume_min=0.01, volume_max=100.0,
                               volume_step=0.01, digits=2)
        atr_now = 15.66
        s = sig(ref_price=4600.0, stop=4600.0 - 1.5 * atr_now,
                target=4600.0 + 3.0 * atr_now, atr=atr_now)
        vol, rm = risk.position_volume(s, 10_000.0, gold)
        self.assertGreaterEqual(vol, 0.01)


class Maintenance(unittest.TestCase):
    """🔴 14.09. sbf-engine.service запускает код прямо из рабочего дерева,
    и дерево общее для нескольких чатов. Правка риск-модуля уехала в бой на
    полпути: прогон в 15:03 подхватил снятый запрет раньше, чем были
    дописаны тесты."""

    def test_смотрим_только_на_файлы_движка(self):
        """Правка в вёрстке сайта не должна останавливать торговлю — иначе
        предохранитель начнёт мешать и его отключат целиком."""
        from analyze.engine import run as engine_run
        self.assertEqual(engine_run.ENGINE_DIR, "analyze/engine")

    def test_отказ_git_не_блокирует_торговлю(self):
        """Предохранитель полезный, но не критичный: падать из-за него хуже,
        чем не сработать."""
        import subprocess
        from analyze.engine import run as engine_run
        real = subprocess.run
        try:
            subprocess.run = lambda *a, **k: (_ for _ in ()).throw(OSError("нет git"))
            self.assertEqual(engine_run.dirty_engine_files(), [])
        finally:
            subprocess.run = real

    def test_грязное_дерево_видно(self):
        """Замер на себе: этот файл сейчас изменён и не закоммичен, значит
        функция обязана его вернуть. Тест самоподтверждающийся — если
        механизм сломается, он это покажет на любом живом изменении."""
        import subprocess
        from analyze.engine import run as engine_run
        out = subprocess.run(["git", "-C", "/mnt/sbfdata/sbf-platform/market_intel",
                              "status", "--porcelain", "--", "analyze/engine"],
                             capture_output=True, text=True)
        expect = [ln[3:].strip() for ln in out.stdout.splitlines() if ln.strip()]
        self.assertEqual(engine_run.dirty_engine_files(), expect)


class StopClamp(unittest.TestCase):
    """🔴 14.09. Барьер брокера проверялся только на ВХОДЕ. Сопровождение
    просило стоп ближе минимальной дистанции, получало «Invalid stops» и
    повторяло это каждый час: 15 прогонов подряд 13.09 с «перенесено=0
    ошибок=2», потом ещё трижды по три ошибки 14.09."""

    ZAR = SimpleNamespace(point=0.00001, trade_stops_level=2000, digits=5)
    GBP = SimpleNamespace(point=0.00001, trade_stops_level=20, digits=5)

    @staticmethod
    def tick(bid, ask):
        return SimpleNamespace(bid=bid, ask=ask)

    def test_слишком_близкий_стоп_прижимается_а_не_падает(self):
        """Числа из живого замера: хотели 16.28914 при цене 16.28640, то есть
        0.00274 при нужных 0.02200."""
        got = risk.clamp_stop(16.28914, is_long=True, price=16.28640,
                              cur_stop=16.13596, symbol_info=self.ZAR,
                              tick=self.tick(16.28640, 16.28840))
        self.assertIsNotNone(got, "перенос не должен отменяться целиком")
        need = risk.min_barrier(self.ZAR, self.tick(16.28640, 16.28840))
        self.assertLessEqual(got, 16.28640 - need + 1e-9,
                             "прижали недостаточно — брокер снова откажет")
        self.assertGreater(got, 16.13596, "стоп обязан уйти вперёд")

    def test_шорт_прижимается_вверх(self):
        got = risk.clamp_stop(1.34768, is_long=False, price=1.34799,
                              cur_stop=1.35179, symbol_info=self.GBP,
                              tick=self.tick(1.34779, 1.34799))
        need = risk.min_barrier(self.GBP, self.tick(1.34779, 1.34799))
        self.assertGreaterEqual(got, 1.34799 + need - 1e-9)
        self.assertLess(got, 1.35179)

    def test_назад_стоп_не_едет(self):
        """Если даже разрешённый уровень хуже нынешнего стопа — не двигаем
        вовсе. Иначе прижатие превратилось бы в ослабление защиты."""
        self.assertIsNone(
            risk.clamp_stop(16.30, is_long=True, price=16.10,
                            cur_stop=16.09, symbol_info=self.ZAR,
                            tick=self.tick(16.10, 16.11)))

    def test_свободный_стоп_не_трогается(self):
        """Когда до цены места хватает, прижимать нечего."""
        t = self.tick(1.35000, 1.35002)
        got = risk.clamp_stop(1.34500, is_long=True, price=1.35000,
                              cur_stop=1.34000, symbol_info=self.GBP, tick=t)
        self.assertAlmostEqual(got, 1.34500)


class Portfolio(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.executescript(ledger.SCHEMA)

    @staticmethod
    def _lonely(i: int) -> str:
        """Пара с НЕПЕРЕСЕКАЮЩИМИСЯ ногами: AAABBB, CCCDDD, …

        Нужна там, где проверяется портфельный потолок и только он. С
        настоящими инструментами так не выйдет: у любых двух пар из нашего
        списка есть общая нога (обычно доллар), и тест упрётся в потолок по
        ноге, не дойдя до проверяемого."""
        a = chr(ord("A") + (i * 2) % 26) * 3
        b = chr(ord("A") + (i * 2 + 1) % 26) * 3
        return a + b

    def _open(self, symbol="XAUUSD", direction=LONG, strategy="t", rm=25.0):
        self.con.execute(
            "INSERT INTO engine_trades (strategy, symbol, direction, mode, status, "
            "risk_money) VALUES (?,?,?,'live','open',?)", (strategy, symbol, direction, rm))
        self.con.commit()

    def test_десять_лонгов_по_золоту_упрутся_в_риск(self):
        """🔴 26-27.08: старый потолок «10 наших позиций» не различал символ
        и сторону, набралось десять лонгов по золоту и вынесло одним
        движением — шесть стопов за 13 минут.

        Теперь потолок в деньгах, и он срабатывает РАНЬШЕ счётного: при 0.5%
        на сделку и 1.5% на инструмент четвёртый лонг уже не пройдёт."""
        equity = 10_000.0
        rm = equity * risk.RISK_PER_TRADE
        n = int(risk.MAX_SYMBOL_RISK / risk.RISK_PER_TRADE)
        self.assertLess(n, risk.MAX_OPEN_PER_SYMBOL,
                        "счётный потолок обязан остаться ПОЗАДИ денежного — "
                        "иначе он снова станет рабочим ограничением")
        for _ in range(n):
            self._open(symbol="XAUUSD", direction=LONG, rm=rm)
        with self.assertRaises(risk.RiskRefusal) as c:
            risk.portfolio_gate(self.con, sig(symbol="XAUUSD", direction=LONG),
                                equity, rm)
        self.assertEqual(c.exception.status, "cap_symbol_risk")

    def test_выкупленный_стоп_освобождает_инструмент(self):
        """Штуки не различали позицию с полным риском и позицию, которой
        нечего терять: третий вход блокировался, даже когда двум предыдущим
        стоп уже подтянули за точку входа. 416 отказов за 14 дней, 207 по
        EURUSD."""
        equity = 10_000.0
        rm = equity * risk.RISK_PER_TRADE
        for _ in range(int(risk.MAX_SYMBOL_RISK / risk.RISK_PER_TRADE)):
            # стоп ВЫШЕ входа у лонга: риска не осталось
            self._open_live("EURUSD", LONG, entry=1.1000, stop=1.1020,
                            rpp=10_000.0, rm=rm)
        risk.portfolio_gate(self.con, sig(symbol="EURUSD", direction=LONG),
                            equity, rm)

    def test_другой_символ_не_блокируется(self):
        """Потолок на инструмент не должен мешать входу по ДРУГОМУ
        инструменту. Размеры подобраны так, чтобы не задеть долларовую ногу:
        иначе тест упрётся в неё и перестанет проверять то, что называет."""
        equity = 10_000.0
        rm = equity * risk.RISK_PER_TRADE
        self.assertLessEqual(3 * rm / equity, risk.leg_cap(),
                             "три ставки в одну сторону уже не влезают в "
                             "долларовую ногу — подбери размеры заново")
        for _ in range(2):
            self._open(symbol="XAUUSD", direction=LONG, rm=rm)
        risk.portfolio_gate(self.con, sig(symbol="EURUSD", direction=LONG,
                                          strategy="other"), equity, rm)

    def test_суммарный_риск_портфеля_ограничен(self):
        """Число позиций выводится из константы, а не зашито: иначе тест
        перестал бы ловить дефект при первой же правке MAX_PORTFOLIO_RISK
        (ровно это и случилось при переходе с 2% на 3%)."""
        equity, rm = 10_000.0, 40.0
        budget = equity * risk.MAX_PORTFOLIO_RISK
        n = int(budget // rm)                     # столько ещё помещается
        self.assertLess(n + 1, risk.MAX_OPEN_TOTAL, "тест упрётся не в тот лимит")
        for i in range(n):
            self._open(symbol=self._lonely(i), strategy=f"st{i}", rm=rm)
        with self.assertRaises(risk.RiskRefusal) as c:
            risk.portfolio_gate(self.con, sig(symbol=self._lonely(20), strategy="new"), equity, rm)
        self.assertEqual(c.exception.status, "cap_portfolio_risk")

    def test_встречная_позиция_гасит_нетто(self):
        """🔴 14.09. Запрет opposite_open снят: R считается по ценам самой
        сделки и от чужой позиции не зависит. Встречный риск обязан
        вычитаться, а не складываться."""
        equity = 10_000.0
        # Размер берём такой, чтобы ПАРА укладывалась в валовой потолок:
        # по нетто она даёт ноль, и упереться должна только в валовой.
        rm = equity * risk.MAX_GROSS_RISK / 2 * 0.9
        self.assertGreater(rm, equity * risk.MAX_PORTFOLIO_RISK / 2,
                           "размер должен быть таким, чтобы СУММА перебрала "
                           "направленный лимит — иначе тест ничего не проверяет")
        self._open(symbol="EURUSD", direction=SHORT, rm=rm, strategy="a")
        # Встречный лонг: нетто становится нулём, а не удвоением.
        risk.portfolio_gate(self.con, sig(symbol="EURUSD", direction=LONG,
                                          strategy="b"), equity, rm)

    def test_пила_ловится_валовым_потолком(self):
        """Нетто этот случай НЕ ловит, и в этом весь смысл второго потолка:
        цена сходила вверх и выбила стоп шорта, вернулась вниз и выбила стоп
        лонга — потеряны оба, худший случай равен СУММЕ. Нетто в этот момент
        показывал бы ноль."""
        equity = 10_000.0
        rm = equity * risk.MAX_GROSS_RISK / 2 + 1.0     # пара переберёт валовой
        self._open(symbol="EURUSD", direction=SHORT, rm=rm, strategy="a")
        with self.assertRaises(risk.RiskRefusal) as c:
            risk.portfolio_gate(self.con, sig(symbol="EURUSD", direction=LONG,
                                              strategy="b"), equity, rm)
        self.assertEqual(c.exception.status, "cap_gross_risk")

    def test_разные_инструменты_не_гасят_друг_друга(self):
        """Гасить имеют право лонг и шорт ОДНОГО инструмента. Лонг EURUSD
        против шорта золота — две разные ставки, а не ноль.

        Размер каждой позиции держим НИЖЕ потолка на инструмент, иначе тест
        упрётся в него и перестанет проверять то, ради чего написан."""
        equity = 10_000.0
        rm = equity * risk.RISK_PER_TRADE
        n = int(risk.MAX_PORTFOLIO_RISK / risk.RISK_PER_TRADE)
        for i in range(n):
            self._open(symbol=self._lonely(i), direction=SHORT, rm=rm, strategy=f"st{i}")
        with self.assertRaises(risk.RiskRefusal) as c:
            risk.portfolio_gate(self.con, sig(symbol=self._lonely(20), direction=LONG,
                                              strategy="new"), equity, rm)
        self.assertEqual(c.exception.status, "cap_portfolio_risk")

    def test_три_ставки_против_доллара_считаются_одной(self):
        """🔴 14.09, по замеру ops/measure_legs.py: если развернуть ряды так,
        чтобы «+» означал сильный доллар, все 15 пар инструментов
        положительны, медиана 0.48. Лонг EURUSD, лонг GBPUSD и шорт USDJPY —
        одна ставка, а не три независимые."""
        equity = 10_000.0
        rm = equity * risk.RISK_PER_TRADE
        # Сколько одинаковых ставок влезает в ногу — выводим из потолка,
        # а не зашиваем: потолок считается из корреляции и будет меняться.
        n = int(risk.leg_cap() * equity // rm)
        self.assertGreaterEqual(n, 1)
        pool = [("EURUSD", LONG), ("GBPUSD", LONG), ("USDJPY", SHORT),
                ("USDZAR", SHORT), ("USDCNY", SHORT)]
        for i in range(n):
            s, d = pool[i]
            self._open(symbol=s, direction=d, rm=rm, strategy=f"st{i}")
        s, d = pool[n]
        with self.assertRaises(risk.RiskRefusal) as c:
            risk.portfolio_gate(self.con, sig(symbol=s, direction=d,
                                              strategy="new"), equity, rm)
        self.assertEqual(c.exception.status, "cap_leg_risk")

    def test_встречные_ноги_доллара_гасятся(self):
        """Лонг EURUSD и лонг USDJPY — ставки в РАЗНЫЕ стороны по доллару.
        Они обязаны вычитаться, иначе потолок ловил бы диверсификацию."""
        equity = 10_000.0
        rm = equity * risk.RISK_PER_TRADE
        for i in range(3):
            self._open(symbol="EURUSD", direction=LONG, rm=rm, strategy=f"a{i}")
        # USD-нога здесь −3 сделки; встречная по доллару возвращает её к −2.
        risk.portfolio_gate(self.con, sig(symbol="USDJPY", direction=LONG,
                                          strategy="b"), equity, rm)

    def test_ноги_раскладываются(self):
        self.assertEqual(risk.legs("EURUSD"), ("EUR", "USD"))
        self.assertEqual(risk.legs("USDJPY"), ("USD", "JPY"))
        # Золото — своя нога, а не «валюта против доллара с полным весом».
        self.assertEqual(risk.legs("XAUUSD"), ("XAU", "USD"))
        # Кросс без доллара тоже раскладывается: раньше он молча получал ноль.
        self.assertEqual(risk.legs("EURGBP"), ("EUR", "GBP"))

    def test_нераскладываемый_инструмент_это_отказ_а_не_ноль(self):
        """🔴 Доделка 14.09. Первая версия возвращала 0 для всего, в чём нет
        доллара, — инструмент выпадал из расчёта риска целиком и молча.
        Неизвестный риск это не нулевой риск."""
        with self.assertRaises(risk.RiskRefusal) as c:
            risk.legs("BTC")
        self.assertEqual(c.exception.status, "unknown_legs")

    def test_кросс_пара_попадает_в_обе_ноги(self):
        """Лонг EURGBP — ставка за евро и против фунта. При открытом лонге
        EURUSD ставка по евро удваивается, и лимит обязан это видеть."""
        e = risk.leg_exposure([("EURUSD", "long", "a", 100.0, 1)],
                              add=("EURGBP", True, 100.0))
        self.assertAlmostEqual(e["EUR"], 200.0)
        self.assertAlmostEqual(e["USD"], -100.0)
        self.assertAlmostEqual(e["GBP"], -100.0)

    def test_потолок_ноги_выводится_из_корреляции(self):
        """Потолок обязан ужесточаться при росте корреляции, а не быть
        назначенным числом."""
        soft = risk.leg_cap.__wrapped__ if hasattr(risk.leg_cap, "__wrapped__") else None
        self.assertIsNone(soft)
        cap = risk.leg_cap()
        self.assertLess(cap, risk.MAX_PORTFOLIO_RISK,
                        "при положительной корреляции нога обязана быть строже "
                        "портфельного потолка")
        self.assertGreater(cap, risk.RISK_PER_TRADE,
                           "иначе не пройдёт даже одна сделка полного размера")

    def test_протухший_замер_не_ослабляет_лимит(self):
        """Незнание не повод ослаблять: без свежего файла берётся запасное
        значение, и оно СТРОЖЕ последнего замера."""
        rho, src = risk._corr_now()
        self.assertGreaterEqual(risk.CORR_FALLBACK, rho - 1e-9,
                                "запасная корреляция должна быть не мягче замера")

    def test_пересечение_помечается(self):
        self._open(symbol="EURUSD", direction=SHORT, strategy="a")
        tid = risk.crossing_trade(self.con, "EURUSD", is_long=True)
        self.assertIsNotNone(tid)
        self.assertIsNone(risk.crossing_trade(self.con, "EURUSD", is_long=False))
        self.assertIsNone(risk.crossing_trade(self.con, "GBPUSD", is_long=True))

    def _open_live(self, symbol, direction, entry, stop, rpp, rm, strategy="t"):
        """Позиция с полной геометрией — по ней считается ЖИВОЙ риск."""
        self.con.execute(
            "INSERT INTO engine_trades (strategy, symbol, direction, mode, status, "
            "risk_money, risk_per_price, entry_price, stop) "
            "VALUES (?,?,?,'live','open',?,?,?,?)",
            (strategy, symbol, direction, rm, rpp, entry, stop))
        self.con.commit()

    def test_стоп_за_безубытком_освобождает_лимит(self):
        """🔴 14.09. risk_money пишется на входе и не меняется, а manage_open
        двигает стоп. На живом счёте шесть позиций занимали 328 USD при
        потолке 324, то есть лимит был выбран целиком, — при реальном остатке
        риска 187 USD: у трёх стоп стоял ЗА точкой входа."""
        equity = 10_000.0
        rm = equity * risk.RISK_PER_TRADE
        n = int(risk.MAX_PORTFOLIO_RISK / risk.RISK_PER_TRADE)
        for i in range(n):
            # Лонг со стопом ВЫШЕ входа: терять нечего, прибыль заперта.
            self._open_live(self._lonely(i), LONG, entry=1.1000, stop=1.1020,
                            rpp=10_000.0, rm=rm, strategy=f"st{i}")
        # По записи лимит выбран целиком, живого риска в нём нет — проходим.
        risk.portfolio_gate(self.con, sig(symbol=self._lonely(20), strategy="new"),
                            equity, rm)

    def test_живой_риск_считается_и_вверх(self):
        """Если брокер налил хуже расчётного и дистанция до стопа шире
        задуманной, живой риск обязан выйти БОЛЬШЕ записанного — иначе это
        не честный пересчёт, а поблажка в одну сторону."""
        r = risk.live_risk(LONG, entry=1.1000, stop=1.0950,
                           risk_per_price=10_000.0, risk_money=40.0)
        self.assertAlmostEqual(r, 50.0, places=6)

    def test_без_геометрии_остаётся_старое_число(self):
        """Строки, заведённые до появления risk_per_price, не должны молча
        обнулиться: нет данных для пересчёта — берём то, что записано."""
        self.assertEqual(
            risk.live_risk(LONG, entry=None, stop=None,
                           risk_per_price=None, risk_money=33.0), 33.0)


class BrokerConstraints(unittest.TestCase):
    """🔴 Первый боевой прогон 28.08: 4 из 9 принятых сигналов отбились
    `Invalid stops` (retcode 10016) — все по USDCNY и USDZAR. У брокера
    свой минимум дистанции барьеров, и он очень разный: GOLD 50 пунктов,
    EURUSD 1, USDZAR 120 плюс спред ещё 100."""

    def _si(self, point, stops_level):
        return SimpleNamespace(point=point, trade_stops_level=stops_level,
                               trade_tick_value=1.0, trade_tick_size=point,
                               volume_min=0.01, volume_max=100.0,
                               volume_step=0.01, digits=4)

    def test_слишком_близкий_стоп_отвергается_до_отправки(self):
        si = self._si(0.0001, 120)                      # USDZAR
        tick = SimpleNamespace(bid=15.9719, ask=15.9819)
        s = sig(symbol="USDZAR", ref_price=15.97, stop=15.975, target=15.96, atr=0.01,
                direction=SHORT)
        with self.assertRaises(risk.RiskRefusal) as c:
            risk.broker_barrier_gate(s, si, tick)
        self.assertEqual(c.exception.status, "barrier_too_close")

    def test_нормальная_дистанция_проходит(self):
        si = self._si(0.01, 50)                         # GOLD
        tick = SimpleNamespace(bid=4600.0, ask=4600.3)
        risk.broker_barrier_gate(sig(atr=15.0, stop=4577.0, target=4646.0), si, tick)

    def test_спред_входит_в_минимум(self):
        """Стоп внутри спреда выбьет мгновенно и не по движению рынка."""
        si = self._si(0.0001, 0)
        tick = SimpleNamespace(bid=15.9719, ask=15.9819)   # спред 0.01
        s = sig(symbol="USDZAR", ref_price=15.98, stop=15.975, target=15.99, atr=0.01)
        with self.assertRaises(risk.RiskRefusal):
            risk.broker_barrier_gate(s, si, tick)

    def test_маржа_ограничена_долей_свободной(self):
        """1.93 лота по USDCNY требовали 4283 при свободных 9944 — 43%
        маржи в одной сделке."""
        mt5 = SimpleNamespace(ORDER_TYPE_BUY=0, ORDER_TYPE_SELL=1,
                              order_calc_margin=lambda *a: 4283.0)
        with self.assertRaises(risk.RiskRefusal) as c:
            risk.margin_gate(mt5, "USDCNY", 1.93, False, 6.72, 9944.0)
        self.assertEqual(c.exception.status, "margin_too_big")

    def test_неизвестная_маржа_это_отказ(self):
        """«Не смог посчитать» и «посчитал, всё хорошо» — разные исходы."""
        mt5 = SimpleNamespace(ORDER_TYPE_BUY=0, ORDER_TYPE_SELL=1,
                              order_calc_margin=lambda *a: None)
        with self.assertRaises(risk.RiskRefusal) as c:
            risk.margin_gate(mt5, "USDCNY", 0.1, True, 6.72, 9944.0)
        self.assertEqual(c.exception.status, "margin_unknown")


class CostAndGeometry(unittest.TestCase):
    """🔴 31.08, по 22 закрытым сделкам движка."""

    def test_широкий_спред_отвергается(self):
        """У USDCNY спред 105.7% ATR — он один съедает 35% награды.
        Никакое улучшение сигнала этого не отыграет."""
        tick = SimpleNamespace(bid=6.7205, ask=6.7225)      # спред 0.002
        s = sig(symbol="USDCNY", ref_price=6.7215, stop=6.7187,
                target=6.7271, atr=0.00189, direction=LONG)
        with self.assertRaises(risk.RiskRefusal) as c:
            risk.cost_gate(s, tick)
        self.assertEqual(c.exception.status, "spread_too_wide")

    def test_спред_как_доля_риска_ловит_USDZAR(self):
        """🔴 07.09. Порог по награде (3 ATR) пропускал USDZAR: 0.010/0.088
        = 11%, на грани. Но от риска (1.5 ATR = 0.044) это 23% — каждая
        сделка стартует с четверти пути к стопу. За неделю живьём: 1 из 8,
        -5.87 R, худший инструмент счёта."""
        atr = 0.0294
        # Спред чуть уже дневного, чтобы порог по награде ПРОШЁЛ (9.6% < 10%),
        # а по риску — нет (19% > 12%). Именно эта щель и пропускала сделки.
        tick = SimpleNamespace(bid=15.9727, ask=15.9812)          # спред 0.0085
        s = sig(symbol="USDZAR", ref_price=15.977, stop=15.977 - 1.5 * atr,
                target=15.977 + 3.0 * atr, atr=atr)
        with self.assertRaises(risk.RiskRefusal) as c:
            risk.cost_gate(s, tick)
        self.assertEqual(c.exception.status, "spread_too_wide")
        self.assertIn("риска", str(c.exception))

    def test_узкий_спред_проходит(self):
        """У золота спред 0.6% награды."""
        tick = SimpleNamespace(bid=4600.0, ask=4600.37)
        risk.cost_gate(sig(atr=22.0, ref_price=4600.0, stop=4567.0,
                           target=4666.0), tick)

    def test_геометрия_привязана_к_цене_входа(self):
        """Стоп и цель обязаны считаться от фактического входа, иначе снос
        ломает RR несимметрично: заявленное 2.0 гуляло от 1.135 до 3.357,
        и средняя награда вышла 1.73R вместо 2.0 — безубыточный винрейт
        поднялся с 33.3% до 36.6%."""
        s = sig(ref_price=4600.0, stop=4570.0, target=4660.0)   # RR 2.0
        fill = 4610.0                                            # снос 0.33R
        dist, rr = s.stop_distance, s.rr
        stop, target = fill - dist, fill + rr * dist
        got = abs(target - fill) / abs(fill - stop)
        self.assertAlmostEqual(got, 2.0, places=9)
        # а «как было»: барьеры от бара-основания при том же сносе
        was = abs(s.target - fill) / abs(fill - s.stop)
        self.assertLess(was, 1.3)


class Drawdown(unittest.TestCase):
    def test_стоп_кран_меряет_просадку_от_пика(self):
        """🔴 Старое правило считало накопленную сумму: при пике +32 ATR оно
        разрешало потерять ещё 23 прежде чем сработать, то есть ослабевало
        по мере того, как стратегия зарабатывала."""
        state = {"n_closed": 40, "peak_r": 32.0, "cum_r": 32.0 - risk.MAX_DRAWDOWN_R - 0.1}
        self.assertIsNotNone(risk.drawdown_halt(state))
        # то же в абсолюте — сумма ПОЛОЖИТЕЛЬНА, старое правило молчало бы
        self.assertGreater(state["cum_r"], 0)

    def test_молодая_стратегия_не_глушится_серией(self):
        state = {"n_closed": 3, "peak_r": 2.0, "cum_r": -20.0}
        self.assertIsNone(risk.drawdown_halt(state))

    def test_остановленная_стратегия_не_торгует(self):
        with self.assertRaises(risk.RiskRefusal) as c:
            risk.strategy_gate({"status": ST_HALTED, "halt_reason": "просадка"})
        self.assertEqual(c.exception.status, "strategy_halted")


class LedgerBehaviour(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.executescript(ledger.SCHEMA)

    def test_отклонённый_сигнал_получает_второй_шанс(self):
        """Лимит мог освободиться к следующему прогону — дедуп не должен
        хоронить сигнал, по которому мы не вошли."""
        from analyze.engine.contracts import Decision
        ledger.record_decision(self.con, Decision(sig(), False, "cap_symbol: полно"))
        self.assertFalse(ledger.already_taken(self.con, "t:1"))

    def test_дедуп_срабатывает_по_реальной_сделке(self):
        from analyze.engine.contracts import Decision
        d = Decision(sig(), True, "принят", volume=0.1, risk_money=50.0)
        sid = ledger.record_decision(self.con, d)
        self.assertFalse(ledger.already_taken(self.con, "t:1"))   # сделки ещё нет
        ledger.open_trade(self.con, sid, d, mode="live", broker_symbol="GOLD",
                          req_price=4600.0)
        self.assertTrue(ledger.already_taken(self.con, "t:1"))

    def test_принятое_решение_без_сделки_не_травит_дедуп(self):
        """🔴 Регрессия на живой дефект 28.08: `--dry-run` записал 16 решений
        как «принято», ордеров не слал, и следующий боевой прогон отвалился
        целиком — 16 сигналов из 21 упёрлись в «уже входили», движок
        отчитался «взято сделок: 0» и выглядел работающим."""
        from analyze.engine.contracts import Decision
        ledger.record_decision(self.con, Decision(sig(), True, "принят"))
        self.assertFalse(ledger.already_taken(self.con, "t:1"))

    def test_отклонённый_брокером_ордер_не_повторяется(self):
        """Обратная сторона: если ордер ушёл и брокер его отверг, входить
        второй раз по тому же основанию не надо — причина отказа не в нас."""
        from analyze.engine.contracts import Decision
        d = Decision(sig(), True, "принят", volume=0.1, risk_money=50.0)
        sid = ledger.record_decision(self.con, d)
        tid = ledger.open_trade(self.con, sid, d, mode="live", broker_symbol="GOLD",
                                req_price=4600.0)
        ledger.mark_rejected(self.con, tid, "retcode=10016 invalid stops")
        self.assertFalse(ledger.already_taken(self.con, "t:1"))

    def test_пик_не_едет_вниз(self):
        ledger.ensure_strategy(self.con, "s", ST_LIVE)
        ledger.apply_result(self.con, "s", 3.0)
        st = ledger.apply_result(self.con, "s", -1.0)
        self.assertEqual(st["peak_r"], 3.0)
        self.assertEqual(st["cum_r"], 2.0)

    def test_R_считается_по_цене_а_не_по_деньгам(self):
        """Объём плавает вместе с волатильностью, поэтому денежные исходы
        между собой не сравнимы. Единица риска — расстояние вход-стоп."""
        self.con.execute(
            "INSERT INTO engine_trades (id, strategy, symbol, direction, mode, status, "
            "entry_price, stop) VALUES (1,'s','XAUUSD','long','live','open',4600,4570)")
        self.con.commit()
        r = ledger.close_trade(self.con, 1, exit_price=4660.0, profit=999.0,
                               commission=0, swap=0, reason="tp")
        self.assertAlmostEqual(r, 2.0, places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
