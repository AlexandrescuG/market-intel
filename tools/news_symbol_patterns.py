#!/usr/bin/env python3
"""tools/news_symbol_patterns.py — словарь «новость → инструмент» из каталога.

ЗАЧЕМ. news_burst_job.py тегирует новости по словарю из 15 символов, зашитому в
код: золото, нефть, биткоин, мажоры. Новостей приходит 3252 в сутки, тегов
накоплено 19 610 — механизм работает прекрасно, просто адресатов у него
пятнадцать. На витрине к этому моменту 334 инструмента, из них 206 акций, и
новость про Boeing не может попасть на график Boeing, потому что такого адреса
в словаре нет.

ЧТО ДЕЛАЕТ. Строит выражения для оставшихся инструментов из каталога брокера:
имя (#BOEING → BOEING) и биржевой тикер (BA). Результат — файл, который
news_burst_job подхватывает и объединяет со своим встроенным словарём.

🔴 ГЛАВНАЯ ОПАСНОСТЬ ЗДЕСЬ — ЛОЖНЫЕ СРАБАТЫВАНИЯ, А НЕ ПРОПУСКИ.
Пропущенная новость — это отсутствие отметки на графике. Ложная — это чужая
новость под видом относящейся к активу, то есть прямая дезинформация на
публичной витрине. Поэтому:

  • тикеры и имена короче 4 символов НЕ ищутся как слова: #GE, #EA, #ARM, #3M
    дали бы совпадение на «ge», «ea», «arm» в любом английском тексте. Для них
    остаётся только форма с долларом ($GE) — так тикеры пишут в лентах и в X;
  • имена, совпадающие с обычными словами, отсеиваются по стоп-листу;
  • подчёркивания и суффиксы страны (.UK, .DE) убираются, но само имя не
    «додумывается»: если после чистки осталось нечитаемое, инструмент
    пропускается и это видно в отчёте.

Запуск:  python3 tools/news_symbol_patterns.py           # показать
         python3 tools/news_symbol_patterns.py --write   # записать
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
CATALOG = ROOT / "web" / "data" / "broker_catalog.json"
AVAIL = ROOT / "web" / "data" / "chart_available.json"
OUT = ROOT / "data" / "news_symbol_patterns.json"

# Уже зашиты в news_burst_job.py вручную и написаны точнее, чем получится
# автоматически (там учтены русские написания и жаргон вроде "cable").
BUILTIN = {"GOLD", "SILVER", "BTC", "ETH", "SOL", "SPX", "NASDAQ", "DJI",
           "VIX", "WTI", "NG", "EURUSD", "GBPUSD", "USDJPY", "DXY"}

# Имена, которые в английском тексте значат что угодно. Список рос по мере
# чтения каталога; каждая строка — реальный инструмент, чьё имя без этого
# фильтра ловило бы новости обо всём подряд.
AMBIGUOUS = {
    "ARM", "GE", "EA", "ADM", "ALL", "KEY", "GAP", "SO", "IT", "ON", "NOW",
    "OPEN", "PLUS", "REAL", "NICE", "BEST", "MOTION", "UNITY", "BOX", "DISH",
    "SHOP", "LIFE", "FAST", "PRIME", "SUN", "STAR", "TWO", "ONE", "MATCH",
    "SNAP", "CROWN", "HUB", "PATH", "WELL", "WORK", "AXIS",
    # Добавлено после сухого прогона по живым заголовкам: «_TOTAL» ловил
    # «'Total Dumps' Start at $500K», «TARGET» поймал бы любую цель, «VISA» —
    # любую визу, «ORANGE» — цвет. Все они настоящие компании, и именно поэтому
    # опасны: имя правильное, новость чужая.
    "TOTAL", "TARGET", "VISA", "ORANGE", "APPLE_TEST", "NEXT", "CAPITAL",
    "GENERAL", "NATIONAL", "STANDARD", "UNITED", "AMERICAN", "PUBLIC",
    "ALPHABET", "META", "SQUARE", "BLOCK", "STELLAR", "ADVANCE",
}

MIN_WORD_LEN = 4          # короче — только форма с долларом
MIN_TICKER_LEN = 3


def clean_name(symbol: str) -> str:
    """#BOEING → BOEING, _SAFRAN.FR → SAFRAN, #AMERICAN_E → AMERICAN E."""
    s = symbol.lstrip("#_")
    s = re.sub(r"\.(UK|DE|FR|IT|ES|NL|CH|CA|AU|JP|HK)$", "", s, flags=re.I)
    return s.replace("_", " ").strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    items = json.loads(CATALOG.read_text(encoding="utf-8")).get("items", [])
    avail = json.loads(AVAIL.read_text(encoding="utf-8")).get("items", {})

    out: dict[str, dict] = {}
    skipped: list[str] = []

    for it in items:
        sym = it.get("symbol") or ""
        # Тегируем только то, что открывается: отметка на графике, которого
        # нет, никому не поможет.
        if not avail.get(sym, {}).get("ok"):
            continue
        if sym in BUILTIN:
            continue

        name = clean_name(sym)
        ticker = (it.get("name") or "").strip()
        if ticker == sym or ticker.startswith("#"):
            ticker = ""

        words: list[str] = []      # ищем как слово в тексте
        cash: list[str] = []       # ищем только в форме $TICKER

        # 🔴 Биржевой тикер ищем ТОЛЬКО в форме с долларом, каким бы длинным он
        # ни был. Сухой прогон по 3059 живым заголовкам показал, почему: тикер
        # Costco — COST, и выражение поймало «These 3 High-Yield ETFs **Cost**
        # You Thousands». Четыре буквы, порог длины пройден, а новость не про
        # Costco. Тикеры сплошь и рядом совпадают с обычными словами, и
        # отличить их в тексте нельзя — зато «$COST» ни с чем не спутать.
        if ticker:
            tu = ticker.upper()
            if re.fullmatch(r"[A-Z0-9.\-]+", tu):
                cash.append(tu)

        # Читаемое имя инструмента можно искать как слово: COSTCO, BOEING,
        # SAFRAN сами по себе однозначны. Кроме тех, что совпадают с обычными
        # словами, — они в стоп-листе.
        cand = name.upper()
        if re.fullmatch(r"[A-Z0-9 &.\-]+", cand):
            if cand in AMBIGUOUS:
                cash.append(cand)
            elif len(cand.replace(" ", "")) >= MIN_WORD_LEN:
                words.append(cand)
            elif len(cand) >= MIN_TICKER_LEN:
                cash.append(cand)

        if not words and not cash:
            skipped.append(sym)
            continue

        parts = []
        for w in sorted(set(words)):
            parts.append(r"\b" + re.escape(w).replace(r"\ ", r"\s+") + r"\b")
        for c in sorted(set(cash)):
            parts.append(r"\$" + re.escape(c) + r"\b")
        out[sym] = {"pattern": "|".join(parts),
                    "words": sorted(set(words)), "cashtags": sorted(set(cash)),
                    "category": it.get("category")}

    print(f"инструментов с графиком: {sum(1 for i in items if avail.get(i.get('symbol',''),{}).get('ok'))}")
    print(f"  получили выражение: {len(out)}")
    print(f"  пропущено (имя нечитаемо): {len(skipped)}"
          + (f" — {', '.join(skipped[:8])}" if skipped else ""))
    only_cash = [s for s, v in out.items() if not v["words"]]
    print(f"  только по $тикеру (короткое или двусмысленное имя): {len(only_cash)}")

    if args.write:
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True),
                       encoding="utf-8")
        print(f"\nзаписано: {OUT}")
    else:
        print("\nЭто предпросмотр. Записать: --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
