#!/usr/bin/env python3
"""Скачанный оригинал → две веб-версии станции хроники.

🔴 ЗАЧЕМ. Станции хроники показывают пару «webp + jpg» шириной 900 px, а с
Wikimedia Commons приходит оригинал на 1245–2320 px и несколько мегабайт.
Раньше эту пересборку делали руками, и в chrono.js остались размеры,
которые никто не перепроверял: неверные width/height у <img> — это прыжок
вёрстки при загрузке, а его не видно на быстром канале.

Скрипт делает три вещи и ни одной лишней:
  1. собирает `<ключ>.webp` и `<ключ>_web.jpg` шириной не больше 900 px;
  2. НЕ растягивает то, что уже меньше 900 (снимок Бреттон-Вудса — 706 px,
     растянутый до 900 он станет мылом, но не станет подробнее);
  3. сверяет получившиеся размеры с записью в chrono.js и печатает, что
     именно надо поправить, — вместо того чтобы молча разойтись с кодом.

Оригиналы владелец кладёт в web/edu/assets/history/ под именем из
манифеста (поле filename). Запуск:

    python3 tools/prepare_history_images.py            # все, у кого есть файл
    python3 tools/prepare_history_images.py 1907_morgan
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from PIL import Image

КОРЕНЬ = Path(__file__).resolve().parents[1]
ПАПКА = КОРЕНЬ / "web" / "edu" / "assets" / "history"
МАНИФЕСТ = ПАПКА / "manifest.json"
CHRONO = КОРЕНЬ / "web" / "edu" / "assets" / "chrono.js"
ШИРИНА = 900


def размеры_из_кода() -> dict[str, tuple[int, int]]:
    """Что chrono.js обещает браузеру по каждой станции."""
    текст = CHRONO.read_text(encoding="utf-8")
    итог = {}
    for м in re.finditer(r'"([\w]+)":\s*\{[^}]*?w:(\d+),\s*h:(\d+)', текст, re.S):
        итог[м.group(1)] = (int(м.group(2)), int(м.group(3)))
    return итог


def поправить_код(ключ: str, ш: int, в: int) -> bool:
    """Переписать w:/h: у станции в chrono.js под то, что реально на диске.

    Нужен, потому что размер оригинала заранее не известен: с Commons легко
    скачать превью на 500 px вместо оригинала на 2320, и тогда записанные
    заранее 900×1127 — прыжок вёрстки. Правка точечная: меняются только два
    числа внутри записи этого ключа.
    """
    текст = CHRONO.read_text(encoding="utf-8")
    шаблон = re.compile(r'("' + re.escape(ключ) + r'":\s*\{.*?w:)(\d+)(,\s*h:)(\d+)', re.S)
    новый, сколько = шаблон.subn(lambda м: м.group(1) + str(ш) + м.group(3) + str(в), текст, count=1)
    if сколько:
        CHRONO.write_text(новый, encoding="utf-8")
    return bool(сколько)


def собрать(ключ: str, исходник: Path) -> tuple[int, int]:
    изо = Image.open(исходник)
    if изо.mode not in ("RGB", "L"):
        изо = изо.convert("RGB")
    ш, в = изо.size
    if ш > ШИРИНА:
        в = round(в * ШИРИНА / ш)
        ш = ШИРИНА
        изо = изо.resize((ш, в), Image.LANCZOS)
    изо.save(ПАПКА / f"{ключ}_web.jpg", "JPEG", quality=82, optimize=True,
             progressive=True)
    изо.save(ПАПКА / f"{ключ}.webp", "WEBP", quality=80, method=6)
    return ш, в


def main() -> None:
    записи = json.loads(МАНИФЕСТ.read_text(encoding="utf-8"))
    нужны = set(sys.argv[1:])
    чинить = "--fix" in нужны
    нужны.discard("--fix")
    обещано = размеры_из_кода()
    сделано = пропущено = расхождений = 0
    for r in записи:
        ключ = r["station"]
        if нужны and ключ not in нужны:
            continue
        исходник = ПАПКА / r["filename"]
        if not исходник.exists():
            print(f"  нет оригинала: {r['filename']:24} ({ключ})")
            пропущено += 1
            continue
        ш, в = собрать(ключ, исходник)
        кб = (ПАПКА / f"{ключ}_web.jpg").stat().st_size // 1024
        строка = f"  {ключ:16} {ш}×{в}  jpg {кб} КБ"
        если_в_коде = обещано.get(ключ)
        if если_в_коде and если_в_коде != (ш, в):
            if чинить and поправить_код(ключ, ш, в):
                строка += f"   chrono.js поправлен: было {если_в_коде[0]}×{если_в_коде[1]}"
            else:
                строка += (f"   ⚠ в chrono.js записано {если_в_коде[0]}×{если_в_коде[1]}"
                           " — поправить (или запустить с --fix)")
                расхождений += 1
        elif если_в_коде is None:
            строка += "   ⚠ в chrono.js нет записи STATION_IMAGE"
            расхождений += 1
        print(строка)
        сделано += 1
    print(f"\nсобрано: {сделано}, без оригинала: {пропущено}, расхождений с кодом: {расхождений}")
    if расхождений:
        sys.exit(1)


if __name__ == "__main__":
    main()
