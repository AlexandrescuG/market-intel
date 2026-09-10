"""Сколько ВИДИМОГО текста читатель проходит подряд, ни на что не нажимая.

🔴 Считается только то, что видно. Первый заход этого замера дал по главе 6
«24 834 знака подряд» — и это оказались подсказки <title> у точек SVG-графика,
которых на экране нет вовсе. Метрика, которая считает невидимое, не измеряет
чтение; она измеряет разметку.
"""
import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

SRC = Path("/tmp/sbf_audit_chapters")

MEASURE = """() => {
  const root = document.querySelector('#sbf-book-root') || document.body;
  const СЛУЖЕБНЫЕ = new Set(['SCRIPT','STYLE','TITLE','DESC','METADATA','DEFS','NOSCRIPT']);
  const isInteractive = el =>
    el.matches('button, input, select, textarea, canvas, [role="button"]') ||
    el.tagName === 'IFRAME';

  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, {
    acceptNode(el) {
      const tag = el.tagName.toUpperCase();
      if (СЛУЖЕБНЫЕ.has(tag)) return NodeFilter.FILTER_REJECT;
      const s = getComputedStyle(el);
      if (s.display === 'none' || s.visibility === 'hidden' || +s.opacity === 0)
        return NodeFilter.FILTER_REJECT;
      if (el.getAttribute('aria-hidden') === 'true') return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    }
  });

  const seq = [];
  let node;
  while ((node = walker.nextNode())) {
    if (isInteractive(node)) { seq.push({t:'i'}); continue; }
    for (const ch of node.childNodes) {
      if (ch.nodeType === 3) {
        const s = ch.textContent.trim();
        if (s.length > 1) seq.push({t:'x', n:s.length, s:s});
      }
    }
  }
  const runs = []; let acc = 0, начало = '';
  for (const s of seq) {
    if (s.t === 'i') { if (acc) runs.push({длина:acc, начало:начало}); acc = 0; начало = ''; }
    else { if (!acc) начало = s.s.slice(0,60); acc += s.n; }
  }
  if (acc) runs.push({длина:acc, начало:начало});
  const total = runs.reduce((a,b)=>a+b.длина,0);
  const отсорт = [...runs].sort((a,b)=>b.длина-a.длина);
  return {всего_текста: total,
          интерактивов: seq.filter(s=>s.t==='i').length,
          пробегов: runs.length,
          макс_пробег: отсорт[0] ? отсорт[0].длина : 0,
          макс_начало: отсорт[0] ? отсорт[0].начало : '',
          медиана_пробега: runs.length
            ? [...runs].sort((a,b)=>a.длина-b.длина)[Math.floor(runs.length/2)].длина : 0,
          высота: Math.round(document.body.scrollHeight)};
}"""


def main() -> int:
    rows = []
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
            pg.wait_for_timeout(5000)
            d = pg.evaluate(MEASURE)
            d["глава"] = ch
            rows.append(d)
            pg.unroute(re.compile(r"/edu/b/\d+$"))
        b.close()

    print(f"{'гл':>3} {'текста':>7} {'интер':>6} {'проб':>5} {'макс':>7} "
          f"{'медиана':>8} {'знаков/интер':>13}  начало самого длинного куска")
    for d in rows:
        на_один = d["всего_текста"] // max(d["интерактивов"], 1)
        print(f"{d['глава']:3d} {d['всего_текста']:7d} {d['интерактивов']:6d} "
              f"{d['пробегов']:5d} {d['макс_пробег']:7d} {d['медиана_пробега']:8d} "
              f"{на_один:13d}  «{d['макс_начало'][:44]}…»")

    # Глава 1 — стартовый экран, не урок: 3 элемента и почти без текста.
    # Держать её в среднем по «1-5» значило бы занизить обе стороны сравнения.
    п, в = [r for r in rows if 2 <= r["глава"] <= 5], [r for r in rows if r["глава"] >= 6]
    ср = lambda rs, k: sum(r[k] for r in rs) / len(rs)  # noqa: E731
    print("\n(глава 1 — стартовый экран, а не урок; в сравнение не входит)")
    print("                            главы 2-5   главы 6-15   отношение")
    for k, подпись in (("всего_текста", "видимого текста"),
                       ("интерактивов", "интерактивных элементов"),
                       ("макс_пробег", "самый длинный кусок"),
                       ("медиана_пробега", "медиана куска"),
                       ("высота", "высота страницы, px")):
        a, b_ = ср(п, k), ср(в, k)
        print(f"  {подпись:26s} {a:9.0f} {b_:12.0f} {(f'{b_/a:.2f}x' if a else '—'):>11}")
    a = ср(п, "всего_текста") / max(ср(п, "интерактивов"), 1)
    b_ = ср(в, "всего_текста") / max(ср(в, "интерактивов"), 1)
    print(f"  {'знаков на интерактив':26s} {a:9.0f} {b_:12.0f} {b_/a:10.2f}x")

    Path("/tmp/audit_render.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
