#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mt5_deep_backfill_30m.py — WP2 доп. находка, REVIEW_alpha_engine_WP0-WP3.md §8
(12.08.2026, решение Георгия: расширять глубину 30m, не переходить на 1h).

ЗАЧЕМ: price_bars.30m у всех Daoti-инструментов начинается 2024-07-16 —
окно ~2 года — один макрорежим (цикл снижения ставок + тренд в золоте),
искажающий любой длинный паттерн в лучшую сторону. Ревью предположил, что
это "известный лимит глубины терминала для мелких ТФ" — ПРОВЕРЕНО живым
запросом `copy_rates_range()` через rpyc-мост (та же venv-версия rpyc, что
у sbf-mt5-bridge.service, иначе "invalid message type" — версии rpyc на
двух сторонах должны совпадать): у брокера ЕСТЬ M30-история минимум с
2018-01 (522 бара за январь-март 2018 против ~1900 за такой же период в
2020/2022/2024) -- 2024-07-16 был не пределом брокера, а пределом ОДНОГО
прошлого ручного бэкфилла, который никогда не докатили до начала D1-истории
(2018-01-02). Здесь — тот докат, чанками по 3 месяца через copy_rates_range
(не copy_rates_from_pos — тот слепой по смещению, не по дате, и не подходит
для целевого докатывания до конкретной границы).

Как и mt5_bridge_pull.py: ничего не пишет и не трогает в MT5 кроме чтения
истории (copy_rates_range) — read-only мост, в бутылке живёт торговый EA.
НЕ вызывает mt5.shutdown() — sbf-mt5-pull.timer (ежечасно, *:05) может
делить тот же MT5-процесс в Wine; initialize() идемпотентен и безопасен
вызывать повторно, а произвольный shutdown() из стороннего скрипта мог бы
разорвать одновременный штатный прогон.

ВАЖНО: запускать ИЗ ТОГО ЖЕ venv, что и sbf-mt5-bridge.service
(/home/sbf/market_intel/.venv/bin/python3) — иначе несовпадение версий
rpyc на клиенте/сервере даёт "invalid message type: 18" (найдено 12.08,
см. Core-лог и REVIEW_alpha_engine_WP0-WP3.md §3).

Использование:
  /home/sbf/market_intel/.venv/bin/python3 mt5_deep_backfill_30m.py \
      --symbols GOLD EURUSD USDJPY USDCNY USDZAR --until 2018-01-01 --verbose
"""
import argparse
import logging
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import rpyc

sys.path.insert(0, str(Path(__file__).parent))
from mt5_config import SYMBOL_MAP

HOST, PORT = "127.0.0.1", 18812
TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"
BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
CHUNK_DAYS = 90
SLEEP_BETWEEN_CALLS = 1.0  # не долбить Wine-процесс, который делит штатный таймер

log = logging.getLogger("mt5_deep_backfill_30m")


def _write_bars(con: sqlite3.Connection, bars: list[dict]) -> None:
    if not bars:
        return
    con.executemany(
        "INSERT OR REPLACE INTO price_bars (symbol, tf, ts, o, h, l, c, v) "
        "VALUES (:symbol, :tf, :ts, :o, :h, :l, :c, :v)",
        bars,
    )
    con.commit()


def _earliest_ts(con: sqlite3.Connection, our_key: str, tf: str = "30m") -> int | None:
    row = con.execute(
        "SELECT MIN(ts) FROM price_bars WHERE symbol=? AND tf=?", (our_key, tf)
    ).fetchone()
    return row[0] if row and row[0] is not None else None


def backfill_symbol(conn, con: sqlite3.Connection, our_key: str, broker_sym: str,
                     until_dt: datetime, verbose: bool) -> int:
    mt5 = conn.modules["MetaTrader5"]
    rdatetime = conn.modules["datetime"]
    if not mt5.symbol_select(broker_sym, True):
        log.warning("%s (%s) недоступен у брокера — пропуск", broker_sym, our_key)
        return 0
    earliest = _earliest_ts(con, our_key)
    if earliest is None:
        log.warning("%s: нет ни одного 30m-бара в price_bars — сначала обычный pull", our_key)
        return 0
    cursor_end = datetime.fromtimestamp(earliest, tz=timezone.utc).replace(tzinfo=None)
    total = 0
    while cursor_end > until_dt:
        cursor_start = max(until_dt, cursor_end - timedelta(days=CHUNK_DAYS))
        r_start = rdatetime.datetime(cursor_start.year, cursor_start.month, cursor_start.day)
        r_end = rdatetime.datetime(cursor_end.year, cursor_end.month, cursor_end.day)
        rates = mt5.copy_rates_range(broker_sym, mt5.TIMEFRAME_M30, r_start, r_end)
        n = len(rates) if rates is not None else 0
        if n == 0:
            if verbose:
                log.info("%s %s..%s: 0 баров — граница истории у брокера, стоп",
                         our_key, cursor_start.date(), cursor_end.date())
            break
        bars = []
        for r in rates:
            vol = float(r["real_volume"]) if r["real_volume"] else float(r["tick_volume"])
            bars.append({"symbol": our_key, "tf": "30m", "ts": int(r["time"]),
                        "o": float(r["open"]), "h": float(r["high"]),
                        "l": float(r["low"]), "c": float(r["close"]), "v": vol})
        _write_bars(con, bars)
        total += len(bars)
        if verbose:
            log.info("%s %s..%s: +%d баров (закоммичено)",
                     our_key, cursor_start.date(), cursor_end.date(), len(bars))
        cursor_end = cursor_start
        time.sleep(SLEEP_BETWEEN_CALLS)
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=list(SYMBOL_MAP.keys()))
    ap.add_argument("--until", default="2018-01-01", help="докатить до этой даты (YYYY-MM-DD)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                         format="%(asctime)s %(levelname)s %(message)s")
    until_dt = datetime.strptime(args.until, "%Y-%m-%d")

    con = sqlite3.connect(str(BOT_DB))
    conn = rpyc.classic.connect(HOST, PORT)
    try:
        mt5 = conn.modules["MetaTrader5"]
        if not mt5.initialize(path=TERMINAL_PATH, timeout=60000):
            log.error("initialize() не удался: %s", mt5.last_error())
            sys.exit(1)
        total = 0
        for our_key in args.symbols:
            broker_sym = SYMBOL_MAP.get(our_key)
            if not broker_sym:
                log.warning("%s: нет в SYMBOL_MAP — пропуск", our_key)
                continue
            n = backfill_symbol(conn, con, our_key, broker_sym, until_dt, args.verbose)
            total += n
            print(f"{our_key}: +{n} баров 30m")
        print(f"итого: +{total} баров 30m")
        # НЕ mt5.shutdown() — см. докстринг модуля.
    finally:
        conn.close()
        con.close()


if __name__ == "__main__":
    main()
