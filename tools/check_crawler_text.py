#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_crawler_text.py — сколько текста страница отдаёт БЕЗ JavaScript.

🔴 ЗАЧЕМ. ИИ-краулеры (GPTBot, ClaudeBot, PerplexityBot) JavaScript не
исполняют. Сайт собирается React'ом и JS-виджетами, поэтому «страница
работает» и «страница что-то говорит машине» — разные утверждения, и
второе легко теряется молча: достаточно поправить рендер, и текстовый
слой перестанет попадать в разметку. Внешне не изменится ничего.

Замер 17.09.2026 до работ: /brokers/xm отдавал 20 знаков, /brokers —
686, /glossary — 63, /edu/b/3 — 514.

Порог у каждой страницы свой и стоит НИЖЕ достигнутого, но выше того,
что отдавала пустая страница: щуп ловит обвал, а не колебания живых
данных. Платные главы проверяются отдельным, низким порогом — анониму
там честно отдаётся пейволл, и требовать от него текста нельзя.

Запуск:
    python3 tools/check_crawler_text.py
    python3 tools/check_crawler_text.py --база http://127.0.0.1:8085
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_sitemap import БРОКЕРЫ, ЯЗЫКИ, адрес  # noqa: E402

БАЗА = "http://127.0.0.1:8085"
ПЕЙВОЛЛ = 120          # пейволл: заголовок, объяснение и кнопка

# путь → сколько знаков обязано быть без JS
ПОРОГИ: dict[str, int] = {
    "/": 800,
    "/brokers": 2500,
    "/glossary": 15000,
    "/edu/": 400,
    **{f"/brokers/{б}": 3000 for б in БРОКЕРЫ},
    **{f"/edu/b/{n}": 5000 for n in range(1, 6)},        # бесплатные главы
    **{f"/edu/b/{n}": ПЕЙВОЛЛ for n in range(6, 16)},    # платные: только пейволл
}


def main() -> int:
    р = argparse.ArgumentParser()
    р.add_argument("--база", default=БАЗА)
    р.add_argument("--подробно", action="store_true")
    а = р.parse_args()

    from playwright.sync_api import sync_playwright
    мало: list[tuple[str, int, int]] = []
    всего = 0
    сумма = 0
    with sync_playwright() as pw:
        бр = pw.chromium.launch()
        # 🔴 Ровно то, чем отличается краулер от человека.
        ктx = бр.new_context(java_script_enabled=False)
        стр = ктx.new_page()
        for путь, порог in ПОРОГИ.items():
            for я in ЯЗЫКИ:
                п = адрес(путь, я)
                всего += 1
                try:
                    стр.goto(а.база + п, wait_until="domcontentloaded", timeout=25000)
                    знаков = стр.evaluate(
                        "()=>(document.body?document.body.innerText:'').length")
                except Exception as e:
                    мало.append((п, -1, порог))
                    print(f"✗ {п}: не открылась ({type(e).__name__})")
                    continue
                сумма += знаков
                if знаков < порог:
                    мало.append((п, знаков, порог))
                    print(f"✗ {п}: {знаков} знаков при пороге {порог}")
                elif а.подробно:
                    print(f"  {п}: {знаков}")
        бр.close()

    print(f"\nстраниц проверено: {всего}, знаков без JS всего: {сумма}")
    print(f"ниже порога: {len(мало)}")
    return 1 if мало else 0


if __name__ == "__main__":
    sys.exit(main())
