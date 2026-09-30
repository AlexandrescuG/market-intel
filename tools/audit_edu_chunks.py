"""Самые длинные куски текста без единого управления — в одной главе.

Общий замер (audit_edu_render.py) отвечает «в главе 11 медиана 343, знаков на
интерактив 680». Это говорит, что плохо, но не говорит ГДЕ. Здесь — список
кусков по убыванию длины с началом текста, чтобы можно было пойти и найти их
в исходнике.

Запуск: python3 tools/audit_edu_chunks.py 11 [сколько_показать]
"""
import re
import sys
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
  const куски = [];
  let текущий = '';
  let node;
  while ((node = walker.nextNode())) {
    if (isInteractive(node)) {
      if (текущий.trim()) куски.push(текущий.trim());
      текущий = '';
      continue;
    }
    for (const ch of node.childNodes) {
      if (ch.nodeType === 3) {
        const t = ch.textContent.replace(/\\s+/g, ' ');
        if (t.trim()) текущий += t;
      }
    }
  }
  if (текущий.trim()) куски.push(текущий.trim());
  return куски;
}"""


def main() -> None:
    глава = sys.argv[1] if len(sys.argv) > 1 else "11"
    сколько = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    файл = SRC / f"ch{глава}.html"
    if not файл.exists():
        print(f"нет {файл} — сначала tools/audit_edu_build.py")
        return
    html = файл.read_text(encoding="utf-8")
    # 🔴 Открывать надо на РОДНОМ адресе, а не на выдуманном: глава тянет
    # /assets/*, и на чужом origin React просто не запускается. Первый прогон
    # этого инструмента отрапортовал «кусков 0» — не потому что их нет, а
    # потому что страница осталась пустой.
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_context(viewport={"width": 1400, "height": 950}).new_page()

        def отдать(route, h=html):
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=h)

        page.route(re.compile(r"/edu/b/\d+$"), lambda route: отдать(route))
        page.goto(f"http://127.0.0.1:8085/edu/b/{глава}", wait_until="load", timeout=60000)
        page.wait_for_timeout(5000)
        куски = page.evaluate(MEASURE)
        b.close()

    куски.sort(key=len, reverse=True)
    print(f"глава {глава}: кусков {len(куски)}, "
          f"суммарно {sum(len(k) for k in куски)} знаков\n")
    for i, к in enumerate(куски[:сколько], 1):
        print(f"{i:2}. {len(к):5} знаков")
        print(f"    начало: {к[:150]}")
        print(f"    конец:  …{к[-90:]}\n")


if __name__ == "__main__":
    main()
