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

# 🔴 ВСЕ 15 глав, а не одна первая. Ровно та же ошибка уже стоила замеру
# контраста правдоподобия: по выборке из трёх глав отчёт печатался как
# «по сайту». Главы 6-15 анониму отдают заглушку пейволла — для них нужен
# --база/--токен от tools/edu_preview.py, иначе строка будет про заглушку.
СТРАНИЦЫ = [
    "/", "/brokers", "/brokers/xm", "/glossary", "/edu", "/edu/calendar",
    # 🔴 /chart.html, а не /grafik. «/grafik» — редирект-заглушка на 988
    # байт (уводит на /#tech/...), и замер по ней честно показывал нули,
    # потому что мерить там нечего. Полный терминал с каталогом из 800
    # инструментов живёт по /chart.html — на него ведёт ссылка «живая
    # цена» из каждой из 15 глав, и ни один замер туда не заходил.
    "/chart.html?s=EURUSD",
    *[f"/edu/b/{n}" for n in range(1, 16)],
    "/login", "/register", "/survey", "/privacy",
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
    # На телефоне терминал открывается сразу на графике, каталог убран за
    # ссылку «← К списку инструментов». Без клика замер видит 7 целей
    # вместо всего списка из 800 строк — и это опять «я туда не заходил».
    "/chart.html?s=EURUSD": [("К списку инструментов", "каталог инструментов")],
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

  const цели = [], подписи = [], фреймы = [], прокрутка = [], вложенные = [];

  // 🔴 Управление внутри управления (axe nested-interactive). Кнопка
  // «в избранное» 16×13 лежит внутри кликабельной строки инструмента:
  // диктор объявляет строку кнопкой и читает её содержимое как одно имя,
  // а палец на телефоне почти гарантированно попадает в строку вместо
  // звёздочки. Проверки на это не было ни в одном замере — пункт Ч-1
  // аудита закрывать было нечем.
  // 🔴 Здесь НЕ `видно`, а более мягкая проверка: opacity:0 убирает
  // элемент с экрана, но НЕ из дерева доступности — диктор его читает.
  // Первая версия использовала `видно` и отрапортовала «вложенных 0»,
  // хотя кнопка «в избранное» лежит внутри строки-кнопки у всех 23
  // инструментов: `.inst-fav` прозрачна до наведения мышью, и мой же
  // фильтр её выбрасывал. Ноль означал «я не туда посмотрел».
  const в_дереве = (e) => {
    const s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    if (e.closest('[aria-hidden="true"],[hidden]')) return false;
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  for (const e of document.querySelectorAll(УПР)) {
    if (!в_дереве(e)) continue;
    const род = e.parentElement && e.parentElement.closest(УПР);
    if (!род || !в_дереве(род)) continue;
    const r = e.getBoundingClientRect();
    вложенные.push({ кто: описание(e), внутри: описание(род),
                     w: Math.round(r.width), h: Math.round(r.height),
                     текст: (e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 24) });
  }

  // 🔴 Исключение «Inline» из WCAG 2.5.8: цель внутри предложения выведена
  // из-под требования — её размер задан строкой текста, и раздувать слово
  // до 44 px значило бы испортить абзац ради метрики. Ровно так устроены
  // термины глоссария в главах: «Пункт (pip) — минимальный шаг цены»,
  // кнопка 32×16 посреди фразы. Считаем целью только то, что стоит
  // отдельно: если у абзаца-предка есть свой текст помимо этой кнопки —
  // это inline-цель.
  const в_строке_текста = (e) => {
    const род = e.closest('p, li, td, th, figcaption, blockquote');
    if (!род) return false;
    const весь = (род.innerText || '').trim().length;
    const свой = (e.innerText || '').trim().length;
    return весь - свой > 20;          // вокруг есть настоящий текст
  };

  for (const e of document.querySelectorAll(УПР)) {
    if (!видно(e)) continue;
    if (e.disabled || e.closest('[disabled]')) continue;
    const r = e.getBoundingClientRect();
    const мал = Math.min(r.width, r.height);
    if (мал < МИН && !в_строке_текста(e)) {
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
    // Адрес и кусок содержимого: «div 378×504» не говорит ничего, а
    // искать по грепу нечего — у блока нет класса.
    var дорога = [], у = e, шагов = 0;
    while (у && у.tagName && шагов++ < 5) {
      var имя_у = у.tagName.toLowerCase();
      if (у.id) { дорога.unshift(имя_у + '#' + у.id); break; }
      var кл = (у.className && typeof у.className === 'string' ? у.className.trim() : '');
      if (кл) имя_у += '.' + кл.split(/\s+/).slice(0, 2).join('.');
      дорога.unshift(имя_у);
      у = у.parentElement;
    }
    прокрутка.push({ кто: описание(e),
                     ш: Math.round(e.scrollWidth), в: Math.round(e.scrollHeight),
                     путь: дорога.join(' > '),
                     текст: (e.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 60) });
  }

  return { цели, подписи, фреймы, прокрутка, вложенные,
           всего_упр: document.querySelectorAll(УПР).length,
           // 🔴 Сколько на странице ЕСТЬ, а не только сколько плохого.
           // Без этого метрика на мёртвой странице выглядит идеальной:
           // 16.09 я уронил главу 5 опечаткой в aria-label, замер
           // отрапортовал «без подписи — 0», и ноль означал «контролов
           // не осталось вовсе». Отсутствие плохого и наличие хорошего —
           // разные вопросы, спрашивать надо оба.
           текста: (document.body.innerText || '').trim().length };
}"""


def прогон(ctx, путь: str, ширина: int, готовить: bool = False,
           база: str = БАЗА) -> dict:
    стр = ctx.new_page()
    стр.set_viewport_size({"width": ширина, "height": 900})
    открыто = []
    ошибки_страницы: list[str] = []
    стр.on("pageerror", lambda e: ошибки_страницы.append(str(e)[:160]))
    try:
        стр.goto(база + путь, wait_until="domcontentloaded", timeout=45000)
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
        # 🔴 Метрика «сколько плохого» на упавшей странице всегда идеальна:
        # уронив главу 5 своим же aria-label, я получил «0 контролов без
        # имени» — потому что контролов не осталось. Ошибка страницы едет
        # в тот же результат, чтобы ноль не проходил молча.
        д["ошибки_страницы"] = ошибки_страницы
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
    р.add_argument("--база", default=БАЗА,
                   help="адрес сервера; для платных глав — стенд edu_preview.py")
    р.add_argument("--токен",
                   help="сессия из edu_preview.py: кладётся в куку sbf_session, "
                        "иначе главы 6-15 отдают заглушку пейволла и все "
                        "метрики по ним — нули на пустой странице")
    а = р.parse_args()

    итог: dict[str, dict] = {}
    with sync_playwright() as pw:
        бр = pw.chromium.launch()
        ctx = бр.new_context()
        if а.токен:
            # Кука, а не localStorage: гейт платных глав серверный
            # (_handle_edu → is_pro), а обычная навигация заголовков не шлёт.
            ctx.add_cookies([{"name": "sbf_session", "value": а.токен,
                              "url": а.база}])
            ctx.add_init_script(
                f"try {{ localStorage.setItem('sbf_token', {json.dumps(а.токен)}); }}"
                " catch (e) {}")
        print(f"{'страница':22} {'цели<44':>8} {'из них<24':>10} {'без подписи':>12} "
              f"{'фреймы':>7} {'прокрутка':>10} {'вложено':>8} {'текста':>7}")
        for путь in (а.url or СТРАНИЦЫ):
            строка = {}
            for имя, ш in (("desktop", 1366), ("mobile", 390)):
                строка[имя] = прогон(ctx, путь, ш, база=а.база)
            # Состояния за вкладками меряются отдельным прогоном: иначе
            # элементы, которых нет в DOM до клика, попадают в отчёт нулём.
            for подпись, _ in ПОДГОТОВКА.get(путь, []):
                строка[f"mobile+{подпись}"] = прогон(ctx, путь, 390, готовить=True, база=а.база)
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
            if m.get("ошибки_страницы"):
                пусто += f"  ✗ {m['ошибки_страницы'][0][:60]}"
            print(f"{путь:22} {len(m['цели']):8} {жёстко:10} {len(m['подписи']):12} "
                  f"{len(m['фреймы']):7} {len(m['прокрутка']):10} "
                  f"{len(m.get('вложенные', [])):8} {m.get('текста', 0):7}{пусто}")
            if а.подробно:
                for в in m.get("вложенные", [])[:6]:
                    print(f"      вложено: {в['кто']} {в['w']}×{в['h']} внутри {в['внутри']}  «{в['текст']}»")
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
          f"прокрутка {сумма('прокрутка')}, вложенные {сумма('вложенные')} "
          f"(по всем прогонам)")

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
            for к in ("цели", "подписи", "фреймы", "прокрутка", "вложенные"):
                с, д = len(б.get(к, [])), len(м.get(к, []))
                if с or д:
                    знак = "=" if с == д else ("↓" if д < с else "↑")
                    части.append(f"{к} {с}→{д} {знак}")
            print(f"  {путь:22} " + "  ".join(части))
    return 0


if __name__ == "__main__":
    sys.exit(main())
