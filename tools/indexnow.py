#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""indexnow.py — сообщить Bing, Yandex и др. о новых и изменённых страницах.

🔴 ЗАЧЕМ. ChatGPT Search и Copilot во многом берут выдачу из индекса Bing,
Алиса — из Яндекса. Оба поддерживают IndexNow: один POST — и адрес попадает
в очередь на обход за минуты, а не за недели. Особенно важно для
датированных брифов sbfconsult.com/brief/<дата>.html: их ценность — свежесть.

Ключ не секретный по устройству протокола: он лежит в открытом файле
https://<домен>/<КЛЮЧ>.txt, и поисковик проверяет, что его содержимое
совпадает с ключом из запроса. Файлы ключа:
    lp.sbfconsult.com → web/<КЛЮЧ>.txt            (этот репозиторий)
    sbfconsult.com    → <КЛЮЧ>.txt в корне сайта  (репозиторий sbf-nexus)

Запуск:
    python3 tools/indexnow.py                       # оба sitemap, только новое
    python3 tools/indexnow.py --all                 # всё из sitemap заново
    python3 tools/indexnow.py --url https://sbfconsult.com/brief/2026-09-30.html
    python3 tools/indexnow.py --dry-run             # показать, ничего не слать

Уже отправленные адреса (с их lastmod) помнятся в data/indexnow_sent.json:
повторно шлём только то, что появилось или поменяло lastmod.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

КОРЕНЬ = Path(__file__).resolve().parents[1]
КЛЮЧ = "7a03d9d8dbb9e212c083081e54ad5773"
ТОЧКА = "https://api.indexnow.org/indexnow"   # раздаёт всем участникам протокола
КАРТЫ = ("https://lp.sbfconsult.com/sitemap.xml",
         "https://sbfconsult.com/sitemap.xml")
СОСТОЯНИЕ = КОРЕНЬ / "data" / "indexnow_sent.json"
ПАЧКА = 10_000                                  # лимит протокола на один запрос
NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


# 🔴 СВОЙ User-Agent ОБЯЗАТЕЛЕН: Cloudflare отдаёт 403 стандартному
# urllib ("Python-urllib/3.x"). Проверено 30.09.2026 — curl на те же адреса
# получал 200, а скрипт 403 на обе карты сайта. Ловушка в том, что дальше
# он печатал «нового нет — отправлять нечего» и выходил с кодом 0: молчание
# вместо ошибки, то есть cron годами рапортовал бы об успехе, не отправив
# ни одного адреса.
АГЕНТ = "SBFIndexNow/1.0 (+https://lp.sbfconsult.com/)"


def читать_карту(url: str) -> dict[str, str]:
    """{адрес: lastmod} из sitemap (включая sitemap index на один уровень)."""
    запрос = urllib.request.Request(url, headers={"User-Agent": АГЕНТ})
    with urllib.request.urlopen(запрос, timeout=30) as r:
        корень = ET.fromstring(r.read())
    итог: dict[str, str] = {}
    for sm in корень.findall("sm:sitemap", NS):
        итог.update(читать_карту(sm.findtext("sm:loc", "", NS).strip()))
    for u in корень.findall("sm:url", NS):
        loc = u.findtext("sm:loc", "", NS).strip()
        if loc:
            итог[loc] = u.findtext("sm:lastmod", "", NS).strip()
    return итог


def отправить(хост: str, адреса: list[str]) -> int:
    тело = json.dumps({
        "host": хост,
        "key": КЛЮЧ,
        "keyLocation": f"https://{хост}/{КЛЮЧ}.txt",
        "urlList": адреса,
    }).encode("utf-8")
    запрос = urllib.request.Request(
        ТОЧКА, data=тело, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(запрос, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def main() -> int:
    р = argparse.ArgumentParser()
    р.add_argument("--url", action="append", default=[],
                   help="отправить только эти адреса (можно несколько раз)")
    р.add_argument("--all", action="store_true", help="игнорировать память об отправленном")
    р.add_argument("--dry-run", action="store_true")
    а = р.parse_args()

    отправлено: dict[str, str] = {}
    if СОСТОЯНИЕ.exists() and not а.all:
        отправлено = json.loads(СОСТОЯНИЕ.read_text(encoding="utf-8"))

    if а.url:
        кандидаты = {u: "" for u in а.url}
    else:
        кандидаты, карт_прочитано = {}, 0
        for карта in КАРТЫ:
            try:
                кандидаты.update(читать_карту(карта))
                карт_прочитано += 1
            except Exception as e:                      # одна карта не должна ронять другую
                print(f"✗ {карта}: {e}", file=sys.stderr)
        # 🔴 «Ни одной карты не прочитано» — это ОТКАЗ, а не «нечего слать».
        # Без этой ветки 403 от Cloudflare выглядел ровно как пустая очередь.
        if not карт_прочитано:
            print("✗ ни одна карта сайта не прочитана — отправлять нечего, "
                  "и это ошибка, а не пустая очередь", file=sys.stderr)
            return 1
        кандидаты = {u: lm for u, lm in кандидаты.items()
                     if u not in отправлено or (lm and lm != отправлено[u])}

    по_хостам: dict[str, list[str]] = defaultdict(list)
    for u in кандидаты:
        по_хостам[urlparse(u).netloc].append(u)

    if not по_хостам:
        print("нового нет — отправлять нечего")
        return 0

    код_выхода = 0
    for хост, адреса in по_хостам.items():
        for i in range(0, len(адреса), ПАЧКА):
            пачка = адреса[i:i + ПАЧКА]
            if а.dry_run:
                print(f"[dry-run] {хост}: {len(пачка)} адрес(ов)")
                continue
            статус = отправить(хост, пачка)
            # 200 — принято, 202 — принято, ключ ещё проверяется.
            ок = статус in (200, 202)
            print(f"{'✓' if ок else '✗'} {хост}: {len(пачка)} адрес(ов) → HTTP {статус}")
            if ок:
                for u in пачка:
                    отправлено[u] = кандидаты.get(u, "")
            else:
                код_выхода = 1
                if статус == 403:
                    print(f"   ключ не подтверждён: проверьте https://{хост}/{КЛЮЧ}.txt",
                          file=sys.stderr)

    if not а.dry_run:
        СОСТОЯНИЕ.parent.mkdir(parents=True, exist_ok=True)
        СОСТОЯНИЕ.write_text(json.dumps(отправлено, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    return код_выхода


if __name__ == "__main__":
    sys.exit(main())
