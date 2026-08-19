#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/live_strategy.py — форвард-проверка кандидата на демо (пункт 3).

ЧТО ЭТО. Единственный признак, взявший планку издержек в пункте 2:
золото, лонг, при растущей нефти. Геометрия — стоп 2.0 ATR, цель 1.0 ATR
(RR 0.5), горизонт 12 баров H1; она выбрана в пункте 1 как имеющая
наименьший структурный минус.

ЗАЧЕМ ФОРВАРД, А НЕ ПРОД. Признак прошёл пререгистрированный критерий
(2026-08-19_macro_edge.md, коммит bf821e9), но walk-forward показал, что в
одном окне из четырёх знак обратный, а тестовая половина — четыре месяца
одного режима. Единственная проверка, которую нельзя подогнать, — данные,
которых не было ни в обучающей, ни в проверочной выборке.

🔴 ВХОД БЕРЁТСЯ ПО ПРЕРЕГИСТРИРОВАННОМУ УСЛОВИЮ, НЕ ПО УТОЧНЁННОМУ.
Разведочная проверка (после результата, поэтому не подтверждение) показала,
что эффект сидит не в «нефть тянет золото», а в расхождении: при «нефть
растёт И золото уже растёт» прирост +0.022 (ниже планки), при «нефть
растёт, золото ещё нет» — +0.270. Соблазн торговать сразу уточнённое
условие велик, но это подгонка входа под находку, сделанную на тех же
данных. Поэтому вход — по `oil_rising`, а признак `gold_up` ЛОГИРУЕТСЯ
рядом: форвард сам разделит две группы, и разделит честно.

Замечание владельца, которое и породило проверку: механической связи
нефть->золото нет, золото может расти на уже выделенных деньгах вопреки
фону. Данные это подтвердили — совместный рост как раз не работает.
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import core.price_bars as _pb
from analyze.mt5_calibration import BOT_DB, Bridge, record, remote_order_send
from analyze.mt5_safety import MAGIC, SafetyRefusal, preflight
from mt5_config import CALIBRATION_SERVER, symbol_map_for

SYMBOL = "XAUUSD"
ATR_MULT, RR, HORIZON_BARS = 2.0, 0.5, 12
OIL = "DCOILWTICO"
OIL_LOOKBACK = 20          # публикаций назад, §3 пререгистрации
GOLD_MOMENTUM_BARS = 120   # ~5 суток H1, только для логирования

log = logging.getLogger("live_strategy")


def _macro_at(con: sqlite3.Connection, code: str, ts: int, back: int = 0) -> float | None:
    """Значение, ИЗВЕСТНОЕ на момент ts (asof_ts <= ts). Ради этого и делался
    бэкфилл FRED с датами публикации: брать по дате периода значило бы
    заглядывать вперёд на недели."""
    rows = con.execute(
        "SELECT value FROM factor_values WHERE factor_key=? AND asof_ts<=? "
        "ORDER BY asof_ts DESC LIMIT ?", (f"macro.{code}", ts, back + 1)).fetchall()
    return rows[back][0] if len(rows) > back else None


def atr(candles: list[dict], i: int, period: int = 14) -> float | None:
    if i < period:
        return None
    tr = [max(candles[k]["h"] - candles[k]["l"],
              abs(candles[k]["h"] - candles[k - 1]["c"]),
              abs(candles[k]["l"] - candles[k - 1]["c"]))
          for k in range(i - period + 1, i + 1)]
    return sum(tr) / period


def evaluate(con: sqlite3.Connection) -> dict:
    """Состояние сигнала на последнем ЗАКРЫТОМ баре."""
    c = _pb.load_candles(SYMBOL, "1h")
    if not c or len(c) < GOLD_MOMENTUM_BARS + 20:
        return {"ok": False, "reason": "недостаточно баров"}
    i = len(c) - 2                       # -1 может быть незакрытым
    ts = c[i]["ts"]
    a = atr(c, i)
    if not a:
        return {"ok": False, "reason": "ATR не считается"}

    oil_now, oil_prev = _macro_at(con, OIL, ts), _macro_at(con, OIL, ts, OIL_LOOKBACK)
    if oil_now is None or oil_prev is None:
        return {"ok": False, "reason": "нет данных по нефти на этот момент"}

    oil_rising = oil_now > oil_prev
    gold_up = c[i]["c"] > c[i - GOLD_MOMENTUM_BARS]["c"]
    entry = c[i]["c"]
    return {"ok": True, "ts": ts, "bar_close": entry, "atr": a,
            "oil_rising": oil_rising, "gold_up": gold_up,
            "signal": oil_rising,                       # пререгистрированное условие
            "divergence": oil_rising and not gold_up,   # разведочное уточнение
            "stop": entry - ATR_MULT * a, "target": entry + RR * ATR_MULT * a}


def run(dry: bool, verbose: bool) -> int:
    con = sqlite3.connect(str(BOT_DB), timeout=30)
    s = evaluate(con)
    if not s["ok"]:
        log.info("сигнала нет: %s", s["reason"])
        con.close()
        return 2
    log.info("бар %s: нефть_растёт=%s золото_растёт=%s -> сигнал=%s (расхождение=%s)",
             s["ts"], s["oil_rising"], s["gold_up"], s["signal"], s["divergence"])
    if not s["signal"]:
        con.close()
        return 2
    if dry:
        log.info("dry-run: вход %.2f стоп %.2f цель %.2f", s["bar_close"], s["stop"], s["target"])
        con.close()
        return 0

    note = (f"strategy=gold_oil oil_rising={int(s['oil_rising'])} "
            f"gold_up={int(s['gold_up'])} divergence={int(s['divergence'])} "
            f"atr={s['atr']:.4f} horizon_bars={HORIZON_BARS}")
    try:
        with Bridge() as (mt5, conn):
            account = mt5.account_info()
            server = getattr(account, "server", CALIBRATION_SERVER) if account else CALIBRATION_SERVER
            broker = symbol_map_for(server).get(SYMBOL, SYMBOL)
            mt5.symbol_select(broker, True)
            si = mt5.symbol_info(broker)
            volume = preflight(account, mt5.terminal_info(), mt5.positions_get(), si)
            tick = mt5.symbol_info_tick(broker)
            # 🔴 Стоп и цель ставятся В ЗАЯВКЕ, а не «закроем потом сами».
            # Без них позиция висит бесконечно: калибровочный сборщик её не
            # тронет (он закрывает по возрасту, а у стратегии свой горизонт),
            # а горизонт в 12 баров H1 — это 12 часов, за которые процесс
            # может быть перезапущен. Барьеры на стороне брокера переживают
            # всё, что происходит на нашей стороне.
            digits = int(getattr(si, "digits", 2))
            res, err = remote_order_send(conn, broker, volume, True, float(tick.ask),
                                          sl=round(s["stop"], digits),
                                          tp=round(s["target"], digits))
            base = dict(forecast_id=None, account=account.login, server=server,
                        symbol=SYMBOL, broker_symbol=broker, tf="H1", direction="bullish",
                        volume=volume, req_price=float(tick.ask), req_ts=int(time.time()),
                        spread_at_entry=float(tick.ask - tick.bid))
            if err or res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
                record(con, **base, order_status="order_rejected",
                       note=f"{note} | {err or getattr(res, 'comment', '')}")
                con.close()
                return 2
            record(con, **base, ticket=res.order, deal_entry_price=res.price,
                   slippage_entry=res.price - float(tick.ask),
                   order_status="sent", note=note)
            log.info("вход отправлен: ticket=%s по %.2f", res.order, res.price)
    except SafetyRefusal as e:
        record(con, forecast_id=None, account=0, server=CALIBRATION_SERVER, symbol=SYMBOL,
               broker_symbol="?", tf="H1", direction="bullish", volume=0.0,
               order_status=e.status, note=f"{note} | {e}")
        con.close()
        return 2
    con.close()
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="только показать сигнал, не торговать")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | [strategy] %(message)s")
    sys.exit(run(args.dry_run, args.verbose))


if __name__ == "__main__":
    main()
