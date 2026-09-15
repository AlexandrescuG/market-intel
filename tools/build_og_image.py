#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_og_image.py — картинка превью ссылки (og:image).

🔴 ЗАЧЕМ. В шапке главной страницы стоит
<meta property="og:image" content="https://lp.sbfconsult.com/assets/og-image.png">,
а файла с таким именем в web/assets никогда не было: запрос отдаёт 404.
Мета-тег при этом валиден, страница проходит любую проверку разметки, в
консоли чисто — картинку запрашивает не браузер, а мессенджер на своей
стороне, и его ошибку никто не видит.

Результат виден только там, куда мы сами не смотрим: ссылка на
lp.sbfconsult.com в Telegram, WhatsApp, Facebook и Slack разворачивается
без картинки. Это первое, что видит человек, которому ссылку переслали.

Картинка собирается из собственного логотипа (assets/logo-master.png) и
фирменных цветов design.css — ничего чужого. Размер 1200×630: соотношение
1.91:1, которого ждут все перечисленные площадки; меньше 600×315 они
показывают маленькой плашкой вместо большой карточки.

Запуск: python3 tools/build_og_image.py
Перезапускать только при смене логотипа или названия.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

КОРЕНЬ = Path(__file__).resolve().parents[1]
# 🔴 logo-master.png — 4000×4000, но БЕЗ альфы: фон у него белый, и на
# тёмной подложке логотип лёг белой плашкой (видно на первом же снимке).
# favicon-master.png тот же знак с прозрачностью, 1024×1024 — для 260 px
# запаса более чем достаточно.
ЛОГОТИП = КОРЕНЬ / "web" / "assets" / "favicon-master.png"
ВЫХОД = КОРЕНЬ / "web" / "assets" / "og-image.png"

Ш, В = 1200, 630
ФОН = (24, 24, 26)        # --ink-dark, тот же, что у шапки сайта
ЗОЛОТО = (201, 162, 39)   # --gold
СВЕТЛЫЙ = (251, 246, 239)  # --bg
ТУСКЛЫЙ = (138, 130, 117)

ШРИФТЫ = {
    "жирный": "/usr/share/fonts/julietaula-montserrat-fonts/Montserrat-Bold.otf",
    "обычный": "/usr/share/fonts/julietaula-montserrat-fonts/Montserrat-Regular.otf",
    "моно": "/usr/share/fonts/liberation-mono-fonts/LiberationMono-Regular.ttf",
}


def шрифт(имя: str, размер: int):
    путь = ШРИФТЫ.get(имя)
    if путь and Path(путь).exists():
        return ImageFont.truetype(путь, размер)
    # Запасной путь обязан быть заметен в выводе, а не молча подставить
    # другой шрифт: картинку потом печатают в соцсети, и «почему-то не тот
    # шрифт» разбирать будет некому.
    print(f"   ⚠ шрифт {имя} не найден ({путь}) — беру системный по умолчанию")
    return ImageFont.load_default(размер)


def main() -> int:
    if not ЛОГОТИП.exists():
        print(f"нет логотипа {ЛОГОТИП}")
        return 1

    холст = Image.new("RGB", (Ш, В), ФОН)
    рисунок = ImageDraw.Draw(холст)

    # Тонкая золотая линия сверху — как у шапки сайта.
    рисунок.rectangle([0, 0, Ш, 6], fill=ЗОЛОТО)

    лого = Image.open(ЛОГОТИП).convert("RGBA")
    сторона = 260
    лого.thumbnail((сторона, сторона), Image.LANCZOS)
    x_лого, y_лого = 90, (В - лого.height) // 2 - 20
    холст.paste(лого, (x_лого, y_лого), лого)

    x = x_лого + лого.width + 60
    рисунок.text((x, 214), "SBF INTELLIGENCE", font=шрифт("жирный", 58), fill=СВЕТЛЫЙ)
    рисунок.text((x, 292), "рыночная разведка", font=шрифт("обычный", 30), fill=ЗОЛОТО)
    рисунок.text((x, 344), "Котировки, графики и курс из 15 глав —",
                 font=шрифт("обычный", 24), fill=ТУСКЛЫЙ)
    рисунок.text((x, 380), "на реальных данных, без обещаний доходности",
                 font=шрифт("обычный", 24), fill=ТУСКЛЫЙ)
    рисунок.text((x, 446), "sbfconsult.com", font=шрифт("моно", 26), fill=СВЕТЛЫЙ)

    ВЫХОД.parent.mkdir(parents=True, exist_ok=True)
    холст.save(ВЫХОД, "PNG", optimize=True)
    кб = ВЫХОД.stat().st_size // 1024
    print(f"собрано: {ВЫХОД.relative_to(КОРЕНЬ)} — {Ш}×{В}, {кб} КБ")
    if кб > 300:
        print("   ⚠ больше 300 КБ: часть площадок обрезает превью по весу")
    return 0


if __name__ == "__main__":
    sys.exit(main())
