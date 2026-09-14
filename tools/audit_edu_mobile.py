"""Что не влезает по ширине на телефоне — поимённо.

ЗАЧЕМ. На записи экрана видно, что текст в главах обрезан справа: «Три
центробанка тянут в разные сто…», карточка Bitcoin в симуляторе ФРС уходит за
край, колонка S&P 500 в матрице влияния режется на цифре. Глазами видно ЧТО,
но не видно КТО: какой именно элемент шире экрана.

🔴 СЧИТАЕМ ВИНОВНИКА, А НЕ ФАКТ. `document.scrollWidth > innerWidth` говорит
только «страница шире экрана» — это и так видно. Нужен элемент: обходим все
узлы, берём те, чей правый край выходит за вьюпорт, и отбрасываем тех, у кого
виноват родитель (если предок уже переполнен, потомок лишь следствие). Ещё
отбрасываем то, что внутри собственной горизонтальной прокрутки: таблица с
`overflow-x:auto` уезжает за край ПО ЗАМЫСЛУ, и записывать её в поломку —
значит утопить список настоящих виновников в шуме.

Запуск: python3 tools/audit_edu_mobile.py [ширина] [глава ...]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SRC = Path("/tmp/sbf_audit_chapters")

MEASURE = """(ширина) => {
  const вылезли = [];
  const прокрутки = [];        // предки со своим горизонтальным скроллом
  for (const el of document.querySelectorAll('*')) {
    const s = getComputedStyle(el);
    if (s.overflowX === 'auto' || s.overflowX === 'scroll') прокрутки.push(el);
  }
  const виноват = new Set();
  const кандидаты = [];
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden') continue;
    if (s.position === 'fixed') continue;          // шапка/панель живут поверх
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const перелёт = Math.round(r.right - ширина);
    if (перелёт <= 1) continue;
    // Внутри собственной прокрутки — это задумано.
    if (прокрутки.some(p => p !== el && p.contains(el))) continue;
    кандидаты.push({el, перелёт, r});
  }
  // Родитель важнее потомка: если предок уже в списке, потомок — следствие.
  const набор = new Set(кандидаты.map(k => k.el));
  for (const k of кандидаты) {
    let p = k.el.parentElement, есть = false;
    while (p) { if (набор.has(p)) { есть = true; break; } p = p.parentElement; }
    if (есть) continue;
    const путь = [];
    let n = k.el;
    for (let i = 0; i < 3 && n && n !== document.body; i++) {
      путь.unshift(n.tagName.toLowerCase()
        + (n.className && typeof n.className === 'string'
            ? '.' + n.className.trim().split(/\\s+/).slice(0,2).join('.') : ''));
      n = n.parentElement;
    }
    вылезли.push({
      перелёт: k.перелёт,
      ширина_элемента: Math.round(k.r.width),
      тег: k.el.tagName.toLowerCase(),
      путь: путь.join(' > '),
      текст: (k.el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 70),
    });
  }
  вылезли.sort((a, b) => b.перелёт - a.перелёт);
  return {
    страница_шире_на: Math.round(document.documentElement.scrollWidth - ширина),
    виновники: вылезли.slice(0, 12),
    всего_виновников: вылезли.length,
  };
}"""


def main() -> None:
    ширина = int(sys.argv[1]) if len(sys.argv) > 1 else 390
    главы = [int(x) for x in sys.argv[2:]] or list(range(1, 16))
    итог = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": ширина, "height": 844},
                            device_scale_factor=2, is_mobile=True,
                            has_touch=True)
        pg = ctx.new_page()
        for ch in главы:
            f = SRC / f"ch{ch}.html"
            if not f.exists():
                continue
            html = f.read_text(encoding="utf-8")

            # 🔴 Не `lambda route, h=html:`. Playwright смотрит, сколько
            # аргументов принимает обработчик, и при двух передаёт вторым
            # НЕ значение по умолчанию, а Request — html подменяется запросом,
            # и fulfill падает с «Object of type Request is not JSON
            # serializable». Этот же капкан уже ловился в audit_edu_render.py;
            # поймался второй раз, потому что там он был обойдён, а не описан.
            # Правильно — замыкание на одном аргументе.
            def отдать(route, _html=html):
                route.fulfill(status=200,
                              content_type="text/html; charset=utf-8", body=_html)

            pg.route(re.compile(r"/edu/b/\d+$"), lambda route: отдать(route))
            pg.goto(f"http://127.0.0.1:8085/edu/b/{ch}", wait_until="load", timeout=60000)
            pg.wait_for_timeout(4500)
            d = pg.evaluate(MEASURE, ширина)
            d["глава"] = ch
            итог.append(d)
            pg.unroute(re.compile(r"/edu/b/\d+$"))
        b.close()

    print(f"ширина экрана: {ширина} px\n")
    print(f"{'гл':>3} {'страница шире на':>17} {'виновников':>11}")
    for d in итог:
        print(f"{d['глава']:3d} {d['страница_шире_на']:17d} {d['всего_виновников']:11d}")
    print()
    for d in итог:
        if not d["виновники"]:
            continue
        print(f"── глава {d['глава']} " + "─" * 50)
        for v in d["виновники"]:
            print(f"   +{v['перелёт']:4d} px  ширина {v['ширина_элемента']:4d}  {v['путь']}")
            if v["текст"]:
                print(f"              «{v['текст']}»")
        print()


if __name__ == "__main__":
    main()
