#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""broker_catalog_loop.py — живой снимок каталога брокера (SPEC_chart_all_instruments §4, ярус 1).

Долгоживущий цикл, по образцу quotes_loop.py: дешевле, чем systemd-таймер раз
в 15 секунд. Пишет web/data/broker_quotes.json — его читает страница графика,
и только его: в MT5 из веб-запроса не ходят никогда (см. докстринг
core/broker_catalog.py).

ДВА ТАКТА, А НЕ ОДИН. Котировки уходят в JSON каждые 15 с — это цена, она
меняется постоянно. Каталог (broker_symbols в bot.db) переписывается раз в
CATALOG_EVERY итераций: состав инструментов, их категории и имена меняются
раз в недели, а 842 UPDATE каждые 15 секунд в общую базу, которую пишут
соседние джобы, — это нагрузка без содержания.

    python3 broker_catalog_loop.py [--once] [--interval 15]
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core import broker_catalog as BC
from core.db_migrations import apply_all
from core.logging_setup import setup

INTERVAL = 15
CATALOG_EVERY = 20          # 20 x 15 c = каталог в базе освежается раз в 5 минут
FAIL_LOUD_AFTER = 4         # столько подряд отказов моста — уже не рябь

log = logging.getLogger("broker_catalog_loop")


def tick(write_catalog: bool) -> int:
    """Возвращает число символов в снимке. Бросает BridgeUnavailable."""
    rows = BC.fetch_snapshot()
    BC.publish_quotes(rows)
    if write_catalog:
        BC.publish_catalog(rows)
        con = BC.connect_db()
        try:
            apply_all(con)
            new, upd = BC.upsert(con, rows)
        finally:
            con.close()
        if new:
            log.info("каталог: новых инструментов %d, обновлено %d", new, upd)
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="один прогон и выход")
    ap.add_argument("--interval", type=int, default=INTERVAL)
    args = ap.parse_args()
    setup("broker_catalog")

    if args.once:
        n = tick(write_catalog=True)
        print(f"broker_catalog: {n} символов -> {BC.OUT_PATH.name}")
        return 0

    i = 0
    fails = 0
    while True:
        try:
            n = tick(write_catalog=(i % CATALOG_EVERY == 0))
            if fails >= FAIL_LOUD_AFTER:
                log.warning("каталог: мост снова отвечает после %d отказов подряд", fails)
            fails = 0
            if i % CATALOG_EVERY == 0:
                log.info("каталог: снимок %d символов", n)
        except BC.BridgeUnavailable as e:
            fails += 1
            # 🔴 Ровно один раз громко, потом тихо. Мост в Wine падает и
            # поднимается сам; лог, в котором каждые 15 секунд одна и та же
            # строка, перестают читать — и настоящий отказ в нём тонет.
            # Но и молчать нельзя: страница будет показывать вчерашний снимок
            # без единого признака, что он вчерашний.
            if fails == FAIL_LOUD_AFTER:
                log.error("каталог: мост не отвечает %d раз подряд (%s) — "
                          "снимок не обновляется", fails, e)
            elif fails < FAIL_LOUD_AFTER:
                log.warning("каталог: мост не ответил (%s)", e)
        except Exception as e:
            log.exception("каталог: непредвиденная ошибка: %s", e)
        i += 1
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
