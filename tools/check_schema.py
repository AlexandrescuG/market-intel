#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_schema.py — живая проверка разметки schema.org на всех страницах.

🔴 ЗАЧЕМ ИМЕННО ЖИВАЯ. Разметка — это JSON внутри HTML внутри шаблона.
Сломать её можно тремя способами сразу: невалидный JSON (краулер молча
выбрасывает весь блок), ссылка на @id, которого нигде нет (связь есть
только на бумаге), и адрес, отличающийся от canonical на слэш (для машины
это другая страница). Ни один из трёх не виден глазами: страница
выглядит одинаково.

Проверяется:
  • JSON разбирается, есть @context;
  • у каждого типа — обязательные для него поля;
  • все ссылки {"@id": …} либо описаны на этой же странице, либо ведут на
    существующий адрес сайта (курс ссылается на главы, главы — на курс:
    это законная связь между страницами, но опечатка в ней тоже законно
    выглядит и молча рвёт граф);
  • url и @id ведут на адрес, совпадающий с canonical страницы;
  • обещание доступа: isAccessibleForFree:true только там, где текст
    действительно отдан анониму (проверяем по длине текстового слоя).

🔴 Запускать АНОНИМНО, без PRO-стенда (tools/edu_preview.py). Смысл
проверки — увидеть страницу глазами краулера, а у него сессии нет.
На стенде платные главы отдаются целиком, и проверка доступа честно
отругается на isAccessibleForFree:false — это будет ложная тревога.

Запуск:
    python3 tools/check_schema.py
    python3 tools/check_schema.py --база http://127.0.0.1:8085
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_sitemap import ДОМЕН, ЯЗЫКИ, адрес, собрать  # noqa: E402

БАЗА = "http://127.0.0.1:8085"
# Все адреса сайта во всех языках — тот же список, что уходит в карту
# сайта. Ссылка на @id за пределами этого множества — это ссылка в никуда.
АДРЕСА_САЙТА = {ДОМЕН + п for г in собрать() for _, п in г} | {ДОМЕН + "/"}

# Что обязано быть у каждого типа, который мы выпускаем.
ОБЯЗАТЕЛЬНО = {
    "Course":          ("name", "description", "url"),
    "LearningResource": ("name", "description", "url", "isAccessibleForFree"),
    "DefinedTermSet":  ("name", "url", "hasDefinedTerm"),
    "DefinedTerm":     ("name", "description", "url"),
    "HowTo":           ("name", "step"),
    "HowToStep":       ("text",),
    "BreadcrumbList":  ("itemListElement",),
    "ItemList":        ("itemListElement",),
}

ЩУП = """() => {
  const блоки = [...document.querySelectorAll('script[type="application/ld+json"]')]
      .map(э => э.textContent);
  const кан = document.querySelector('link[rel="canonical"]');
  const слой = document.querySelector('.sbf-text-layer');
  return {блоки, канонический: кан ? кан.getAttribute('href') : null,
          слой: слой ? slojDlina(слой) : 0};
  function slojDlina(э) { return (э.textContent || '').length; }
}"""


def узлы(о):
    """Все словари в дереве — разметка вложенная, проверять надо всё."""
    if isinstance(о, dict):
        yield о
        for з in о.values():
            yield from узлы(з)
    elif isinstance(о, list):
        for э in о:
            yield from узлы(э)


def проверить(данные: dict, страница: str) -> list[str]:
    беды: list[str] = []
    блоки = данные["блоки"]
    if not блоки:
        return ["разметки нет вовсе"]

    свои_id: set[str] = set()
    ссылки: list[str] = []
    разобранные = []
    for i, сырой in enumerate(блоки):
        try:
            разобранные.append(json.loads(сырой))
        except json.JSONDecodeError as e:
            беды.append(f"блок {i + 1}: JSON не разбирается — {e}")
    for корень in разобранные:
        if "@context" not in корень:
            беды.append("нет @context — краулер не поймёт словарь")
        for у in узлы(корень):
            ид = у.get("@id")
            # Узел объявляет себя, если у него есть @type; иначе это ссылка.
            if ид and у.get("@type"):
                свои_id.add(ид)
            elif ид:
                ссылки.append(ид)
            тип = у.get("@type")
            for поле in ОБЯЗАТЕЛЬНО.get(тип, ()):
                if поле not in у:
                    беды.append(f"{тип}: нет поля {поле}")

    for ид in ссылки:
        if ид in свои_id:
            continue
        # Ссылка на другую страницу сайта — законно (курс → главы,
        # глава → курс). Проверяем, что страница существует: граф
        # рвётся тихо, и опечатка в адресе выглядит так же, как связь.
        голый = ид.split("#")[0].rstrip("/")
        if голый in {а.rstrip("/") for а in АДРЕСА_САЙТА}:
            continue
        беды.append(f"ссылка на @id {ид} — ни узла на этой странице, "
                    f"ни такого адреса на сайте")

    кан = данные["канонический"]
    for корень in разобранные:
        for у in узлы(корень):
            url = у.get("url")
            if not isinstance(url, str) or not url.startswith("http"):
                continue
            голый = url.split("#")[0]
            if кан and голый != кан and у.get("@type") in ("Course", "LearningResource",
                                                           "DefinedTermSet"):
                беды.append(f"{у.get('@type')}.url = {url}, а canonical = {кан}")

    # Обещание доступа против того, что реально отдано.
    for корень in разобранные:
        for у in узлы(корень):
            if у.get("@type") != "LearningResource":
                continue
            обещано = у.get("isAccessibleForFree")
            есть_текст = данные["слой"] > 2000
            if обещано is True and not есть_текст:
                беды.append(f"isAccessibleForFree:true, а текста отдано "
                            f"{данные['слой']} знаков — обещание пустое")
            if обещано is False and есть_текст:
                беды.append("isAccessibleForFree:false, а текст главы отдан "
                            "целиком — платного доступа нет на деле")
    return беды


СТРАНИЦЫ = ["/", "/brokers", "/glossary", "/edu/", "/brokers/xm", "/brokers/naga",
            "/brokers/fxpro", "/brokers/instaforex", "/brokers/avatrade",
            *[f"/edu/b/{n}" for n in range(1, 16)]]


def main() -> int:
    р = argparse.ArgumentParser()
    р.add_argument("--база", default=БАЗА)
    а = р.parse_args()

    from playwright.sync_api import sync_playwright
    всего = сломано = узлов_всего = 0
    with sync_playwright() as pw:
        бр = pw.chromium.launch()
        стр = бр.new_page()
        for путь in СТРАНИЦЫ:
            for я in ЯЗЫКИ:
                п = адрес(путь, я)
                всего += 1
                try:
                    стр.goto(а.база + п, wait_until="domcontentloaded", timeout=25000)
                    д = стр.evaluate(ЩУП)
                except Exception as e:
                    print(f"✗ {п}\n    не открылась: {type(e).__name__}")
                    сломано += 1
                    continue
                узлов_всего += sum(
                    len(list(узлы(json.loads(б)))) for б in д["блоки"]
                    if б.strip().startswith("{"))
                беды = проверить(д, п)
                if беды:
                    сломано += 1
                    print(f"✗ {п}")
                    for б in беды[:6]:
                        print(f"    {б}")
        бр.close()

    print(f"\nстраниц проверено: {всего}, узлов разметки: {узлов_всего}")
    print(f"с бедой: {сломано}")
    return 1 if сломано else 0


if __name__ == "__main__":
    sys.exit(main())
