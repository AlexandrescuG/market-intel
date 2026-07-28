#!/usr/bin/env python3
"""
ema_reality.py — глава 8 «Тренд и Циклы», §3.4/§3.5/§4.2
(SPEC_edu_level8_trend_cycles_ema.md). Считает лабораторию переобучения:
для каждого (symbol, tf) перебирает сетку 61 пары (fast, slow) EMA-периодов,
находит лучшую по суммарному ходу за вычетом издержек на ПЕРВОЙ половине
истории, затем прогоняет ЭТУ ЖЕ пару на второй половине и записывает её
место в рейтинге всех 61 пар, пересчитанном заново на второй половине.

[ДОПУЩЕНИЕ] cost_per_trade_atr = 0.03 -- издержка (спред+комиссия) на смену
позиции как доля ATR. Реального тика спреда по всем 15 инструментам у нас
нет (только точечно для GOLD/XAU из главы 14: 0.29pt). 0.03*ATR --
консервативная иллюстративная величина того же порядка, что типичный
розничный спред относительно дневного ATR для мажоров; сам феномен
переобучения (§3.4/3.5) не зависит от точного значения константы, только
от того, что она не равна нулю и не абсурдно велика -- проверено: при
cost=0 и cost=0.03 знак вывода (потеря устойчивости IS→OOS) не меняется.

Вход:  web/data/ohlc_*_{H1,H4,D1}.json
Выход: web/data/edu_stats/ema_reality.json (+ .csv)

Запуск: python3 tools/edu_build/ema_reality.py
"""
import glob
import json
import pathlib
import statistics

ROOT = pathlib.Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
DATA_DIR = WEB / "data"
OUT_JSON = WEB / "data" / "edu_stats" / "ema_reality.json"
OUT_CSV = WEB / "data" / "edu_stats" / "ema_reality.csv"

FAST_PERIODS = [5, 8, 10, 12, 15, 20, 25, 30, 40, 50]
SLOW_PERIODS = [20, 30, 50, 80, 100, 150, 200]
GRID = [(f, s) for s in SLOW_PERIODS for f in FAST_PERIODS if s > f]
COST_PER_TRADE_ATR = 0.03
MIN_CANDLES_FACTOR = 6  # нужно как минимум 6x самого длинного периода, чтобы обе половины были содержательны
TFS = ["H1", "H4", "D1"]


def load_candles(symbol, tf):
    f = DATA_DIR / f"ohlc_{symbol}_{tf}.json"
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    out = []
    for c in data.get("candles") or []:
        try:
            out.append({"h": float(c["high"]), "l": float(c["low"]), "c": float(c["close"])})
        except (KeyError, TypeError, ValueError):
            continue
    return out if len(out) >= 30 else None


def rolling_atr(candles, period=14):
    trs = [None]
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = [None] * len(candles)
    running = None
    for i in range(1, len(candles)):
        if i >= period:
            window = trs[i - period + 1:i + 1]
            if None not in window:
                atr[i] = sum(window) / period
    return atr


def ema_series(closes, period):
    out = [None] * len(closes)
    if len(closes) < period:
        return out
    k = 2 / (period + 1)
    seed = sum(closes[:period]) / period
    out[period - 1] = seed
    for i in range(period, len(closes)):
        out[i] = closes[i] * k + out[i - 1] * (1 - k)
    return out


def backtest_pair(closes, atr, ema_fast, ema_slow, lo, hi, cost):
    """Метрики для полуинтервала [lo,hi) индексов. Позиция решается на баре
    i-1 (уже известные EMA), применяется к возврату бара i -- без lookahead."""
    agree, total = 0, 0
    net = 0.0
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    prev_pos = None
    n_changes = 0
    for i in range(max(lo, 1), hi):
        f, s = ema_fast[i - 1], ema_slow[i - 1]
        a = atr[i - 1]
        if f is None or s is None or a is None or a <= 0:
            continue
        pos = 1 if f > s else (-1 if f < s else 0)
        if pos == 0:
            continue
        bar_ret = closes[i] - closes[i - 1]
        signed = pos * bar_ret / a
        net += signed
        equity += signed
        if prev_pos is not None and pos != prev_pos:
            n_changes += 1
            net -= cost
            equity -= cost
        prev_pos = pos
        total += 1
        if (bar_ret > 0 and pos == 1) or (bar_ret < 0 and pos == -1):
            agree += 1
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "sum_move_net": round(net, 4), "share_agree": round(agree / total, 4) if total else None,
        "max_dd": round(max_dd, 4), "n": total, "n_changes": n_changes,
    }


def process_symbol_tf(symbol, tf):
    candles = load_candles(symbol, tf)
    if not candles:
        return None
    longest = max(SLOW_PERIODS)
    if len(candles) < longest * MIN_CANDLES_FACTOR:
        return None

    closes = [c["c"] for c in candles]
    atr = rolling_atr(candles)
    ema_cache = {p: ema_series(closes, p) for p in set(FAST_PERIODS) | set(SLOW_PERIODS)}

    mid = len(candles) // 2
    is_range, oos_range = (0, mid), (mid, len(candles))

    is_results, oos_results = {}, {}
    for fast, slow in GRID:
        ef, es = ema_cache[fast], ema_cache[slow]
        is_results[(fast, slow)] = backtest_pair(closes, atr, ef, es, *is_range, COST_PER_TRADE_ATR)
        oos_results[(fast, slow)] = backtest_pair(closes, atr, ef, es, *oos_range, COST_PER_TRADE_ATR)

    valid_is = {k: v for k, v in is_results.items() if v["n"] >= 20}
    if not valid_is:
        return None
    best_pair = max(valid_is, key=lambda k: valid_is[k]["sum_move_net"])

    oos_valid = {k: v for k, v in oos_results.items() if v["n"] >= 20}
    if best_pair not in oos_valid:
        return None
    oos_sorted = sorted(oos_valid.items(), key=lambda kv: -kv[1]["sum_move_net"])
    rank = next(i for i, (k, v) in enumerate(oos_sorted, start=1) if k == best_pair)
    of = len(oos_sorted)

    lab_grid = []
    for (fast, slow) in GRID:
        if fast in [p for p in ema_cache] and slow in ema_cache:
            lab_grid.append({
                "fast": fast, "slow": slow,
                "is": is_results[(fast, slow)], "oos": oos_results[(fast, slow)],
            })

    return {
        "symbol": symbol, "tf": tf,
        "best_is": {"fast": best_pair[0], "slow": best_pair[1], **valid_is[best_pair]},
        "oos": {**oos_valid[best_pair], "rank": rank, "of": of, "percentile": round(100 * rank / of, 1)},
        "lab_grid": lab_grid,
        "split_ts": None,
    }


def main():
    symbols = sorted({pathlib.Path(f).stem.replace("ohlc_", "").rsplit("_", 1)[0]
                       for f in glob.glob(str(DATA_DIR / "ohlc_*_D1.json"))})
    print(f"инструментов: {len(symbols)}, сетка: {len(GRID)} пар")

    cells = []
    lab = {}
    for symbol in symbols:
        for tf in TFS:
            r = process_symbol_tf(symbol, tf)
            if not r:
                continue
            cells.append({
                "symbol": symbol, "tf": tf,
                "best_is": r["best_is"], "oos": {k: v for k, v in r["oos"].items() if k != "lab_grid"},
            })
            lab.setdefault(symbol, {})[tf] = {"grid": r["lab_grid"]}
            print(f"  {symbol} {tf}: best_is=({r['best_is']['fast']},{r['best_is']['slow']}) "
                  f"is_net={r['best_is']['sum_move_net']} -> oos_net={r['oos']['sum_move_net']} "
                  f"rank={r['oos']['rank']}/{r['oos']['of']}")

    ranks = [c["oos"]["rank"] for c in cells]
    of_vals = [c["oos"]["of"] for c in cells]
    median_rank = statistics.median(ranks) if ranks else None
    of_typical = statistics.median(of_vals) if of_vals else len(GRID)

    if median_rank is None:
        verdict_key = "no_persistence"
    else:
        frac = median_rank / of_typical
        if frac >= 0.5:
            verdict_key = "no_persistence"
        elif frac >= 0.30:
            verdict_key = "weak_persistence"
        else:
            verdict_key = "some_persistence"

    long_c = [c for c in cells if c["best_is"]["slow"] >= 100]
    short_c = [c for c in cells if c["best_is"]["slow"] < 100]
    pcts = sorted(c["oos"]["percentile"] for c in cells)

    def pct_at(vals, q):
        i = min(len(vals) - 1, max(0, int(round(q * (len(vals) - 1)))))
        return vals[i]

    payload = {
        "_meta": {
            "grid_size": len(GRID), "tfs": TFS,
            "cost_per_trade_atr": COST_PER_TRADE_ATR,
            "n_cells": len(cells),
            "note_ru": "учебная модель для демонстрации переобучения, не торговая система",
        },
        "cells": cells,
        "summary": {
            "median_oos_rank": median_rank, "of": of_typical, "verdict_key": verdict_key,
            # разброс OOS-перцентиля лучшей IS-пары по всем ячейкам -- заменяет
            # исходную идею "within-grid vs across-instrument spread" из спеки:
            # та сравнивала сырые суммы хода в ATR-единицах между инструментами
            # и таймфреймами с разным числом баров (H1 накапливает тысячи баров,
            # D1 -- сотни), что само по себе раздувает разброс независимо от
            # реальной разницы инструментов -- нашёл на первом прогоне, когда
            # across-instrument stdev (64.7) вышел БОЛЬШЕ within-grid (14.0),
            # то есть в противоположную сторону от утверждения спеки. Перцентиль
            # места в рейтинге (1..of) уже нормирован и сравним между ячейками.
            "oos_percentile_spread": {
                "min": pcts[0], "p25": pct_at(pcts, 0.25), "median": statistics.median(pcts),
                "p75": pct_at(pcts, 0.75), "max": pcts[-1],
            },
            # long_vs_short: два независимых честных критерия, которые дают
            # РАЗНЫЕ направления на этих данных -- см. докстринг скрипта и
            # project_edu_trend_ema_ch8 в memory. Не подгонялось под спеку.
            "long_vs_short": {
                "median_rank_slow_ge_100": statistics.median(c["oos"]["rank"] for c in long_c) if long_c else None,
                "median_rank_slow_lt_100": statistics.median(c["oos"]["rank"] for c in short_c) if short_c else None,
                "net_positive_share_long": round(sum(1 for c in long_c if c["oos"]["sum_move_net"] > 0) / len(long_c), 3) if long_c else None,
                "net_positive_share_short": round(sum(1 for c in short_c if c["oos"]["sum_move_net"] > 0) / len(short_c), 3) if short_c else None,
                "n_long": len(long_c), "n_short": len(short_c),
            },
        },
        "lab": lab,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        import csv
        w = csv.writer(f)
        w.writerow(["symbol", "tf", "best_is_fast", "best_is_slow", "is_net", "is_agree", "oos_net", "oos_agree", "oos_rank", "oos_of"])
        for c in cells:
            w.writerow([c["symbol"], c["tf"], c["best_is"]["fast"], c["best_is"]["slow"],
                        c["best_is"]["sum_move_net"], c["best_is"]["share_agree"],
                        c["oos"]["sum_move_net"], c["oos"]["share_agree"], c["oos"]["rank"], c["oos"]["of"]])

    print(f"\nклеток: {len(cells)}, медианное место OOS: {median_rank} из ~{of_typical}, verdict={verdict_key}")
    print(f"percentile spread: {payload['summary']['oos_percentile_spread']}")
    print(f"long_vs_short: {payload['summary']['long_vs_short']}")
    print(f"→ {OUT_JSON}\n→ {OUT_CSV}")


if __name__ == "__main__":
    main()
