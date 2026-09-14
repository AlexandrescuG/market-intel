#!/usr/bin/env python3
"""Правда ли лонг EURUSD и лонг GBPUSD — одна ставка против доллара.

Гипотеза пункта 4: портфельный риск считается по инструментам, а рискуем мы
валютами. Лонг EURUSD, лонг GBPUSD и шорт USDJPY — это три раза шорт
доллара; сейчас они считаются тремя независимыми ставками по 0.5%.

Но складывать ноги как равные — тоже упрощение, только в другую сторону: у
валют корреляция не единица. Поэтому сначала МЕРИМ, а потом решаем, с каким
весом складывать.

Считается две вещи:

  1. Корреляция дневных доходностей между нашими инструментами. Прямая
     проверка «одна ставка или разные».
  2. Она же, но после разложения на ноги: для каждой пары строится ряд
     «сколько стоит доллар», и проверяется, объясняет ли он совместное
     движение. Если да — складывать по ногам осмысленно.

Источник — price_bars, те же бары, на которых работает движок.

    python3 ops/measure_legs.py
    python3 ops/measure_legs.py --days 180 --tf 1d
"""
from __future__ import annotations

import argparse
import sys
from itertools import combinations

sys.path.insert(0, "/mnt/sbfdata/sbf-platform/market_intel")

import core.price_bars as pb                                      # noqa: E402

# Инструменты, которыми движок реально торгует (по журналу сделок).
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "USDZAR", "USDCNY", "XAUUSD"]

# Разложение на ноги. Для XAUUSD базовая «валюта» — золото: оно ведёт себя
# как самостоятельный актив, и приписывать ему поведение валюты нельзя.
LEGS = {
    "EURUSD": ("EUR", "USD"), "GBPUSD": ("GBP", "USD"),
    "USDJPY": ("USD", "JPY"), "USDZAR": ("USD", "ZAR"),
    "USDCNY": ("USD", "CNY"), "XAUUSD": ("XAU", "USD"),
}


def returns(symbol: str, tf: str, limit: int) -> dict[int, float]:
    """Логарифмические доходности по закрытиям, ключ — метка бара."""
    try:
        c = pb.load_candles(symbol, tf)
    except Exception as e:                                        # noqa: BLE001
        print(f"  {symbol}: баров нет ({type(e).__name__})")
        return {}
    c = c[-limit:] if limit else c
    out = {}
    for i in range(1, len(c)):
        p0, p1 = c[i - 1].get("c"), c[i].get("c")
        if p0 and p1 and p0 > 0 and p1 > 0:
            out[c[i].get("t") or i] = (p1 / p0) - 1.0
    return out


def corr(a: dict[int, float], b: dict[int, float]) -> tuple[float, int]:
    keys = sorted(set(a) & set(b))
    n = len(keys)
    if n < 30:
        return float("nan"), n
    xs = [a[k] for k in keys]
    ys = [b[k] for k in keys]
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return float("nan"), n
    return sxy / (sxx * syy) ** 0.5, n


def usd_sign(symbol: str) -> int:
    """+1, если рост цены означает СИЛЬНЫЙ доллар (USD базовая), иначе -1."""
    return 1 if LEGS[symbol][0] == "USD" else -1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1d")
    ap.add_argument("--bars", type=int, default=400)
    a = ap.parse_args()

    print(f"Доходности по закрытиям, tf={a.tf}, последние {a.bars} баров\n")
    r = {s: returns(s, a.tf, a.bars) for s in SYMBOLS}
    r = {s: v for s, v in r.items() if v}
    if len(r) < 2:
        raise SystemExit("данных не хватает")

    print("=== корреляция как есть (знак цены инструмента) ===")
    print(f"{'пара':22}{'корр':>8}{'баров':>8}")
    for x, y in combinations(sorted(r), 2):
        c, n = corr(r[x], r[y])
        print(f"{x + '/' + y:22}{c:>8.2f}{n:>8}")

    print("\n=== корреляция «ставки на доллар» ===")
    print("Ряд каждого инструмента развёрнут так, чтобы + означал СИЛЬНЫЙ")
    print("доллар. Если ноги — общая ставка, здесь всё должно стать плюсом.")
    print(f"{'пара':22}{'корр':>8}{'баров':>8}")
    usd = {s: {k: v * usd_sign(s) for k, v in d.items()} for s, d in r.items()}
    vals = []
    for x, y in combinations(sorted(usd), 2):
        c, n = corr(usd[x], usd[y])
        print(f"{x + '/' + y:22}{c:>8.2f}{n:>8}")
        if c == c:
            vals.append(c)

    if vals:
        vals.sort()
        med = vals[len(vals) // 2]
        print(f"\nмедианная корреляция по доллару: {med:.2f}")
        print("Вес для сложения ног — это она и есть: при 1.0 ноги складываются")
        print("целиком, при 0.0 инструменты независимы и складывать нечего.")


if __name__ == "__main__":
    main()
