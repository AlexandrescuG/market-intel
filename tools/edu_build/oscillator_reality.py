#!/usr/bin/env python3
"""
oscillator_reality.py — глава 9 «Отчётности и Осцилляторы», §3.6/§4.2
(SPEC_edu_level9_earnings_oscillators.md). Проверяет два проверяемых
утверждения: «после RSI>70 вероятен откат» и «дивергенция предвещает
разворот» — против БАЗОВОЙ ЛИНИИ (доля разворотов на всех барах инструмента
без всякого условия), а не против 50%.

Правила фиксируются до подсчёта:
  RSI            период 14, пороги 70/30, событие = пересечение порога
  дивергенция    новый экстремум цены за 20 баров без нового экстремума RSI
  исходы         движение через 5/10/20 баров; "разворот" = ход против
                 предшествующего тренда > 0.5 ATR
  базовая линия  доля таких же разворотов на ВСЕХ барах инструмента

Вход:  web/data/ohlc_*_{H1,H4,D1}.json
Выход: web/data/edu_stats/oscillator_reality.json (+ .csv)

Запуск: python3 tools/edu_build/oscillator_reality.py
"""
import csv
import glob
import json
import pathlib
import statistics

ROOT = pathlib.Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
DATA_DIR = WEB / "data"
OUT_JSON = WEB / "data" / "edu_stats" / "oscillator_reality.json"
OUT_CSV = WEB / "data" / "edu_stats" / "oscillator_reality.csv"

RSI_PERIOD = 14
RSI_HIGH, RSI_LOW = 70, 30
DIV_WINDOW = 20
TREND_WINDOW = 10  # баров "предшествующего тренда" для определения направления
REVERSAL_ATR_MULT = 0.5
CHECKPOINTS = (5, 10, 20)
MIN_N_SHOWN = 15
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
    return out if len(out) >= 100 else None


def rolling_atr(candles, period=14):
    trs = [None]
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = [None] * len(candles)
    for i in range(1, len(candles)):
        if i >= period:
            window = trs[i - period + 1:i + 1]
            if None not in window:
                atr[i] = sum(window) / period
    return atr


def rsi_series(closes, period=RSI_PERIOD):
    n = len(closes)
    rsi = [None] * n
    gains, losses = [], []
    for i in range(1, n):
        d = closes[i] - closes[i - 1]
        gains.append(max(0.0, d))
        losses.append(max(0.0, -d))
        if i >= period:
            avg_gain = sum(gains[-period:]) / period
            avg_loss = sum(losses[-period:]) / period
            if avg_loss == 0:
                rsi[i] = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi[i] = 100 - (100 / (1 + rs))
    return rsi


def prior_trend_dir(closes, i, window=TREND_WINDOW):
    if i < window:
        return None
    return 1 if closes[i] > closes[i - window] else -1


def is_reversal(closes, atr, i, k, trend_dir):
    if i + k >= len(closes) or atr[i] is None or atr[i] <= 0 or trend_dir is None:
        return None
    delta = closes[i + k] - closes[i]
    move_against = (-delta if trend_dir == 1 else delta)
    return move_against > REVERSAL_ATR_MULT * atr[i]


def wilson(k, n, z=1.96):
    if not n:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    s = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5
    return [round(100 * (c - s) / d, 1), round(100 * (c + s) / d, 1)]


def find_rsi_crossings(rsi, threshold, from_below):
    out = []
    for i in range(1, len(rsi)):
        if rsi[i - 1] is None or rsi[i] is None:
            continue
        if from_below and rsi[i - 1] < threshold <= rsi[i]:
            out.append(i)
        if not from_below and rsi[i - 1] > threshold >= rsi[i]:
            out.append(i)
    return out


def find_divergences(closes, rsi):
    """Новый экстремум цены за DIV_WINDOW баров без нового экстремума RSI —
    в обе стороны (бычья/медвежья), возвращает индексы события."""
    out = []
    for i in range(DIV_WINDOW, len(closes)):
        if rsi[i] is None:
            continue
        window_c = closes[i - DIV_WINDOW:i]
        window_r = [r for r in rsi[i - DIV_WINDOW:i] if r is not None]
        if not window_r:
            continue
        price_new_high = closes[i] > max(window_c)
        price_new_low = closes[i] < min(window_c)
        rsi_new_high = rsi[i] > max(window_r)
        rsi_new_low = rsi[i] < min(window_r)
        if (price_new_high and not rsi_new_high) or (price_new_low and not rsi_new_low):
            out.append(i)
    return out


def eval_condition(closes, atr, idxs, k):
    n, hits = 0, 0
    for i in idxs:
        trend_dir = prior_trend_dir(closes, i)
        r = is_reversal(closes, atr, i, k, trend_dir)
        if r is None:
            continue
        n += 1
        if r:
            hits += 1
    return n, hits


def eval_baseline(closes, atr, k):
    n, hits = 0, 0
    for i in range(TREND_WINDOW, len(closes)):
        trend_dir = prior_trend_dir(closes, i)
        r = is_reversal(closes, atr, i, k, trend_dir)
        if r is None:
            continue
        n += 1
        if r:
            hits += 1
    return n, hits


def median_rsi_high_duration(rsi):
    runs = []
    cur = 0
    for v in rsi:
        if v is not None and v > RSI_HIGH:
            cur += 1
        else:
            if cur > 0:
                runs.append(cur)
            cur = 0
    if cur > 0:
        runs.append(cur)
    return statistics.median(runs) if runs else None


def verdict_for(edge_pp):
    if edge_pp is None:
        return "no_edge"
    if abs(edge_pp) < 5:
        return "no_edge"
    if abs(edge_pp) < 12:
        return "weak_edge"
    return "edge"


def process_symbol_tf(symbol, tf):
    candles = load_candles(symbol, tf)
    if not candles:
        return None
    closes = [c["c"] for c in candles]
    atr = rolling_atr(candles)
    rsi = rsi_series(closes)

    rsi_high_idxs = find_rsi_crossings(rsi, RSI_HIGH, from_below=True)
    div_idxs = find_divergences(closes, rsi)

    result = {"symbol": symbol, "tf": tf, "conditions": {}}
    base_by_k = {}
    for k in CHECKPOINTS:
        n_b, hits_b = eval_baseline(closes, atr, k)
        base_by_k[k] = (n_b, hits_b, round(100 * hits_b / n_b, 1) if n_b else None)

    for cond_name, idxs in (("rsi_high", rsi_high_idxs), ("divergence", div_idxs)):
        cond_out = {}
        for k in CHECKPOINTS:
            n, hits = eval_condition(closes, atr, idxs, k)
            share = round(100 * hits / n, 1) if n >= MIN_N_SHOWN else None
            n_b, hits_b, share_b = base_by_k[k]
            edge = round(share - share_b, 1) if (share is not None and share_b is not None) else None
            cond_out[f"k{k}"] = {
                "n": n, "share_reversal": share, "ci95": wilson(hits, n) if n >= MIN_N_SHOWN else [None, None],
                "base_share": share_b, "base_n": n_b, "edge_pp": edge,
                "verdict_key": verdict_for(edge), "shown": n >= MIN_N_SHOWN,
            }
        result["conditions"][cond_name] = cond_out

    result["rsi_high_duration_median_bars"] = median_rsi_high_duration(rsi)
    result["n_rsi_events"] = len(rsi_high_idxs)
    result["n_div_events"] = len(div_idxs)
    return result


def main():
    symbols = sorted({pathlib.Path(f).stem.replace("ohlc_", "").rsplit("_", 1)[0]
                       for f in glob.glob(str(DATA_DIR / "ohlc_*_D1.json"))})
    print(f"инструментов: {len(symbols)}")

    cells = []
    for symbol in symbols:
        for tf in TFS:
            r = process_symbol_tf(symbol, tf)
            if r:
                cells.append(r)
                k10 = r["conditions"]["rsi_high"]["k10"]
                d10 = r["conditions"]["divergence"]["k10"]
                print(f"  {symbol} {tf}: rsi_high k10 n={k10['n']} share={k10['share_reversal']} base={k10['base_share']} | "
                      f"div k10 n={d10['n']} share={d10['share_reversal']} base={d10['base_share']} | "
                      f"rsi_dur_median={r['rsi_high_duration_median_bars']}")

    def pooled(cond, k):
        shown = [c["conditions"][cond][f"k{k}"] for c in cells if c["conditions"][cond][f"k{k}"]["shown"]]
        if not shown:
            return None
        total_n = sum(x["n"] for x in shown)
        total_hits = sum(round(x["share_reversal"] / 100 * x["n"]) for x in shown)
        total_base_n = sum(x["base_n"] for x in shown)
        total_base_hits = sum(round(x["base_share"] / 100 * x["base_n"]) for x in shown if x["base_share"] is not None)
        share = round(100 * total_hits / total_n, 1) if total_n else None
        base_share = round(100 * total_base_hits / total_base_n, 1) if total_base_n else None
        edge = round(share - base_share, 1) if (share is not None and base_share is not None) else None
        return {"n": total_n, "share_reversal": share, "base_share": base_share, "base_n": total_base_n,
                "edge_pp": edge, "verdict_key": verdict_for(edge)}

    rsi_pooled = pooled("rsi_high", 10)
    div_pooled = pooled("divergence", 10)
    rsi_durations = [c["rsi_high_duration_median_bars"] for c in cells if c["rsi_high_duration_median_bars"]]

    payload = {
        "_meta": {
            "tfs": TFS, "rsi_period": RSI_PERIOD, "rsi_thresholds": [RSI_LOW, RSI_HIGH],
            "div_window": DIV_WINDOW, "reversal_atr_mult": REVERSAL_ATR_MULT, "checkpoints": list(CHECKPOINTS),
            "min_n_shown": MIN_N_SHOWN, "n_cells": len(cells),
            "note_ru": "базовая линия — доля разворотов на всех барах инструмента без условия, не 50%",
        },
        "cells": cells,
        "summary": {
            "rsi_high_k10_pooled": rsi_pooled,
            "divergence_k10_pooled": div_pooled,
            "rsi_high_duration_median_bars": statistics.median(rsi_durations) if rsi_durations else None,
        },
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "tf", "condition", "k", "n", "share_reversal", "base_share", "base_n", "edge_pp"])
        for c in cells:
            for cond in ("rsi_high", "divergence"):
                for k in CHECKPOINTS:
                    d = c["conditions"][cond][f"k{k}"]
                    w.writerow([c["symbol"], c["tf"], cond, k, d["n"], d["share_reversal"], d["base_share"], d["base_n"], d["edge_pp"]])

    print(f"\nклеток: {len(cells)}")
    print(f"RSI>70 k10 pooled: {rsi_pooled}")
    print(f"divergence k10 pooled: {div_pooled}")
    print(f"RSI>70 медианная длительность серии: {payload['summary']['rsi_high_duration_median_bars']}")
    print(f"→ {OUT_JSON}\n→ {OUT_CSV}")


if __name__ == "__main__":
    main()
