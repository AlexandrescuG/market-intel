#!/usr/bin/env python3
"""Разовая правка: стрелка «назад» в шапке главы — из span в ссылку.

Замер доступности по всем пятнадцати главам (tools/audit_edu_a11y.py) нашёл
150 элементов, которые ведут себя как управление, но управлением не являются.
Стрелка «← предыдущая глава» есть в каждой главе и относится к худшему их
роду: это НАВИГАЦИЯ. С клавиатуры до неё не добраться, экранный диктор читает
её как символ «←», и в списке ссылок страницы её нет вовсе.

Заменяется на <a href>, а не на кнопку: это переход по адресу, и ссылка даёт
бесплатно открытие в новой вкладке, копирование адреса и правильную роль.

🔴 Совпадение проверяется строго; при отличии — глава пропускается.
Идемпотентно.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BOOK = Path(__file__).resolve().parent.parent / "web" / "book"

RE_СТРЕЛКА = re.compile(
    r"<span onClick=\{\(\) => window\.location\.href = getChUrl\((?P<ch>\d+), lang\)\} "
    r"style=\{\{color:C\.gold,cursor:\"pointer\",(?P<хвост>[^}]*)\}\}>(?P<знак>[←→])</span>")


def перевести(путь: Path) -> str:
    src = путь.read_text(encoding="utf-8")
    if "aria-label={lang===" in src:
        return f"{путь.name}: уже переведена"

    # Подпись берётся из lang, а не из STRINGS: переменная lang в этом месте
    # точно в области видимости (её тут же передают в getChUrl), а ключа в
    # STRINGS ни в одной главе нет и добавлять его в сорок пять мест ради
    # одной подписи — лишняя работа с лишним риском.
    def подпись(знак: str) -> str:
        если_назад = знак == "←"
        ru = "Предыдущая глава" if если_назад else "Следующая глава"
        ro = "Capitolul anterior" if если_назад else "Capitolul următor"
        en = "Previous chapter" if если_назад else "Next chapter"
        return (f'{{lang==="ru"?"{ru}":lang==="ro"?"{ro}":"{en}"}}')

    новый, n = RE_СТРЕЛКА.subn(
        lambda m: (
            f'<a href={{getChUrl({m.group("ch")}, lang)}} '
            f'aria-label={подпись(m.group("знак"))} '
            f'style={{{{color:C.gold,cursor:"pointer",textDecoration:"none",'
            f'{m.group("хвост")}}}}}>{m.group("знак")}</a>'),
        src)
    if not n:
        return f"{путь.name}: стрелка не найдена — не трогаю"
    путь.write_text(новый, encoding="utf-8")
    return f"{путь.name}: заменено стрелок {n}"


def main() -> int:
    плохих = 0
    for ch in range(1, 16):
        p = BOOK / f"edu_book_{ch}.html"
        if not p.exists():
            continue
        итог = перевести(p)
        print(" ", итог)
        if "не трогаю" in итог:
            плохих += 1
    return 0 if плохих <= 1 else 1


if __name__ == "__main__":
    sys.exit(main())
