#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mt5_pull.py — мост MetaTrader 5 → сервер SBF (price_bars).

ЗАЧЕМ: под Wine («бутылка») пакет MetaTrader5 не работает. Этот скрипт
запускается на НАТИВНОМ Windows, где установлен и залогинен терминал MT5,
качает свечи по нужным символам/таймфреймам и:
  • POST'ит их на сервер lp (режим по умолчанию), ИЛИ
  • пишет в локальный SQLite price_bars, ИЛИ
  • выгружает в CSV.
Тем самым наполняется price_bars, из которого рисуются графики и календарь.

ТРЕБОВАНИЯ (на Windows):
  py -m pip install MetaTrader5 requests
  Терминал MT5 установлен, запущен и залогинен под брокером (AvaTrade/NAGA).

ЗАПУСК:
  # разовая доливка истории (бэкфилл) с даты:
  py mt5_pull.py --mode post --backfill-from 2018-01-01
  # штатный догон свежих баров раз в 5 минут:
  py mt5_pull.py --mode post --loop 300
  # без сервера, в локальный SQLite:
  py mt5_pull.py --mode sqlite

СЕКРЕТЫ — только через переменные окружения, НЕ хардкодить, НЕ логировать:
  set INGEST_URL=https://lp.sbfconsult.com/api/ingest/bars
  set INGEST_TOKEN=<секрет>            (общий с сервером)
  set MT5_LOGIN=12345678               (опционально, если терминал не залогинен)
  set MT5_PASSWORD=...                 (опционально)
  set MT5_SERVER=Broker-Server         (опционально)
  set MT5_PATH=C:\\Path\\terminal64.exe  (опционально, путь к терминалу)
"""

import os
import sys
import time
import json
import argparse
import logging
from datetime import datetime, timezone

try:
    import MetaTrader5 as mt5
except ImportError:
    sys.exit("Нет пакета MetaTrader5. Установи: py -m pip install MetaTrader5 (только Windows).")

import requests  # для режима post

# ------------------------------------------------------------------ КОНФИГ ---

# SYMBOL_MAP / RECENT_BARS — общие с mt5_bridge_pull.py, см. mt5_config.py.
from mt5_config import SYMBOL_MAP, TIMEFRAME_ATTR, RECENT_BARS

# наш tf-код -> константа таймфрейма MT5  (совпадает с тумблерами графика)
# 15m — SPEC_chart_fixes_and_staged_signup.md §3 (добавлен на сервере
# publish.py::publish_charts_mt5, ждёт бэкфилла отсюда).
TIMEFRAMES = {name: getattr(mt5, attr) for name, attr in TIMEFRAME_ATTR.items()}

HTTP_CHUNK = 5000          # баров в одном POST
LOCAL_DB   = "price_bars.sqlite"
CSV_DIR    = "bars_csv"

log = logging.getLogger("mt5_pull")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# --------------------------------------------------------------- ПОДКЛЮЧЕНИЕ -

def connect():
    kwargs = {}
    if os.getenv("MT5_PATH"):
        kwargs["path"] = os.getenv("MT5_PATH")
    if os.getenv("MT5_LOGIN"):
        kwargs.update(
            login=int(os.getenv("MT5_LOGIN")),
            password=os.getenv("MT5_PASSWORD", ""),
            server=os.getenv("MT5_SERVER", ""),
        )
    if not mt5.initialize(**kwargs):
        sys.exit(f"MT5 initialize() не удался: {mt5.last_error()}")
    info = mt5.account_info()
    # НЕ логируем логин/пароль/токен — только факт подключения
    log.info("MT5 подключён. Терминал: %s", mt5.terminal_info().name if mt5.terminal_info() else "?")
    if info is None:
        log.warning("account_info() пуст — терминал может быть не залогинен.")

# ------------------------------------------------------------------ ВЫГРУЗКА -

def fetch(our_key, broker_sym, tf_code, tf_name, backfill_from):
    """Возвращает список dict-баров нашего формата или []"""
    if not mt5.symbol_select(broker_sym, True):
        log.warning("Символ %s (%s) не найден у брокера — пропуск.", broker_sym, our_key)
        return []
    if backfill_from:
        date_to = datetime.now(timezone.utc)
        rates = mt5.copy_rates_range(broker_sym, tf_code, backfill_from, date_to)
    else:
        rates = mt5.copy_rates_from_pos(broker_sym, tf_code, 0, RECENT_BARS.get(tf_name, 2000))
    if rates is None or len(rates) == 0:
        log.warning("Нет данных: %s %s (%s)", our_key, tf_name, mt5.last_error())
        return []
    out = []
    for r in rates:
        vol = float(r["real_volume"]) if r["real_volume"] else float(r["tick_volume"])
        out.append({
            "symbol": our_key,
            "tf": tf_name,
            "ts": int(r["time"]),          # POSIX-секунды (UTC)
            "o": float(r["open"]),
            "h": float(r["high"]),
            "l": float(r["low"]),
            "c": float(r["close"]),
            "v": vol,
        })
    log.info("%s %s: %d баров", our_key, tf_name, len(out))
    return out

# -------------------------------------------------------------------- ВЫВОД -

def push_http(bars):
    url = os.getenv("INGEST_URL")
    token = os.getenv("INGEST_TOKEN")
    if not url or not token:
        sys.exit("Режим post требует INGEST_URL и INGEST_TOKEN в переменных окружения.")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    for i in range(0, len(bars), HTTP_CHUNK):
        chunk = bars[i:i + HTTP_CHUNK]
        resp = requests.post(url, headers=headers, data=json.dumps({"bars": chunk}), timeout=60)
        if resp.status_code >= 300:
            log.error("POST %s -> %s: %s", url, resp.status_code, resp.text[:200])
            resp.raise_for_status()
        log.info("Отправлено %d баров (HTTP %s)", len(chunk), resp.status_code)

def write_sqlite(bars):
    import sqlite3
    con = sqlite3.connect(LOCAL_DB)
    con.execute("""CREATE TABLE IF NOT EXISTS price_bars(
        symbol TEXT, tf TEXT, ts INTEGER, o REAL, h REAL, l REAL, c REAL, v REAL,
        PRIMARY KEY(symbol, tf, ts))""")
    con.executemany(
        "INSERT OR REPLACE INTO price_bars VALUES (:symbol,:tf,:ts,:o,:h,:l,:c,:v)", bars)
    con.commit(); con.close()
    log.info("SQLite: записано %d баров в %s", len(bars), LOCAL_DB)

def write_csv(bars):
    import csv, collections
    os.makedirs(CSV_DIR, exist_ok=True)
    groups = collections.defaultdict(list)
    for b in bars:
        groups[(b["symbol"], b["tf"])].append(b)
    for (sym, tf), rows in groups.items():
        path = os.path.join(CSV_DIR, f"{sym}_{tf}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["symbol", "tf", "ts", "o", "h", "l", "c", "v"])
            w.writeheader(); w.writerows(rows)
        log.info("CSV: %s (%d)", path, len(rows))

# --------------------------------------------------------------------- MAIN -

def run_once(mode, backfill_from):
    all_bars = []
    for our_key, broker_sym in SYMBOL_MAP.items():
        for tf_name, tf_code in TIMEFRAMES.items():
            all_bars.extend(fetch(our_key, broker_sym, tf_code, tf_name, backfill_from))
    if not all_bars:
        log.warning("Пусто — ничего не выгружено."); return
    if mode == "post":   push_http(all_bars)
    elif mode == "sqlite": write_sqlite(all_bars)
    elif mode == "csv":  write_csv(all_bars)

def main():
    ap = argparse.ArgumentParser(description="MT5 → price_bars мост (Windows)")
    ap.add_argument("--mode", choices=["post", "sqlite", "csv"], default="post")
    ap.add_argument("--backfill-from", help="дата начала истории YYYY-MM-DD (разовый бэкфилл)")
    ap.add_argument("--loop", type=int, default=0, help="интервал повтора в секундах (0 = один раз)")
    args = ap.parse_args()

    backfill_from = None
    if args.backfill_from:
        backfill_from = datetime.strptime(args.backfill_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    connect()
    try:
        if args.loop:
            log.info("Цикл каждые %d c. Ctrl+C для выхода.", args.loop)
            while True:
                try:
                    run_once(args.mode, backfill_from)
                    backfill_from = None  # бэкфилл только на первой итерации
                except Exception as e:
                    log.error("Итерация упала: %s", e)
                time.sleep(args.loop)
        else:
            run_once(args.mode, backfill_from)
    finally:
        mt5.shutdown()
        log.info("MT5 отключён.")

if __name__ == "__main__":
    main()
