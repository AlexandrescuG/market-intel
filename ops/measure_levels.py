#!/usr/bin/env python3
"""Несёт ли близость к уровню информацию — на наших данных и наших сделках.

Повод: совет практика торговать по уровням. Его метод: часовик, окно около
недели, уровни по экстремумам; при подходе к уровню смотрится реакция рынка,
объёмы и СТАКАН, и решение принимается по тому, есть ли в точке интереса
покупатели.

🔴 ЧТО МЫ ВОСПРОИЗВЕСТИ НЕ МОЖЕМ, и это проверено, а не предположено:
  · стакан — Ava отказывает в market_book_add, Daoti подписку принимает и
    отдаёт НОЛЬ уровней. Глубины рынка нет ни у одного из брокеров;
  · объёмы — real_volume = 0 везде, есть только tick_volume, то есть число
    изменений цены. По газу это 210 «объёма» в час: у нас CFD, настоящий
    объём торгуется на бирже фьючерсов.

Поэтому здесь меряется не метод практика, а один его слой: помогает ли
БЛИЗОСТЬ ВХОДА К УРОВНЮ тому, что мы уже делаем. Если да — уровень стоит
брать фильтром; если нет — значит без стакана эта часть не работает, и это
тоже ответ.

Уровни строятся КАК ОПИСАНО: фракталы на 1h по скользящему окну около недели,
и только по барам, закрытым ДО сигнального — иначе получится подглядывание.

    python3 ops/measure_levels.py --symbols NG,EURUSD,XAUUSD
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

sys.path.insert(0, "/mnt/sbfdata/sbf-platform/market_intel")

from analyze.engine import backtest                              # noqa: E402
from analyze.engine.execution import ACTIVE_RULES                # noqa: E402

WINDOW = 168          # около недели часовых баров — как смотрел практик
FRACTAL = 2           # экстремум сильнее двух соседей с каждой стороны
BUCKETS = ((0.0, 0.25), (0.25, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 99.0))


def levels_as_of(candles, i: int, atr: float, min_touch: int = 2,
                 keep: int = 6) -> list[float]:
    """Уровни, видимые НА МОМЕНТ бара i. Только закрытые бары до него.

    🔴 Первая версия брала ВСЕ фракталы окна — и в ближнюю корзину попадало
    84% сделок по газу, 80% по EURUSD. Такой «фильтр» не отделяет ничего:
    при сотне уровней на недельном окне рядом с уровнем находится почти
    любая точка. Вывод «уровни не работают» из такой разметки был бы
    выводом о разметке, а не о рынке.

    Практик описывал иначе: несколько уровней на недельном окне. Поэтому
    фракталы схлопываются в кластеры по допуску 0.25 ATR, и остаются только
    те, которых рынок касался не меньше min_touch раз, — сильнейшие keep
    штук по числу касаний."""
    lo = max(FRACTAL, i - WINDOW)
    raw = []
    for k in range(lo, i - FRACTAL):
        hi = candles[k]["h"]
        if all(candles[k + d]["h"] <= hi for d in range(-FRACTAL, FRACTAL + 1) if d):
            raw.append(hi)
        low = candles[k]["l"]
        if all(candles[k + d]["l"] >= low for d in range(-FRACTAL, FRACTAL + 1) if d):
            raw.append(low)
    if not raw or not atr:
        return []
    tol = 0.25 * atr
    clusters: list[list[float]] = []
    for p in sorted(raw):
        if clusters and p - clusters[-1][-1] <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    strong = [(len(c), sum(c) / len(c)) for c in clusters if len(c) >= min_touch]
    strong.sort(reverse=True)
    return [p for _, p in strong[:keep]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="NG,EURUSD,XAUUSD,GBPUSD")
    ap.add_argument("--tf", default="1h")
    a = ap.parse_args()

    import core.price_bars as pb
    from analyze.engine import sources

    geom = {"stop_atr": 1.5, "rr": 2.0}
    for sym in a.symbols.split(","):
        candles = pb.load_candles(sym, a.tf)
        if not candles or len(candles) < 500:
            print(f"{sym}: баров мало"); continue
        out = backtest.run_symbol(sym, a.tf, "base", geom, costs=True,
                                  with_random=False, rules=ACTIVE_RULES)
        trades = [t for k, v in out.items() if not k.startswith("_") for t in v]
        if not trades:
            print(f"{sym}: сделок нет"); continue

        # расстояние от цены входа до ближайшего уровня, в ATR
        buckets = defaultdict(list)
        for t in trades:
            i = t["open_i"]
            atr = sources.atr(candles, i - 1)
            if not atr:
                continue
            lv = levels_as_of(candles, i, atr)
            if not lv:
                continue
            price = candles[i]["o"]
            d = min(abs(price - x) for x in lv) / atr
            for loq, hiq in BUCKETS:
                if loq <= d < hiq:
                    buckets[(loq, hiq)].append(t)
                    break

        share = sum(len(v) for v in buckets.values())
        print(f"\n═══ {sym} {a.tf} ═══  сделок {len(trades)}, "
              f"окно {WINDOW} баров, уровни сильные (>=2 касаний, до 6 штук)")
        print(f"  размечено сделок: {share} ({share / len(trades) * 100:.0f}%)")
        print(f"  {'до уровня, ATR':18}{'сделок':>8}{'EV в R':>9}{'ниж.':>9}"
              f"{'верх.':>9}{'винрейт':>9}")
        base = backtest.summarize(trades)
        for key in BUCKETS:
            s = backtest.summarize(buckets.get(key, []))
            if not s.get("n"):
                continue
            mark = ""
            if s["lo"] > base["ev"]:
                mark = "  ↑ лучше общего"
            elif s["hi"] < base["ev"]:
                mark = "  ↓ хуже общего"
            print(f"  {key[0]:.2f}–{key[1]:<13.2f}{s['n']:>8}{s['ev']:>9.4f}"
                  f"{s['lo']:>9.4f}{s['hi']:>9.4f}{s['wr'] * 100:>8.1f}%{mark}")
        print(f"  {'всё вместе':18}{base['n']:>8}{base['ev']:>9.4f}"
              f"{base['lo']:>9.4f}{base['hi']:>9.4f}{base['wr'] * 100:>8.1f}%")

    print("\nКак читать. Если у ближних к уровню входов EV выше общего и")
    print("интервалы не пересекаются — уровень несёт информацию и годится в")
    print("фильтр. Если разницы нет, то без стакана и настоящих объёмов эта")
    print("часть метода у нас не воспроизводится, и это ответ, а не неудача.")


if __name__ == "__main__":
    main()
