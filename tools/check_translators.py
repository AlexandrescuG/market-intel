#!/usr/bin/env python3
"""tools/check_translators.py — кто из переводчиков жив и сколько квоты съел.

ЗАЧЕМ. Цепочка из пяти служб молчалива по устройству: пока хоть одна
отвечает, наружу всё выглядит одинаково. Узнать, что DeepL кончился ещё
десятого числа и месяц мы переводили самым слабым звеном, иначе неоткуда.

Щуп делает ровно две вещи: шлёт каждому КОРОТКИЙ контрольный текст с
числами и печатает расход за месяц. Текст с числами — не случайность:
30.09.2026 MyMemory вернул чужой перевод вместо запрошенного, и поймал
это только контроль по цифрам (core/news_i18n.числа_совпадают).

🔴 Щуп ТРАТИТ КВОТУ, пусть и копейки: 46 знаков на службу. Не ставить в
cron — это ручная проверка.

Запуск:
    .venv/bin/python tools/check_translators.py
    .venv/bin/python tools/check_translators.py --только-учёт   # без запросов
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(КОРЕНЬ))

from core import news_i18n, translator_quota  # noqa: E402
from core.config import DB_PATH  # noqa: E402

# Контрольный текст: есть числа (проверяется сохранность) и есть смысл
# (видно глазами, что перевод настоящий, а не кусок чужого запроса).
ПРОБА = "Золото 4 179,46 выросло на 0,13% за день"


def _загрузить_env() -> None:
    """Ключи лежат в .env; отдельной зависимости ради трёх строк не берём."""
    п = КОРЕНЬ / ".env"
    if not п.exists():
        return
    for строка in п.read_text(encoding="utf-8", errors="replace").splitlines():
        строка = строка.strip()
        if not строка or строка.startswith("#") or "=" not in строка:
            continue
        имя, _, значение = строка.partition("=")
        os.environ.setdefault(имя.strip(), значение.strip())


def проверить_живость() -> None:
    print(f"Контрольный текст: {ПРОБА!r}\n")
    for имя, fn in news_i18n._ПЕРЕВОДЧИКИ:
        перем = news_i18n._КЛЮЧ.get(имя)
        if перем and not os.environ.get(перем, "").strip():
            print(f"  {имя:14s} ключа нет ({перем}) — пропускается")
            continue
        t0 = time.time()
        try:
            ответ = fn([ПРОБА], "en")
        except news_i18n.ИсчерпанаКвота as e:
            print(f"  {имя:14s} 🔴 КВОТА ИСЧЕРПАНА: {str(e)[:70]}")
            continue
        except Exception as e:                  # noqa: BLE001
            print(f"  {имя:14s} ✗ {type(e).__name__}: {str(e)[:70]}")
            continue
        dt = time.time() - t0
        текст = (ответ or [""])[0]
        if not текст:
            print(f"  {имя:14s} ✗ пустой ответ за {dt:.2f} с")
        elif not news_i18n.числа_совпадают(ПРОБА, текст):
            print(f"  {имя:14s} 🔴 ЧИСЛА НЕ СОВПАЛИ за {dt:.2f} с: {текст[:60]}")
        else:
            print(f"  {имя:14s} ✓ {dt:.2f} с  {текст[:66]}")


def показать_учёт() -> None:
    con = sqlite3.connect(str(DB_PATH), timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    translator_quota.ensure_schema(con)
    print("\nРасход за текущий месяц:")
    for имя, потрачено, бюджет, исчерпан in translator_quota.сводка(con):
        if бюджет is None:
            print(f"  {имя:14s} {потрачено:>9,} знаков  (бюджет не в знаках)")
            continue
        доля = 100 * потрачено / бюджет if бюджет else 0
        метка = " 🔴 ИСЧЕРПАН" if исчерпан else ""
        print(f"  {имя:14s} {потрачено:>9,} из {бюджет:>9,}  {доля:5.1f}%{метка}")
    con.close()


def main() -> int:
    р = argparse.ArgumentParser()
    р.add_argument("--только-учёт", action="store_true",
                   help="не ходить в службы, показать только расход")
    а = р.parse_args()
    _загрузить_env()
    if not а.только_учёт:
        проверить_живость()
    показать_учёт()
    return 0


if __name__ == "__main__":
    sys.exit(main())
