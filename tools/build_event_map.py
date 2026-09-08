#!/usr/bin/env python3
"""tools/build_event_map.py — какие события календаря касаются какого инструмента.

ЗАЧЕМ. Слой «События» на графике читает таблицу `event_instrument_map`
(страна, инструмент, вес). В ней было 53 строки на 26 инструментов — только
реестр. На витрине инструментов 780, и на 754 из них кнопка «События» просто
не появлялась: на графике итальянского индекса не было ни решения ЕЦБ, ни
итальянской инфляции, хотя и то и другое двигает его напрямую.

ОТКУДА БЕРЁТСЯ СТРАНА. Не из справочника, которого нет, а из самого имени
инструмента — оно в каталоге снято с терминала брокера и устроено регулярно:

  • валютные пары   EURUSD → EU + US, USDJPY → US + JP (обе стороны котировки)
  • биржевые суффиксы `_BMW.DE` → DE, `_RYANAIR.UK` → GB, `_EXOR.IT` → IT
  • американские акции `#BOEING` → US (каталог брокера так помечает листинг США)
  • индексы по названию GERMANY_40 → DE, JAPAN_225 → JP, US_500 → US
  • сырьё и крипта — US: их двигает американская макростатистика (ставка,
    инфляция, запасы нефти), собственной страны у них нет

ВЕСА. 2 — событие страны самого инструмента (для EURUSD это EU и US). 1 —
событие США для всего остального: доллар и ставка ФРС двигают и немецкую
акцию, и золото, просто слабее. Обработчик графика фильтрует `weight>=1` и
скрывает низкую важность, а на дневках оставляет только высокую — то есть
шума от веса 1 не будет.

⚠️ ЧЕГО ЭТА КАРТА НЕ ДЕЛАЕТ. Она не утверждает, что событие сдвинет цену. Она
отвечает на вопрос «может ли это событие иметь отношение к этому инструменту»
— то есть отбирает, что показать рядом с графиком, а не предсказывает реакцию.

Запуск:  python3 tools/build_event_map.py [--dry] [--verbose]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOT_DB = "/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db"

# Страны, по которым в календаре реально есть события. Ставить в карту страну,
# которой нет в econ_events, — значит писать строки, которые никогда никому не
# пригодятся; список сверяется с базой при запуске.
FALLBACK_COUNTRY = "US"

# Код валюты → страна календаря. EUR → EU, а не список из двадцати стран:
# события еврозоны в календаре помечены именно так.
CCY_COUNTRY = {
    "USD": "US", "EUR": "EU", "JPY": "JP", "GBP": "GB", "AUD": "AU",
    "CAD": "CA", "CHF": "CH", "NZD": "NZ", "CNY": "CN", "CNH": "CN",
    "ZAR": "ZA", "KZT": "KZ", "AED": "AE", "TRY": "TR", "MXN": "MX",
    "KRW": "KR", "BRL": "BR", "CZK": "CZ", "HUF": "HU", "PLN": "PL",
    "SEK": "SE", "NOK": "NO", "DKK": "DK", "SGD": "SG", "HKD": "HK",
    "INR": "IN", "RUB": "RU", "ILS": "IL", "THB": "TH", "RON": "RO",
}

# Биржевой суффикс каталога → страна.
SUFFIX_COUNTRY = {
    ".DE": "DE", ".UK": "GB", ".IT": "IT", ".FR": "FR", ".ES": "ES",
    ".NL": "NL", ".BE": "BE", ".PT": "PT", ".AT": "AT", ".FI": "FI",
    ".CH": "CH", ".SE": "SE", ".NO": "NO", ".DK": "DK", ".IE": "IE",
    ".PL": "PL", ".JP": "JP", ".AU": "AU", ".CA": "CA", ".HK": "HK",
}

# Индексы: кусок имени → страна. Проверяется по вхождению, поэтому порядок
# важен — сначала длинные и однозначные.
INDEX_COUNTRY = [
    ("GERMANY", "DE"), ("FRANCE", "FR"), ("ITALY", "IT"), ("SPAIN", "ES"),
    ("NETHERLANDS", "NL"), ("SWISS", "CH"), ("SWITZERLAND", "CH"),
    ("UK_", "GB"), ("UK100", "GB"), ("JAPAN", "JP"), ("HONGKONG", "HK"),
    ("HONG_KONG", "HK"), ("CHINA", "CN"), ("AUS", "AU"), ("AUSTRALIA", "AU"),
    ("CANADA", "CA"), ("US_", "US"), ("USA", "US"), ("EUROPE", "EU"),
    ("EU_", "EU"), ("EUROSTOXX", "EU"), ("STOXX", "EU"), ("POLAND", "PL"),
    ("PORTUGAL", "PT"), ("NORWAY", "NO"), ("SWEDEN", "SE"), ("DENMARK", "DK"),
    ("TAIWAN", "TW"), ("INDIA", "IN"), ("BRAZIL", "BR"), ("MEXICO", "MX"),
    ("SOUTHAFRICA", "ZA"), ("SINGAPORE", "SG"), ("KOREA", "KR"),
]

_CCY = re.compile(r"^([A-Z]{3})([A-Z]{3})$")


def countries_for(symbol: str, category: str | None, name: str | None) -> list[str]:
    """Страны, чьи события имеют отношение к инструменту. Первая — «своя»."""
    s = symbol.upper()

    # Валютная пара: обе стороны котировки. Это единственный случай, где у
    # инструмента две равноправные «свои» страны.
    m = _CCY.match(s)
    if m and category == "fx":
        out = [CCY_COUNTRY.get(m.group(1)), CCY_COUNTRY.get(m.group(2))]
        return [c for c in out if c]

    # Акция европейской или азиатской биржи — по суффиксу каталога.
    for suf, country in SUFFIX_COUNTRY.items():
        if s.endswith(suf):
            return [country]

    # Американский листинг: каталог брокера помечает его решёткой.
    if s.startswith("#"):
        return ["US"]

    if category == "index":
        for frag, country in INDEX_COUNTRY:
            if frag in s:
                return [country]

    # Сырьё, крипта, ETF и всё, что не опознали: американская макростатистика.
    # Это не «затычка» — ставка ФРС и запасы нефти действительно двигают и
    # золото, и биткоин, и европейский ETF, номинированный в долларах.
    return [FALLBACK_COUNTRY]


def build(dry: bool = False, verbose: bool = False) -> int:
    cat = json.loads((ROOT / "web" / "data" / "broker_catalog.json").read_text(encoding="utf-8"))
    items = cat["items"] if isinstance(cat, dict) else cat

    con = sqlite3.connect(BOT_DB, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    known = {c for (c,) in con.execute(
        "SELECT DISTINCT country FROM econ_events WHERE country IS NOT NULL")}
    if not known:
        print("в econ_events нет ни одной страны — карту строить не из чего", file=sys.stderr)
        return 1

    rows: set[tuple[str, str, int]] = set()
    skipped: dict[str, int] = {}
    for it in items:
        sym = it["symbol"]
        # 🔴 Пишем строки и на имя брокера, и на каноническое. Ссылка на график
        # приходит с каноническим (LINK), а каталог знает LINKUSD — на этом
        # уже ломались свечи, повторять не будем.
        names = {sym}
        if it.get("canonical"):
            names.add(it["canonical"])

        own = countries_for(sym, it.get("category"), it.get("name"))
        for country in own:
            if country not in known:
                skipped[country] = skipped.get(country, 0) + 1
                continue
            for n in names:
                rows.add((country, n, 2))
        # США вторым весом — если это уже не своя страна.
        if FALLBACK_COUNTRY in known and FALLBACK_COUNTRY not in own:
            for n in names:
                rows.add((FALLBACK_COUNTRY, n, 1))
        # Акция или индекс еврозоны: решения ЕЦБ касаются их напрямую.
        if any(c in ("DE", "FR", "IT", "ES", "NL", "BE", "PT", "AT", "FI", "IE")
               for c in own) and "EU" in known:
            for n in names:
                rows.add(("EU", n, 2))

    if verbose:
        print(f"строк к записи: {len(rows)}, инструментов: {len(items)}")
        if skipped:
            print("страны без событий в календаре (пропущены): "
                  + ", ".join(f"{k}×{v}" for k, v in sorted(skipped.items())))
    if dry:
        con.close()
        return 0

    # Полная замена, а не дополнение: карта пересчитывается из каталога целиком,
    # и старые строки по инструментам, которых у брокера больше нет, должны
    # уйти. Пишем в одной транзакции — слой «События» не должен на секунду
    # увидеть пустую таблицу.
    with con:
        con.execute("DELETE FROM event_instrument_map")
        con.executemany(
            "INSERT INTO event_instrument_map(country, symbol, weight) VALUES(?,?,?)",
            sorted(rows))
    n_sym = len({r[1] for r in rows})
    print(f"готово: {len(rows)} строк, {n_sym} инструментов, {len({r[0] for r in rows})} стран")
    con.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="посчитать, но не писать")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    raise SystemExit(build(a.dry, a.verbose))
