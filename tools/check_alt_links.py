#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_alt_links.py — живая проверка canonical и hreflang на всех страницах.

🔴 ЗАЧЕМ. Теги вставляются в двух разных местах: в шаблонах через
{{ alt_links(...) }} и в serve.py для глав курса (у книги свой конвейер
с Babel, Jinja её не рендерит). Два места — два способа промахнуться, и
ни один не виден глазами: страница выглядит нормально и с канониклом, и
без него.

🔴 Отдельно проверяется, что страница вообще жива. Я уже ронял главную
в 500, вписав {{ }} внутрь JS-комментария: Jinja разбирает шаблон целиком
и не знает, что это комментарий. Поэтому здесь не только теги, но и
статус со счётчиком текста — «страница есть» и «страница пустая»
различаются только замером.

Список адресов берётся из build_sitemap.py: карта сайта и разметка
головы обязаны говорить об одних и тех же страницах.

Запуск:
    python3 tools/check_alt_links.py
    python3 tools/check_alt_links.py --база http://127.0.0.1:8085
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_sitemap import ДОМЕН, ЯЗЫКИ, собрать  # noqa: E402

БАЗА = "http://127.0.0.1:8085"

ЩУП = """() => {
  const кан = [...document.querySelectorAll('link[rel="canonical"]')]
      .map(э => э.getAttribute('href'));
  const альт = [...document.querySelectorAll('link[rel="alternate"][hreflang]')]
      .map(э => [э.getAttribute('hreflang'), э.getAttribute('href')]);
  return {кан, альт, текст: (document.body ? document.body.innerText : '').length};
}"""


def проверить_страницу(стр, база: str, путь: str, язык: str,
                       группа: list[tuple[str, str]]) -> list[str]:
    беды: list[str] = []
    try:
        о = стр.goto(база + путь, wait_until="domcontentloaded", timeout=25000)
    except Exception as e:
        return [f"не открылась: {type(e).__name__}"]
    статус = о.status if о else 0
    if статус != 200:
        return [f"статус {статус}"]

    д = стр.evaluate(ЩУП)
    if len(д["кан"]) != 1:
        беды.append(f"canonical: {len(д['кан'])} шт. вместо одного")
    else:
        ждём = ДОМЕН + путь
        if д["кан"][0] != ждём:
            беды.append(f"canonical указывает на {д['кан'][0]}, а страница — {ждём}")

    альт = dict(д["альт"])
    for я, п in группа:
        if альт.get(я) != ДОМЕН + п:
            беды.append(f"hreflang={я}: {альт.get(я)!r}, ждали {ДОМЕН + п}")
    if "x-default" not in альт:
        беды.append("нет x-default")

    # Текста меньше сотни знаков — это либо пустой шаблон, либо страница
    # упала уже после ответа 200. Порог низкий намеренно: он ловит
    # катастрофу, а не бедность содержимого.
    if д["текст"] < 100:
        беды.append(f"текста всего {д['текст']} знаков")
    return беды


def main() -> int:
    р = argparse.ArgumentParser()
    р.add_argument("--база", default=БАЗА)
    а = р.parse_args()

    группы = собрать()
    всего = сломано = 0
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        бр = pw.chromium.launch()
        стр = бр.new_page()
        for группа in группы:
            for язык, путь in группа:
                всего += 1
                беды = проверить_страницу(стр, а.база, путь, язык, группа)
                if беды:
                    сломано += 1
                    print(f"✗ {путь}")
                    for б in беды:
                        print(f"    {б}")
        бр.close()

    print(f"\nстраниц проверено: {всего} ({len(группы)} материалов × {len(ЯЗЫКИ)})")
    print(f"с бедой: {сломано}")
    return 1 if сломано else 0


if __name__ == "__main__":
    sys.exit(main())
