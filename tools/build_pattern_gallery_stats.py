#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_pattern_gallery_stats.py — наши измерения к карточкам галереи паттернов.

🔴 ЗАЧЕМ. Галерея главы 10 рисует 15 карточек из генератора со случайным
зерном под заголовком «Паттерны рынка» — без единой пометки, что формы
нарисованы, а не найдены в истории. Это единственный из инжектируемых
блоков без метки «СХЕМА · ИЛЛЮСТРАЦИЯ»: у остальных 24 она есть.

Метку вернуть надо, но одной метки мало. По девяти из этих паттернов у
нас есть НАСТОЯЩИЕ измерения — pattern_stats_job считает их еженедельно
по 80+ инструментам: 233 тысячи наблюдений суммарно. И измерения говорят
ровно то, ради чего эта глава написана: доля случаев, когда цена через
пять баров пошла в «обещанную» паттерном сторону, лежит между 0.477 и
0.518. То есть монетка.

Показать рядом с красивой картинкой её же измеренную бесполезность — это
и есть замена выдумки данными. Формы остаются схемами (они объясняют, как
паттерн выглядит), но больше не выдают себя за знание о рынке.

Доля считается взвешенной по числу наблюдений: у EURUSD H1 их 7604, у
редкой пары — полсотни, и простое среднее по инструментам дало бы
одинаковый вес обоим.

Источник: SBFAcademy_bot/bot.db, таблица pattern_stats (порог n>=15 — тот
же, что у ручки /api/chart/pattern-stats).

Запуск: python3 tools/build_pattern_gallery_stats.py
Частота: после еженедельного pattern_stats_job.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]
БАЗА = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
ВЫХОД = КОРЕНЬ / "web" / "data" / "edu_capsules" / "pattern_gallery_stats.json"

# Ключи галереи (widgets.js) → ключи pattern_stats. Пустая строка значит
# «мы этот паттерн не измеряли» — и на карточке будет честно сказано это,
# а не подставлено чужое число.
СООТВЕТСТВИЕ = {
    "bullEngulf": "bullish_engulfing",
    "bearEngulf": "bearish_engulfing",
    "hammer": "hammer",
    "doji": "",
    "morningStar": "",
    "eveningStar": "shooting_star",
    "harami": "",
    "triangleAsc": "",
    "triangleDesc": "",
    "pennant": "",
    "hns": "",
    "doubleTop": "double_top",
    "doubleBottom": "double_bottom",
    "wedge": "",
    "flag": "",
}


def main() -> int:
    if not БАЗА.exists():
        print(f"нет базы {БАЗА}")
        return 1
    con = sqlite3.connect(f"file:{БАЗА}?mode=ro", uri=True)
    сырое = {}
    for ключ, n, доля in con.execute(
        """SELECT pattern_key, SUM(n), SUM(agree_share_5 * n) / SUM(n)
           FROM pattern_stats WHERE n >= 15 GROUP BY pattern_key"""):
        сырое[ключ] = {"наблюдений": int(n), "доля_5": round(доля, 4)}
    окно = con.execute(
        "SELECT MIN(history_from_ts), MAX(computed_ts) FROM pattern_stats WHERE n >= 15"
    ).fetchone()
    con.close()

    вышло = {}
    for карточка, ключ in СООТВЕТСТВИЕ.items():
        if ключ and ключ in сырое:
            вышло[карточка] = dict(сырое[ключ], ключ=ключ)
    if not вышло:
        print("ни одного паттерна не сопоставилось — файл не тронут")
        return 1

    ВЫХОД.parent.mkdir(parents=True, exist_ok=True)
    ВЫХОД.write_text(json.dumps({
        "собрано": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "источник": "pattern_stats_job · SBFAcademy_bot/bot.db",
        "история_с": окно[0], "посчитано": окно[1],
        "что_значит_доля": "доля случаев, когда через 5 баров цена ушла в "
                           "сторону, которую обещает паттерн. 0.5 — монетка.",
        "паттерны": вышло,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"сопоставлено {len(вышло)} из {len(СООТВЕТСТВИЕ)} карточек → "
          f"{ВЫХОД.relative_to(КОРЕНЬ)}")
    for к, з in sorted(вышло.items(), key=lambda x: -x[1]["наблюдений"]):
        print(f"   {к:16} {з['наблюдений']:>7} набл.  доля {з['доля_5']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
