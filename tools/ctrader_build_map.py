#!/usr/bin/env python3
"""tools/ctrader_build_map.py — карта «наш инструмент → инструмент cTrader».

ЗАЧЕМ. Витрина знает инструменты именами AvaTrade (broker_symbols: EURUSD,
#BOEING, _BMW.DE), у cTrader написания свои (EURUSD, XAUUSD, NAT.GAS,
#Germany40). Резолвить на лету нельзя: тихий фолбэк «возьмём имя как есть»
однажды уже дал бы пустые графики по всему золоту и выглядел бы как «данных
нет», а не как «мы не нашли соответствие».

Поэтому соответствие вычисляется ОДИН РАЗ, кладётся в файл и дальше только
читается. Не нашли — значит инструмент остаётся на MT5, и это видно в файле,
а не выясняется в момент показа страницы.

ГДЕ ЛЕЖИТ И ПОЧЕМУ НЕ В symbol_map. symbol_map живёт в bot.db рядом с
price_bars, который принадлежит торговому движку. Карта витрины — данные
витрины, у неё свой файл в market_intel/data. Задание прямо требует не трогать
движковое, и «мы только колонку добавим» — начало ровно того пути.

Запуск:  python3 tools/ctrader_build_map.py          # показать план
         python3 tools/ctrader_build_map.py --write  # записать карту
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CT_SYMBOLS = ROOT / "data" / "ctrader_symbols.json"
OUT = ROOT / "data" / "ctrader_map.json"
BOT_DB = "/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db"

# 🔴 Ручные соответствия. Каждая строка — решение, а не догадка: имена
# отличаются так, что автоматика их не свяжет, а связать их неправильно
# опаснее, чем не связать вовсе (получим чужой инструмент на графике —
# ровно то, что 17.08 испортило 45% трек-рекорда Signals).
#
# Слева — имя в нашем каталоге (broker_symbols.broker_symbol), справа —
# имя у cTrader. Пустая строка справа = сознательно НЕ сопоставлять.
MANUAL = {
    # ── металлы и сырьё ───────────────────────────────────────────────────
    "GOLD":            "XAUUSD",
    "SILVER":          "XAGUSD",
    "CrudeOIL":        "WTI",      # у нас «Нефть WTI», у cTrader просто WTI
    "WTICrude":        "",         # дубль CrudeOIL в каталоге, не плодим
    "BRENT_OIL":       "BRENT",
    "NATURAL_GAS":     "NAT.GAS",
    "COPPER":          "COPPER",
    # ── крипта: у нас тикером, у cTrader словом ───────────────────────────
    "BTCUSD":          "BITCOIN",
    "ETHUSD":          "ETHEREUM",
    "LTCUSD":          "LITECOIN",
    "XRPUSD":          "XRP",
    "BCHUSD":          "BITCOINCASH",
    "LINKUSD":         "CHAINLINK",
    "XLMUSD":          "STELLAR",
    "DOGEUSD":         "DOGECOIN",
    "TRUMPUSD":        "TRUMP",
    # ── индексы ───────────────────────────────────────────────────────────
    # 🔴 Здесь первая версия карты была неверна во всех трёх главных строках:
    # я написал #USA500 / #DJ30 / #USTech100 по памяти, а у брокера они
    # называются #USSPX500 / #US30 / #USNDAQ100. Поймано тем, что скрипт
    # ругается на ручное соответствие, указывающее на несуществующий
    # инструмент, вместо того чтобы тихо его пропустить.
    "US_500":          "#USSPX500",
    "US_30":           "#US30",
    "US_TECH100":      "#USNDAQ100",
    "US_2000":         "#US2000",
    "GERMANY_40":      "#Germany40",
    "GERMANY_TECH30":  "#GerTech30",
    "UK_100":          "#UK100",
    "FRANCE_40":       "#France40",
    "JAPAN_225":       "#Japan225",
    "AUS_200":         "#AUS200",
    "EUROPE_50":       "#Euro50",
    "SPAIN35":         "#Spain35",
    "SWISS_20":        "#Swiss20",
    "NED_25":          "#Holland25",
    "HK_50":           "#HongKong50",
    "CHINA_A50":       "#ChinaA50",
    # Тематических индексов AvaTrade (FAANG, GREEN_ENERGY, CORONA_IMPACT…)
    # у cTrader нет и быть не может — это собственные корзины площадки.
    # Остаются на MT5, и это правильный исход, а не пробел в карте.
    "DOLLAR_INDX":     "",   # индекса доллара у cTrader нет
}


# 🔴 Автоматически сопоставляем ТОЛЬКО валюты. Всё остальное — вручную.
#
# Причина конкретная, поймана на первой же сборке карты: у нас есть ETF `#XRP`
# (биржевой фонд на XRP), у cTrader есть криптовалюта `XRP`. Нормализация
# срезает решётку, имена совпадают — и фонд молча получил бы график монеты.
# Разные инструменты с разной ценой под одним именем на публичной витрине.
#
# У валют такой ловушки нет: EURUSD у всех означает одно и то же. Индексы,
# сырьё и крипта немногочисленны и перечислены в MANUAL поимённо; акции и ETF
# не сопоставляются вовсе, их у этого счёта нет.
AUTO_CATEGORIES = {"fx"}


def norm(s: str) -> str:
    """Написание без разделителей: EURUSD == EUR/USD == eur_usd."""
    return (s or "").upper().replace("#", "").replace("_", "").replace(".", "") \
                           .replace("-", "").replace(" ", "").replace("/", "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    if not CT_SYMBOLS.exists():
        print(f"нет {CT_SYMBOLS} — сначала tools/ctrader_symbols_dump.py", file=sys.stderr)
        return 1
    ct = json.loads(CT_SYMBOLS.read_text(encoding="utf-8"))
    by_name = {r["name"]: r for r in ct}
    by_norm: dict[str, dict] = {}
    for r in ct:
        by_norm.setdefault(norm(r["name"]), r)

    con = sqlite3.connect(BOT_DB)
    rows = con.execute(
        "SELECT broker_symbol, canonical, display_name, category FROM broker_symbols").fetchall()
    con.close()

    mapping: dict[str, dict] = {}
    manual_used, auto, unmapped = 0, 0, 0
    problems: list[str] = []

    for bs, canon, disp, cat in rows:
        target = None
        how = None

        if bs in MANUAL:
            want = MANUAL[bs]
            if not want:
                continue  # сознательный отказ, см. комментарий у MANUAL
            target = by_name.get(want)
            how = "вручную"
            if target is None:
                # Ручное соответствие указывает на несуществующий инструмент —
                # это опечатка в карте, а не повод молча пропустить.
                problems.append(f"{bs}: в MANUAL указан {want!r}, которого у cTrader нет")
                continue
            manual_used += 1
        elif cat in AUTO_CATEGORIES:
            target = by_norm.get(norm(bs)) or (by_norm.get(norm(canon)) if canon else None)
            if target is not None:
                how = "по имени"
                auto += 1

        if target is None:
            unmapped += 1
            continue
        if not target.get("enabled", True):
            problems.append(f"{bs} -> {target['name']}: инструмент отключён у брокера")
            continue

        mapping[bs] = {"ct_name": target["name"], "ct_id": target["symbolId"],
                       "category": cat, "how": how}

    print(f"каталог витрины: {len(rows)}")
    print(f"  сопоставлено: {len(mapping)}  (по имени {auto}, вручную {manual_used})")
    print(f"  без соответствия: {unmapped} — остаются на MT5")
    if problems:
        print("\n  требуют внимания:")
        for p in problems:
            print("   ", p)

    from collections import Counter
    c = Counter(v["category"] for v in mapping.values())
    print("\n  по категориям:", ", ".join(f"{k}={v}" for k, v in c.most_common()))

    if args.write:
        OUT.write_text(json.dumps(mapping, ensure_ascii=False, indent=1, sort_keys=True),
                       encoding="utf-8")
        print(f"\nзаписано: {OUT} ({len(mapping)} инструментов)")
    else:
        print("\nЭто предпросмотр. Записать: python3 tools/ctrader_build_map.py --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
