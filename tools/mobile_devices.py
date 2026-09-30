"""Проверка страниц на ЭМУЛЯЦИИ УСТРОЙСТВ, а не на узком окне.

🔴 ЧЕМ УЗКОЕ ОКНО ОТЛИЧАЕТСЯ ОТ ТЕЛЕФОНА — по пунктам, потому что разница
не очевидна и я сам на ней ошибся.

Сужение вьюпорта задаёт ровно одно: ширину. Телефон отличается ещё и:

  • user-agent — сайты и скрипты ветвятся по нему (и наш sbf-header.js тоже);
  • device_scale_factor — плотность пикселей, от неё зависит, как ложатся
    тонкие линии и рамки в 1px и как выглядят растровые картинки;
  • is_mobile — включает в Blink мобильный вьюпорт: работает <meta viewport>,
    вступает в силу text autosizing, иначе считающийся выключенным;
  • has_touch — включает события касания; интерфейсы, у которых поведение
    висит на hover, на этом и ломаются;
  • высота вьюпорта — у телефона она заметно меньше, и всё, что считает
    100vh или «первый экран», ведёт себя иначе.

У Playwright для этого есть готовый реестр: 143 устройства с уже
выверенными параметрами. Пользоваться надо им, а не своим
`viewport={"width": 390}` — это ровно та ошибка «уменьшил окно и решил, что
проверил мобильный вид», с которой начался этот файл.

🔴 ЧЕСТНЫЙ РЕЗУЛЬТАТ ПЕРВОГО ЖЕ СРАВНЕНИЯ, И ОН НЕ ТОТ, КОТОРОГО ЖДАЛИ.
Замер главы 2 на всех устройствах набора дал РОВНО ТЕ ЖЕ ЧИСЛА, что и узкое
окно той же ширины: Galaxy S8 (360) — перелёт 34 px, узкое окно 360 — те же
34 px. Для дефектов ширины (сетка не свернулась, ряд карточек не влез)
эмуляция не добавляет ничего: значение имеет только ширина.

Из этого не следует, что эмуляция не нужна. Из этого следует, где она
нужна: user-agent, касания вместо hover, высота вьюпорта и dpr — там, где
ветвится поведение, а не раскладка. Для раскладки правильный вывод другой:
проверять на 320/360/393/430, а не на одной «мобильной» ширине.

🔴 ЧЕГО ЭМУЛЯЦИЯ НЕ ДАЁТ ВООБЩЕ. Настройку размера шрифта в браузере
читателя. Здесь был ключ --шрифт через CDP Page.setFontSizes — он не
работал: эта ручка задаёт размер ПО УМОЛЧАНИЮ, то есть влияет только на
страницы без явных размеров, а у нас в CSS всюду проставлены px. Первый же
прогон показал те же 34 px и тот же 16px в замере — ключ убран, чтобы не
изображать проверку, которой нет. Настройку шрифта проверяют на живом
телефоне: tools/mobile_real_device.py (adb).

Запуск:
  python3 tools/mobile_devices.py --список
  python3 tools/mobile_devices.py "Pixel 5" --глава 2
  python3 tools/mobile_devices.py --сравнить --глава 2
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SRC = Path("/tmp/sbf_audit_chapters")
СНИМКИ = Path("/tmp/sbf_mobile")

# Что реально стоит у читателей: узкий Android, обычный Android, iPhone.
НАБОР = ["Galaxy S8", "Pixel 5", "iPhone 14", "iPhone SE"]

ЗАМЕР = """(ширина) => {
  const прокрутки = [...document.querySelectorAll('*')].filter(el => {
    const s = getComputedStyle(el);
    return s.overflowX === 'auto' || s.overflowX === 'scroll';
  });
  const кандидаты = [];
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || s.position === 'fixed') continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (Math.round(r.right - ширина) <= 1) continue;
    if (прокрутки.some(p => p !== el && p.contains(el))) continue;
    кандидаты.push(el);
  }
  const набор = new Set(кандидаты);
  const итог = [];
  for (const el of кандидаты) {
    let p = el.parentElement, вложен = false;
    while (p) { if (набор.has(p)) { вложен = true; break; } p = p.parentElement; }
    if (вложен) continue;
    const r = el.getBoundingClientRect();
    итог.push({
      перелёт: Math.round(r.right - ширина),
      ширина: Math.round(r.width),
      текст: (el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 58),
    });
  }
  итог.sort((a, b) => b.перелёт - a.перелёт);
  return {
    шире_на: Math.round(document.documentElement.scrollWidth - ширина),
    виновников: итог.length,
    верх: итог.slice(0, 6),
    // Размер основного текста: по нему видно, сработал ли text autosizing
    // и наш ли это шрифт или подменённый.
    шрифт_абзаца: (() => {
      const p = document.querySelector('#sbf-book-root p');
      return p ? getComputedStyle(p).fontSize : '—';
    })(),
  };
}"""


def прогон(pw, устройство: dict | None, имя: str, глава: int,
           снимок: bool = False) -> dict:
    html = (SRC / f"ch{глава}.html").read_text(encoding="utf-8")
    опции = dict(устройство) if устройство else {
        "viewport": {"width": 390, "height": 844}}
    ctx = pw.chromium.launch().new_context(**опции)
    pg = ctx.new_page()

    def отдать(route, _html=html):
        route.fulfill(status=200, content_type="text/html; charset=utf-8", body=_html)

    pg.route(re.compile(r"/edu/b/\d+$"), lambda route: отдать(route))
    pg.goto(f"http://127.0.0.1:8085/edu/b/{глава}", wait_until="load", timeout=60000)
    pg.wait_for_timeout(4500)
    ширина = pg.evaluate("() => window.innerWidth")
    d = pg.evaluate(ЗАМЕР, ширина)
    d["устройство"] = имя
    d["ширина_css"] = ширина
    if снимок:
        СНИМКИ.mkdir(parents=True, exist_ok=True)
        путь = СНИМКИ / f"ch{глава}_{имя.replace(' ', '_')}.png"
        pg.screenshot(path=str(путь), full_page=False)
        d["снимок"] = str(путь)
    ctx.browser.close()
    return d


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("устройство", nargs="?", default="Pixel 5")
    ap.add_argument("--глава", type=int, default=2)
    ap.add_argument("--список", action="store_true")
    ap.add_argument("--сравнить", action="store_true",
                    help="узкое окно против набора настоящих устройств")
    ap.add_argument("--снимок", action="store_true")
    a = ap.parse_args()

    with sync_playwright() as pw:
        if a.список:
            for имя in sorted(pw.devices):
                d = pw.devices[имя]
                print(f"  {имя:28} {d['viewport']['width']:4}x{d['viewport']['height']:<4} "
                      f"dpr={d['device_scale_factor']}")
            return

        прогоны = []
        if a.сравнить:
            прогоны.append(прогон(pw, None, "узкое окно 390", a.глава, a.снимок))
            for имя in НАБОР:
                if имя in pw.devices:
                    прогоны.append(прогон(pw, pw.devices[имя], имя, a.глава, a.снимок))
        else:
            уст = pw.devices.get(a.устройство)
            if уст is None:
                print(f"нет такого устройства: {a.устройство} (см. --список)")
                sys.exit(1)
            прогоны.append(прогон(pw, уст, a.устройство, a.глава, a.снимок))

    print(f"глава {a.глава}\n")
    print(f"{'устройство':24} {'ширина':>7} {'шрифт':>7} {'шире на':>8} {'виновников':>11}")
    for d in прогоны:
        print(f"{d['устройство']:24} {d['ширина_css']:7} {d['шрифт_абзаца']:>7} "
              f"{d['шире_на']:8} {d['виновников']:11}")
    print()
    for d in прогоны:
        if not d["верх"]:
            continue
        print(f"── {d['устройство']} " + "─" * 40)
        for v in d["верх"]:
            print(f"   +{v['перелёт']:4d} px  ширина {v['ширина']:4d}  «{v['текст']}»")
        if d.get("снимок"):
            print(f"   снимок: {d['снимок']}")
        print()


if __name__ == "__main__":
    main()
