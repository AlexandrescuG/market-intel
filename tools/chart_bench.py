#!/usr/bin/env python3
"""tools/chart_bench.py — замер графиков каталога: сколько отдаётся и за сколько.

Написан 31.08.2026, когда «большая часть графиков не работает» оказалась суммой
трёх разных причин, и отличить их можно было только измерением:
  • имя инструмента с '#' рвало URL (585 из 842) — сервер видел пустой s= и
    отвечал 400;
  • холодный инструмент шёл в мост MT5 синхронно, 1.5-3.4 с на запрос;
  • пачка запросов подряд роняла мост, и тогда пустыми становились ВСЕ графики.

Поэтому здесь три прохода: холодный кэш, прогретый, и одновременная нагрузка.
Символы кодируются через quote(safe='') — ровно так же, как это теперь делает
фронт; без этого замер меряет собственную ошибку, а не сайт.

Запуск:  python3 tools/chart_bench.py [--n 60] [--tf D1]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import threading
import time
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8085"
BOT_DB = "/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db"


def hit(sym: str, tf: str) -> tuple[int, float]:
    url = (f"{BASE}/api/chart/tail?s={urllib.parse.quote(sym, safe='')}"
           f"&tf={urllib.parse.quote(tf)}")
    t0 = time.time()
    try:
        d = json.load(urllib.request.urlopen(url, timeout=30))
        n = len(d.get("candles", []))
    except Exception:
        n = 0
    return n, (time.time() - t0) * 1000


def report(title: str, results: list[tuple[int, float]]) -> None:
    ok = sum(1 for n, _ in results if n)
    times = sorted(t for _, t in results)
    k = len(times)
    print(f"{title}: со свечами {ok} из {k}")
    if k:
        print(f"  медиана {times[k // 2]:.0f} мс, p90 {times[int(k * 0.9) - 1]:.0f} мс, "
              f"максимум {times[-1]:.0f} мс")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--tf", default="D1")
    args = ap.parse_args()

    con = sqlite3.connect(BOT_DB)
    syms = [r[0] for r in con.execute(
        "SELECT broker_symbol FROM broker_symbols ORDER BY RANDOM() LIMIT ?", (args.n,))]
    con.close()

    report("ПЕРВЫЙ ПРОХОД (кэш пуст)", [hit(s, args.tf) for s in syms])
    report("ВТОРОЙ ПРОХОД (кэш прогрет)", [hit(s, args.tf) for s in syms])

    # Одновременная нагрузка — то, чего сайт раньше не переживал.
    res: list = []
    lock = threading.Lock()

    def worker(s):
        r = hit(s, args.tf)
        with lock:
            res.append(r)

    ths = [threading.Thread(target=worker, args=(s,)) for s in syms[:12]]
    t0 = time.time()
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    print(f"12 ОДНОВРЕМЕННЫХ: со свечами {sum(1 for n, _ in res if n)} из 12 "
          f"за {(time.time() - t0) * 1000:.0f} мс")

    t0 = time.time()
    try:
        urllib.request.urlopen(BASE + "/", timeout=20).read()
        print(f"главная страница сразу после нагрузки: {(time.time() - t0) * 1000:.0f} мс")
    except Exception as e:
        print(f"главная страница НЕ ответила: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
