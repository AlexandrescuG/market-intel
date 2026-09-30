#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_guides_i18n.py — ru/en/ro инструкций по площадкам описывают одно и то же.

Структура web/data/guides/<id>[.lang].json у трёх языков одной площадки
обязана совпадать: те же processes в том же порядке, те же блоки, то же
число шагов и те же кадры под шагами. Разное число шагов значит, что один
язык отстал после пересъёмки. Текст en/ro, совпадающий с ru слово в слово
или написанный кириллицей, — не перевод, а копия.

Запуск:  python3 tools/check_guides_i18n.py        # отчёт, код 1 при расхождениях
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]
ПАПКА = КОРЕНЬ / "web" / "data" / "guides"
ЯЗЫКИ = ("en", "ro")
КИРИЛЛИЦА = re.compile(r"[А-Яа-яЁё]")
# Поля, которые обязаны совпадать у всех языков (факты, а не текст).
ФАКТЫ = ("img", "img_webp", "legal_name", "licence_no", "register_url", "confirmed")
# Поля, которые обязаны быть переведены.
ТЕКСТ = ("label", "lead", "caption", "note", "title", "body", "quote", "account_label",
         "platform", "confirm_note", "register_note")


def загрузить(площадка: str, язык: str | None) -> dict:
    имя = f"{площадка}.json" if язык is None else f"{площадка}.{язык}.json"
    return json.loads((ПАПКА / имя).read_text(encoding="utf-8"))


def текстовые_поля(o, путь=""):
    """(путь, значение) для всех строковых полей из ТЕКСТ, рекурсивно."""
    if isinstance(o, dict):
        for k, v in o.items():
            p = f"{путь}.{k}" if путь else k
            if k in ТЕКСТ and isinstance(v, str):
                yield p, v
            else:
                yield from текстовые_поля(v, p)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from текстовые_поля(v, f"{путь}[{i}]")


def сравнить(площадка: str) -> list[str]:
    ru = загрузить(площадка, None)
    проблемы: list[str] = []
    for яз in ЯЗЫКИ:
        try:
            пер = загрузить(площадка, яз)
        except FileNotFoundError:
            проблемы.append(f"{площадка}.{яз}: файла нет")
            continue
        pr, pp = ru.get("processes", []), пер.get("processes", [])
        if [p.get("key") for p in pr] != [p.get("key") for p in pp]:
            проблемы.append(f"{площадка}.{яз}: processes {[p.get('key') for p in pp]} "
                            f"≠ ru {[p.get('key') for p in pr]}")
        for i, (a, b) in enumerate(zip(pr, pp)):
            ключ = a.get("key")
            if a.get("captured") != b.get("captured"):
                проблемы.append(f"{площадка}.{яз} {ключ}: captured {b.get('captured')} ≠ ru {a.get('captured')}")
            if len(a.get("needed") or []) != len(b.get("needed") or []):
                проблемы.append(f"{площадка}.{яз} {ключ}: needed {len(b.get('needed') or [])} ≠ ru {len(a.get('needed') or [])}")
            ba, bb = a.get("blocks") or [], b.get("blocks") or []
            if [x.get("type") for x in ba] != [x.get("type") for x in bb]:
                проблемы.append(f"{площадка}.{яз} {ключ}: блоки {[x.get('type') for x in bb]} "
                                f"≠ ru {[x.get('type') for x in ba]}")
                continue
            for j, (x, y) in enumerate(zip(ba, bb)):
                где = f"{площадка}.{яз} {ключ} блок {j} ({x.get('type')})"
                for поле in ("items", "rows", "missing"):
                    if isinstance(x.get(поле), list) and len(x[поле]) != len(y.get(поле) or []):
                        проблемы.append(f"{где}: {поле} {len(y.get(поле) or [])} ≠ ru {len(x[поле])}")
                for поле in ФАКТЫ:
                    if x.get(поле) != y.get(поле):
                        проблемы.append(f"{где}: {поле} «{y.get(поле)}» ≠ ru «{x.get(поле)}»")
                for k, (sx, sy) in enumerate(zip(x.get("items") or [], y.get("items") or [])):
                    if isinstance(sx, dict) and isinstance(sy, dict) and sx.get("img") != sy.get("img"):
                        проблемы.append(f"{где} шаг {k + 1}: кадр {sy.get('img')} ≠ ru {sx.get('img')}")
        # Перевод, а не копия ru: кириллицы в en/ro быть не должно.
        # Исключение — дословная цитата («quote») с русской версии сайта
        # брокера: её помечаем отдельно, решает владелец.
        for путь, значение in текстовые_поля(пер):
            if КИРИЛЛИЦА.search(значение):
                вид = "цитата на русском" if путь.endswith(".quote") else "кириллица"
                проблемы.append(f"{площадка}.{яз} {путь}: {вид} — «{значение[:70]}»")
    # ro не должен быть копией en (длинные строки, совпадающие слово в слово).
    try:
        en = dict(текстовые_поля(загрузить(площадка, "en")))
        for путь, значение in текстовые_поля(загрузить(площадка, "ro")):
            if len(значение) > 30 and en.get(путь) == значение:
                проблемы.append(f"{площадка}.ro {путь}: совпадает с en — «{значение[:70]}»")
    except FileNotFoundError:
        pass
    return проблемы


def main() -> int:
    площадки = sorted(p.stem for p in ПАПКА.glob("*.json") if p.stem.count(".") == 0)
    всего = 0
    for п in площадки:
        пр = сравнить(п)
        всего += len(пр)
        print(f"{'✓' if not пр else '✗'} {п}: {len(пр)} расхождений")
        for строка in пр:
            print(f"   {строка}")
    return 1 if всего else 0


if __name__ == "__main__":
    sys.exit(main())
