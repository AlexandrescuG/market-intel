#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_cls.py — кто именно толкает макет при загрузке.

🔴 ЗАЧЕМ НЕ «CLS 1.15», А СПИСОК ВИНОВНИКОВ.
Число CLS говорит, что страница прыгает, и молчит о том, где. Чинить по
числу — значит гадать: поставить min-height десяти блокам и надеяться.
Здесь собираются сами записи layout-shift вместе с sources — элементами,
которые сдвинулись, — и считается вклад каждого в итог. Правка идёт по
верхушке списка, а проверяется падением того же числа.

Что важно понимать про метрику:
* CLS считается по ОКНАМ: берётся максимальная сумма сдвигов за окно
  в 5 с (разрыв между сдвигами не больше 1 с). Простая сумма всех сдвигов
  завышает результат и не совпадает с тем, что показывает Lighthouse.
* Сдвиги после действия пользователя (hadRecentInput) не считаются — это
  не «прыжок», а реакция на клик. Скрипт их отбрасывает, как и браузер.
* Мерить надо С ПРОКРУТКОЙ: блоки ниже сгиба дорисовываются лениво, и без
  прокрутки страница выглядит стабильной там, где она прыгает сильнее
  всего. Но прокрутка — это НЕ ввод для layout-shift API: сдвиги при
  скролле продолжают считаться, поэтому прокрутка идёт скриптом
  (window.scrollTo), а не колесом, и без hadRecentInput.

Запуск:
    python3 tools/audit_cls.py                       # весь список
    python3 tools/audit_cls.py --url / --url /brokers
    python3 tools/audit_cls.py --json до.json
    python3 tools/audit_cls.py --diff до.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

БАЗА = "http://127.0.0.1:8085"

СТРАНИЦЫ = ["/", "/brokers", "/edu", "/edu/calendar", "/glossary", "/edu/b/2"]

# Наблюдатель ставится ДО загрузки страницы через add_init_script: если
# подписаться после goto, первые — самые крупные — сдвиги уже случились,
# и отчёт покажет благополучие. buffered:true подстраховывает.
НАБЛЮДАТЕЛЬ = """
window.__сдвиги = [];
try {
  new PerformanceObserver(function (список) {
    for (const з of список.getEntries()) {
      if (з.hadRecentInput) continue;          // реакция на ввод — не прыжок
      const кто = [];
      for (const и of (з.sources || [])) {
        const у = и.node;
        if (!у || !у.tagName) { кто.push('(удалён из DOM)'); continue; }
        кто.push(
          у.tagName.toLowerCase()
          + (у.id ? '#' + у.id : '')
          + (у.className && typeof у.className === 'string'
             ? '.' + у.className.trim().split(/\\s+/).slice(0, 2).join('.') : '')
        );
      }
      window.__сдвиги.push({value: з.value, t: з.startTime, кто: кто});
    }
  }).observe({type: 'layout-shift', buffered: true});
} catch (e) { window.__сдвигиОшибка = String(e); }
"""

СБОР = """() => ({
  сдвиги: window.__сдвиги || [],
  ошибка: window.__сдвигиОшибка || null,
  высота: document.body.scrollHeight,
})"""


def окнами(сдвиги: list[dict]) -> float:
    """CLS как его считает браузер: максимум по окнам 5 с / разрыв 1 с.

    Простая сумма завышает: страница, которая дёрнулась трижды за минуту,
    получила бы ту же оценку, что и страница, прыгающая всё время загрузки.
    """
    лучший = 0.0
    текущая = 0.0
    начало = предыдущий = None
    for с in сорт(сдвиги):
        t, v = с["t"], с["value"]
        if начало is None or t - предыдущий > 1000 or t - начало > 5000:
            начало = t
            текущая = 0.0
        текущая += v
        предыдущий = t
        лучший = max(лучший, текущая)
    return лучший


def сорт(сдвиги: list[dict]) -> list[dict]:
    return sorted(сдвиги, key=lambda с: с["t"])


def прогон(ctx, путь: str, ширина: int) -> dict:
    стр = ctx.new_page()
    стр.add_init_script(НАБЛЮДАТЕЛЬ)
    стр.set_viewport_size({"width": ширина, "height": 900})
    try:
        стр.goto(БАЗА + путь, wait_until="domcontentloaded", timeout=45000)
        стр.wait_for_timeout(3500)
        # Ленивые блоки: без прокрутки половина страницы не отрисована.
        for доля in (0.25, 0.5, 0.75, 1.0):
            стр.evaluate("(д) => window.scrollTo(0, document.body.scrollHeight*д)", доля)
            стр.wait_for_timeout(900)
        стр.evaluate("() => window.scrollTo(0, 0)")
        стр.wait_for_timeout(1200)
        данные = стр.evaluate(СБОР)
    except Exception as e:
        стр.close()
        return {"ошибка": str(e)[:200]}
    стр.close()

    виновники: dict[str, float] = {}
    for с in данные["сдвиги"]:
        доля = с["value"] / max(len(с["кто"]), 1)
        for к in (с["кто"] or ["(без источника)"]):
            виновники[к] = виновники.get(к, 0.0) + доля
    return {
        "cls": round(окнами(данные["сдвиги"]), 4),
        "сумма": round(sum(с["value"] for с in данные["сдвиги"]), 4),
        "штук": len(данные["сдвиги"]),
        "виновники": dict(sorted(виновники.items(), key=lambda x: -x[1])[:12]),
        "ошибка_наблюдателя": данные["ошибка"],
    }


def main() -> int:
    р = argparse.ArgumentParser()
    р.add_argument("--url", action="append")
    р.add_argument("--json")
    р.add_argument("--diff")
    а = р.parse_args()

    итог: dict[str, dict] = {}
    with sync_playwright() as pw:
        бр = pw.chromium.launch()
        ctx = бр.new_context()
        for путь in (а.url or СТРАНИЦЫ):
            строка = {}
            for имя, ш in (("desktop", 1366), ("mobile", 390)):
                строка[имя] = прогон(ctx, путь, ш)
            итог[путь] = строка
            d, m = строка["desktop"], строка["mobile"]
            if "ошибка" in d:
                print(f"{путь:20} ✗ {d['ошибка'][:60]}")
                continue
            оценка = "хорошо" if max(d["cls"], m["cls"]) <= 0.1 else (
                "терпимо" if max(d["cls"], m["cls"]) <= 0.25 else "ПЛОХО")
            print(f"{путь:20} desktop {d['cls']:6.3f}  mobile {m['cls']:6.3f}   "
                  f"сдвигов {d['штук']:3}/{m['штук']:3}   {оценка}")
            for кто, вклад in list(m["виновники"].items())[:4]:
                print(f"      {вклад:6.3f}  {кто}")
        бр.close()

    if а.json:
        Path(а.json).write_text(json.dumps(итог, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nзамер сохранён: {а.json}")

    if а.diff:
        было = json.loads(Path(а.diff).read_text(encoding="utf-8"))
        print(f"\nСравнение с {а.diff}:")
        for путь, строка in итог.items():
            for вид, д in строка.items():
                б = (было.get(путь, {}).get(вид, {}) or {}).get("cls")
                if б is None or "cls" not in д:
                    continue
                знак = "=" if abs(б - д["cls"]) < 0.005 else ("↓" if д["cls"] < б else "↑")
                print(f"  {путь:20} {вид:8} {б:6.3f} → {д['cls']:6.3f}  {знак}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
