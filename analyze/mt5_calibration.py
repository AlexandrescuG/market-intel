#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/mt5_calibration.py — калибровочный контур издержек через демо MT5
(SPEC_mt5_cost_calibration_2026-08-18.md, §4 и §5).

ЧТО ЭТО ДЕЛАЕТ: отправляет минимальным объёмом сделки на ДЕМО-счёте, ловит
из history_deals_get() фактическую комиссию и своп и складывает пары
«предсказано моделью / получено фактически» в cost_observations. По 30-50
таким парам core/costs.py либо подтверждается, либо получает поправку.

ЧЕГО ЭТО НЕ ДЕЛАЕТ: не резолвит прогнозы, не участвует в bss, не попадает
в форвард-трек, не влияет на status_label и на текст сообщений. Если от
работы контура изменится хоть одна цифра трек-рекорда — это дефект.

ЧЕГО ЭТИМ НЕЛЬЗЯ ИЗМЕРИТЬ: проскальзывание. Демо наливает по котировке —
нет проскока на гэпах и новостях, реквотов, отказов, — и ошибается в
оптимистичную сторону, ровно там, где хочется верить. slippage_entry
пишется, но как наблюдение демо-сервера, а не как оценка реального
исполнения. Корректная формулировка вывода: «комиссия и своп измерены,
спред измерен, проскальзывание не измерено».
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from pathlib import Path

import rpyc

sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze.mt5_safety import MAGIC, SafetyRefusal, our_positions, preflight
from core.db_migrations import apply_all
from mt5_config import CALIBRATION_SERVER, symbol_map_for

HOST, PORT = "127.0.0.1", 18812
TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"
BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

# §5: N подряд идущих неудач -> алерт в ОПЕРАЦИОННЫЙ канал (core/telegram.py),
# не в @gdenigi_bot: там исследовательский лог, а это эксплуатация.
CONSECUTIVE_FAILURES_FOR_ALERT = 5

log = logging.getLogger("mt5_calibration")


# ─── запись наблюдений ──────────────────────────────────────────────────────

def record(con: sqlite3.Connection, **kw) -> int:
    """Строка пишется ВСЕГДА — и на успех, и на любой отказ. Пропуск без
    строки запрещён (§5): именно так 17.08 автономный цикл двое суток
    выглядел работающим."""
    kw.setdefault("created_ts", int(time.time()))
    kw.setdefault("magic", MAGIC)
    cols = ", ".join(kw)
    ph = ", ".join("?" * len(kw))
    cur = con.execute(f"INSERT INTO cost_observations ({cols}) VALUES ({ph})", tuple(kw.values()))
    con.commit()
    return cur.lastrowid


def _alert_operational(message: str) -> None:
    """Тот же канал, куда идут дневной дайджест и операционные алерты."""
    try:
        import asyncio

        from core.config import TELEGRAM_REPORT_CHAT_ID
        from core.telegram import send_text
        asyncio.run(send_text(f"⚠️ mt5_calibration: {message}", chat_id=TELEGRAM_REPORT_CHAT_ID))
    except Exception as e:                                    # алерт не обязан работать
        log.error("не удалось отправить алерт: %s", e)


def consecutive_failures(con: sqlite3.Connection, n: int = CONSECUTIVE_FAILURES_FOR_ALERT) -> bool:
    """Последние n наблюдений подряд — неудачи? Отличать техническую
    неудачу от штатного 'нечего отправлять' обязательно, иначе алерт
    приучит себя игнорировать."""
    rows = con.execute(
        "SELECT order_status FROM cost_observations ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    if len(rows) < n:
        return False
    return all(r[0] not in ("sent", "closed") for r in rows)


# ─── мост ───────────────────────────────────────────────────────────────────

class Bridge:
    """Контекст-менеджер: соединение + initialize/shutdown. Недоступность
    моста — это SafetyRefusal('bridge_down'), а не исключение наружу:
    контур не имеет права ронять цикл, прогноз важнее наблюдения."""

    def __enter__(self):
        self.conn = rpyc.classic.connect(HOST, PORT)
        self.mt5 = self.conn.modules.MetaTrader5
        if not self.mt5.initialize(path=TERMINAL_PATH, timeout=60000):
            raise SafetyRefusal("bridge_down", f"initialize(): {self.mt5.last_error()}")
        return self.mt5

    def __exit__(self, *exc):
        try:
            self.mt5.shutdown()
        except Exception:
            pass
        return False


# ─── отправка ───────────────────────────────────────────────────────────────

def send_one(mt5, con: sqlite3.Connection, *, symbol: str, tf: str, direction: str,
             forecast_id: str | None, account, server: str,
             pred_cost_price: float | None = None, pred_swap_night: float | None = None,
             pred_spread_atr: float | None = None) -> str:
    """Одно наблюдение. Возвращает order_status. Никогда не raise —
    любой отказ становится строкой в cost_observations."""
    broker_symbol = symbol_map_for(server).get(symbol, symbol)
    base = dict(forecast_id=forecast_id, account=account.login, server=server,
                symbol=symbol, broker_symbol=broker_symbol, tf=tf, direction=direction,
                pred_cost_price=pred_cost_price, pred_swap_night=pred_swap_night,
                pred_spread_atr=pred_spread_atr)
    try:
        if not mt5.symbol_select(broker_symbol, True):
            raise SafetyRefusal("bad_symbol", f"symbol_select({broker_symbol}) не удался")
        si = mt5.symbol_info(broker_symbol)
        volume = preflight(account, mt5.terminal_info(), mt5.positions_get(), si)

        tick = mt5.symbol_info_tick(broker_symbol)
        is_buy = direction.lower() in ("bullish", "buy", "long")
        price = tick.ask if is_buy else tick.bid
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": broker_symbol,
            "volume": volume,
            "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
            "price": price,
            "deviation": 20,
            "magic": MAGIC,
            "comment": "sbf_cost_calib",
            "type_time": mt5.ORDER_TIME_GTC,
        }
        res = mt5.order_send(req)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            rc = getattr(res, "retcode", None)
            cm = getattr(res, "comment", mt5.last_error())
            record(con, **base, volume=volume, req_price=price, req_ts=int(time.time()),
                   spread_at_entry=(tick.ask - tick.bid), order_status="order_rejected",
                   note=f"retcode={rc} {cm}")
            return "order_rejected"

        record(con, **base, volume=volume, req_price=price, req_ts=int(time.time()),
               spread_at_entry=(tick.ask - tick.bid), ticket=res.order,
               deal_entry_price=res.price, slippage_entry=(res.price - price),
               order_status="sent", note=f"deal={res.deal}")
        return "sent"

    except SafetyRefusal as e:
        record(con, **base, volume=0.0, order_status=e.status, note=str(e))
        return e.status
    except Exception as e:                                     # мост/rpyc/что угодно
        record(con, **base, volume=0.0, order_status="error", note=f"{type(e).__name__}: {e}")
        return "error"


# ─── добор закрытых ─────────────────────────────────────────────────────────

def collect_closed(mt5, con: sqlite3.Connection) -> int:
    """history_deals_get(position=ticket) -> комиссия, своп, цена выхода.
    Комиссия — главное, ради чего весь контур: в модели она сейчас 0.0."""
    open_rows = con.execute(
        "SELECT id, ticket FROM cost_observations WHERE order_status='sent' AND ticket IS NOT NULL"
    ).fetchall()
    still_open = {getattr(p, "ticket", None) for p in our_positions(mt5.positions_get())}
    n = 0
    for oid, ticket in open_rows:
        if ticket in still_open:
            continue
        deals = mt5.history_deals_get(position=ticket)
        if not deals:
            continue
        commission = sum(getattr(d, "commission", 0.0) for d in deals)
        swap = sum(getattr(d, "swap", 0.0) for d in deals)
        exits = [d for d in deals if getattr(d, "entry", None) == 1]
        exit_price = exits[-1].price if exits else None
        closed_ts = max(getattr(d, "time", 0) for d in deals)
        con.execute(
            "UPDATE cost_observations SET commission=?, swap=?, deal_exit_price=?, "
            "closed_ts=?, order_status='closed' WHERE id=?",
            (commission, swap, exit_price, closed_ts, oid))
        n += 1
    con.commit()
    return n


# ─── прогон ─────────────────────────────────────────────────────────────────

def run(symbols: list[str], tf: str, direction: str, synthetic: bool, verbose: bool) -> int:
    """Возвращает exit-код: 0 — что-то отправлено или добрано; 2 —
    систематический отказ. Ненулевой код нужен, чтобы systemd видел
    разницу между «отработал» и «отработал вхолостую» (§5)."""
    con = sqlite3.connect(str(BOT_DB), timeout=30)
    apply_all(con)
    stats = {"sent": 0, "closed": 0}
    refusals: dict[str, int] = {}
    try:
        with Bridge() as mt5:
            account = mt5.account_info()
            server = getattr(account, "server", CALIBRATION_SERVER) if account else CALIBRATION_SERVER
            stats["closed"] = collect_closed(mt5, con) if account else 0
            for sym in symbols:
                st = send_one(mt5, con, symbol=sym, tf=tf, direction=direction,
                              forecast_id=None if synthetic else None,
                              account=account, server=server)
                if st == "sent":
                    stats["sent"] += 1
                else:
                    refusals[st] = refusals.get(st, 0) + 1
    except SafetyRefusal as e:
        for sym in symbols:
            record(con, forecast_id=None, account=0, server=CALIBRATION_SERVER, symbol=sym,
                   broker_symbol="?", tf=tf, direction=direction, volume=0.0,
                   order_status=e.status, note=str(e))
        refusals[e.status] = len(symbols)

    log.info("отправлено=%d добрано закрытых=%d отказы=%s", stats["sent"], stats["closed"], refusals)
    if consecutive_failures(con):
        msg = (f"{CONSECUTIVE_FAILURES_FOR_ALERT} наблюдений подряд неудачны; "
               f"последние отказы: {refusals}")
        log.error(msg)
        _alert_operational(msg)
    con.close()
    return 0 if (stats["sent"] or stats["closed"]) else 2


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["EURUSD"])
    ap.add_argument("--tf", default="H1")
    ap.add_argument("--direction", default="bullish")
    ap.add_argument("--synthetic", action="store_true",
                    help="наблюдение не по сигналу (forecast_id NULL) — для комиссии и свопа "
                         "они полноценны, для проскальзывания смешивать с сигнальными нельзя")
    ap.add_argument("--collect-only", action="store_true", help="только добрать закрытые")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s | [mt5_calib] %(message)s")
    code = run([] if args.collect_only else args.symbols,
               args.tf, args.direction, args.synthetic, args.verbose)
    sys.exit(code)


if __name__ == "__main__":
    main()
