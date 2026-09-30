#!/usr/bin/env python3
"""Разовая правка: статичный «АНТИ-МИФ» → общий интерактивный компонент.

Замер 10.09.2026: рубрика «АНТИ-МИФ» стоит в начале самого длинного куска
текста без единого действия в шести главах из десяти. В главе 5 та же рубрика
интерактивна, в 6-14 её скопировали как три-четыре подряд идущих <p>.

Скрипт заменяет в главах 6-14 связку «подпись + карточка с абзацами» на
<AntiMythBlock/> из academy-shared.js и дописывает имя в разбор
window.AcademyShared.

🔴 Совпадение проверяется строго. Если разметка главы отличается от ожидаемой
хоть на символ — глава пропускается с сообщением, а не правится «примерно».
Молча испортить девять файлов проще, чем потом понять, который из них сломан.
Скрипт идемпотентен: уже переведённые главы пропускаются.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BOOK = Path(__file__).resolve().parent.parent / "web" / "book"
ГЛАВЫ = range(6, 15)

# Подпись рубрики и карточка с абзацами — ровно то, что заменяем.
RE_БЛОК = re.compile(
    r"[ \t]*<Mono size=\{11\} color=\{C\.gold\} spacing=\{3\} "
    # Имя объекта с текстами в главах разное: T6…T11 против просто T в 12-14.
    r"style=\{\{display:\"block\",marginBottom:10\}\}>\{(?P<t>T\d*)\.antiMyth\.tag\}</Mono>\n"
    r"[ \t]*<div style=\{\{background:C\.surface,border:`1px solid \$\{C\.border\}`,"
    r"borderRadius:8,padding:\"22px 26px\"(?P<хвост>[^}]*)\}\}>\n"
    r"(?P<нутро>(?:[ \t]*<p [^\n]*\n)+)"
    r"[ \t]*</div>\n")

RE_ОТСТУП = re.compile(r"marginBottom:(\d+)")
RE_ТЕЛО = re.compile(r"\{(?P<выражение>[^}]*?T\d*\.antiMyth\.body\d?[^}]*?)\}</p>")


def перевести(ch: int) -> str:
    путь = BOOK / f"edu_book_{ch}.html"
    src = путь.read_text(encoding="utf-8")
    if "<AntiMythBlock" in src:
        return f"глава {ch}: уже переведена, пропуск"

    m = RE_БЛОК.search(src)
    if not m:
        return f"глава {ch}: РАЗМЕТКА НЕ СОВПАЛА — не трогаю"

    тела = RE_ТЕЛО.findall(m.group("нутро"))
    if not тела:
        return f"глава {ch}: не нашёл абзацев внутри карточки — не трогаю"

    поля = RE_ОТСТУП.search(m.group("хвост") or "")
    стиль = "{{marginBottom:%s}}" % (поля.group(1) if поля else "28")

    # Абзацы могут быть не голыми полями, а выражениями (в главе 6 —
    # fillTemplate с живыми числами). Поэтому список собирается из тех же
    # выражений, что стояли в разметке, а не из имён полей.
    список = ", ".join(t.strip() for t in тела)
    отступ_строки = re.match(r"[ \t]*", m.group(0)).group(0)
    t = m.group("t")
    замена = (f"{отступ_строки}<AntiMythBlock lang={{INITIAL_LANG}} style={стиль}\n"
              f"{отступ_строки}  data={{{{tag: {t}.antiMyth.tag, "
              f"title: {t}.antiMyth.title, bodies: [{список}]}}}}/>\n")

    src = src[:m.start()] + замена + src[m.end():]

    # Имя компонента в разбор общего модуля.
    if "AntiMythBlock," not in src:
        src = src.replace("const {C, Mono, Chip, Rule,",
                          "const {C, Mono, Chip, Rule, AntiMythBlock,", 1)

    путь.write_text(src, encoding="utf-8")
    return f"глава {ch}: переведена, абзацев {len(тела)}"


def main() -> int:
    плохих = 0
    for ch in ГЛАВЫ:
        итог = перевести(ch)
        print(" ", итог)
        if "НЕ" in итог:
            плохих += 1
    return 1 if плохих else 0


if __name__ == "__main__":
    sys.exit(main())
