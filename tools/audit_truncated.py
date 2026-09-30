#!/usr/bin/env python3
"""Подписи, обрезанные до неузнаваемости, — поимённо.

🔴 ЗАЧЕМ ОТДЕЛЬНАЯ ПРОВЕРКА. Обрезка многоточием не ломает ни ширину, ни
консоль, ни сеть: страница «здорова» по всем прежним замерам. Но чип с
подписью «Зона вни…» — это не чип, а угадайка, и увидеть это можно только
глазами либо вот такой проверкой. Найдено на снимке с живого телефона
14.09.2026: четыре чипа подряд в дневнике, каждый обрезан на середине слова.

ЧТО СЧИТАЕМ. Элемент с `text-overflow: ellipsis` (или `-webkit-line-clamp`),
у которого содержимое действительно не влезает: scrollWidth > clientWidth.
Плюс доля потерянного текста — по ней видно разницу между «обрезано одно
слово из десяти» и «от подписи осталась половина слова».

🔴 ЧЕГО НЕ СЧИТАЕМ. Обрезку в один-два пикселя (округления) и элементы, где
полный текст продублирован в title/aria-label: там подпись дочитываема, пусть
и не глазами. Без этих отсевов список наполнится шумом, а в шуме утонет
случай, ради которого проверка и написана.

Запуск: python3 tools/audit_truncated.py [ширина] [страница ...]
"""
from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

СТРАНИЦЫ = ["/", "/journal", "/chart.html", "/grafik", "/brokers",
            "/brokers/xm", "/edu/", "/edu/calendar", "/glossary",
            "/edu/b/2", "/edu/b/5"]

JS = r"""() => {
  const вышло = [];
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden') continue;
    const многоточие = s.textOverflow === 'ellipsis'
      || (s.webkitLineClamp && s.webkitLineClamp !== 'none');
    if (!многоточие) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) continue;
    const срез = el.scrollWidth - el.clientWidth;
    if (срез <= 2) continue;                 // округления — не обрезка
    // Полный текст доступен другим способом — подпись дочитываема.
    const полный = (el.textContent || '').replace(/\s+/g, ' ').trim();
    const подсказка = el.getAttribute('title') || el.getAttribute('aria-label') || '';
    if (подсказка && подсказка.replace(/\s+/g, ' ').trim() === полный) continue;
    if (!полный) continue;
    вышло.push({
      текст: полный.slice(0, 50),
      видно_долей: +(el.clientWidth / el.scrollWidth).toFixed(2),
      срез_px: Math.round(срез),
      ширина: Math.round(r.width),
      что: el.tagName.toLowerCase() + '.'
           + (el.className || '').toString().trim().split(/\s+/).slice(0, 2).join('.'),
    });
  }
  вышло.sort((a, b) => a.видно_долей - b.видно_долей);
  return JSON.stringify({всего: вышло.length, худшие: вышло.slice(0, 8)});
}"""


def main() -> None:
    ширина = int(sys.argv[1]) if len(sys.argv) > 1 else 393
    страницы = sys.argv[2:] or СТРАНИЦЫ
    итог = 0
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": ширина, "height": 735},
                            is_mobile=True, has_touch=True, device_scale_factor=2)
        pg = ctx.new_page()
        print(f"ширина экрана {ширина} px\n")
        for стр in страницы:
            pg.goto(f"http://127.0.0.1:8085{стр}", wait_until="load", timeout=90000)
            pg.wait_for_timeout(6000)
            d = json.loads(pg.evaluate(JS))
            итог += d["всего"]
            метка = "" if not d["всего"] else f"  ← {d['всего']}"
            print(f"{стр:16} обрезано: {d['всего']}{метка}")
            for x in d["худшие"]:
                print(f"     видно {x['видно_долей']:.0%}  срез {x['срез_px']:4d} px"
                      f"  {x['что'][:28]:28} «{x['текст']}»")
        b.close()
    print(f"\nвсего обрезанных подписей: {итог}")


if __name__ == "__main__":
    main()
