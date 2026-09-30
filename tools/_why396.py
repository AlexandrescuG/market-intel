"""Почему блок в главе шире экрана — цепочка родителей и самый широкий потомок."""
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ГЛАВА = sys.argv[1] if len(sys.argv) > 1 else "7"
ШИРИНА = int(sys.argv[2]) if len(sys.argv) > 2 else 360

JS = """(ш) => {
  // 🔴 Тот же отсев, что в основном замере: элементы внутри собственной
  // горизонтальной прокрутки выходят за край ПО ЗАМЫСЛУ. Без него щуп
  // первым делом хватает ленту котировок (3599 px) и рапортует про неё.
  const прокрутки = [...document.querySelectorAll('*')].filter(el => {
    const s = getComputedStyle(el);
    // 🔴 Только auto/scroll. `hidden` НЕ отсеиваем: внутри него содержимое
    // не прокручивается, а обрезается — пользователь теряет правый край
    // насовсем. Первый вариант щупа отсеивал и hidden тоже и радостно
    // отрапортовал «виновников нет» ровно там, где текст режется.
    return s.overflowX === 'auto' || s.overflowX === 'scroll';
  });
  let цель = null;
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.right - ш > 2 && r.height > 40 && r.width > ш) {
      const s = getComputedStyle(el);
      if (s.position === 'fixed') continue;
      if (прокрутки.some(p => p !== el && p.contains(el))) continue;
      цель = el; break;
    }
  }
  if (!цель) return {нет: true};
  const цепь = [];
  let n = цель;
  for (let i = 0; i < 4 && n && n.tagName !== 'BODY'; i++) {
    const s = getComputedStyle(n), r = n.getBoundingClientRect();
    цепь.push({тег: n.tagName, класс: (n.className||'').toString().slice(0,22),
               ширина: Math.round(r.width), display: s.display,
               minWidth: s.minWidth, gridTC: s.gridTemplateColumns.slice(0,34),
               overflowX: s.overflowX});
    n = n.parentElement;
  }
  let макс = null, мш = 0;
  for (const c of цель.querySelectorAll('*')) {
    const r = c.getBoundingClientRect();
    if (r.width > мш) { мш = r.width; макс = c; }
  }
  const s0 = getComputedStyle(цель);
  const виновник = {
    margin: s0.margin, padding: s0.padding, box: s0.boxSizing,
    width_css: s0.width, inline_style: (цель.getAttribute('style')||'').slice(0,140),
    html: цель.outerHTML.slice(0, 200),
  };
  return {виновник, цепь, внутри: макс ? {тег: макс.tagName,
          класс:(макс.className||'').toString().slice(0,22), ширина: Math.round(мш),
          display: getComputedStyle(макс).display,
          gridTC: getComputedStyle(макс).gridTemplateColumns.slice(0,50),
          minWidth: getComputedStyle(макс).minWidth,
          текст:(макс.textContent||'').trim().slice(0,45)} : null};
}"""

html = Path(f"/tmp/sbf_audit_chapters/ch{ГЛАВА}.html").read_text(encoding="utf-8")


def отдать(route, _h=html):
    route.fulfill(status=200, content_type="text/html; charset=utf-8", body=_h)


with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_context(viewport={"width": ШИРИНА, "height": 740},
                       is_mobile=True, has_touch=True).new_page()
    pg.route(re.compile(r"/edu/b/\d+$"), lambda r: отдать(r))
    pg.goto(f"http://127.0.0.1:8085/edu/b/{ГЛАВА}", wait_until="load", timeout=45000)
    pg.wait_for_timeout(4000)
    d = pg.evaluate(JS, ШИРИНА)
    if d.get("нет"):
        print(f"глава {ГЛАВА} на {ШИРИНА}: виновников нет")
    else:
        print(f"глава {ГЛАВА} на {ШИРИНА} — цепочка от виновника вверх:")
        for c in d["цепь"]:
            print(f"   {c['тег']:6} .{c['класс']:22} w={c['ширина']:4} "
                  f"display={c['display']:12} minW={c['minWidth']:7} grid={c['gridTC'][:30]}")
        print("\n   сам виновник:")
        for k, v in (d.get("виновник") or {}).items():
            print(f"      {k:14} {v}")
        print("\n   самый широкий внутри:")
        for k, v in (d["внутри"] or {}).items():
            print(f"      {k:10} {v}")
    b.close()
