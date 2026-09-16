#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_a11y.py — четыре проверки доступности, которые чинятся руками.

Контраст меряет tools/audit_contrast.py, прыжки макета — tools/audit_cls.py.
Здесь то, что осталось в бэклоге аудита отдельными пунктами:

  цели      Элементы управления мельче 44×44 CSS-px (WCAG 2.2, 2.5.8 —
            минимум 24×24; 44 — рекомендация Apple/Google и цифра, которой
            мерил аудит). Считаются ТОЛЬКО видимые и только те, у кого нет
            достаточного пустого пространства вокруг: кнопка 30 px с полем
            в 14 px по кругу нажимается пальцем так же, как 44-я, и WCAG
            это прямо разрешает. Без поправки на отступы список раздувается
            в разы за счёт того, что чинить не нужно.
  подписи   Элементы управления без доступного имени: <select>, <input>,
            <button> без текста, ссылки-иконки. Скринридер назовёт такое
            «поле со списком» и не скажет, чего именно.
  фреймы    <iframe> без title — то же самое, только «фрейм».
  прокрутка Область с собственной прокруткой, в которую нельзя попасть
            с клавиатуры (axe scrollable-region-focusable): содержимое
            физически недостижимо без мыши.

Почему свой скрипт, а не один axe: axe даёт список нарушений, но не
отвечает на вопрос «сколько из них настоящих» — по целям касания он
считает без учёта пустого пространства, и 37 находок превращаются в 6.
Число, которое нельзя довести до нуля, перестают смотреть.

Запуск:
    python3 tools/audit_a11y.py
    python3 tools/audit_a11y.py --url /journal
    python3 tools/audit_a11y.py --json до.json --diff было.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

БАЗА = "http://127.0.0.1:8085"
МИН = 44        # целевой размер цели касания
ЗАПАС = 24      # ниже этого — точно плохо, даже с отступами

СТРАНИЦЫ = [
    "/", "/brokers", "/brokers/xm", "/glossary", "/edu", "/edu/calendar",
    "/edu/b/1", "/login", "/register", "/survey", "/privacy",
]

# 🔴 Замер видит только то, что есть в DOM в состоянии по умолчанию.
# Первый прогон отрапортовал «без подписи — 0», хотя аудит нашёл
# `#techSymSel` без label как critical: этот <select> появляется только
# после переключения на вкладку «Технический», и до клика его просто нет.
# Поэтому страницы со скрытыми за вкладкой состояниями меряются дважды:
# как есть и после подготовки. Состояние, в которое нельзя попасть без
# клика, — это не «нет проблемы», это «я туда не заходил».
ПОДГОТОВКА = {
    "/": [("Технический", "вкладка технического анализа")],
}

ЗАМЕР = r"""(парам) => {
  const МИН = парам.МИН, ЗАПАС = парам.ЗАПАС;
  const УПР = 'a[href],button,input,select,textarea,summary,[role="button"],[role="link"],[tabindex]:not([tabindex="-1"])';

  const видно = (e) => {
    const s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden' || +s.opacity === 0) return false;
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const имя = (e) => {
    const t = (e.getAttribute('aria-label') || '').trim();
    if (t) return t;
    const by = e.getAttribute('aria-labelledby');
    if (by) { const у = document.getElementById(by); if (у && (у.textContent || '').trim()) return у.textContent.trim(); }
    if (e.id) { const l = document.querySelector('label[for="' + CSS.escape(e.id) + '"]');
                if (l && (l.textContent || '').trim()) return l.textContent.trim(); }
    if (e.closest('label') && (e.closest('label').textContent || '').trim()) return e.closest('label').textContent.trim();
    const ti = (e.getAttribute('title') || '').trim();  if (ti) return ti;
    const ph = (e.getAttribute('placeholder') || '').trim(); if (ph) return ph;
    const тек = (e.textContent || '').trim();  if (тек) return тек;
    const img = e.querySelector('img[alt]');
    if (img && img.getAttribute('alt').trim()) return img.getAttribute('alt').trim();
    return '';
  };
  const описание = (e) =>
    e.tagName.toLowerCase()
    + (e.id ? '#' + e.id : '')
    + (e.className && typeof e.className === 'string'
       ? '.' + e.className.trim().split(/\s+/).slice(0, 2).join('.') : '');

  const цели = [], подписи = [], фреймы = [], прокрутка = [];

  for (const e of document.querySelectorAll(УПР)) {
    if (!видно(e)) continue;
    if (e.disabled || e.closest('[disabled]')) continue;
    const r = e.getBoundingClientRect();
    const мал = Math.min(r.width, r.height);
    if (мал < МИН) {
      // 🔴 Поправка на пустое пространство. WCAG 2.5.8 засчитывает цель,
      // вокруг которой есть свободное место: важен не размер плашки,
      // а размер области, куда можно попасть пальцем, не задев соседа.
      // Меряем расстояние до ближайшего другого управления.
      let ближний = Infinity;
      for (const д of document.querySelectorAll(УПР)) {
        if (д === e || e.contains(д) || д.contains(e) || !видно(д)) continue;
        const b = д.getBoundingClientRect();
        const dx = Math.max(0, Math.max(b.left - r.right, r.left - b.right));
        const dy = Math.max(0, Math.max(b.top - r.bottom, r.top - b.bottom));
        ближний = Math.min(ближний, Math.hypot(dx, dy));
        if (ближний === 0) break;
      }
      const эфф = Math.min(мал + ближний, МИН + 1);
      if (эфф < МИН) {
        цели.push({ кто: описание(e), w: Math.round(r.width), h: Math.round(r.height),
                    зазор: ближний === Infinity ? -1 : Math.round(ближний),
                    жёстко: мал < ЗАПАС,
                    текст: (e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 30) });
      }
    }
    if (!имя(e)) подписи.push({ кто: описание(e), тип: e.type || '' });

    const s = getComputedStyle(e);
    void s;
  }

  for (const f of document.querySelectorAll('iframe')) {
    if (!видно(f)) continue;
    if (!(f.getAttribute('title') || '').trim())
      фреймы.push({ кто: описание(f), src: (f.src || '').slice(0, 60) });
  }

  for (const e of document.querySelectorAll('*')) {
    if (!видно(e)) continue;
    const s = getComputedStyle(e);
    const прок = /(auto|scroll)/.test(s.overflowX + ' ' + s.overflowY);
    if (!прок) continue;
    if (e.scrollWidth <= e.clientWidth + 2 && e.scrollHeight <= e.clientHeight + 2) continue;
    const ti = e.getAttribute('tabindex');
    if (ti !== null && +ti >= 0) continue;
    if (e.matches(УПР)) continue;
    // Область, внутри которой есть свои фокусируемые элементы, доступна
    // с клавиатуры через них — прокрутка доедет следом за фокусом.
    if (e.querySelector(УПР)) continue;
    прокрутка.push({ кто: описание(e),
                     ш: Math.round(e.scrollWidth), в: Math.round(e.scrollHeight) });
  }

  return { цели, подписи, фреймы, прокрутка,
           всего_упр: document.querySelectorAll(УПР).length,
           // 🔴 Сколько на странице ЕСТЬ, а не только сколько плохого.
           // Без этого метрика на мёртвой странице выглядит идеальной:
           // 16.09 я уронил главу 5 опечаткой в aria-label, замер
           // отрапортовал «без подписи — 0», и ноль означал «контролов
           // не осталось вовсе». Отсутствие плохого и наличие хорошего —
           // разные вопросы, спрашивать надо оба.
           текста: (document.body.innerText || '').trim().length };
}"""


def прогон(ctx, путь: str, ширина: int, готовить: bool = False) -> dict:
    стр = ctx.new_page()
    стр.set_viewport_size({"width": ширина, "height": 900})
    открыто = []
    try:
        стр.goto(БАЗА + путь, wait_until="domcontentloaded", timeout=45000)
        стр.wait_for_timeout(3000)
        if готовить:
            for подпись, что in ПОДГОТОВКА.get(путь, []):
                try:
                    стр.click(f"text={подпись}", timeout=6000)
                    стр.wait_for_timeout(3000)
                    открыто.append(что)
                except Exception:
                    открыто.append(f"НЕ ОТКРЫЛОСЬ: {что}")
        стр.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        стр.wait_for_timeout(1500)
        стр.evaluate("() => window.scrollTo(0, 0)")
        стр.wait_for_timeout(600)
        д = стр.evaluate(ЗАМЕР, {"МИН": МИН, "ЗАПАС": ЗАПАС})
        д["открыто"] = открыто
    except Exception as e:
        стр.close()
        return {"ошибка": str(e)[:180]}
    стр.close()
    return д


def main() -> int:
    р = argparse.ArgumentParser()
    р.add_argument("--url", action="append")
    р.add_argument("--json")
    р.add_argument("--diff")
    р.add_argument("--подробно", action="store_true")
    а = р.parse_args()

    итог: dict[str, dict] = {}
    with sync_playwright() as pw:
        бр = pw.chromium.launch()
        ctx = бр.new_context()
        print(f"{'страница':22} {'цели<44':>8} {'из них<24':>10} {'без подписи':>12} "
              f"{'фреймы':>7} {'прокрутка':>10}")
        for путь in (а.url or СТРАНИЦЫ):
            строка = {}
            for имя, ш in (("desktop", 1366), ("mobile", 390)):
                строка[имя] = прогон(ctx, путь, ш)
            # Состояния за вкладками меряются отдельным прогоном: иначе
            # элементы, которых нет в DOM до клика, попадают в отчёт нулём.
            for подпись, _ in ПОДГОТОВКА.get(путь, []):
                строка[f"mobile+{подпись}"] = прогон(ctx, путь, 390, готовить=True)
                break
            итог[путь] = строка
            m = строка["mobile"]
            if "ошибка" in m:
                print(f"{путь:22} ✗ {m['ошибка'][:50]}")
                continue
            жёстко = sum(1 for ц in m["цели"] if ц["жёстко"])
            # Пустая страница даёт нули по всем колонкам — это не «чисто».
            пусто = " ⚠ страница почти пуста, нули не считать" if (
                m.get("текста", 0) < 300 or m.get("всего_упр", 0) < 3) else ""
            print(f"{путь:22} {len(m['цели']):8} {жёстко:10} {len(m['подписи']):12} "
                  f"{len(m['фреймы']):7} {len(m['прокрутка']):10}{пусто}")
            if а.подробно:
                for ц in m["цели"][:6]:
                    print(f"      цель {ц['w']}×{ц['h']} зазор {ц['зазор']}  {ц['кто']}  «{ц['текст']}»")
                for п in m["подписи"][:6]:
                    print(f"      без подписи: {п['кто']} {п['тип']}")
                for ф in m["фреймы"][:4]:
                    print(f"      фрейм без title: {ф['кто']} {ф['src']}")
                for пр in m["прокрутка"][:4]:
                    print(f"      прокрутка без клавиатуры: {пр['кто']} {пр['ш']}×{пр['в']}")
        бр.close()

    def сумма(ключ: str, только_мобильный: bool = False) -> int:
        всего = 0
        for с in итог.values():
            for вид, в in с.items():
                if только_мобильный and not вид.startswith("mobile"):
                    continue
                всего += len(в.get(ключ, []))
        return всего

    # 🔴 Цели касания считаются ТОЛЬКО по мобильному. Сумма desktop+mobile
    # была враньём в свою сторону и в чужую сразу: она удваивала находки и
    # приписывала к ним desktop, где палец не при чём и норма 44 px не
    # применяется. Подписи, фреймы и прокрутка — наоборот, от ширины экрана
    # не зависят, их считаем по всем прогонам.
    print(f"\nИТОГО — цели касания (только мобильный): {сумма('цели', True)}")
    print(f"        подписи {сумма('подписи')}, фреймы {сумма('фреймы')}, "
          f"прокрутка {сумма('прокрутка')} (по всем прогонам)")

    if а.json:
        Path(а.json).write_text(json.dumps(итог, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"замер сохранён: {а.json}")

    if а.diff:
        было = json.loads(Path(а.diff).read_text(encoding="utf-8"))
        print(f"\nСравнение с {а.diff} (mobile):")
        for путь, строка in итог.items():
            м = строка.get("mobile", {})
            б = (было.get(путь, {}) or {}).get("mobile", {})
            if "цели" not in м or "цели" not in б:
                continue
            части = []
            for к in ("цели", "подписи", "фреймы", "прокрутка"):
                с, д = len(б.get(к, [])), len(м.get(к, []))
                if с or д:
                    знак = "=" if с == д else ("↓" if д < с else "↑")
                    части.append(f"{к} {с}→{д} {знак}")
            print(f"  {путь:22} " + "  ".join(части))
    return 0


if __name__ == "__main__":
    sys.exit(main())
