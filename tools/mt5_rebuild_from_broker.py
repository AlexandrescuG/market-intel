#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/mt5_rebuild_from_broker.py — разовая перестройка price_bars у брокера.

ЗАЧЕМ. До 20.08.2026 доливка (mt5_bridge_pull.py) шла по пяти ключам
SYMBOL_MAP. Остальные 20 инструментов графика попали в price_bars разовым
импортом из Yahoo 06.08.2026 и с тех пор не пополнялись. Отсюда два
последствия, которые долго читались как разные баги:

  * дневные графики этих инструментов и вся считанная по ним аналитика
    (base_rate, event_reactions, бэктесты) две недели стояли на мёртвом ряду;
  * ряд был из ЧУЖОГО фида. Замер расхождения на общей дате 06.08 против D1
    брокера: NASDAQ 12.2% (реестр звал «Nasdaq 100», а тянул ^IXIC Composite,
    у брокера же US_TECH100 — вообще другой индекс), WTI 3.7%, NG 2.3%,
    SOL 1.9%, BTC 0.8%, SILVER 0.8%. Пока такой ряд лежит на диске, живой
    хвост от брокера приклеивать к нему нельзя — получится ступенька.

ЧТО ДЕЛАЕТ. Для каждого символа: снимает историю у брокера, и ТОЛЬКО ЕСЛИ
снял — одной транзакцией удаляет старые строки и кладёт новые. Порядок
именно такой: DELETE до успешной выборки оставил бы аналитику на пустом
месте на всё время загрузки, а при обрыве моста — навсегда.

Старые строки не выбрасываются молча: перед заменой они выгружаются в
отдельный sqlite-файл (--backup, по умолчанию рядом с bot.db). Это не
«на всякий случай», а единственный способ потом объяснить сдвиг статистик.

ЧЕГО НЕ ДЕЛАЕТ. Не трогает символы, которых у брокера нет, и не трогает
ключи, уже набранные у брокера (EURUSD/USDJPY/XAUUSD/USDCNY/USDZAR) —
для них замена была бы работой вхолостую. --all снимает второе ограничение.

Запуск:
    python3 tools/mt5_rebuild_from_broker.py --dry-run     # что будет сделано
    python3 tools/mt5_rebuild_from_broker.py               # сделать
"""
import argparse
import logging
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import rpyc

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mt5_config import (CHART_BROKER_MAP, SYMBOL_MAP, TIMEFRAME_ATTR,
                        RECENT_BARS, bars_pull_map)

HOST, PORT = "127.0.0.1", 18812
TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"
BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

log = logging.getLogger("mt5_rebuild")


def _targets(do_all: bool) -> dict:
    """{ключ price_bars: имя у брокера} — что перестраиваем."""
    pull = bars_pull_map()
    if do_all:
        return pull
    return {k: v for k, v in pull.items() if k not in SYMBOL_MAP}


def _fetch(mt5, broker_sym: str, our_key: str) -> list[dict] | None:
    """Вся история символа по всем ТФ. None — брокер символ не дал."""
    if not mt5.symbol_select(broker_sym, True):
        log.warning("%s (%s): symbol_select не прошёл — пропуск", our_key, broker_sym)
        return None
    bars = []
    for tf_name, tf_attr in TIMEFRAME_ATTR.items():
        tf_code = getattr(mt5, tf_attr)
        rates = mt5.copy_rates_from_pos(broker_sym, tf_code, 0, RECENT_BARS.get(tf_name, 2000))
        # Первый запрос по незагруженному символу часто возвращает пусто и лишь
        # ЗАПУСКАЕТ подкачку истории в терминале. Вторая попытка после паузы —
        # не суеверие: без неё ровно так «пропадали» NZDUSD/USDCAD/USDCHF/
        # USDHUF/USDMXN/USDPLN/USDTRY на замере 20.08, хотя история у брокера
        # есть с 2006-2007 годов.
        if rates is None or len(rates) == 0:
            time.sleep(2)
            rates = mt5.copy_rates_from_pos(broker_sym, tf_code, 0, RECENT_BARS.get(tf_name, 2000))
        if rates is None or len(rates) == 0:
            log.warning("%s %s: баров нет даже со второй попытки", our_key, tf_name)
            continue
        for r in rpyc.classic.obtain(rates):
            vol = float(r["real_volume"]) if r["real_volume"] else float(r["tick_volume"])
            bars.append({"symbol": our_key, "tf": tf_name, "ts": int(r["time"]),
                         "o": float(r["open"]), "h": float(r["high"]),
                         "l": float(r["low"]), "c": float(r["close"]), "v": vol})
    return bars or None


def _backup(con: sqlite3.Connection, backup_path: Path, our_key: str) -> int:
    b = sqlite3.connect(str(backup_path))
    b.execute("CREATE TABLE IF NOT EXISTS price_bars_yahoo_20260820 ("
              "symbol TEXT, tf TEXT, ts INTEGER, o REAL, h REAL, l REAL, c REAL, v REAL)")
    rows = con.execute("SELECT symbol,tf,ts,o,h,l,c,v FROM price_bars WHERE symbol=?",
                       (our_key,)).fetchall()
    b.executemany("INSERT INTO price_bars_yahoo_20260820 VALUES (?,?,?,?,?,?,?,?)", rows)
    b.commit()
    b.close()
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--all", action="store_true",
                    help="перестроить и уже брокерские ключи тоже")
    ap.add_argument("--backup", default=str(BOT_DB.parent / "price_bars_pre_broker_rebuild.db"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    targets = _targets(args.all)
    log.info("к перестройке %d символов: %s", len(targets), sorted(targets))
    if args.dry_run:
        con = sqlite3.connect(str(BOT_DB))
        for our_key in sorted(targets):
            row = con.execute("SELECT COUNT(*), MIN(ts), MAX(ts) FROM price_bars WHERE symbol=?",
                              (our_key,)).fetchone()
            span = ""
            if row[1]:
                span = "%s..%s" % (datetime.fromtimestamp(row[1], timezone.utc).date(),
                                   datetime.fromtimestamp(row[2], timezone.utc).date())
            log.info("  %-8s сейчас %6d строк %s", our_key, row[0], span)
        con.close()
        return

    backup_path = Path(args.backup)
    con = sqlite3.connect(str(BOT_DB), timeout=120)
    # bot.db пишут и читают соседние джобы (alpha-цикл, event_reactions).
    # Без ожидания замок другого писателя убил бы прогон посреди символа.
    con.execute("PRAGMA busy_timeout=120000")
    conn = rpyc.classic.connect(HOST, PORT)
    replaced = skipped = 0
    try:
        mt5 = conn.modules["MetaTrader5"]
        if not mt5.initialize(path=TERMINAL_PATH, timeout=60000):
            log.error("initialize() не удался: %s", mt5.last_error())
            sys.exit(1)
        try:
            for our_key, broker_sym in sorted(targets.items()):
                t0 = time.time()
                bars = _fetch(mt5, broker_sym, our_key)
                if not bars:
                    log.warning("%s: брокер не дал ничего — СТАРЫЕ СТРОКИ ОСТАВЛЕНЫ", our_key)
                    skipped += 1
                    continue
                saved = _backup(con, backup_path, our_key)
                con.execute("BEGIN")
                con.execute("DELETE FROM price_bars WHERE symbol=?", (our_key,))
                con.executemany(
                    "INSERT OR REPLACE INTO price_bars (symbol, tf, ts, o, h, l, c, v) "
                    "VALUES (:symbol, :tf, :ts, :o, :h, :l, :c, :v)", bars)
                con.commit()
                replaced += 1
                log.info("%-8s %s: %d старых -> %d брокерских, %.1f с",
                         our_key, broker_sym, saved, len(bars), time.time() - t0)
        finally:
            mt5.shutdown()
    finally:
        conn.close()
        con.close()

    log.info("готово: перестроено %d, пропущено %d (старое сохранено в %s)",
             replaced, skipped, backup_path)
    if skipped:
        # Частичный успех — это НЕ успех: пропущенный символ остаётся на
        # Yahoo-ряду, а bars_from_broker() уже считает его брокерским.
        sys.exit(2)


if __name__ == "__main__":
    main()
