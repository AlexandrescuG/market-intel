"""Проверка на ЖИВОМ телефоне через adb — не эмуляция.

ЗАЧЕМ, если рядом лежит tools/mobile_devices.py. Потому что эмуляция не
воспроизводит три вещи, а они как раз те, на которых вёрстка и сыплется:

  1. Размер шрифта, выставленный человеком в Android или в самом Chrome.
     Читатель с «крупным шрифтом» видит другую страницу. Эмулировать это
     нечем: CDP Page.setFontSizes задаёт размер по умолчанию и на наш CSS с
     явными px не влияет — проверено, менялось ровно ничего.
  2. Text autosizing Chrome для Android — блинковская добавка к размеру
     текста в узких колонках.
  3. Строку адреса, которая уезжает при скролле и меняет высоту вьюпорта на
     ходу: всё, что считает 100vh, на телефоне дышит.

КАК ПОЛЬЗОВАТЬСЯ.
  1. На телефоне: Настройки → О телефоне → семь раз по «Номер сборки»,
     затем Для разработчиков → Отладка по USB — включить.
  2. Подключить кабелем, на телефоне разрешить отладку с этого компьютера.
  3. `python3 tools/mobile_real_device.py --проверить` — увидеть телефон.
  4. `python3 tools/mobile_real_device.py --замер --url https://lp.sbfconsult.com/edu/b/2`

🔴 ЧТО ЭТОТ ФАЙЛ НЕ ДЕЛАЕТ. Он не листает, не нажимает и ничего не вводит на
чужом телефоне: только открывает адрес и снимает замеры со страницы. На
устройстве владельца открыты его аккаунты, и автоматизация, которая «просто
потыкает», — это автоматизация, которая однажды потыкает не туда.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request

# 🔴 ЭТО ДОЛЖНО СОВПАДАТЬ С ЗАМЕРОМ В tools/mobile_devices.py, ИНАЧЕ
# СРАВНИВАТЬ НЕЧЕГО. Первый прогон на живом телефоне дал «99 элементов
# вылезло» против «6» на эмуляции — не потому, что телефон хуже, а потому,
# что здесь не было отсева того, что лежит внутри собственной
# горизонтальной прокрутки (строка котировок и есть такая прокрутка, в ней
# полсотни элементов «вылезают» по замыслу). Две линейки — две правды;
# ровно этой ошибкой я уже ломал метрику Эпицентра.
ЗАМЕР_JS = """
(() => {
  const ш = window.innerWidth;
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
    if (Math.round(r.right - ш) <= 1) continue;
    if (прокрутки.some(p => p !== el && p.contains(el))) continue;
    кандидаты.push(el);
  }
  const набор = new Set(кандидаты);
  const вылезли = [];
  for (const el of кандидаты) {
    let p = el.parentElement, вложен = false;
    while (p) { if (набор.has(p)) { вложен = true; break; } p = p.parentElement; }
    if (вложен) continue;
    const r = el.getBoundingClientRect();
    вылезли.push({перелёт: Math.round(r.right - ш), ширина: Math.round(r.width),
                  текст: (el.textContent||'').replace(/\\s+/g,' ').trim().slice(0,58)});
  }
  вылезли.sort((a,b) => b.перелёт - a.перелёт);
  const p = document.querySelector('#sbf-book-root p') || document.querySelector('p');
  return JSON.stringify({
    ширина_css: ш,
    высота_css: window.innerHeight,
    dpr: window.devicePixelRatio,
    шрифт_абзаца: p ? getComputedStyle(p).fontSize : '—',
    заголовок: (document.title || '').slice(0, 50),
    абзацев_на_странице: document.querySelectorAll('#sbf-book-root p').length,
    страница_шире_на: Math.round(document.documentElement.scrollWidth - ш),
    виновников: вылезли.length,
    верх: вылезли.slice(0, 8),
  });
})()
"""


def _adb(*args: str) -> str:
    return subprocess.run(["adb", *args], capture_output=True, text=True).stdout.strip()


def устройства() -> list[str]:
    строки = _adb("devices").splitlines()[1:]
    return [s.split("\t")[0] for s in строки if s.strip().endswith("device")]


def проверить() -> int:
    найдены = устройства()
    if not найдены:
        print("Телефон не виден.\n"
              "  1. Отладка по USB включена? (Для разработчиков → Отладка по USB)\n"
              "  2. Кабель воткнут, и на телефоне нажато «Разрешить»?\n"
              "  3. `adb devices` должен показать строку с «device», а не «unauthorized».")
        return 1
    for d in найдены:
        модель = _adb("-s", d, "shell", "getprop", "ro.product.model")
        версия = _adb("-s", d, "shell", "getprop", "ro.build.version.release")
        плотность = _adb("-s", d, "shell", "wm", "density")
        размер = _adb("-s", d, "shell", "wm", "size")
        шрифт = _adb("-s", d, "shell", "settings", "get", "system", "font_scale")
        print(f"  {d}  {модель}, Android {версия}")
        print(f"     {размер}, {плотность}")
        print(f"     масштаб шрифта в системе: {шрифт or '1.0 (по умолчанию)'}")
    return 0


def замер(url: str) -> int:
    найдены = устройства()
    if not найдены:
        return проверить()
    d = найдены[0]
    # Пробрасываем порт отладки Chrome с телефона на этот компьютер.
    subprocess.run(["adb", "-s", d, "forward", "tcp:9222",
                    "localabstract:chrome_devtools_remote"], check=False)
    _adb("-s", d, "shell", "am", "start", "-a", "android.intent.action.VIEW",
         "-d", url, "com.android.chrome")
    print(f"открыл на телефоне: {url}")
    print("жду 15 секунд, пока страница отрисуется…")
    import time
    time.sleep(15)
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5) as r:
            вкладки = json.load(r)
    except Exception as e:
        print(f"не достучался до Chrome на телефоне: {e}")
        print("  В Chrome на телефоне должна быть включена отладка (она включается")
        print("  вместе с отладкой по USB), и сам Chrome должен быть открыт.")
        return 1
    # 🔴 Ищем по ПУТИ, а не по хосту. Первый прогон искал по хосту, зацепил
    # уже открытую вкладку /calendar и бодро отчитался о замере — числа были
    # настоящие, только не той страницы. Заголовок в выводе («SBF ·
    # Экономический календарь») это и выдал. Поэтому заголовок и число
    # абзацев печатаются всегда: замер обязан говорить, ЧТО он измерил.
    путь = "/" + url.split("//")[-1].split("/", 1)[-1].rstrip("/")
    хост = url.split("//")[-1].split("/")[0]
    цели = [t for t in вкладки if t.get("type") == "page"
            and хост in t.get("url", "")
            and t.get("url", "").rstrip("/").endswith(путь)]
    if not цели:
        # Chrome мог не открыть новую вкладку по интенту (переиспользовал
        # существующую, увёл на пейволл, открыл в другом профиле). Тогда
        # берём любую вкладку нашего раздела и ГОВОРИМ, какую именно.
        раздел = путь.rsplit("/", 1)[0] or путь
        цели = [t for t in вкладки if t.get("type") == "page"
                and хост in t.get("url", "") and раздел in t.get("url", "")]
        if цели:
            print(f"точного адреса нет, беру вкладку раздела: {цели[0].get('url','')}")
    if not цели:
        # 🔴 Чужие вкладки не печатаем. На телефоне владельца открыто его
        # личное, и «для отладки покажем список» — ровно тот случай, когда
        # удобство инструмента оплачено чужой приватностью.
        print(f"вкладки с {хост} не видно (всего открыто: {len(вкладки)}).")
        print("Открой нужную страницу на телефоне сам и запусти замер ещё раз.")
        return 1
    if len(цели) > 1:
        print(f"вкладок с {хост}: {len(цели)}, беру самую свежую — {цели[0].get('url','')[:70]}")

    try:
        import websocket
    except ImportError:
        print("нужен websocket-client: pip install --break-system-packages websocket-client")
        print("\nлибо выполнить это в консоли DevTools (chrome://inspect → Inspect):")
        print(ЗАМЕР_JS)
        return 1

    # 🔴 suppress_origin обязателен. Chrome отвергает подключение с
    # заголовком Origin («Rejected an incoming WebSocket connection from the
    # http://127.0.0.1:9222 origin») — защита от того, чтобы страница в
    # браузере сама себе не открыла отладочный канал. Библиотека шлёт Origin
    # по умолчанию; отключаем его, а не ослабляем защиту на телефоне флагом
    # --remote-allow-origins=*.
    ws = websocket.create_connection(цели[0]["webSocketDebuggerUrl"],
                                     timeout=20, suppress_origin=True)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": ЗАМЕР_JS,
                                       "returnByValue": True,
                                       "awaitPromise": False}}))
        while True:
            ответ = json.loads(ws.recv())
            if ответ.get("id") == 1:
                break
    finally:
        ws.close()

    рез = ответ.get("result", {}).get("result", {}).get("value")
    if not рез:
        print("замер не вернулся:", json.dumps(ответ, ensure_ascii=False)[:300])
        return 1
    d = json.loads(рез)
    print(f"\n── ЖИВОЙ ТЕЛЕФОН ──────────────────────────────────")
    print(f"  ширина CSS:        {d['ширина_css']} px")
    print(f"  высота CSS:        {d['высота_css']} px")
    print(f"  плотность (dpr):   {d['dpr']}")
    print(f"  шрифт абзаца:      {d['шрифт_абзаца']}")
    print(f"  страница:          {d.get('заголовок','—')}")
    print(f"  абзацев главы:     {d.get('абзацев_на_странице', 0)}")
    print(f"  страница шире на:  {d['страница_шире_на']} px")
    print(f"  элементов вылезло: {d['виновников']}")
    for v in d["верх"]:
        print(f"     +{v['перелёт']:4d} px  ширина {v['ширина']:4d}  «{v['текст']}»")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--проверить", action="store_true")
    ap.add_argument("--замер", action="store_true")
    ap.add_argument("--url", default="https://lp.sbfconsult.com/edu/b/2")
    a = ap.parse_args()
    if a.замер:
        sys.exit(замер(a.url))
    sys.exit(проверить())


if __name__ == "__main__":
    main()
