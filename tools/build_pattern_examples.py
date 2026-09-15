#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_pattern_examples.py — настоящие вхождения паттернов вместо рисунков.

🔴 ЗАЧЕМ. Галерея главы 10 рисует формы генератором со случайным зерном:
идеальный молот, идеальное поглощение, ровная двойная вершина. В жизни
таких не бывает, и это не придирка — на рисунке паттерн всегда «сработал»,
потому что его так нарисовали. Читатель учится узнавать фигуру, которой
нет.

При этом у нас лежит 1.19 млн баров по 31 инструменту (price_bars в
bot.db, дневки с 2014 года, недельки с 2006) и детектор на 11 паттернов
(core/patterns.py) — тот самый, которым считает бэктест и рисует живой
график. То есть настоящие вхождения искать нечем не надо: надо взять.

Скрипт находит вхождения каждого паттерна в реальной истории, выбирает
по одному показательному и сохраняет ФРАГМЕНТ БАРОВ как есть — без
подгонки, сглаживания и «докрутки» под красивую форму.

🔴 КАК ВЫБИРАЕТСЯ ПОКАЗАТЕЛЬНЫЙ. Не «самый красивый» — это вернуло бы нас
к рисунку, только через отбор. Берётся вхождение, ближайшее к медиане по
размаху окна: типичный случай, а не рекорд. Крайности врут в обе стороны:
самый яркий пример учит ждать яркого, самый вялый — не узнавать вовсе.

ВАЖНО ПРО ЧЕСТНОСТЬ ИТОГА. Что было ПОСЛЕ паттерна, скрипт не выбирает и
не подгоняет: в окно всегда входят ПОСЛЕДУЮЩИЕ бары (ХВОСТ), какими бы
они ни были. Если после «бычьего поглощения» цена пошла вниз — так и
будет нарисовано. Иначе получилась бы витрина удачных случаев, а глава
именно о том, что паттерн не даёт преимущества.

Результат: web/data/edu_capsules/pattern_examples.json.
Запуск: python3 tools/build_pattern_examples.py
"""
from __future__ import annotations

import json
import sqlite3
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(КОРЕНЬ))
from core.patterns import detect, PATTERNS  # noqa: E402

БАЗА = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
ВЫХОД = КОРЕНЬ / "web" / "data" / "edu_capsules" / "pattern_examples.json"

# Инструменты с самой длинной историей и понятными читателю именами.
ИНСТРУМЕНТЫ = [("XAUUSD", "Золото"), ("EURUSD", "EUR/USD"),
               ("BTC", "Биткойн"), ("USDJPY", "USD/JPY"),
               ("GBPUSD", "GBP/USD"), ("DJI", "Dow Jones")]
ТФ = "1d"
ДО = 12      # баров до паттерна — чтобы был виден контекст
ПОСЛЕ = 8    # баров после — что случилось дальше, без отбора

# Ключи карточек галереи (widgets.js) → ключи детектора.
КАРТОЧКИ = {
    "bullEngulf": "bullish_engulfing",
    "bearEngulf": "bearish_engulfing",
    "hammer": "hammer",
    "doji": "doji",
    "eveningStar": "shooting_star",
    "harami": "inside_bar",
    "doubleTop": "double_top",
    "doubleBottom": "double_bottom",
}


def бары(con, символ: str) -> list[dict]:
    строки = con.execute(
        "SELECT ts, o, h, l, c FROM price_bars WHERE symbol=? AND tf=? ORDER BY ts",
        (символ, ТФ)).fetchall()
    return [{"ts": t, "o": o, "h": h, "l": l, "c": c} for t, o, h, l, c in строки]


def окно(ряд: list[dict], i: int) -> list[dict] | None:
    если_рано = i - ДО < 0
    если_поздно = i + ПОСЛЕ >= len(ряд)
    if если_рано or если_поздно:
        return None
    return ряд[i - ДО: i + ПОСЛЕ + 1]


def размах(куски: list[dict]) -> float:
    в = max(к["h"] for к in куски)
    н = min(к["l"] for к in куски)
    с = statistics.median([к["c"] for к in куски])
    return (в - н) / с if с else 0.0


def main() -> int:
    if not БАЗА.exists():
        print(f"нет базы {БАЗА}")
        return 1
    con = sqlite3.connect(f"file:{БАЗА}?mode=ro", uri=True)

    # Собираем все вхождения по всем инструментам разом.
    найдено: dict[str, list[dict]] = {}
    for символ, имя in ИНСТРУМЕНТЫ:
        ряд = бары(con, символ)
        if len(ряд) < ДО + ПОСЛЕ + 30:
            continue
        по_ts = {б["ts"]: i for i, б in enumerate(ряд)}
        for событие in detect(ряд):
            ключ = событие["pattern_key"]
            i = по_ts.get(событие["ts"])
            if i is None:
                continue
            куски = окно(ряд, i)
            if not куски:
                continue
            найдено.setdefault(ключ, []).append({
                "символ": символ, "имя": имя, "tf": ТФ,
                "ts": событие["ts"], "направление": событие["direction"],
                "индекс_паттерна": ДО, "бары": куски, "размах": размах(куски),
            })
    con.close()

    вышло = {}
    for карточка, ключ in КАРТОЧКИ.items():
        случаи = найдено.get(ключ, [])
        if not случаи:
            print(f"   {карточка:14} — вхождений не найдено")
            continue
        случаи.sort(key=lambda с: с["размах"])
        типичный = случаи[len(случаи) // 2]
        # Что случилось после — считаем и записываем, каким бы оно ни было.
        бары_окна = типичный["бары"]
        цена_на = бары_окна[ДО]["c"]
        цена_после = бары_окна[-1]["c"]
        типичный["итог_пунктов"] = round(цена_после - цена_на, 5)
        типичный["итог_процентов"] = round((цена_после / цена_на - 1) * 100, 2) if цена_на else 0
        типичный["всего_вхождений"] = len(случаи)
        типичный["название"] = PATTERNS.get(ключ, {}).get("display_name_ru", ключ)
        типичный.pop("размах", None)
        вышло[карточка] = типичный

    if not вышло:
        print("ни одного примера — файл не тронут")
        return 1

    ВЫХОД.parent.mkdir(parents=True, exist_ok=True)
    ВЫХОД.write_text(json.dumps({
        "собрано": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "источник": "price_bars (bot.db) · детектор core/patterns.py",
        "как_выбран": "вхождение, медианное по размаху окна: типичный случай, "
                      "а не рекорд. Хвост после паттерна не отбирался.",
        "баров_до": ДО, "баров_после": ПОСЛЕ,
        "примеры": вышло,
    }, ensure_ascii=False), encoding="utf-8")

    print(f"примеров: {len(вышло)} из {len(КАРТОЧКИ)} → {ВЫХОД.relative_to(КОРЕНЬ)}")
    for к, з in вышло.items():
        дата = datetime.fromtimestamp(з["ts"], timezone.utc).strftime("%d.%m.%Y")
        знак = "+" if з["итог_процентов"] >= 0 else ""
        print(f"   {к:14} {з['имя']:10} {дата}  из {з['всего_вхождений']:>5} вхождений, "
              f"через {ПОСЛЕ} баров {знак}{з['итог_процентов']}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
