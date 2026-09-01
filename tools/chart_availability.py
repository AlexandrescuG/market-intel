#!/usr/bin/env python3
"""tools/chart_availability.py — какие инструменты каталога РЕАЛЬНО рисуют график.

ЗАЧЕМ. В левом списке страницы «Графики» лежат все 842 инструмента каталога, и
кликабельность определялась по полю `canonical` — то есть по тому, есть ли у
инструмента имя в реестре, а не по тому, есть ли у него свечи. Наличие
котировки в списке тоже ничего не обещает: у #REDDIT, #SPACEX, GOLD_FUTURE,
_SAFRAN.FR цена показана, а график пустой.

Список, где половина строк открывается в пустоту, читается как сломанный сайт —
и совершенно справедливо.

КАК ПРОВЕРЯЕТ. Единственный надёжный способ — спросить ровно тем же путём,
которым ходит браузер: GET /api/chart/tail. Никаких догадок по метаданным:
«котировка свежая» и «свечи есть» — разные вещи, мы на этом уже обжигались.

БЕРЕЖНО К МОСТУ. Один запрос в секунду, последовательно. Обход каталога сотнями
параллельных вызовов положил сайт 25.08; здесь темп заведомо ниже того, что
создаёт один живой посетитель, листающий графики.

Результат: data/chart_available.json — {symbol: {"ok": bool, "source": str,
"bars": int}} плюс метка времени проверки. Файл читает фронт и прячет строки,
по которым графика нет.

Запуск:  python3 tools/chart_availability.py            # полная проверка
         python3 tools/chart_availability.py --tf D1     # другой таймфрейм
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "chart_available.json"
BOT_DB = "/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db"
BASE = "http://127.0.0.1:8085"

# Минимум свечей, ниже которого график рисовать нечем. Две-три точки — это не
# график, а обещание графика.
MIN_BARS = 30


def probe(sym: str, tf: str) -> tuple[bool, str, int]:
    url = f"{BASE}/api/chart/tail?s={urllib.parse.quote(sym, safe='')}&tf={tf}"
    try:
        d = json.load(urllib.request.urlopen(url, timeout=30))
    except Exception:
        return False, "error", 0
    n = len(d.get("candles") or [])
    return n >= MIN_BARS, (d.get("source") or "yahoo"), n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="D1", help="на каком ТФ проверять (D1 — самый полный)")
    ap.add_argument("--pace", type=float, default=1.0, help="пауза между запросами, с")
    ap.add_argument("--limit", type=int, default=0, help="проверить только первые N (для отладки)")
    args = ap.parse_args()

    con = sqlite3.connect(BOT_DB)
    syms = [r[0] for r in con.execute(
        "SELECT broker_symbol FROM broker_symbols ORDER BY broker_symbol")]
    con.close()
    if args.limit:
        syms = syms[:args.limit]

    result: dict[str, dict] = {}
    t0 = time.time()
    for i, s in enumerate(syms, 1):
        ok, source, n = probe(s, args.tf)
        result[s] = {"ok": ok, "source": source, "bars": n}
        if i % 50 == 0 or i == len(syms):
            good = sum(1 for v in result.values() if v["ok"])
            print(f"  {i}/{len(syms)}  открывается {good}  ({time.time()-t0:.0f} с)",
                  flush=True)
        time.sleep(args.pace)

    good = sum(1 for v in result.values() if v["ok"])
    payload = {"checked_at": int(time.time()), "tf": args.tf,
               "total": len(result), "ok": good, "items": result}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=0, sort_keys=True),
                   encoding="utf-8")

    from collections import Counter
    by_src = Counter(v["source"] for v in result.values() if v["ok"])
    print(f"\nитог: {good} из {len(result)} инструментов рисуют график")
    print("  по источникам:", ", ".join(f"{k}={v}" for k, v in by_src.most_common()))
    print(f"  записано: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
