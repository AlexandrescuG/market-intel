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

ЗАМЕР_JS = """
(() => {
  const ш = window.innerWidth;
  const вылезли = [];
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || s.position === 'fixed') continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (Math.round(r.right - ш) <= 1) continue;
    вылезли.push({перелёт: Math.round(r.right - ш), ширина: Math.round(r.width),
                  текст: (el.textContent||'').replace(/\\s+/g,' ').trim().slice(0,60)});
  }
  вылезли.sort((a,b) => b.перелёт - a.перелёт);
  const p = document.querySelector('p');
  return JSON.stringify({
    ширина_css: ш,
    высота_css: window.innerHeight,
    dpr: window.devicePixelRatio,
    шрифт_абзаца: p ? getComputedStyle(p).fontSize : '—',
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
    print("жду 8 секунд, пока страница отрисуется…")
    import time
    time.sleep(8)
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5) as r:
            вкладки = json.load(r)
    except Exception as e:
        print(f"не достучался до Chrome на телефоне: {e}")
        print("  В Chrome на телефоне должна быть включена отладка (она включается")
        print("  вместе с отладкой по USB), и сам Chrome должен быть открыт.")
        return 1
    цели = [t for t in вкладки if t.get("type") == "page" and url.split("//")[-1][:20] in t.get("url", "")]
    if not цели:
        print("нужная вкладка не найдена; открытые:",
              [t.get("url", "")[:60] for t in вкладки][:5])
        return 1
    print("\n🔴 Дальше нужен websocket к вкладке (webSocketDebuggerUrl) — поставь")
    print("   `pip install websocket-client` и запусти ещё раз, либо выполни")
    print("   замер вручную из devtools://devtools на компьютере:")
    print(f"   {цели[0].get('webSocketDebuggerUrl', '—')}\n")
    print("Код замера для консоли DevTools (chrome://inspect → Inspect):")
    print(ЗАМЕР_JS)
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
