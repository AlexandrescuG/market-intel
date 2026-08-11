#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mt5_bridge_pull.py — доливка price_bars через rpyc-мост mt5_server.py
(SPEC_alpha_engine_implementation.md WP0.3).

ЗАЧЕМ: `mt5_pull.py` по своему докстрингу рассчитан на ОТДЕЛЬНУЮ нативную
Windows-машину (её отключили, см. Core-лог 07.08.2026). Реальный работающий
путь с 16.07 — MetaTrader5 внутри Wine-бутылки `Trading`, доступный по rpyc
через `mt5_server.py` (теперь под systemd — `sbf-mt5-bridge.service`). До
этого файла у этого пути не было ни одного постоянного скрипта на диске —
доливка делалась вручную/разово, отсюда дыры в price_bars (H1/H4 не росли
с 16.07, 30m/1d встали 06.08 — терминал был закрыт с 26.07 по 07.08).

Пишет ПРЯМО в price_bars (bot.db) — тот же формат, что и mt5_pull.py в
режиме --mode sqlite, просто в боевую таблицу вместо локального файла.

Ничего не пишет и не трогает в MT5 кроме чтения баров: initialize()/
copy_rates_from_pos()/shutdown(). Никаких order_send и торговых вызовов —
в бутылке живёт торговый EA, это read-only мост.

Запуск: python3 mt5_bridge_pull.py [--verbose]
Расписание: sbf-mt5-pull.timer (каждые 15 мин).
"""
import argparse
import logging
import sqlite3
import sys
from pathlib import Path

import rpyc

sys.path.insert(0, str(Path(__file__).parent))
from mt5_config import SYMBOL_MAP, TIMEFRAME_ATTR, RECENT_BARS

HOST, PORT = "127.0.0.1", 18812
TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"
BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

log = logging.getLogger("mt5_bridge_pull")


def _write_bars(con: sqlite3.Connection, bars: list[dict]) -> None:
    if not bars:
        return
    con.executemany(
        "INSERT OR REPLACE INTO price_bars (symbol, tf, ts, o, h, l, c, v) "
        "VALUES (:symbol, :tf, :ts, :o, :h, :l, :c, :v)",
        bars,
    )
    con.commit()


def fetch_and_write(verbose: bool) -> int:
    """🔴 Раньше собирало все бары в один список и писало в БД ОДНИМ
    вызовом в самом конце — реальный прод-баг: TimeoutStartSec=600 у
    systemd-юнита короче, чем фактическое время полного прогона (~30 мин на
    5 символов), SIGTERM убивал процесс ДО записи -- каждый час 2+ суток
    подряд честно тянул все бары и терял их все, ничего не попадало в
    price_bars (см. Core-лог 10.08). Теперь коммит после КАЖДОГО символа —
    таймаут теряет только необработанный остаток, не всю работу целиком."""
    con = sqlite3.connect(str(BOT_DB))
    conn = rpyc.classic.connect(HOST, PORT)
    total = 0
    try:
        mt5 = conn.modules["MetaTrader5"]
        if not mt5.initialize(path=TERMINAL_PATH, timeout=60000):
            log.error("initialize() не удался: %s", mt5.last_error())
            return 0
        try:
            for our_key, broker_sym in SYMBOL_MAP.items():
                if not mt5.symbol_select(broker_sym, True):
                    if verbose:
                        log.info("%s (%s) недоступен у брокера — пропуск", broker_sym, our_key)
                    continue
                bars = []
                for tf_name, tf_attr in TIMEFRAME_ATTR.items():
                    tf_code = getattr(mt5, tf_attr)
                    rates = mt5.copy_rates_from_pos(broker_sym, tf_code, 0, RECENT_BARS.get(tf_name, 2000))
                    if rates is None or len(rates) == 0:
                        continue
                    for r in rates:
                        vol = float(r["real_volume"]) if r["real_volume"] else float(r["tick_volume"])
                        bars.append({
                            "symbol": our_key, "tf": tf_name, "ts": int(r["time"]),
                            "o": float(r["open"]), "h": float(r["high"]),
                            "l": float(r["low"]), "c": float(r["close"]), "v": vol,
                        })
                    if verbose:
                        log.info("%s %s: %d баров", our_key, tf_name, len(rates))
                _write_bars(con, bars)
                total += len(bars)
                if verbose:
                    log.info("%s: закоммичено %d строк", our_key, len(bars))
            return total
        finally:
            mt5.shutdown()
    finally:
        conn.close()
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                         format="%(asctime)s %(levelname)s %(message)s")
    try:
        n = fetch_and_write(args.verbose)
    except (ConnectionRefusedError, EOFError, OSError) as e:
        log.error("Мост недоступен (sbf-mt5-bridge.service живой?): %s", e)
        sys.exit(1)
    if args.verbose or n == 0:
        print(f"price_bars: записано/обновлено {n} строк")


if __name__ == "__main__":
    main()
