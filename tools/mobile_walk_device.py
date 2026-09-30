#!/usr/bin/env python3
"""Обход всего сайта на ЖИВОМ телефоне: снимок экрана + диагностика на каждой странице.

ЗАЧЕМ ОТДЕЛЬНО ОТ mobile_real_device.py. Тот умеет открыть один адрес и снять
замер. Здесь нужен обход: тридцать страниц подряд, и на каждой — не только
ширина, но и то, чего замер ширины не видит вовсе:

  • ошибки в консоли (Runtime.exceptionThrown, Log.entryAdded);
  • запросы, которые не дошли: 4xx/5xx и оборванные (Network.loadingFailed);
  • пустые блоки — секция есть, содержимого в ней нет;
  • сам снимок экрана: половина поломок видна только глазами, и метрика,
    которая их не ловит, будет бодро рапортовать «ноль».

🔴 ПОЧЕМУ ВКЛАДКА ОДНА И ТА ЖЕ. Первый заход открывался через `am start` на
каждый адрес — Chrome заводил новую вкладку на каждую страницу, и к концу
обхода на телефоне владельца висело тридцать лишних вкладок. Теперь адрес
открывается один раз, дальше та же вкладка переводится через Page.navigate.

🔴 ЧЕГО ЭТОТ ФАЙЛ НЕ ДЕЛАЕТ. Не нажимает, не вводит текст, не трогает чужие
вкладки и не печатает их адреса — только их количество. На устройстве
владельца открыты его аккаунты.

Запуск:
    python3 tools/mobile_walk_device.py --база https://lp.sbfconsult.com
    python3 tools/mobile_walk_device.py --только /journal /chart.html
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

СНИМКИ = Path("/tmp/sbf_walk")

# Список повторяет tools/mobile_sweep.py: обе проверки обязаны ходить по
# одним и тем же адресам, иначе «на телефоне чисто» и «в эмуляторе чисто»
# будут про разные наборы страниц.
СТРАНИЦЫ = [
    "/", "/grafik", "/chart.html", "/journal", "/brokers", "/brokers/xm",
    "/brokers/avatrade", "/glossary", "/privacy", "/register", "/login",
    "/survey", "/edu/", "/edu/calendar", "/edu/glossary",
] + [f"/edu/b/{i}" for i in range(1, 16)]

ЗАМЕР_JS = r"""
(() => {
  const ш = window.innerWidth;
  const прокрутки = [...document.querySelectorAll('*')].filter(el => {
    const s = getComputedStyle(el);
    return s.overflowX === 'auto' || s.overflowX === 'scroll';
  });
  const канд = [];
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden') continue;
    let закреплён = false;
    for (let n = el; n && n !== document.body; n = n.parentElement) {
      if (getComputedStyle(n).position === 'fixed') { закреплён = true; break; }
    }
    if (закреплён) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const перелёт = Math.round(r.right - ш);
    if (перелёт <= 1) continue;
    if (прокрутки.some(p => p !== el && p.contains(el))) continue;
    if (Math.abs(Math.round(r.left) + перелёт) <= 2) continue;
    канд.push({el, перелёт, r});
  }
  const набор = new Set(канд.map(k => k.el));
  const вышли = [];
  for (const k of канд) {
    let p = k.el.parentElement, есть = false;
    while (p) { if (набор.has(p)) { есть = true; break; } p = p.parentElement; }
    if (есть) continue;
    вышли.push({перелёт: k.перелёт,
      что: k.el.tagName.toLowerCase() + '.' + (k.el.className||'').toString().slice(0,24),
      текст: (k.el.textContent||'').replace(/\s+/g,' ').trim().slice(0,44)});
  }
  вышли.sort((a,b) => b.перелёт - a.перелёт);

  // 🔴 Пустой блок — это поломка, которую ширина не видит. Секция на месте,
  // рамка на месте, внутри ничего: ровно так выглядели четыре станции
  // хроники и белое поле графика. Считаем заметные блоки без текста, без
  // картинки и без холста.
  const пустые = [];
  for (const el of document.querySelectorAll('section, .card, .panel, .h-artwork, [id^=sec]')) {
    const r = el.getBoundingClientRect();
    if (r.height < 60 || r.width < 60) continue;
    const текст = (el.textContent||'').trim().length;
    const медиа = el.querySelector('img, svg, canvas, picture, video');
    if (текст < 3 && !медиа) {
      пустые.push({что: el.tagName.toLowerCase() + '.' + (el.className||'').toString().slice(0,24),
                   h: Math.round(r.height)});
    }
  }
  return JSON.stringify({
    адрес: location.pathname,
    заголовок: document.title.slice(0, 60),
    ширина: ш,
    высота_страницы: document.documentElement.scrollHeight,
    экранов: +(document.documentElement.scrollHeight / window.innerHeight).toFixed(1),
    шире_на: Math.round(document.documentElement.scrollWidth - ш),
    вылезло: вышли.length,
    верх: вышли.slice(0, 4),
    пустых: пустые.length,
    пустые: пустые.slice(0, 3),
    текста: (document.body.innerText || '').trim().length,
    картинок: document.querySelectorAll('img').length,
    // 🔴 Картинка без src — не битая. Первый прогон отрапортовал «битая
    // картинка» на всех тридцати страницах подряд, и это выглядело как
    // сквозной дефект в шапке. На деле это <img> нулевого размера внутри
    // виджета отзыва: он ждёт скриншот, который приложит человек, и до
    // тех пор у него нет src вовсе. Признак complete && naturalWidth===0
    // верен для такого элемента, поэтому проверка обязана требовать ещё
    // и src, и видимый размер: иначе тридцать ложных тревог утопят две
    // настоящие находки.
    битых_картинок: [...document.querySelectorAll('img')]
      .filter(i => i.complete && i.naturalWidth === 0
                   && i.getAttribute('src')
                   && i.getBoundingClientRect().width > 0).length,
  });
})()
"""


def _adb(*args: str) -> str:
    return subprocess.run(["adb", *args], capture_output=True, text=True).stdout


def устройство() -> str | None:
    строки = _adb("devices").splitlines()[1:]
    for s in строки:
        if s.strip().endswith("device"):
            return s.split()[0]
    return None


class Вкладка:
    """Одно соединение с вкладкой Chrome на телефоне."""

    def __init__(self, ws_url: str):
        import websocket
        # suppress_origin обязателен: Chrome отвергает подключение с
        # заголовком Origin. Подробности — в mobile_real_device.py.
        self.ws = websocket.create_connection(ws_url, timeout=30,
                                              suppress_origin=True)
        self._id = 0
        self.ошибки: list[str] = []
        self.отказы: list[str] = []
        for домен in ("Runtime.enable", "Log.enable", "Network.enable",
                      "Page.enable"):
            self.вызов(домен)

    def вызов(self, метод: str, **параметры):
        self._id += 1
        мой = self._id
        self.ws.send(json.dumps({"id": мой, "method": метод,
                                 "params": параметры or {}}))
        while True:
            соб = json.loads(self.ws.recv())
            self._событие(соб)
            if соб.get("id") == мой:
                return соб

    def _событие(self, соб: dict):
        м = соб.get("method")
        п = соб.get("params", {})
        if м == "Runtime.exceptionThrown":
            д = п.get("exceptionDetails", {})
            self.ошибки.append((д.get("exception", {}).get("description")
                                or д.get("text") or "?")[:140])
        elif м == "Log.entryAdded" and п.get("entry", {}).get("level") == "error":
            self.ошибки.append(str(п["entry"].get("text"))[:140])
        elif м == "Network.loadingFailed" and not п.get("canceled"):
            self.отказы.append(str(п.get("errorText"))[:60])
        elif м == "Network.responseReceived":
            от = п.get("response", {})
            if от.get("status", 200) >= 400:
                self.отказы.append(f"{от['status']} {от.get('url','')[-58:]}")

    def подождать(self, секунд: float):
        """Дать странице поработать, продолжая собирать события."""
        конец = time.time() + секунд
        self.ws.settimeout(0.4)
        while time.time() < конец:
            try:
                self._событие(json.loads(self.ws.recv()))
            except Exception:
                pass
        self.ws.settimeout(30)

    def чисто(self):
        self.ошибки.clear()
        self.отказы.clear()


def снимок(куда: Path) -> bool:
    сырое = subprocess.run(["adb", "exec-out", "screencap", "-p"],
                           capture_output=True)
    if not сырое.stdout:
        return False
    куда.write_bytes(сырое.stdout)
    return True


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--база", default="https://lp.sbfconsult.com")
    p.add_argument("--только", nargs="*", default=None)
    p.add_argument("--пауза", type=float, default=6.0)
    а = p.parse_args()

    d = устройство()
    if not d:
        print("телефон не виден: adb devices пуст")
        sys.exit(1)
    subprocess.run(["adb", "-s", d, "forward", "tcp:9222",
                    "localabstract:chrome_devtools_remote"], check=False)
    СНИМКИ.mkdir(parents=True, exist_ok=True)

    страницы = а.только or СТРАНИЦЫ
    хост = а.база.split("//")[-1].split("/")[0]

    # Открываем первый адрес — дальше переводим ту же вкладку.
    _adb("-s", d, "shell", "am", "start", "-a", "android.intent.action.VIEW",
         "-d", а.база + страницы[0], "com.android.chrome")
    time.sleep(8)

    with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=6) as r:
        вкладки = json.load(r)
    наши = [t for t in вкладки if t.get("type") == "page" and хост in t.get("url", "")]
    if not наши:
        print(f"вкладки с {хост} не видно (всего открыто: {len(вкладки)}).")
        sys.exit(1)
    print(f"вкладка найдена, всего открыто на телефоне: {len(вкладки)}")

    в = Вкладка(наши[0]["webSocketDebuggerUrl"])
    итог = []
    for i, путь in enumerate(страницы, 1):
        url = а.база + путь
        в.чисто()
        в.вызов("Page.navigate", url=url)
        в.подождать(а.пауза)
        ответ = в.вызов("Runtime.evaluate", expression=ЗАМЕР_JS,
                        returnByValue=True, awaitPromise=False)
        сырое = ответ.get("result", {}).get("result", {}).get("value")
        if not сырое:
            print(f"{i:3d}. {путь:18} замер не вернулся")
            итог.append({"адрес": путь, "провал": True})
            continue
        z = json.loads(сырое)
        имя = путь.strip("/").replace("/", "_") or "главная"
        z["снимок"] = str(СНИМКИ / f"{имя}.png") if снимок(СНИМКИ / f"{имя}.png") else None
        z["ошибок"] = len(в.ошибки)
        z["ошибки"] = в.ошибки[:3]
        z["отказов"] = len(в.отказы)
        z["отказы"] = в.отказы[:3]
        итог.append(z)
        флаг = ""
        if z["шире_на"] > 1 or z["вылезло"]:
            флаг += f" ШИРИНА+{z['шире_на']}"
        if z["ошибок"]:
            флаг += f" ОШИБОК={z['ошибок']}"
        if z["отказов"]:
            флаг += f" ОТКАЗОВ={z['отказов']}"
        if z["пустых"]:
            флаг += f" ПУСТЫХ={z['пустых']}"
        if z["битых_картинок"]:
            флаг += f" БИТЫХ_КАРТИНОК={z['битых_картинок']}"
        print(f"{i:3d}. {путь:18} {z['экранов']:5.1f} экр  текста {z['текста']:6d}"
              f"  картинок {z['картинок']:3d}{флаг}")

    (СНИМКИ / "итог.json").write_text(
        json.dumps(итог, ensure_ascii=False, indent=1), encoding="utf-8")
    плохо = [z for z in итог if z.get("провал") or z.get("шире_на", 0) > 1
             or z.get("ошибок") or z.get("отказов") or z.get("пустых")
             or z.get("битых_картинок")]
    print(f"\nстраниц пройдено: {len(итог)}, с замечаниями: {len(плохо)}")
    print(f"снимки: {СНИМКИ}/  ·  подробности: {СНИМКИ}/итог.json")


if __name__ == "__main__":
    main()
