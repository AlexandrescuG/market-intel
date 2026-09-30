#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prepare_guide_images.py — скриншоты гайдов брокеров в веб-формат.

🔴 ЗАЧЕМ. Страницы /brokers/<id> — это лидогенерация: человек пришёл
открывать счёт и смотрит, как это делается. Гайд весил 2.2 МБ по сети,
LCP на медленном канале 4.2 с. 88 снимков лежат в PNG по 300–1170 КБ,
потому что PNG — формат для скриншота с резкими границами, и он честно
хранит каждый пиксель интерфейса без потерь. Только смотрят их в 780 px
шириной на desktop и 350 px на телефоне, а исходники 1280–1440 px.

Что делает скрипт:
  1. кладёт рядом с каждым PNG `.webp` (quality 88) шириной не больше
     1560 px — это двойной размер показа, запас под retina;
  2. НЕ увеличивает то, что уже меньше: растянутый скриншот не станет
     подробнее, только тяжелее;
  3. записывает в JSON гайда поля `img_webp`, `img_w`, `img_h` — по всем
     языковым версиям сразу, потому что ru/en/ro ссылаются на одни файлы.

Про качество: на ширине показа (780 px) q80 и q88 от оригинала
неотличимы — сверял выдернутым кадром на самом текстовом скриншоте
(договор FxPro мелким шрифтом). Взято q88: разница в весе между ними
невелика, а запас на будущие скриншоты с более мелким текстом полезен.

Про размеры: `img_w`/`img_h` нужны не для красоты. Без них браузер не
знает пропорций до загрузки, оставляет нулевую высоту и двигает страницу,
когда картинка приходит, — тот же класс проблемы, что чинили в CLS.

PNG остаются на диске: они и архив, и запасной вариант внутри <picture>
для браузеров без webp. Пользователь их не качает.

Запуск:
    python3 tools/prepare_guide_images.py            # всё, чего ещё нет
    python3 tools/prepare_guide_images.py --заново   # пересобрать всё
    python3 tools/prepare_guide_images.py --проверить # ничего не писать
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

КОРЕНЬ = Path(__file__).resolve().parents[1]
СНИМКИ = КОРЕНЬ / "web" / "assets" / "guides"
ГАЙДЫ = КОРЕНЬ / "web" / "data" / "guides"
ВЕБ = КОРЕНЬ / "web"

МАКС_ШИРИНА = 1560   # 780 px показа × 2 (retina)
КАЧЕСТВО = 88


def собрать(png: Path, заново: bool) -> tuple[Path, int, int, int, int] | None:
    """PNG → webp рядом. Возвращает (путь, w, h, было_байт, стало_байт)."""
    webp = png.with_suffix(".webp")
    if webp.exists() and not заново:
        with Image.open(webp) as им:
            return webp, им.width, им.height, png.stat().st_size, webp.stat().st_size
    try:
        with Image.open(png) as им:
            им.load()
            кадр = им.convert("RGB")
            if кадр.width > МАКС_ШИРИНА:
                в = round(кадр.height * МАКС_ШИРИНА / кадр.width)
                кадр = кадр.resize((МАКС_ШИРИНА, в), Image.LANCZOS)
            кадр.save(webp, "WEBP", quality=КАЧЕСТВО, method=6)
            return webp, кадр.width, кадр.height, png.stat().st_size, webp.stat().st_size
    except Exception as e:
        print(f"   ⚠ {png.relative_to(ВЕБ)}: {e}")
        return None


def проставить(карта: dict[str, dict], проверить: bool) -> tuple[int, int]:
    """Вписывает img_webp/img_w/img_h в каждый объект с полем `img`.

    Правит ВСЕ языковые версии: ru/en/ro ссылаются на одни и те же файлы,
    и если проставить размеры только в русской, английская страница
    продолжит прыгать — ровно тот случай, когда «починено» относится
    к одной трети пользователей.
    """
    тронуто = файлов = 0

    def обход(о) -> bool:
        изм = False
        if isinstance(о, dict):
            путь = о.get("img")
            if isinstance(путь, str) and путь in карта:
                д = карта[путь]
                for ключ, знач in (("img_webp", д["webp"]), ("img_w", д["w"]), ("img_h", д["h"])):
                    if о.get(ключ) != знач:
                        о[ключ] = знач
                        изм = True
            for v in о.values():
                if isinstance(v, (dict, list)) and обход(v):
                    изм = True
        elif isinstance(о, list):
            for v in о:
                if isinstance(v, (dict, list)) and обход(v):
                    изм = True
        return изм

    for ф in sorted(ГАЙДЫ.glob("*.json")):
        данные = json.loads(ф.read_text(encoding="utf-8"))
        if обход(данные):
            тронуто += 1
            файлов += 1
            if not проверить:
                ф.write_text(json.dumps(данные, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    return тронуто, файлов


def main() -> int:
    р = argparse.ArgumentParser()
    р.add_argument("--заново", action="store_true", help="пересобрать уже существующие webp")
    р.add_argument("--проверить", action="store_true", help="ничего не записывать")
    а = р.parse_args()

    пнг = sorted(СНИМКИ.rglob("*.png"))
    if not пнг:
        print(f"нет снимков в {СНИМКИ}")
        return 1

    карта: dict[str, dict] = {}
    было = стало = 0
    for п in пнг:
        итог = собрать(п, а.заново) if not а.проверить else None
        if а.проверить:
            webp = п.with_suffix(".webp")
            if not webp.exists():
                print(f"   нет webp: {п.relative_to(ВЕБ)}")
                continue
            with Image.open(webp) as им:
                итог = (webp, им.width, им.height, п.stat().st_size, webp.stat().st_size)
        if not итог:
            continue
        webp, w, h, б, с = итог
        было += б
        стало += с
        карта["/" + п.relative_to(ВЕБ).as_posix()] = {
            "webp": "/" + webp.relative_to(ВЕБ).as_posix(), "w": w, "h": h,
        }

    тронуто, _ = проставить(карта, а.проверить)

    print(f"снимков: {len(карта)} из {len(пнг)}")
    print(f"вес:     {было/1024/1024:.1f} МБ PNG → {стало/1024/1024:.1f} МБ webp "
          f"({100 - стало*100//max(было,1)}% меньше)")
    print(f"JSON:    обновлено файлов гайдов — {тронуто}")
    if а.проверить:
        print("(--проверить: на диск ничего не записано)")
    if len(карта) != len(пнг):
        print("⚠ часть снимков не собралась — смотри предупреждения выше; "
              "у них останется старый PNG, и это не поломка, а недоработка")
    return 0


if __name__ == "__main__":
    sys.exit(main())
