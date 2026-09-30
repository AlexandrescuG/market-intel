#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_sitemap.py — карта сайта по реальным маршрутам и трём языкам.

🔴 ЗАЧЕМ. В web/sitemap.xml лежало ДВА адреса: «/» и «/edu/b». Всё
остальное — пятнадцать глав курса в трёх языках, глоссарий, брокеры,
календарь, страницы пяти площадок — краулер должен был найти сам, по
ссылкам, исполняя JavaScript. Он его не исполняет (см. tools/
build_text_layer.js), то есть по большинству страниц карта была
единственным способом узнать об их существовании — и она молчала.

Список строится из правил ниже, а не переписывается руками: карта,
которую правят отдельно от маршрутов, расходится с сайтом — и это
незаметно, потому что XML никто не читает глазами.

🔴 Каждый адрес проверяется живым запросом. Карта с битой ссылкой хуже
отсутствующей: она говорит краулеру «вот наши страницы» и отправляет
его в 404. Именно так выяснилось (Л-2), что /ro/edu/b не существует —
хотя ссылка на него стояла на живой странице.

Запуск:
    python3 tools/build_sitemap.py            # собрать и проверить
    python3 tools/build_sitemap.py --без-проверки
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]
ВЫХОД = КОРЕНЬ / "web" / "sitemap.xml"
ДОМЕН = "https://lp.sbfconsult.com"
БАЗА_ПРОВЕРКИ = "http://127.0.0.1:8085"
ЯЗЫКИ = ("ru", "ro", "en")

БРОКЕРЫ = ("xm", "naga", "fxpro", "instaforex", "avatrade")

# Публичные страницы: (путь без префикса локали, приоритет, частота).
# Служебное (/journal, /admin, /m, /survey, /login, /register) в карту не
# кладём: это личные кабинеты и формы, им в поиске делать нечего.

# Главы, открытые без регистрации. 6-15 доступны только после неё: аноним
# (и краулер) видит экран-заглушку с noindex — в карте ему делать нечего.
ОТКРЫТЫЕ_ГЛАВЫ = range(1, 6)
СТРАНИЦЫ: list[tuple[str, str, str]] = [
    ("/",            "1.0", "daily"),
    ("/brokers",     "0.9", "weekly"),
    ("/glossary",    "0.8", "monthly"),
    ("/calendar",    "0.7", "daily"),
    ("/chart.html",  "0.7", "daily"),
    ("/edu/",        "0.9", "weekly"),
    ("/privacy",     "0.3", "yearly"),
    *[(f"/brokers/{б}", "0.8", "monthly") for б in БРОКЕРЫ],
]


def адрес(путь: str, язык: str) -> str:
    """Путь в нужной локали. У курса локаль стоит ПОСЛЕ /edu."""
    if язык == "ru":
        return путь
    if путь.startswith("/edu/b"):
        return путь.replace("/edu/b", f"/edu/{язык}/b", 1)
    if путь == "/edu/":
        return f"/{язык}/edu/"
    return f"/{язык}{путь}"


def собрать() -> list[list[tuple[str, str]]]:
    """Группы «одна страница на трёх языках»: [[(язык, путь), ...], ...]."""
    группы = []
    for путь, _, _ in СТРАНИЦЫ:
        группы.append([(я, адрес(путь, я)) for я in ЯЗЫКИ])
    for n in ОТКРЫТЫЕ_ГЛАВЫ:
        группы.append([(я, адрес(f"/edu/b/{n}", я)) for я in ЯЗЫКИ])
    return группы


def свойства(путь: str) -> tuple[str, str]:
    for п, приоритет, частота in СТРАНИЦЫ:
        if путь == п:
            return приоритет, частота
    return "0.8", "weekly"     # главы курса


def проверить(пути: list[str]) -> dict[str, int]:
    """Живой прогон: какой статус реально отдаёт каждый адрес."""
    from playwright.sync_api import sync_playwright
    статусы: dict[str, int] = {}
    with sync_playwright() as pw:
        бр = pw.chromium.launch()
        стр = бр.new_page()
        for п in пути:
            try:
                о = стр.goto(БАЗА_ПРОВЕРКИ + п, wait_until="commit", timeout=20000)
                статусы[п] = о.status if о else 0
            except Exception:
                статусы[п] = 0
        бр.close()
    return статусы


def xml(группы: list[list[tuple[str, str]]]) -> str:
    сегодня = date.today().isoformat()
    строки = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
              '        xmlns:xhtml="http://www.w3.org/1999/xhtml">']
    for группа in группы:
        база = группа[0][1]
        приоритет, частота = свойства(база)
        for язык, путь in группа:
            строки.append("  <url>")
            строки.append(f"    <loc>{ДОМЕН}{путь}</loc>")
            # Альтернативы — внутри КАЖДОГО <url>, так требует стандарт:
            # страница должна сама перечислять все свои языковые версии,
            # включая себя. Без этого связь односторонняя и не засчитывается.
            for я2, п2 in группа:
                строки.append(f'    <xhtml:link rel="alternate" hreflang="{я2}" '
                              f'href="{ДОМЕН}{п2}"/>')
            строки.append(f'    <xhtml:link rel="alternate" hreflang="x-default" '
                          f'href="{ДОМЕН}{группа[0][1]}"/>')
            строки.append(f"    <lastmod>{сегодня}</lastmod>")
            строки.append(f"    <changefreq>{частота}</changefreq>")
            строки.append(f"    <priority>{приоритет}</priority>")
            строки.append("  </url>")
    строки.append("</urlset>")
    return "\n".join(строки) + "\n"


def main() -> int:
    р = argparse.ArgumentParser()
    р.add_argument("--без-проверки", action="store_true",
                   help="не ходить на сервер (карта соберётся как есть)")
    а = р.parse_args()

    группы = собрать()
    все_пути = [п for г in группы for _, п in г]
    print(f"страниц в карте: {len(все_пути)} "
          f"({len(группы)} материалов × {len(ЯЗЫКИ)} языка)")

    if not а.без_проверки:
        статусы = проверить(все_пути)
        битые = {п: с for п, с in статусы.items() if с != 200}
        if битые:
            print(f"\n✗ отдают не 200 ({len(битые)}):")
            for п, с in sorted(битые.items()):
                print(f"   {с}  {п}")
            print("\nКарта НЕ записана: битый адрес в карте хуже отсутствующего — "
                  "он обещает краулеру страницу и приводит в 404.")
            return 1
        print("все адреса отдают 200")

    ВЫХОД.write_text(xml(группы), encoding="utf-8")
    print(f"записано: {ВЫХОД.relative_to(КОРЕНЬ)} ({ВЫХОД.stat().st_size} байт)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
