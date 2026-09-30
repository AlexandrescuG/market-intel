"""Кликабельное, но не кнопка: что нельзя нажать с клавиатуры.

Находит элементы, которые ведут себя как управление (курсор-палец, обработчик
клика), но не являются button/a/input и не объявлены role="button". Такие
элементы недоступны с клавиатуры, не озвучиваются как управление — и вдобавок
невидимы для замера интерактивности, который считает настоящие элементы
управления.
"""
import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

SRC = Path("/tmp/sbf_audit_chapters")

MEASURE = """() => {
  const наст = new Set(['BUTTON','A','INPUT','SELECT','TEXTAREA','LABEL','SUMMARY']);
  const плохие = [];
  for (const el of document.querySelectorAll('*')) {
    if (наст.has(el.tagName)) continue;
    if (el.getAttribute('role') === 'button') continue;
    const s = getComputedStyle(el);
    if (s.cursor !== 'pointer') continue;
    if (s.display === 'none' || s.visibility === 'hidden') continue;
    if (el.closest('button, a, [role="button"], label')) continue;

    // 🔴 Внутренности SVG отсекаются целиком, и это не косметика замера.
    // Первый прогон дал 3515 «недоступных элементов» — почти всё оказалось
    // тегами g/line/rect внутри графиков, которым курсор достался по
    // наследству от <svg>. Отдельной кнопкой ни один из них не является;
    // управление там — сам холст. Считать их значит выдать разметку за
    // проблему доступности, ровно как <title> в SVG однажды выдал себя за
    // 24 834 знака текста.
    if (el.ownerSVGElement || el.tagName === 'svg') continue;
    // Курсор, унаследованный от родителя, — не признак управления.
    if (el.parentElement && getComputedStyle(el.parentElement).cursor === 'pointer') continue;
    // Управление без доступного имени нажимать всё равно незачем.
    const текст = (el.textContent || '').trim().replace(/\\s+/g,' ');
    if (!текст) continue;

    плохие.push({тег: el.tagName, текст: текст.slice(0, 44),
                 фокусируем: el.tabIndex >= 0});
  }
  return плохие;
}"""


def main() -> int:
    итог = {}
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_context(viewport={"width": 1400, "height": 950}).new_page()
        for ch in range(1, 16):
            f = SRC / f"ch{ch}.html"
            if not f.exists():
                continue
            html = f.read_text(encoding="utf-8")

            def подставить(route, h=html):
                route.fulfill(status=200, content_type="text/html; charset=utf-8", body=h)

            pg.route(re.compile(r"/edu/b/\d+$"), lambda route: подставить(route))
            pg.goto(f"http://127.0.0.1:8085/edu/b/{ch}", wait_until="load", timeout=60000)
            pg.wait_for_timeout(4500)
            итог[ch] = pg.evaluate(MEASURE)
            pg.unroute(re.compile(r"/edu/b/\d+$"))
        b.close()

    всего = 0
    for ch, плохие in итог.items():
        без_фокуса = [p for p in плохие if not p["фокусируем"]]
        всего += len(без_фокуса)
        if не_пусто := без_фокуса:
            теги = {}
            for p in не_пусто:
                теги[p["тег"]] = теги.get(p["тег"], 0) + 1
            примеры = ", ".join(f"«{p['текст']}»" for p in не_пусто[:3] if p["текст"])
            print(f"гл {ch:2d}: {len(не_пусто):3d} кликабельных не-кнопок {теги}  {примеры}")
    print(f"\nвсего элементов, которые нельзя нажать с клавиатуры: {всего}")
    Path("/tmp/audit_a11y.json").write_text(json.dumps(итог, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
