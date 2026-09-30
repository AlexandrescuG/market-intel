#!/usr/bin/env python3
"""tools/check_headings.py — h1, title и description по всей карте сайта.

ЗАЧЕМ. 30.09.2026 Bing Webmaster Tools на главной выдал три ошибки разом:
«Title too long», «Meta Description too long or too short», «H1 tag missing».
Прогон по всей карте показал, что это не про одну страницу: без h1 было
39 адресов из 51. Щуп нужен, чтобы находка не вернулась незамеченной —
заголовки правят в пяти разных местах (шаблоны, i18n, генератор текстового
слоя), и уследить за ними глазами нельзя.

🔴 СЧИТАТЬ НАДО ЭЛЕМЕНТЫ, А НЕ ВХОЖДЕНИЯ СТРОКИ «<h1».
Первая версия щупа обвинила главы 4 и 5 в трёх h1 на страницу. На самом
деле два из трёх лежали ВНУТРИ <script type="text/babel"> — это исходник
JSX, который компилируется в браузере, и для HTML-парсера это текст
скрипта, а не разметка. Ни один краулер их не увидит. Поэтому содержимое
script и style вырезается до подсчёта; без этого щуп ловит собственную
тень (тот же класс, что «мои щупы трижды обвинили рабочий код»).

Пороги взяты из того, на что ругается Bing:
    title        не длиннее 60 знаков
    description  от 25 до 160 знаков
    h1           ровно один на странице

Использование:
    python3 tools/check_headings.py [--base http://localhost:8085]
Код возврата 1, если есть нарушения — годится для проверки перед выкаткой.
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

АГЕНТ = {"User-Agent": "SBFHeadings/1.0"}
NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

TITLE_MAX = 60
DESC_MIN, DESC_MAX = 25, 160

_СКРИПТ = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.S | re.I)
_H1 = re.compile(r"<h1[\s>]", re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_DESC = re.compile(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', re.S | re.I)


def _достать(url: str) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers=АГЕНТ), timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def разметка(html: str) -> str:
    """HTML без содержимого script и style — только то, что парсер считает разметкой."""
    return _СКРИПТ.sub("", html)


def проверить(html: str) -> list[str]:
    чистый = разметка(html)
    беды = []

    n = len(_H1.findall(чистый))
    if n == 0:
        беды.append("нет h1")
    elif n > 1:
        беды.append(f"h1 несколько ({n})")

    м = _TITLE.search(чистый)
    t = (м.group(1).strip() if м else "")
    if not t:
        беды.append("нет title")
    elif len(t) > TITLE_MAX:
        беды.append(f"title {len(t)} знаков (макс {TITLE_MAX})")

    м = _DESC.search(чистый)
    d = (м.group(1).strip() if м else "")
    if not d:
        беды.append("нет description")
    elif not (DESC_MIN <= len(d) <= DESC_MAX):
        беды.append(f"description {len(d)} знаков (норма {DESC_MIN}-{DESC_MAX})")

    return беды


def main() -> int:
    р = argparse.ArgumentParser()
    р.add_argument("--base", default="http://localhost:8085",
                   help="куда ходить; карта сайта берётся оттуда же")
    а = р.parse_args()

    карта = ET.fromstring(_достать(а.base.rstrip("/") + "/sitemap.xml"))
    адреса = [u.findtext("sm:loc", "", NS) for u in карта.findall("sm:url", NS)]
    # В карте абсолютные боевые адреса; для локального прогона подменяем хост.
    корень = re.match(r"https?://[^/]+", адреса[0]).group(0) if адреса else ""

    плохих = 0
    for адрес in адреса:
        куда = адрес.replace(корень, а.base.rstrip("/")) if корень else адрес
        try:
            html = _достать(куда)
        except Exception as e:                      # noqa: BLE001
            print(f"✗ {адрес}: не открылась — {str(e)[:60]}")
            плохих += 1
            continue
        беды = проверить(html)
        if беды:
            плохих += 1
            print(f"✗ {адрес.replace(корень, '')or '/'}: {', '.join(беды)}")

    итог = f"проверено {len(адреса)}, с нарушениями {плохих}"
    print(("🔴 " if плохих else "✅ ") + итог)
    return 1 if плохих else 0


if __name__ == "__main__":
    sys.exit(main())
