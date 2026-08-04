#!/usr/bin/env python3
"""
breakeven_cost.py — глава 13 «Анатомия Свинга и Пирамидинг», §3.5/§4.2
(SPEC_edu_level13_swing_pyramiding.md). Считает: как часто перевод стопа в
точку входа («безубыток») закрывает сделку, которая иначе дошла бы до цели.

Метод (зафиксирован до подсчёта, как требует спека):
  Для каждого бара i инструмента, в обоих направлениях (long/short):
    entry = close[i]
    Фаза 1 — идём вперёд (не дальше LOOKAHEAD баров) и смотрим, что случится
      раньше: цена уходит на +X*ATR в пользу позиции (стоп можно перевести
      в безубыток) или на -S*ATR против (срабатывает исходный стоп, сценарий
      безубытка вообще не наступает — этот случай не входит в знаменатель
      §3.5, он про ДРУГОЙ вопрос: как часто позиция вообще доживает до X).
    Фаза 2 — если +X достигнут первым, с этого бара вперёд (тот же общий
      LOOKAHEAD) смотрим, что произойдёт раньше для каждого Y из сетки:
      возврат цены к entry («закрыт в ноль») или достижение +Y*ATR
      («дошёл до цели»). Если до конца окна не случилось ни то, ни другое —
      случай цензурирован (censored), не учитывается ни в числителе, ни в
      знаменателе конкретной пары (X,Y).

[ДОПУЩЕНИЕ] S (исходный стоп для фазы 1) = 1.0 ATR — спека даёт сетку для X
и Y явно, но не для S («S из сетки» упомянуто вскользь, без чисел). Взято
фиксированное консервативное значение, типичное для начального стопа свинг-
позиции; не влияет на METOD §3.5 (условная статистика "что после X"), влияет
только на то, какая ДОЛЯ входов вообще доживает до X — не публикуется как
основной вывод главы, только для полноты `_meta`.

[ДОПУЩЕНИЕ] LOOKAHEAD = 120 баров — свинг-горизонт главы («живёт не часы,
а недели»); на D1 это ~4-6 месяцев, на H4 — around 20 торговых дней.
Только H4/D1 — H1 в чужой горизонт этой главы (скальпинг — глава 14),
и было бы избыточно дорого по вычислениям без содержательной пользы здесь.

[ДОПУЩЕНИЕ] ATR берётся один раз, на баре входа (entry bar), период 14 —
не пересчитывается на каждом шаге вперёд (типичная практика в этой серии
скриптов, см. ema_reality.py).

Вход:  web/data/ohlc_*_{H4,D1}.json
Выход: web/data/edu_stats/breakeven_cost.json (+ .csv)

Запуск: python3 tools/edu_build/breakeven_cost.py
"""
import csv
import glob
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "web" / "data"
OUT_JSON = ROOT / "web" / "data" / "edu_stats" / "breakeven_cost.json"
OUT_CSV = ROOT / "web" / "data" / "edu_stats" / "breakeven_cost.csv"

TFS = ["H4", "D1"]
X_GRID = [0.2, 0.3, 0.5, 0.8, 1.0]
Y_GRID = [1.0, 1.5, 2.0, 3.0]
S_ATR = 1.0
ATR_PERIOD = 14
LOOKAHEAD = 120
MIN_N_SHOWN = 30


def wilson(k, n, z=1.96):
    if not n:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    s = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5
    return [round(100 * (c - s) / d, 1), round(100 * (c + s) / d, 1)]


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
    return out if len(out) >= 60 else None


def compute_atr(candles, period=ATR_PERIOD):
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
                running = sum(window) / period
                atr[i] = running
        elif i == period - 1:
            pass
    return atr


def simulate_symbol_tf(candles, atr):
    """Возвращает per-(X,Y) счётчики: {(x,y): {'zero':n,'target':n}} + reach_x/no_reach для S_ATR."""
    counts = {(x, y): {"zero": 0, "target": 0} for x in X_GRID for y in Y_GRID}
    reached_x_total = {x: 0 for x in X_GRID}
    stopped_before_x_total = {x: 0 for x in X_GRID}
    n = len(candles)

    for i in range(n - 5):
        a = atr[i]
        if a is None or a <= 0:
            continue
        entry = candles[i]["c"]
        end = min(n, i + 1 + LOOKAHEAD)
        if end <= i + 1:
            continue

        for direction in (1, -1):  # 1=long, -1=short
            s_level = entry - direction * S_ATR * a  # против позиции
            # Фаза 1: найти первый бар, на котором достигнут каждый X (или стоп S)
            x_touch_bar = {x: None for x in X_GRID}
            stopped_first = {x: False for x in X_GRID}
            remaining_x = set(X_GRID)
            hit_stop = False
            for j in range(i + 1, end):
                hi, lo = candles[j]["h"], candles[j]["l"]
                fav = (hi - entry) if direction == 1 else (entry - lo)
                adv_hit = (lo <= s_level) if direction == 1 else (hi >= s_level)
                if adv_hit:
                    hit_stop = True
                for x in list(remaining_x):
                    if fav >= x * a:
                        x_touch_bar[x] = j
                        remaining_x.discard(x)
                if hit_stop:
                    for x in remaining_x:
                        stopped_first[x] = True
                    break
                if not remaining_x:
                    break

            for x in X_GRID:
                if x_touch_bar[x] is not None:
                    reached_x_total[x] += 1
                elif stopped_first[x]:
                    stopped_before_x_total[x] += 1

            # Фаза 2: для каждый X, достигнутый, смотрим Y-исходы одним проходом
            for x in X_GRID:
                tb = x_touch_bar[x]
                if tb is None:
                    continue
                target_levels = {y: entry + direction * y * a for y in Y_GRID}
                open_ys = set(Y_GRID)
                end2 = min(n, tb + 1 + LOOKAHEAD)
                for j in range(tb, end2):
                    hi, lo, cl = candles[j]["h"], candles[j]["l"], candles[j]["c"]
                    returned_to_zero = (lo <= entry) if direction == 1 else (hi >= entry)
                    if returned_to_zero:
                        for y in open_ys:
                            counts[(x, y)]["zero"] += 1
                        open_ys = set()
                        break
                    reached_ys = set()
                    for y in open_ys:
                        lvl = target_levels[y]
                        hit = (hi >= lvl) if direction == 1 else (lo <= lvl)
                        if hit:
                            counts[(x, y)]["target"] += 1
                            reached_ys.add(y)
                    open_ys -= reached_ys
                    if not open_ys:
                        break
                # оставшиеся open_ys в конце окна — censored, не учитываем

    return counts, reached_x_total, stopped_before_x_total


def main():
    symbols = sorted({pathlib.Path(f).stem.split("_")[1]
                       for f in glob.glob(str(DATA_DIR / "ohlc_*_D1.json"))})
    print(f"Символы: {symbols}")

    cells = []
    pooled = {(x, y): {"zero": 0, "target": 0} for x in X_GRID for y in Y_GRID}

    for symbol in symbols:
        for tf in TFS:
            candles = load_candles(symbol, tf)
            if not candles:
                continue
            atr = compute_atr(candles)
            counts, reached_x_total, stopped_before_x_total = simulate_symbol_tf(candles, atr)
            for x in X_GRID:
                for y in Y_GRID:
                    z, t = counts[(x, y)]["zero"], counts[(x, y)]["target"]
                    n = z + t
                    shown = n >= MIN_N_SHOWN
                    zero_pct = round(z / n * 100, 1) if n else None
                    ci = wilson(z, n) if shown else [None, None]
                    cells.append({
                        "symbol": symbol, "tf": tf, "x": x, "y": y,
                        "n": n, "zero_count": z, "target_count": t,
                        "zero_pct": zero_pct, "ci95": ci, "shown": shown,
                        "reached_x_n": reached_x_total[x],
                        "stopped_before_x_n": stopped_before_x_total[x],
                    })
                    if shown:
                        pooled[(x, y)]["zero"] += z
                        pooled[(x, y)]["target"] += t
            print(f"  {symbol} {tf}: OK ({len(candles)} candles)")

    pooled_rows = []
    for x in X_GRID:
        for y in Y_GRID:
            z, t = pooled[(x, y)]["zero"], pooled[(x, y)]["target"]
            n = z + t
            pooled_rows.append({
                "x": x, "y": y, "n": n, "zero_count": z, "target_count": t,
                "zero_pct": round(z / n * 100, 1) if n else None,
                "ci95": wilson(z, n) if n >= MIN_N_SHOWN else [None, None],
            })

    # Верифицируемая по спеке точка: X=0.5, Y=2.0 -- "средний" случай для be_verdict в главе
    highlight = next((r for r in pooled_rows if r["x"] == 0.5 and r["y"] == 2.0), None)

    # Монотонность: чем меньше X (раньше переводишь), тем выше zero_pct (при фикс. Y)
    monotonic_checks = []
    for y in Y_GRID:
        row_by_x = {r["x"]: r["zero_pct"] for r in pooled_rows if r["y"] == y and r["zero_pct"] is not None}
        xs_sorted = sorted(row_by_x.keys())
        pcts = [row_by_x[x] for x in xs_sorted]
        is_monotonic = all(pcts[i] >= pcts[i + 1] - 1e-9 for i in range(len(pcts) - 1))  # убывает с ростом X
        monotonic_checks.append({"y": y, "xs": xs_sorted, "zero_pcts": pcts, "monotonic_desc": is_monotonic})

    out = {
        "_meta": {
            "note_ru": "Расчёт по движению цены в нашей истории, БЕЗ учёта спреда и проскальзывания — значит реальная доля закрытых в ноль ВЫШЕ расчётной здесь (не 'примерно', а именно выше: спред добавляет шанс зацепить уровень входа при развороте).",
            "x_grid_atr": X_GRID, "y_grid_atr": Y_GRID, "s_atr": S_ATR,
            "atr_period": ATR_PERIOD, "lookahead_bars": LOOKAHEAD,
            "tfs": TFS, "min_n_shown": MIN_N_SHOWN,
        },
        "cells": cells,
        "pooled": pooled_rows,
        "highlight": highlight,
        "monotonic_checks": monotonic_checks,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"\nЗаписано: {OUT_JSON} ({len(cells)} ячеек)")
    print(f"Highlight X=0.5 Y=2.0: {highlight}")
    for chk in monotonic_checks:
        print(f"  Y={chk['y']}: X={chk['xs']} zero%={chk['zero_pcts']} monotonic_desc={chk['monotonic_desc']}")

    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(cells[0].keys()))
        w.writeheader()
        for row in cells:
            r = dict(row)
            r["ci95"] = f"{r['ci95'][0]}-{r['ci95'][1]}" if r["ci95"][0] is not None else ""
            w.writerow(r)
    print(f"Записано: {OUT_CSV}")


if __name__ == "__main__":
    main()
