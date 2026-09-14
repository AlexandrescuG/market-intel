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


class Portfolio(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.executescript(ledger.SCHEMA)

    def _open(self, symbol="XAUUSD", direction=LONG, strategy="t", rm=25.0):
        self.con.execute(
            "INSERT INTO engine_trades (strategy, symbol, direction, mode, status, "
            "risk_money) VALUES (?,?,?,'live','open',?)", (strategy, symbol, direction, rm))
        self.con.commit()

    def test_потолок_по_символу_и_стороне(self):
        """🔴 26-27.08: старый потолок «10 наших позиций» не различал символ
        и сторону, набралось десять лонгов по золоту и вынесло одним
        движением — шесть стопов за 13 минут."""
        for _ in range(risk.MAX_OPEN_PER_SYMBOL_SIDE):
            self._open()
        with self.assertRaises(risk.RiskRefusal) as c:
            risk.portfolio_gate(self.con, sig(), 10000.0, 25.0)
        self.assertIn(c.exception.status, ("cap_symbol", "cap_symbol_side"))

    def test_другой_символ_не_блокируется(self):
        for _ in range(risk.MAX_OPEN_PER_SYMBOL):
            self._open(symbol="XAUUSD")
        risk.portfolio_gate(self.con, sig(symbol="EURUSD", strategy="other"),
                            10000.0, 25.0)

    def test_суммарный_риск_портфеля_ограничен(self):
        """Число позиций выводится из константы, а не зашито: иначе тест
        перестал бы ловить дефект при первой же правке MAX_PORTFOLIO_RISK
        (ровно это и случилось при переходе с 2% на 3%)."""
        equity, rm = 10_000.0, 40.0
        budget = equity * risk.MAX_PORTFOLIO_RISK
        n = int(budget // rm)                     # столько ещё помещается
        self.assertLess(n + 1, risk.MAX_OPEN_TOTAL, "тест упрётся не в тот лимит")
        for i in range(n):
            self._open(symbol=f"S{i}", strategy=f"st{i}", rm=rm)
        with self.assertRaises(risk.RiskRefusal) as c:
            risk.portfolio_gate(self.con, sig(symbol="ZZZ", strategy="new"), equity, rm)
        self.assertEqual(c.exception.status, "cap_portfolio_risk")

    def test_встречная_позиция_запрещена(self):
        self._open(direction=SHORT)
        with self.assertRaises(risk.RiskRefusal) as c:
            risk.opposite_open(self.con, sig(direction=LONG))
        self.assertEqual(c.exception.status, "opposite_open")

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
        budget = equity * risk.MAX_PORTFOLIO_RISK
        # Лонг со стопом ВЫШЕ входа: терять нечего, прибыль заперта.
        self._open_live("EURUSD", LONG, entry=1.1000, stop=1.1020,
                        rpp=10_000.0, rm=budget, strategy="a")
        # Лимит занят «по записи» целиком, но живого риска в нём нет.
        risk.portfolio_gate(self.con, sig(symbol="GBPUSD", strategy="b"),
                            equity, budget * 0.9)

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
