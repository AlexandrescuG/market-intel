"""Обход ВСЕХ страниц сайта на наборе устройств — по ширине и по ВЫСОТЕ.

🔴 ВЫСОТА — ОТДЕЛЬНОЕ ИЗМЕРЕНИЕ, И РАНЬШЕ Я ЕЁ НЕ МЕРИЛ ВОВСЕ.
Всё, что я считал до сих пор, отвечало на вопрос «что не влезло по ширине».
Но на телефоне ломается и другое:

  • фиксированная обвязка. У нас их две: общая нижняя панель сайта и своя
    панель главы, плюс шапка. На экране 788 px они съедают одну долю, на
    568 px (iPhone SE) — заметно большую. Считаем в ПРОЦЕНТАХ от высоты, а
    не в пикселях: пиксели одинаковы, а доля — нет, и болит именно доля;
  • контент под обвязкой. Нижняя панель не прозрачная: если элемент лежит
    под ней, его не видно и на него нельзя нажать;
  • блоки в 100vh. На низком экране такой блок выдавливает всё остальное за
    пределы первого экрана;
  • полезная площадь первого экрана: сколько остаётся под содержание после
    всей обвязки.

Набор устройств подобран по краям, а не «около 390»: самый низкий экран,
самый узкий, реальный аппарат владельца и большой.

Запуск:
  python3 tools/mobile_sweep.py --список
  python3 tools/mobile_sweep.py --страницы / /brokers /journal
  python3 tools/mobile_sweep.py --все
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

БАЗА = "http://127.0.0.1:8085"

# (имя, ширина, высота) — края диапазона, а не середина.
УСТРОЙСТВА = [
    ("iPhone SE  320x568", 320, 568),      # самый низкий и узкий из живых
    ("Galaxy S8  360x740", 360, 740),
    ("Xiaomi(его) 395x788", 395, 788),     # замерен через adb 14.09.2026
    ("iPhone 14  390x664", 390, 664),      # низкий вьюпорт при обычной ширине
    ("Pro Max    430x740", 430, 740),
]

СТРАНИЦЫ = [
    ("/",                 "Главная"),
    ("/register",         "Регистрация"),
    ("/login",            "Вход"),
    ("/survey",           "Опросник"),
    ("/privacy",          "Приватность"),
    ("/brokers",          "Брокеры — список"),
    ("/brokers/xm",       "Брокер XM"),
    ("/brokers/avatrade", "Брокер AvaTrade"),
    ("/glossary",         "Словарь"),
    ("/grafik",           "Графики (паттерны)"),
    ("/chart.html",       "График инструмента"),
    ("/journal",          "Личный кабинет"),
    ("/edu/",             "Курс — оглавление"),
    ("/edu/calendar",     "Календарь"),
    ("/edu/glossary",     "Словарь курса"),
] + [(f"/edu/b/{n}", f"Глава {n}") for n in range(1, 16)]

ЗАМЕР = """(данные) => {
  const [ш, в] = данные;
  const корень = document.documentElement;

  // ── по ширине ────────────────────────────────────────────────────────
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
    const перелёт = Math.round(r.right - ш);
    if (перелёт <= 1) continue;
    if (прокрутки.some(p => p !== el && p.contains(el))) continue;
    // 🔴 ТА ЖЕ ЛИНЕЙКА, ЧТО В audit_edu_mobile.py: симметричный вынос — не
    // поломка. Приём «во всю ширину» (margin: 0 -5vw + padding: 0 5vw)
    // растягивает плашку за оба края поровну. Без этого отсева свод
    // рапортовал по /edu/b/5 перелёт 16–22 px на всех пяти устройствах,
    // хотя страница по горизонтали не прокручивается вовсе (шире_на=0), и
    // ширина «виновника» ровно равна экрану плюс 10vw. Два инструмента
    // меряли одно и то же разными линейками, и свод девять строк подряд
    // показывал дефект там, где второй инструмент показывал чистоту.
    if (Math.abs(Math.round(r.left) + перелёт) <= 2) continue;
    кандидаты.push(el);
  }
  const набор = new Set(кандидаты);
  const шире = [];
  for (const el of кандидаты) {
    let p = el.parentElement, вложен = false;
    while (p) { if (набор.has(p)) { вложен = true; break; } p = p.parentElement; }
    if (вложен) continue;
    const r = el.getBoundingClientRect();
    шире.push({перелёт: Math.round(r.right - ш), ширина: Math.round(r.width),
               текст: (el.textContent||'').replace(/\\s+/g,' ').trim().slice(0,50)});
  }
  шире.sort((a,b) => b.перелёт - a.перелёт);

  // ── по высоте ────────────────────────────────────────────────────────
  // Фиксированная обвязка: всё, что position:fixed/sticky и реально видно.
  const обвязка = [];
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el);
    if (s.position !== 'fixed' && s.position !== 'sticky') continue;
    if (s.display === 'none' || s.visibility === 'hidden' || +s.opacity === 0) continue;
    const r = el.getBoundingClientRect();
    if (r.height < 8 || r.width < ш * 0.5) continue;      // не полоса — не считаем
    // Только те, что прижаты к краю экрана.
    const сверху = r.top <= 2, снизу = r.bottom >= в - 2;
    if (!сверху && !снизу) continue;
    if (обвязка.some(o => Math.abs(o.верх - r.top) < 4 && Math.abs(o.низ - r.bottom) < 4)) continue;
    обвязка.push({край: сверху ? 'сверху' : 'снизу',
                  высота: Math.round(r.height), верх: r.top, низ: r.bottom,
                  текст: (el.textContent||'').replace(/\\s+/g,' ').trim().slice(0,40)});
  }
  const занято = обвязка.reduce((s, o) => s + o.высота, 0);

  // Блоки, у которых высота задана экраном.
  const стовэ = [];
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el);
    const h = el.style.height || '', mh = el.style.minHeight || '';
    if (/100v(h|dvh|svh)/.test(h) || /100v(h|dvh|svh)/.test(mh)) {
      const r = el.getBoundingClientRect();
      стовэ.push({высота: Math.round(r.height),
                  текст: (el.textContent||'').replace(/\\s+/g,' ').trim().slice(0,40)});
    }
  }

  return {
    шире_на: Math.round(корень.scrollWidth - ш),
    по_ширине: шире.length,
    верх_ширины: шире.slice(0, 4),
    обвязка: обвязка,
    обвязка_px: занято,
    обвязка_доля: Math.round(занято / в * 100),
    полезно_px: в - занято,
    блоков_100vh: стовэ.length,
    высота_страницы: Math.round(корень.scrollHeight),
    экранов: +(корень.scrollHeight / в).toFixed(1),
  };
}"""


def прогон(pw, токен: str, страницы, устройства) -> list[dict]:
    итог = []
    for имя_у, ш, в in устройства:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": ш, "height": в},
                            device_scale_factor=2, is_mobile=True, has_touch=True)
        # Вход: тот же токен, что кладёт sbf-auth.js — и в localStorage, и в
        # куку. Без куки серверный гейт PRO-глав не пустит на обычной
        # навигации (заголовок она приложить не может).
        if токен:
            ctx.add_cookies([{"name": "sbf_session", "value": токен,
                              "domain": "127.0.0.1", "path": "/"}])
            ctx.add_init_script(
                f"try{{localStorage.setItem('sbf_token','{токен}')}}catch(e){{}}")
        pg = ctx.new_page()
        for путь, подпись in страницы:
            try:
                pg.goto(БАЗА + путь, wait_until="load", timeout=45000)
                pg.wait_for_timeout(3500)
                d = pg.evaluate(ЗАМЕР, [ш, в])
            except Exception as e:
                d = {"ошибка": str(e)[:80]}
            d.update({"устройство": имя_у, "путь": путь, "подпись": подпись})
            итог.append(d)
        b.close()
    return итог


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--страницы", nargs="*")
    ap.add_argument("--все", action="store_true")
    ap.add_argument("--список", action="store_true")
    ap.add_argument("--токен", default="")
    ap.add_argument("--вывод", default="/tmp/sweep.json")
    a = ap.parse_args()

    if a.список:
        print(f"страниц в обходе: {len(СТРАНИЦЫ)}\n")
        for путь, подпись in СТРАНИЦЫ:
            print(f"  {путь:20} {подпись}")
        print(f"\nустройств: {len(УСТРОЙСТВА)}")
        for имя, ш, в in УСТРОЙСТВА:
            print(f"  {имя}")
        return

    страницы = СТРАНИЦЫ if a.все or not a.страницы else [
        (p, dict(СТРАНИЦЫ).get(p, p)) for p in a.страницы]

    with sync_playwright() as pw:
        итог = прогон(pw, a.токен, страницы, УСТРОЙСТВА)

    Path(a.вывод).write_text(json.dumps(итог, ensure_ascii=False, indent=1),
                             encoding="utf-8")

    # Сводка: по странице — худшее по всем устройствам.
    по_странице: dict[str, dict] = {}
    for d in итог:
        if "ошибка" in d:
            continue
        к = по_странице.setdefault(d["путь"], {"подпись": d["подпись"],
                                               "ширина": 0, "доля": 0, "vh": 0,
                                               "где_доля": "", "где_ширина": ""})
        if d["по_ширине"] and d["верх_ширины"] and d["верх_ширины"][0]["перелёт"] > к["ширина"]:
            к["ширина"] = d["верх_ширины"][0]["перелёт"]
            к["где_ширина"] = d["устройство"]
        if d["обвязка_доля"] > к["доля"]:
            к["доля"] = d["обвязка_доля"]
            к["где_доля"] = d["устройство"]
        к["vh"] = max(к["vh"], d["блоков_100vh"])

    print(f"{'страница':22} {'перелёт':>8} {'обвязка':>8}  худшее устройство")
    for путь, к in sorted(по_странице.items(), key=lambda x: -x[1]["доля"]):
        метка = f"{к['доля']}%"
        print(f"{путь:22} {к['ширина']:8} {метка:>8}  {к['где_доля']}")
    print(f"\nподробности: {a.вывод}")


if __name__ == "__main__":
    main()
