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
BAR_SEC = 3600             # рабочий ТФ — H1
# Сигнальный бар не старше двух баров на момент входа. Доливка price_bars
# идёт своим таймером и отстаёт (а 19.08 на час вставала целиком: у Ava
# symbol_select("GOLD") вернул False на одном прогоне). Торговать по бару
# трёхчасовой давности — это ставить стоп и цель вокруг цены, которой уже
# нет: ATR ещё как-то переживает, а расстояние до барьеров едет вместе с
# ушедшей ценой. Лучше пропустить час, чем войти с поехавшей геометрией.
MAX_SIGNAL_LAG_SEC = 2 * BAR_SEC
# Насколько цена вправе уйти от закрытия сигнального бара к моменту входа.
# Не подобранное число: в бэктесте, которым измерена планка и прирост,
# вход стоит РОВНО на закрытии сигнального бара. Если цена уже прошла
# расстояние до цели, то движение, ради которого сделка бралась, случилось
# ДО входа — берётся не та сделка, которую измеряли, и её исход попадёт в
# журнал под тем же именем. Порог выражен через саму геометрию
# (RR * ATR_MULT — это и есть расстояние до цели), а не задан отдельно,
# чтобы его нельзя было тихо подкрутить под результат.
MAX_ENTRY_DRIFT_ATR = RR * ATR_MULT

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


def geometry(anchor: float, a: float) -> tuple[float, float]:
    """Стоп и цель от ЦЕНЫ ВХОДА, а не от закрытия сигнального бара.

    🔴 19.08, найдено на первой же сделке форварда. Барьеры считались от
    `bar_close`, а ордер уходил по рыночному `ask`; между ними — весь разрыв
    доливки баров. Первая сделка: сигнальный бар закрылся на 4367.22, вход
    прошёл по 4369.73, барьеры встали на 4339.42/4381.12. То есть риск
    получился 2.18 ATR вместо 2.0, а награда 0.82 ATR вместо 1.0 — реальное
    RR 0.38 при пререгистрированном 0.5. Сделка закрылась по цели с +11.39,
    и в журнал легло EV=+0.82 ATR вместо +1.0.

    Смещение не случайное: разрыв между ценой сигнального бара и текущей
    ценой в среднем растёт вместе с задержкой доливки, и знак у него тот же,
    что у движения, которое признак ловит. То есть в удачных случаях награда
    урезается сильнее всего — ровно там, где её измеряют.

    Это не изменение геометрии, а её восстановление: 2.0/1.0 ATR
    пререгистрировано ОТ ВХОДА (`2026-08-19_geometry.md`)."""
    return anchor - ATR_MULT * a, anchor + RR * ATR_MULT * a


def evaluate(con: sqlite3.Connection) -> dict:
    """Состояние сигнала на последнем ЗАКРЫТОМ баре."""
    c = _pb.load_candles(SYMBOL, "1h")
    if not c or len(c) < GOLD_MOMENTUM_BARS + 20:
        return {"ok": False, "reason": "недостаточно баров"}
    # Последний ЗАКРЫВШИЙСЯ бар. Было `len(c)-2` вслепую: доливка кладёт и
    # текущий формирующийся бар, поэтому «минус два» безопасно, но когда
    # последний бар УЖЕ закрыт, оно выбрасывает свежий бар и добавляет к
    # задержке доливки ещё час на ровном месте.
    now = int(time.time())
    i = len(c) - 1
    if c[i]["ts"] + BAR_SEC > now:
        i -= 1
    ts = c[i]["ts"]
    lag = now - (ts + BAR_SEC)
    if lag > MAX_SIGNAL_LAG_SEC:
        return {"ok": False,
                "reason": f"бары устарели: сигнальный бар закрылся {lag // 60} мин назад "
                          f"(предел {MAX_SIGNAL_LAG_SEC // 60})"}
    a = atr(c, i)
    if not a:
        return {"ok": False, "reason": "ATR не считается"}

    oil_now, oil_prev = _macro_at(con, OIL, ts), _macro_at(con, OIL, ts, OIL_LOOKBACK)
    if oil_now is None or oil_prev is None:
        return {"ok": False, "reason": "нет данных по нефти на этот момент"}

    oil_rising = oil_now > oil_prev
    gold_up = c[i]["c"] > c[i - GOLD_MOMENTUM_BARS]["c"]
    entry = c[i]["c"]
    ref_stop, ref_target = geometry(entry, a)
    return {"ok": True, "ts": ts, "bar_close": entry, "atr": a, "lag_sec": lag,
            "oil_rising": oil_rising, "gold_up": gold_up,
            "signal": oil_rising,                       # пререгистрированное условие
            "divergence": oil_rising and not gold_up,   # разведочное уточнение
            # справочно, для dry-run: реальные барьеры считаются от цены входа
            "stop": ref_stop, "target": ref_target}


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
            f"atr={s['atr']:.4f} horizon_bars={HORIZON_BARS} "
            f"bar_ts={s['ts']} lag_sec={s['lag_sec']}")
    try:
        with Bridge() as (mt5, conn):
            account = mt5.account_info()
            server = getattr(account, "server", CALIBRATION_SERVER) if account else CALIBRATION_SERVER
            broker = symbol_map_for(server).get(SYMBOL, SYMBOL)
            mt5.symbol_select(broker, True)
            si = mt5.symbol_info(broker)
            volume = preflight(account, mt5.terminal_info(), mt5.positions_get(), si)
            tick = mt5.symbol_info_tick(broker)
            # 🔴 Отказ от входа, если цена ушла от сигнального бара дальше,
            # чем до цели. Поймано на живой сделке 19.08 16:02: сигнальный
            # бар закрылся на 4365.95, за следующий час золото прошло
            # вертикально до 4442 (+5.4 ATR), и вход по рынку оказался
            # выше цели, посчитанной от бара. Со старым кодом это была бы
            # заявка на покупку с целью НИЖЕ цены входа — брокер отвергает
            # её как invalid stops, и в журнале копились бы order_rejected
            # без внятной причины.
            drift = abs(float(tick.ask) - s["bar_close"]) / s["atr"]
            if drift > MAX_ENTRY_DRIFT_ATR:
                record(con, forecast_id=None, account=account.login, server=server,
                       symbol=SYMBOL, broker_symbol=broker, tf="H1", direction="bullish",
                       volume=0.0, req_price=float(tick.ask), req_ts=int(time.time()),
                       order_status="drift_reject",
                       note=f"{note} drift_atr={drift:.2f} | цена ушла от сигнального "
                            f"бара на {drift:.2f} ATR при пределе {MAX_ENTRY_DRIFT_ATR}")
                log.info("вход отменён: снос %.2f ATR от закрытия сигнального бара", drift)
                con.close()
                return 2
            # 🔴 Стоп и цель ставятся В ЗАЯВКЕ, а не «закроем потом сами».
            # Без них позиция висит бесконечно: калибровочный сборщик её не
            # тронет (он закрывает по возрасту, а у стратегии свой горизонт),
            # а горизонт в 12 баров H1 — это 12 часов, за которые процесс
            # может быть перезапущен. Барьеры на стороне брокера переживают
            # всё, что происходит на нашей стороне.
            digits = int(getattr(si, "digits", 2))
            stop, target = geometry(float(tick.ask), s["atr"])
            res, err = remote_order_send(conn, broker, volume, True, float(tick.ask),
                                          sl=round(stop, digits),
                                          tp=round(target, digits))
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
                   order_status="sent", note=f"{note} drift_atr={drift:.2f}")
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
