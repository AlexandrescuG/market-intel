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
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
# 🔴 web/data, а не data. Фронт читает /data/… — это web/data на диске.
# Первая версия писала в служебный data/ рядом с базами: файл исправно
# создавался, проверка исправно отрабатывала, а браузер получал 404 и молча
# оставался на старом признаке. Отказ был невидим ровно так, как мы не любим:
# всё «работает», результат не применяется.
OUT = ROOT / "web" / "data" / "chart_available.json"
BOT_DB = "/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db"
BASE = "http://127.0.0.1:8085"

# Минимум свечей, ниже которого график рисовать нечем. Две-три точки — это не
# график, а обещание графика.
MIN_BARS = 30


# 🔴 Шесть секунд, а не тридцать. Первый прогон с большим запасом уходил на два
# часа: у восьмисот каталожных символов путь ведёт в Yahoo, а тот под нагрузкой
# отвечает десятками секунд. Но и по сути ждать дольше незачем: график, который
# не появился за шесть секунд, для посетителя не работает — он уже ушёл. Мы
# отвечаем на вопрос «покажется ли график», а не «существуют ли данные вообще».
PROBE_TIMEOUT = 6


def probe(sym: str, tf: str) -> tuple[bool, str, int]:
    url = f"{BASE}/api/chart/tail?s={urllib.parse.quote(sym, safe='')}&tf={tf}"
    try:
        d = json.load(urllib.request.urlopen(url, timeout=PROBE_TIMEOUT))
    except Exception:
        return False, "timeout", 0
    n = len(d.get("candles") or [])
    return n >= MIN_BARS, (d.get("source") or "yahoo"), n



def _blocklist() -> dict:
    """Инструменты, которые мы не показываем сознательно (data/instrument_blocklist.json).

    Проверка доступности отвечает на вопрос «есть ли свечи», а этот файл — на
    вопрос «хотим ли мы это показывать». Второе сильнее первого: у мем-монеты
    свечи есть, но на витрине консалтинговой платформы ей не место.
    Держим решение в файле, а не в коде: его должно быть видно и понятно без
    чтения исходников.
    """
    import json as _json
    path = ROOT / "data" / "instrument_blocklist.json"
    try:
        raw = _json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, dict)}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="D1", help="на каком ТФ проверять (D1 — самый полный)")
    ap.add_argument("--workers", type=int, default=6, help="сколько проверок разом")
    ap.add_argument("--limit", type=int, default=0, help="проверить только первые N (для отладки)")
    ap.add_argument("--no-retry", action="store_true", help="без второго прохода по неудачам")
    args = ap.parse_args()

    con = sqlite3.connect(BOT_DB)
    syms = [r[0] for r in con.execute(
        "SELECT broker_symbol FROM broker_symbols ORDER BY broker_symbol")]
    con.close()
    if args.limit:
        syms = syms[:args.limit]

    # Несколько проверок разом. Последовательный обход уходил почти на два часа
    # (842 холодных похода подряд), и это делало проверку бесполезной: она
    # должна успевать за сменой каталога, а не отставать от неё.
    # Шесть параллельных — заведомо меньше, чем создавал замер 12
    # одновременных запросов после перехода на многопоточный сервер.
    result: dict[str, dict] = {}
    t0 = time.time()
    done = 0

    def work(sym):
        ok, source, n = probe(sym, args.tf)
        if not ok and args.tf != "H1":
            # 🔴 Проверять один таймфрейм недостаточно. CrudeOIL уехал на
            # cTrader и прекрасно рисует H1, но D1 пуллер ещё не успел забрать —
            # по проверке только на D1 инструмент выпал бы из списка как
            # неработающий. Спрашиваем второй ТФ прежде, чем вычёркивать:
            # «графика нет» и «нет вот этого одного графика» — разные вещи.
            ok, source, n = probe(sym, "H1")
            if ok:
                return sym, {"ok": True, "source": source, "bars": n, "tf": "H1"}
        return sym, {"ok": ok, "source": source, "bars": n}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for sym, rec in pool.map(work, syms):
            result[sym] = rec
            done += 1
            if done % 50 == 0 or done == len(syms):
                good = sum(1 for v in result.values() if v["ok"])
                print(f"  {done}/{len(syms)}  открывается {good}  ({time.time()-t0:.0f} с)",
                      flush=True)

    # 🔴 Второй проход по неудачам — по одному и без спешки.
    #
    # Первый проход идёт шестью потоками и режет по 6 с. Это честно отражает
    # нагрузку, но НЕ отражает опыт посетителя: он открывает один график, а не
    # шесть разом, и его запрос не конкурирует сам с собой. Без этого прохода мы
    # вычеркнули бы из списка инструменты, которые у человека открываются
    # прекрасно, — а вычеркнуть рабочее хуже, чем оставить сомнительное.
    failed = [s for s, v in result.items() if not v["ok"]]
    if failed and not args.no_retry:
        print(f"\nвторой проход по {len(failed)} неудачам, по одному, до 20 с:", flush=True)
        global PROBE_TIMEOUT
        PROBE_TIMEOUT = 20
        revived = 0
        for i, s in enumerate(failed, 1):
            ok, source, n = probe(s, args.tf)
            if ok:
                result[s] = {"ok": True, "source": source, "bars": n, "slow": True}
                revived += 1
            if i % 100 == 0 or i == len(failed):
                print(f"  {i}/{len(failed)}  ожило {revived}  ({time.time()-t0:.0f} с)",
                      flush=True)
        print(f"  со второй попытки открылось: {revived}")

    good = sum(1 for v in result.values() if v["ok"])
    # Скрытые сознательно — помечаем отказом с причиной, а не удаляем из файла:
    # список инструментов на фронте читает ok, и «нет строки» от «скрыт» ему
    # не отличить, а нам в отчёте отличать надо.
    blocked = _blocklist()
    for sym, meta in blocked.items():
        if sym in result:
            result[sym] = {"ok": False, "source": "blocklist",
                           "bars": 0, "reason": meta.get("причина", "скрыт")}
    if blocked:
        print(f"  скрыто сознательно: {len(blocked)} ({', '.join(sorted(blocked))})")

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
