#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_fig_series.py — реальные отрезки рынка под индикаторные фигуры курса.

🔴 ЗАЧЕМ. grafik-engine.js рисует 24 фигуры в 12 главах: ATR, полосы
Боллинджера, скользящие, объём, Ишимоку, уровни Фибоначчи. Сами формулы в
движке честные — ATR считается как ATR. Но считаются они по ценам, которых
не было: indSeries() генерирует ряд из `mul(seed)` случайными шагами.

Индикатор — это функция от цены. Посчитанный по выдуманной цене, он
показывает свойства генератора, а не рынка: у случайного блуждания не
бывает ни настоящих сжатий волатильности, ни разворотов на уровне, ни
того, ради чего индикатор вообще смотрят. Читатель видит правильную
формулу на неправильном мире.

Скрипт нарезает из price_bars (1.19 млн баров, 31 инструмент) несколько
отрезков и кладёт их как есть. Никакого отбора «где индикатор сработал»:
берётся последний доступный отрезок по каждому инструменту. Если бы
отрезки подбирались под красивую картинку, мы вернулись бы к генератору —
только медленнее и с видом объективности.

Результат: web/data/edu_capsules/fig_series.json.
Запуск: python3 tools/build_fig_series.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]
БАЗА = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
ВЫХОД = КОРЕНЬ / "web" / "data" / "edu_capsules" / "fig_series.json"

ДЛИНА = 64  # столько баров показывает фигура движка

# Разные инструменты, чтобы фигуры в соседних главах не выглядели одним
# и тем же куском. Имена — те, что увидит читатель.
ОТРЕЗКИ = [
    ("основной", "XAUUSD", "Золото", "1d"),
    ("второй",   "EURUSD", "EUR/USD", "1d"),
    ("третий",   "BTC",    "Биткойн", "1d"),
    ("четвёртый", "USDJPY", "USD/JPY", "1d"),
]


def main() -> int:
    if not БАЗА.exists():
        print(f"нет базы {БАЗА}")
        return 1
    con = sqlite3.connect(f"file:{БАЗА}?mode=ro", uri=True)
    вышло = {}
    for имя_слота, символ, показ, тф in ОТРЕЗКИ:
        строки = con.execute(
            """SELECT ts, o, h, l, c, v FROM price_bars
               WHERE symbol=? AND tf=? ORDER BY ts DESC LIMIT ?""",
            (символ, тф, ДЛИНА)).fetchall()
        if len(строки) < ДЛИНА:
            print(f"   {символ}: баров {len(строки)} < {ДЛИНА}, пропускаем")
            continue
        строки.reverse()
        бары = [{"o": o, "h": h, "l": l, "c": c, "v": v or 0}
                for _, o, h, l, c, v in строки]
        с, по = строки[0][0], строки[-1][0]
        вышло[имя_слота] = {
            "символ": символ, "показ": показ, "tf": тф,
            "от": datetime.fromtimestamp(с, timezone.utc).strftime("%d.%m.%Y"),
            "до": datetime.fromtimestamp(по, timezone.utc).strftime("%d.%m.%Y"),
            "бары": бары,
        }
    con.close()

    if not вышло:
        print("ни одного отрезка — файл не тронут")
        return 1

    ВЫХОД.parent.mkdir(parents=True, exist_ok=True)
    ВЫХОД.write_text(json.dumps({
        "собрано": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "источник": "price_bars (bot.db)",
        "как_выбрано": "последние бары по каждому инструменту, без отбора "
                       "под удачную картинку",
        "отрезки": вышло,
    }, ensure_ascii=False), encoding="utf-8")
    print(f"отрезков: {len(вышло)} → {ВЫХОД.relative_to(КОРЕНЬ)}")
    for к, з in вышло.items():
        print(f"   {к:10} {з['показ']:10} {з['tf']}  {з['от']}…{з['до']}  "
              f"{len(з['бары'])} баров")
    return 0


if __name__ == "__main__":
    sys.exit(main())
