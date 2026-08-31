#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/engine/backtest.py — теневой прогон источников по истории.

ЗАЧЕМ. Живой журнал даёт 22 сделки на 11 стратегий. Чтобы отличить винрейт
40% от безубыточных 33.3% нужно ~400 сделок на стратегию — это девять
месяцев живой торговли, оплаченных деньгами. В `price_bars` лежит 54 тыс.
часовых баров с 2018 года: та же выборка получается за минуты и бесплатно.

ЧЕСТНОСТЬ ПРОГОНА — четыре решения, каждое ухудшает результат намеренно.

1. ВХОД ПО ОТКРЫТИЮ СЛЕДУЮЩЕГО БАРА, не по закрытию сигнального. Сигнал
   известен только после того, как бар закрылся; вход по его же закрытию —
   это торговля по цене, которой уже нет. Проект на этом обжигался: объединённый
   бэктест с честной геометрией `next_open` дал 0 из 9 паттернов после FDR
   против бодрых цифр при входе по закрытию.

2. БАРЬЕРЫ ОТ ЦЕНЫ ВХОДА, как в живом исполнении после правки 31.08.
   Иначе бэктест мерил бы не ту геометрию, что торгуется.

3. СПРЕД ПЛАТИТСЯ. Вход хуже на полный спред инструмента. Без этого
   USDCNY, у которого спред равен 105.7% ATR, выглядел бы рабочим.

4. ПРИ НЕОДНОЗНАЧНОСТИ ВЫИГРЫВАЕТ СТОП. Если стоп и цель задеты одним
   баром, внутрибарового порядка мы не знаем, и выбирать благоприятный
   исход значило бы завышать результат ровно там, где данных нет.

ПРО LOOKAHEAD. `core.patterns.detect()` вызывается один раз на всю серию, а
не заново на каждом баре — это эквивалентно и на два порядка быстрее,
потому что все детекторы смотрят строго назад, а `double_top/bottom`
намеренно репортит бар ПОДТВЕРЖДЕНИЯ фрактала, а не сам пик (см. комментарий
в `_detect_double_extremes` — там этот баг уже находили: agree_share 70-77%
против честных 45-54%). Уровни для `break_retest` строятся из фракталов,
подтверждённых ДО сигнального бара, а не из текущей таблицы `sr_levels` —
она отражает сегодняшнее состояние и была бы прямым заглядыванием вперёд.
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from collections import defaultdict

sys.path.insert(0, "/mnt/sbfdata/sbf-platform/market_intel")

import core.price_bars as _pb                                    # noqa: E402
from analyze.engine import sources                               # noqa: E402
from analyze.engine.contracts import LONG, SHORT                 # noqa: E402
from core.patterns import PATTERNS, FRACTAL_CONFIRM, _fractals   # noqa: E402
from core.patterns import detect as detect_patterns              # noqa: E402

# Спред, замеренный на живом терминале 31.08. Константа, а не среднее по
# истории: истории спредов у нас нет, а брать ноль — значит соврать в свою
# пользу. Число консервативное (дневной спред; ночью шире).
SPREAD = {
    "XAUUSD": 0.37, "EURUSD": 0.00007, "GBPUSD": 0.00012,
    "USDJPY": 0.013, "USDCNY": 0.0020, "USDZAR": 0.0100,
}

# Две геометрии: нынешняя движка и та, на которой gold_oil держался выше
# безубытка (72.5% при пороге 66.7% на 102 сделках).
GEOMETRIES = {
    "rr2.0": {"stop_atr": 1.5, "rr": 2.0},
    "rr0.5": {"stop_atr": 2.0, "rr": 0.5},
}

HORIZON_BARS = 24
LEVEL_WINDOW = 200          # сколько баров назад искать уровни для break_retest


def break_retest_events(candles) -> dict:
    """`break_retest` одним проходом вперёд, с уровнями as-of.

    Отдельно от остальных детекторов по двум причинам. Первая — скорость:
    вызывать `detect()` на окне заново для каждого из 54 тыс. баров это
    O(n·m), прогон не заканчивался. Вторая важнее — уровни. Живой детектор
    берёт их из таблицы `sr_levels`, а она отражает СЕГОДНЯШНЕЕ состояние
    рынка; подставить её в исторический прогон значило бы заглянуть вперёд
    на годы. Здесь уровень появляется ровно тогда, когда его фрактал
    подтвердился — через FRACTAL_CONFIRM свечей после экстремума, ни баром
    раньше."""
    out = defaultdict(list)
    fr_by_idx = defaultdict(list)
    for idx, price, kind in _fractals(candles):
        fr_by_idx[idx].append((price, kind))

    levels: list[dict] = []          # активные уровни: цена, вид, индекс появления
    pending: list[dict] = []         # состоявшиеся пробои, ждут ретеста
    for i in range(60, len(candles)):
        # уровень становится известен только в момент подтверждения фрактала
        born = i - FRACTAL_CONFIRM
        if born >= 0:
            for price, kind in fr_by_idx.get(born, ()):
                levels.append({"price": price,
                               "kind": "resistance" if kind == "high" else "support"})
                if len(levels) > 40:
                    levels.pop(0)
        a = sources.atr(candles, i)
        if not a:
            continue
        c = candles[i]
        half = a * 0.15                       # та же логика, что tolerance/2 у живого

        for p in list(pending):
            if i - p["i"] > 5:
                pending.remove(p)
                continue
            if (p["price"] - half) <= c["h"] and (p["price"] + half) >= c["l"]:
                out[c["ts"]].append({"pattern_key": "break_retest", "ts": c["ts"],
                                     "direction": p["dir"]})
                pending.remove(p)

        # 🔴 Пробой — это ПЕРЕСЕЧЕНИЕ уровня, а не «цена по ту сторону».
        # В первой версии условие проверялось на каждом баре, пока цена
        # оставалась за уровнем, и один пробой давал десятки «сигналов»:
        # прогон выдал 416 156 сделок вместо правдоподобных тысяч. Число,
        # которое не сходится с здравым смыслом, — повод искать ошибку у
        # себя, а не радоваться большой выборке.
        prev_c = candles[i - 1]["c"]
        for lv in levels:
            price = lv["price"]
            if lv["kind"] == "support" and prev_c >= price - half > c["c"]:
                pending.append({"price": price, "i": i, "dir": "bearish"})
            elif lv["kind"] == "resistance" and prev_c <= price + half < c["c"]:
                pending.append({"price": price, "i": i, "dir": "bullish"})
    return out


def _resolve(candles, start_idx, entry, stop, target, is_long):
    """Исход сделки по будущим барам. Возвращает (R, причина, баров)."""
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    end = min(start_idx + HORIZON_BARS, len(candles) - 1)
    for j in range(start_idx, end + 1):
        c = candles[j]
        hit_stop = c["l"] <= stop if is_long else c["h"] >= stop
        hit_tgt = c["h"] >= target if is_long else c["l"] <= target
        if hit_stop:                       # пессимизм при неоднозначности
            return -1.0, "stop", j - start_idx + 1
        if hit_tgt:
            move = (target - entry) if is_long else (entry - target)
            return move / risk, "target", j - start_idx + 1
    c = candles[end]
    move = (c["c"] - entry) if is_long else (entry - c["c"])
    return move / risk, "horizon", end - start_idx + 1


def _overlap(trades):
    """Среднее число одновременно живых сделок.

    Нужно, потому что сделки перекрываются по построению (горизонт 24 бара,
    сигналы чаще). CI по перекрывающимся наблюдениям врёт в сторону
    уверенности — на этом проект уже ловил себя 25.08."""
    if len(trades) < 2:
        return 1.0
    ev = []
    for t in trades:
        ev.append((t["open_i"], 1))
        ev.append((t["open_i"] + t["bars"], -1))
    ev.sort()
    span = ev[-1][0] - ev[0][0]
    if span <= 0:
        return 1.0
    cur = area = 0
    prev = ev[0][0]
    for idx, d in ev:
        area += cur * (idx - prev)
        cur += d
        prev = idx
    return max(1.0, area / span)


def run_symbol(symbol: str, tf: str, geom_name: str, geom: dict, *,
               costs: bool = True, with_random: bool = False,
               seed: int = 20260831) -> dict:
    """Прогон по одному инструменту.

    `costs=False` и `with_random=True` — два контроля, без которых таблицу
    убытков нельзя прочитать. Первый отвечает «сколько из минуса это спред»,
    второй — «отличается ли паттерн от входа наугад». Если случайный вход
    даёт тот же EV, паттерн не несёт направленной информации, и улучшать в
    нём нечего: улучшать надо не его."""
    candles = _pb.load_candles(symbol, tf)
    if not candles or len(candles) < 300:
        return {}
    spread = SPREAD.get(symbol, 0.0) if costs else 0.0
    events = defaultdict(list)
    for ev in detect_patterns(candles, None):        # всё, кроме break_retest
        events[ev["ts"]].append(ev)
    for ts, evs in break_retest_events(candles).items():
        events[ts].extend(evs)

    out = defaultdict(list)
    for i in range(60, len(candles) - HORIZON_BARS - 2):
        a = sources.atr(candles, i)
        if not a:
            continue
        bar = candles[i]

        for ev in events.get(bar["ts"], ()):
            direction = ev.get("direction") or PATTERNS.get(ev["pattern_key"], {}).get("direction")
            if direction == "bullish":
                is_long = True
            elif direction == "bearish":
                is_long = False
            else:
                continue
            # вход по открытию СЛЕДУЮЩЕГО бара, спред против нас
            raw = candles[i + 1]["o"]
            entry = raw + spread if is_long else raw - spread
            d = geom["stop_atr"] * a
            stop = entry - d if is_long else entry + d
            target = entry + geom["rr"] * d if is_long else entry - geom["rr"] * d
            res = _resolve(candles, i + 1, entry, stop, target, is_long)
            if res is None:
                continue
            r, why, bars = res
            out[f"pattern_{ev['pattern_key']}"].append(
                {"r": r, "why": why, "bars": bars, "open_i": i + 1,
                 "long": is_long, "symbol": symbol})

    if with_random:
        # Отрицательный контроль: вход наугад, та же геометрия, те же
        # издержки, столько же сделок. Планка, ниже которой «стратегия»
        # не отличается от монетки.
        rnd = random.Random(f"{seed}:{symbol}:{geom_name}")
        lo, hi = 60, len(candles) - HORIZON_BARS - 2
        for _ in range(8000):
            i = rnd.randrange(lo, hi)
            a = sources.atr(candles, i)
            if not a:
                continue
            is_long = rnd.random() < 0.5
            raw = candles[i + 1]["o"]
            entry = raw + spread if is_long else raw - spread
            d = geom["stop_atr"] * a
            stop = entry - d if is_long else entry + d
            target = entry + geom["rr"] * d if is_long else entry - geom["rr"] * d
            res = _resolve(candles, i + 1, entry, stop, target, is_long)
            if res is None:
                continue
            r, why, bars = res
            out["_случайный_вход"].append(
                {"r": r, "why": why, "bars": bars, "open_i": i + 1,
                 "long": is_long, "symbol": symbol})
    return out


def summarize(trades: list[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0}
    vals = [t["r"] for t in trades]
    mean = sum(vals) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1)) if n > 1 else 0.0
    k = _overlap(trades)
    se = (sd / math.sqrt(n)) * math.sqrt(k) if n > 1 else float("inf")
    wins = sum(1 for t in trades if t["why"] == "target")
    losses = sum(1 for t in trades if t["why"] == "stop")
    return {"n": n, "ev": mean, "total": sum(vals), "sd": sd,
            "lo": mean - 1.96 * se, "hi": mean + 1.96 * se,
            "overlap": k, "n_eff": n / k, "wins": wins, "losses": losses,
            "wr": wins / max(wins + losses, 1)}


def main() -> None:
    p = argparse.ArgumentParser(description="Теневой прогон источников по истории")
    p.add_argument("--symbols", default="EURUSD,USDJPY,XAUUSD,GBPUSD")
    p.add_argument("--tf", default="1h")
    p.add_argument("--min-n", type=int, default=100,
                   help="не показывать стратегии с выборкой меньше этой")
    p.add_argument("--no-costs", action="store_true",
                   help="контроль: прогон без спреда — сколько из минуса это издержки")
    p.add_argument("--random", action="store_true",
                   help="контроль: добавить строку входа наугад")
    p.add_argument("--geometry", default="", help="только одна геометрия")
    a = p.parse_args()
    syms = [s.strip() for s in a.symbols.split(",") if s.strip()]
    geoms = ({a.geometry: GEOMETRIES[a.geometry]} if a.geometry else GEOMETRIES)
    if a.no_costs:
        print("⚠ КОНТРОЛЬ: спред отключён, это не торгуемый результат")

    for gname, geom in geoms.items():
        be = 1.0 / (1.0 + geom["rr"])
        print(f"\n{'=' * 78}\nГЕОМЕТРИЯ {gname}: стоп {geom['stop_atr']} ATR, "
              f"цель {geom['stop_atr'] * geom['rr']} ATR, безубыточный винрейт "
              f"{be * 100:.1f}%\n{'=' * 78}")
        pooled = defaultdict(list)
        for sym in syms:
            for strat, trades in run_symbol(sym, a.tf, gname, geom,
                                            costs=not a.no_costs,
                                            with_random=a.random).items():
                pooled[strat].extend(trades)
        rows = []
        for strat, trades in pooled.items():
            m = summarize(trades)
            if m["n"] >= a.min_n:
                rows.append((strat, m))
        rows.sort(key=lambda x: -x[1]["ev"])
        print(f"{'стратегия':28}{'n':>7}{'n_eff':>7}{'винрейт':>9}{'EV,R':>9}"
              f"{'CI95 низ':>10}{'CI95 верх':>10}{'итог R':>10}")
        for strat, m in rows:
            mark = "  <-- выше нуля" if m["lo"] > 0 else ""
            print(f"{strat:28}{m['n']:>7}{m['n_eff']:>7.0f}{m['wr'] * 100:>8.1f}%"
                  f"{m['ev']:>9.4f}{m['lo']:>10.4f}{m['hi']:>10.4f}"
                  f"{m['total']:>10.1f}{mark}")
        if not rows:
            print("  (нет стратегий с достаточной выборкой)")


if __name__ == "__main__":
    main()
