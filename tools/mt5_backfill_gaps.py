#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/mt5_backfill_gaps.py — заделать дыры в price_bars после простоя MT5.

Штатная доливка (mt5_bridge_pull) берёт то, что терминал отдаёт ПРЯМО СЕЙЧАС,
и честно рапортует «3000 баров», даже если из них последний — вчерашний.
После рестарта терминала так и происходит: MT5 подгружает историю графика
лениво, по одному символу и таймфрейму, и первые запросы возвращают старый
кэш. Ровно этим объясняется дыра 20.08: прогон в 02:06 отчитался успехом, а
15m EURUSD остался на 20:30.

Отличие этого инструмента: он не верит первому ответу. Для каждой пары
символ/ТФ он ЖДЁТ, пока брокер отдаст бар не старше допустимого, и только
потом пишет. Не дождался — говорит об этом вслух и возвращает ненулевой код.

Запуск:  .venv/bin/python3 -m tools.mt5_backfill_gaps [--hours 3]
"""
from __future__ import annotations

import argparse
import datetime
import logging
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import rpyc

from mt5_config import SYMBOL_MAP, TIMEFRAME_ATTR

BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"
TF_SEC = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800}
# Сколько ждать досинхронизации одной пары символ/ТФ
WAIT_SEC, POLL_SEC = 45, 3

log = logging.getLogger("backfill")


def _write(con: sqlite3.Connection, bars: list[dict]) -> None:
    con.executemany(
        "INSERT OR REPLACE INTO price_bars (symbol, tf, ts, o, h, l, c, v) "
        "VALUES (:symbol,:tf,:ts,:o,:h,:l,:c,:v)", bars)
    con.commit()


def _fresh_enough(last_ts: int, tf: str, now: int) -> bool:
    """Допуск — два бара: один может ещё формироваться, второй уже закрыт."""
    return last_ts >= now - 2 * TF_SEC[tf] - 60


def backfill(hours: int, count: int) -> int:
    con = sqlite3.connect(str(BOT_DB), timeout=60)
    conn = rpyc.classic.connect("127.0.0.1", 18812)
    mt5 = conn.modules["MetaTrader5"]
    if not mt5.initialize(path=TERMINAL, timeout=60000):
        log.error("initialize() не удался: %s", mt5.last_error())
        return 1
    stale = []
    try:
        # Прогрев: сначала ЗАПРОСИТЬ все символы, потом идти по кругу. Заказ на
        # подгрузку истории терминал исполняет фоном, и пока ждёшь один символ,
        # остальные успевают догрузиться сами.
        for our, br in SYMBOL_MAP.items():
            mt5.symbol_select(br, True)
            for tf, attr in TIMEFRAME_ATTR.items():
                mt5.copy_rates_from_pos(br, getattr(mt5, attr), 0, 10)

        now0 = int(time.time())
        for our, br in SYMBOL_MAP.items():
            if not mt5.symbol_select(br, True):
                log.warning("%s (%s) недоступен у брокера — пропуск", our, br)
                continue
            # Ждать досинхронизации имеет смысл только там, где рынок идёт.
            # USDCNY/USDZAR/USDRUB у Ava торгуются не круглосуточно: ночью их
            # бары СТАРЫЕ ЗАКОННО, и 45 секунд ожидания на каждый ТФ — это
            # десять минут впустую и, что хуже, «дыра», которой нет.
            tick = mt5.symbol_info_tick(br)
            live = (now0 - int(getattr(tick, "time", 0))) < 1800
            for tf, attr in TIMEFRAME_ATTR.items():
                code = getattr(mt5, attr)
                deadline = time.time() + WAIT_SEC
                rates = None
                while True:
                    rates = mt5.copy_rates_from_pos(br, code, 0, count)
                    now = int(time.time())
                    if rates is not None and len(rates) and _fresh_enough(int(rates[-1]["time"]), tf, now):
                        break
                    if not live or time.time() > deadline:
                        last = (datetime.datetime.fromtimestamp(int(rates[-1]["time"]))
                                if rates is not None and len(rates) else "нет данных")
                        if live:
                            log.error("%s %s: брокер так и не отдал свежие бары (последний %s)",
                                      our, tf, last)
                            stale.append(f"{our}/{tf}")
                        else:
                            log.info("%s %s: рынок закрыт (тик молчит) — беру как есть, "
                                     "последний %s", our, tf, last)
                        break
                    time.sleep(POLL_SEC)
                if rates is None or not len(rates):
                    continue
                bars = [{"symbol": our, "tf": tf, "ts": int(r["time"]),
                         "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]),
                         "c": float(r["close"]),
                         "v": float(r["real_volume"] or r["tick_volume"])} for r in rates]
                _write(con, bars)
                log.info("%s %s: записано %d, последний %s", our, tf, len(bars),
                         datetime.datetime.fromtimestamp(bars[-1]["ts"]).strftime("%d.%m %H:%M"))
    finally:
        # НЕ mt5.shutdown(): терминал общий, на нём висит живой график
        # serve.py::_handle_chart_tail. Погасив его здесь, мы своими руками
        # роняем источник графика — и он уходит на Yahoo, а это как раз те
        # самые скачки цены. Штатная доливка гасит, и это её отдельный грех.
        conn.close()

    # ── что осталось дырявым за последние N часов ──
    print(f"\n── дыры за последние {hours} ч ──")
    now = int(time.time())
    since = now - hours * 3600
    holes = 0
    for our in SYMBOL_MAP:
        for tf in ("15m", "30m", "1h"):
            have = {r[0] for r in con.execute(
                "SELECT ts FROM price_bars WHERE symbol=? AND tf=? AND ts>=?",
                (our, tf, since))}
            step = TF_SEC[tf]
            # ожидаемые метки: от первой границы бара после since до последнего ЗАКРЫТОГО
            first = (since // step + 1) * step
            expect = {t for t in range(first, now - step, step)}
            miss = sorted(expect - have)
            if miss:
                holes += len(miss)
                print(f"  🔴 {our:8s} {tf:4s} не хватает {len(miss):3d} баров, "
                      f"первый {datetime.datetime.fromtimestamp(miss[0]):%d.%m %H:%M}, "
                      f"последний {datetime.datetime.fromtimestamp(miss[-1]):%d.%m %H:%M}")
            else:
                print(f"  ✅ {our:8s} {tf:4s} ряд сплошной")
    con.close()
    if stale:
        print(f"\n🔴 брокер не отдал свежие данные: {', '.join(stale)}")
    print(f"\nитого пропущенных баров: {holes}")
    return 1 if (holes or stale) else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=3)
    # Дыру за несколько часов затыкают десятки баров, а не тысячи. Полный ряд
    # добирает штатная доливка; здесь важно быстро вернуть график.
    ap.add_argument("--bars", type=int, default=250)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | [backfill] %(message)s")
    sys.exit(backfill(a.hours, a.bars))


if __name__ == "__main__":
    main()
