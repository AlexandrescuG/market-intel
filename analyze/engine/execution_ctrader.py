#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/engine/execution_ctrader.py — транспорт cTrader для движка.

Тот же набор операций, что у `execution.py` (MT5), но поверх Open API.
Риск-модуль, журнал и стоп-краны не дублируются: они считают в лотах и в R
и от площадки не зависят.

ПОЧЕМУ ОТДЕЛЬНЫЙ ФАЙЛ, А НЕ ВЕТКИ В СТАРОМ. Пока идёт параллельная работа
двух площадок, любая развилка `if transport == ...` внутри исполнения
означала бы, что оба пути живут в одном коде и ломаются вместе. Здесь два
файла с одинаковой формой; выбирает `run.py` по переменной окружения, и
выключение одного не трогает другой.

КАРТА СИМВОЛОВ У FxPro ОТЛИЧАЕТСЯ ОТ Ava — это не косметика:
    XAUUSD  у Ava `GOLD`,  у FxPro `XAUUSD`
    USDCNY  у Ava есть,    у FxPro НЕТ
Тихий фолбэк «вернём имя как есть» дал бы пустые данные по золоту, а это
неотличимо от «рынок молчит». Поэтому неизвестное имя — отказ.
"""
from __future__ import annotations

import logging
import sqlite3
import time

from analyze.ctrader.execution import Executor
from analyze.ctrader.session import CTraderError, Session
from analyze.engine import ledger
from analyze.engine.contracts import Decision
from analyze.engine.market import Quote, SymbolInfo

log = logging.getLogger("engine.ctrader")

# Наше каноническое имя -> имя у FxPro. Заполняется явно, не выводится:
# у каждой площадки свои написания, и «догадаться» тут значит однажды
# торговать не тем инструментом.
SYMBOL_MAP = {
    "XAUUSD": "XAUUSD",
    "EURUSD": "EURUSD",
    "GBPUSD": "GBPUSD",
    "USDJPY": "USDJPY",
    "USDZAR": "USDZAR",
    "XAGUSD": "XAGUSD",
    # USDCNY у FxPro отсутствует. Потеря нулевая: инструмент отключён 31.08,
    # спред у него был 105.7% ATR и съедал треть награды.
}


class CTraderTransport:
    """Контекст-менеджер, повторяющий форму Bridge из MT5-контура."""

    def __init__(self):
        self.session: Session | None = None
        self.ex: Executor | None = None
        self._info: dict[str, SymbolInfo] = {}

    def __enter__(self):
        self.session = Session().__enter__()
        self.ex = Executor(self.session)
        self.ex.assert_demo()          # состояние от API, не из конфига
        return self

    def __exit__(self, *exc):
        if self.session:
            self.session.__exit__(*exc)
        return False

    # ── справочники ─────────────────────────────────────────────────────

    def broker_symbol(self, canonical: str) -> str:
        if canonical not in SYMBOL_MAP:
            raise CTraderError("UNMAPPED", f"{canonical} нет в карте FxPro",
                               "карта символов")
        return SYMBOL_MAP[canonical]

    def symbol_info(self, canonical: str, quote: Quote) -> SymbolInfo:
        """Инструмент в общем виде. Цена пункта зависит от текущей цены для
        обратных пар, поэтому кэшируем только статику, а не результат."""
        name = self.broker_symbol(canonical)
        d = self.ex.details(name)
        mid = (quote.bid + quote.ask) / 2
        return SymbolInfo(
            name=name,
            canonical=canonical,
            money_per_unit=self.ex.money_per_price_unit(name, mid),
            volume_min=d.minVolume / d.lotSize,
            volume_step=(d.stepVolume or d.minVolume) / d.lotSize,
            volume_max=(d.maxVolume / d.lotSize) if d.maxVolume else 100.0,
            digits=d.digits,
            point=10 ** (-d.digits),
            # У cTrader нет аналога trade_stops_level: брокер проверяет
            # барьеры сам и отвечает TRADING_BAD_STOPS. Ставим ноль — за
            # минимальную дистанцию отвечает cost_gate по живому спреду,
            # а грубые ошибки геометрии ловит geometry_gate до отправки.
            stops_level=0.0,
        )

    def quote(self, canonical: str) -> Quote:
        bid, ask = self.session.spot(self.broker_symbol(canonical))
        return Quote(bid=bid, ask=ask)

    def equity(self) -> tuple[float, float]:
        t = self.session.trader()
        m = 10 ** (getattr(t, "moneyDigits", 2) or 2)
        return t.balance / m, getattr(t, "freeMargin", t.balance) / m

    # ── исполнение ──────────────────────────────────────────────────────

    def execute(self, con: sqlite3.Connection, signal_id: int, d: Decision,
                *, live: bool, quote: Quote) -> tuple[bool, str]:
        s = d.signal
        name = self.broker_symbol(s.symbol)
        mode = "live" if live else "shadow"
        price = quote.entry(s.is_long)

        # Барьеры от ЦЕНЫ ВХОДА, а не от закрытия бара. 31.08 первый ордер
        # был отвергнут как TRADING_BAD_STOPS ровно потому, что стоп
        # посчитали от бара (4420.15) при рынке 4375.74.
        dist, rr = s.stop_distance, s.rr
        if s.is_long:
            stop, target = price - dist, price + rr * dist
        else:
            stop, target = price + dist, price - rr * dist

        if not live:
            tid = ledger.open_trade(con, signal_id, d, mode=mode, broker_symbol=name,
                                    req_price=price, status="open",
                                    note="теневой режим: ордер не отправлялся",
                                    stop=stop, target=target)
            ledger.mark_sent(con, tid, ticket=0, entry_price=price)
            return True, "shadow"

        # Запись ДО отправки: позиция у брокера, не подтверждённая журналом,
        # хуже пропущенного входа (урок 19.08).
        tid = ledger.open_trade(con, signal_id, d, mode=mode, broker_symbol=name,
                                req_price=price, status="pending",
                                note=f"atr={s.atr:.5f} rr={rr:.2f} "
                                     f"снос={abs(price - s.ref_price) / dist:.3f}R",
                                stop=stop, target=target)
        try:
            ev = self.ex.market_order(name, is_long=s.is_long, lots=d.volume,
                                      stop=stop, target=target)
        except CTraderError as e:
            ledger.mark_rejected(con, tid, f"{e.code}: {e.description}")
            return False, f"{e.code}: {e.description}"

        pos = getattr(ev, "position", None)
        if pos is None or not getattr(pos, "positionId", 0):
            ledger.mark_rejected(con, tid, "ответ без позиции")
            return False, "брокер принял ордер, но позиции в ответе нет"
        ledger.mark_sent(con, tid, ticket=int(pos.positionId),
                         entry_price=float(pos.price or price))
        return True, f"позиция {pos.positionId} по {pos.price}"

    # ── сведение ────────────────────────────────────────────────────────

    def settle(self, con: sqlite3.Connection) -> dict:
        """Свести закрытые и закрыть просроченные по горизонту.

        Порядок и смысл те же, что в MT5-контуре: сначала сверка с брокером
        (что журнал считает открытым, а у брокера уже нет), потом горизонт.
        Иначе метрика видит прибыли и не видит свежих убытков — смещение
        систематическое и в опасную сторону (поймано 27.08)."""
        stats = {"closed": 0, "by_horizon": 0, "orphans": 0, "halted": []}
        now = int(time.time())
        alive = {int(p.positionId): p for p in self.ex.positions()}
        rows = [t for t in ledger.open_trades(con) if t["mode"] == "live"]

        gone = [t for t in rows if t["ticket"] and int(t["ticket"]) not in alive]
        if gone:
            deals = self.ex.deals(now - 30 * 86400, now + 3600)
            by_pos: dict[int, list] = {}
            for dl in deals:
                by_pos.setdefault(int(getattr(dl, "positionId", 0)), []).append(dl)
            for t in gone:
                legs = by_pos.get(int(t["ticket"]), [])
                closed = [x for x in legs if getattr(x, "closePositionDetail", None)]
                if not closed:
                    stats["orphans"] += 1
                    log.warning("позиция %s закрыта у брокера, но сделок нет в "
                                "истории — оставляю до следующего прогона", t["ticket"])
                    continue
                last = closed[-1]
                det = last.closePositionDetail
                m = 100.0
                r = ledger.close_trade(
                    con, t["id"], exit_price=float(last.executionPrice),
                    profit=float(det.grossProfit) / m,
                    commission=float(getattr(det, "commission", 0)) / m,
                    swap=float(getattr(det, "swap", 0)) / m,
                    reason="closed")
                st = ledger.apply_result(con, t["strategy"], r)
                stats["closed"] += 1
                self._maybe_halt(con, st, stats)

        for t in rows:
            if not t["ticket"] or int(t["ticket"]) not in alive:
                continue
            if (t["horizon_until"] or 0) > now:
                continue
            try:
                self.ex.close(alive[int(t["ticket"])])
                stats["by_horizon"] += 1
            except CTraderError as e:
                # Молчать нельзя: позиция за горизонтом продолжает жить, и её
                # исход попадёт в журнал как исход стратегии, которой он уже
                # не принадлежит.
                log.error("НЕ закрыт по горизонту %s: %s", t["ticket"], e)
        return stats

    @staticmethod
    def _maybe_halt(con, state: dict, stats: dict) -> None:
        from analyze.engine.risk import MAX_DRAWDOWN_R, drawdown_halt
        reason = drawdown_halt(state)
        if reason:
            ledger.halt(con, state["strategy"], reason, MAX_DRAWDOWN_R)
            stats["halted"].append((state["strategy"], reason))
            log.error("СТРАТЕГИЯ ОСТАНОВЛЕНА %s: %s", state["strategy"], reason)
