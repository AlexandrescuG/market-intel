#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_images.py — что на самом деле показано на страницах вместо картинок.

🔴 ЗАЧЕМ. «Картинка есть» и «картинка нормальная» — разные утверждения, и
код умеет отвечать только на первое. Битый <img> без src, растянутая
превьюшка, серый прямоугольник-заглушка и честная фотография в разметке
выглядят одинаково: тег на месте, ошибок в консоли нет.

Обход открывает каждую страницу в браузере и спрашивает у неё то, что
видно только вживую:
  · дошёл ли файл (naturalWidth > 0) — 404 и пустой src ловятся здесь;
  · во сколько раз картинку растянули (показ / собственный размер) —
    так нашлись превью на 500 px в слоте на 900;
  · подозрительный источник: placeholder, dummy, stub, via.placeholder,
    data:image с однотонным пикселем;
  · пустой alt у содержательных картинок;
  · фоновые картинки (background-image) — их обычный аудит не видит вовсе.

Запуск:
    python3 tools/audit_images.py                 # прод, :8085
    python3 tools/audit_images.py --port 8099 --token <токен>   # стенд
    python3 tools/audit_images.py --только /brokers /edu/
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(КОРЕНЬ / "tools"))

СТРАНИЦЫ = [
    "/", "/grafik", "/chart.html", "/journal", "/brokers", "/brokers/xm",
    "/brokers/avatrade", "/glossary", "/privacy", "/register", "/login",
    "/survey", "/edu/", "/edu/calendar", "/edu/glossary",
] + [f"/edu/b/{i}" for i in range(1, 16)]

ЗАМЕР = r"""
(() => {
  const плохие = /placeholder|dummy|stub|заглушк|no-image|noimage|coming-soon/i;
  const out = {картинки: [], фоны: [], svg: 0};
  for (const i of document.images) {
    const r = i.getBoundingClientRect();
    if (!r.width && !r.height && !i.src) { /* скрытая пустышка — всё равно считаем */ }
    const src = i.currentSrc || i.src || '';
    const дошла = i.complete && i.naturalWidth > 0;
    const растяжение = (дошла && i.naturalWidth && r.width)
      ? +(r.width / i.naturalWidth).toFixed(2) : null;
    out.картинки.push({
      src: src.split('/').slice(-1)[0].slice(0, 48) || '(пустой src)',
      ленивая: i.loading === 'lazy',
      полный: src.slice(0, 120),
      дошла, свой: дошла ? (i.naturalWidth + '×' + i.naturalHeight) : null,
      показ: Math.round(r.width) + '×' + Math.round(r.height),
      растяжение,
      alt: (i.alt || '').slice(0, 40),
      // 🔴 alt="" и отсутствие alt — разные вещи. Пустой alt означает
      // «картинка декоративная, читать вслух нечего», и это осознанное
      // решение автора. Первый прогон считал их нарушением и выдал 33
      // ложные находки на ровном месте: у всех иконок alt="" проставлен.
      есть_alt: i.hasAttribute('alt'),
      подозрительный: плохие.test(src),
      видна: r.width > 0 && r.height > 0
    });
  }
  const виден = el => {
    const s = getComputedStyle(el);
    return s.display !== 'none' && s.visibility !== 'hidden';
  };
  for (const el of document.querySelectorAll('body *')) {
    if (!виден(el)) continue;
    const bg = getComputedStyle(el).backgroundImage;
    if (!bg || bg === 'none' || !bg.includes('url(')) continue;
    const u = (bg.match(/url\(["']?([^"')]+)/) || [])[1] || '';
    if (u.startsWith('data:image/svg')) continue;   // иконки, не фотографии
    out.фоны.push({url: u.slice(0, 110), где: el.tagName.toLowerCase() + '.' +
      String(el.className).slice(0, 26), подозрительный: плохие.test(u)});
  }
  out.svg = document.querySelectorAll('svg').length;
  return out;
})()
"""


async def main() -> int:
    from playwright.async_api import async_playwright

    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8085)
    p.add_argument("--token", default="")
    p.add_argument("--только", nargs="*", default=None)
    a = p.parse_args()
    страницы = a.только or СТРАНИЦЫ
    база = f"http://127.0.0.1:{a.port}"

    итог = {"страниц": 0, "картинок": 0, "битых": 0, "растянутых": 0,
            "подозрительных": 0, "без_alt": 0, "фонов": 0}
    находки: list[str] = []

    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        ctx = await b.new_context(
            viewport={"width": 1280, "height": 1000},
            extra_http_headers=({"X-Auth-Token": a.token} if a.token else {}))
        pg = await ctx.new_page()
        for путь in страницы:
            try:
                r = await pg.goto(база + путь, wait_until="domcontentloaded",
                                  timeout=25000)
            except Exception as e:
                находки.append(f"{путь}: НЕ ОТКРЫЛАСЬ — {str(e)[:60]}")
                continue
            await pg.wait_for_timeout(2000)
            # 🔴 ПРОКРУТИТЬ ДО КОНЦА, ПОТОМ МЕРИТЬ. Первый прогон обвинил
            # две картинки гайда XM в том, что они «не загрузились», —
            # а сервер отдавал их с кодом 200. Они просто lazy и лежали
            # ниже экрана: complete && naturalWidth > 0 у такой картинки
            # ложно, и отличить её от битой нельзя. Читатель страницу
            # листает, значит и замер обязан.
            await pg.evaluate("""async () => {
              const шаг = Math.round(window.innerHeight * 0.8);
              for (let y = 0; y < document.body.scrollHeight; y += шаг) {
                window.scrollTo(0, y);
                await new Promise(r => setTimeout(r, 120));
              }
              window.scrollTo(0, 0);
            }""")
            await pg.wait_for_timeout(2200)
            try:
                д = await pg.evaluate(ЗАМЕР)
            except Exception as e:
                находки.append(f"{путь}: замер не прошёл — {str(e)[:60]}")
                continue
            итог["страниц"] += 1
            итог["фонов"] += len(д["фоны"])
            строки = []
            for к in д["картинки"]:
                итог["картинок"] += 1
                метки = []
                if not к["дошла"]:
                    итог["битых"] += 1; метки.append("НЕ ЗАГРУЗИЛАСЬ")
                if к["подозрительный"]:
                    итог["подозрительных"] += 1; метки.append("ПЛЕЙСХОЛДЕР В ИМЕНИ")
                # 🔴 Растяжение больше 1.35 — это уже мыло: ровно так
                # выглядели превью на 500 px в слоте на 900.
                if к["растяжение"] and к["растяжение"] > 1.35 and к["видна"]:
                    итог["растянутых"] += 1
                    метки.append(f"РАСТЯНУТА ×{к['растяжение']} ({к['свой']} → {к['показ']})")
                if к["видна"] and not к["есть_alt"]:
                    итог["без_alt"] += 1; метки.append("нет атрибута alt")
                if метки:
                    строки.append(f"      {к['src']:44} {' · '.join(метки)}")
            for ф in д["фоны"]:
                if ф["подозрительный"]:
                    итог["подозрительных"] += 1
                    строки.append(f"      фон {ф['где']:30} ПЛЕЙСХОЛДЕР: {ф['url']}")
            статус = "" if (r and r.status == 200) else f" [код {r.status if r else '?'}]"
            print(f"{путь:16} картинок {len(д['картинки']):>3}, фонов {len(д['фоны']):>2}, "
                  f"svg {д['svg']:>3}{статус}")
            for с in строки:
                print(с)
            находки.extend(f"{путь}:{с}" for с in строки)
        await b.close()

    print("\n── итог ──")
    for к, з in итог.items():
        print(f"   {к}: {з}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
