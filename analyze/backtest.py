#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/backtest.py — WP2.3 SPEC_alpha_engine_implementation.md.

Walk-forward с purge/embargo по таблице `labels` (WP2.2). Дисциплина —
как в `tools/edu_build/breakeven_cost.py`: метод описан ЗДЕСЬ, до кода.

ПРОБЛЕМА, которую решает purge: метки triple-barrier разрешаются НЕ на
своём баре, а через `bars_to_resolve` баров после (может быть 1, может
быть весь горизонт). Окно разрешения метки — [ts, ts + bars_to_resolve
* 1800с] (1800с = 30m, RESOLUTION_TF из labeler.py). Если это окно
пересекает тестовый период фолда, статистика на тесте частично объясняется
информацией, которая физически стала известна ВНУТРИ тестового периода —
это lookahead, даже если сама метка "формально" из train.

МЕТОД (зафиксирован до подсчёта):
  1. Строки `labels` сортируются по ts, делятся на N_FOLDS последовательных
     фолдов ПО ВРЕМЕНИ (не shuffle — porядок сохраняется, это ряд, не
     i.i.d. выборка).
  2. Для фолда i (i>=1, первый фолд не тестируем — нет предшествующей
     истории): test = сам фолд, train_candidate = все строки ДО начала
     теста.
  3. PURGE: из train_candidate выбрасываются строки, чьё окно разрешения
     пересекает [test_start_ts, test_end_ts].
  4. EMBARGO: дополнительно выбрасываются строки из train_candidate,
     чьё окно разрешения пересекает [test_end_ts, test_end_ts +
     EMBARGO_BARS*1800с] — буфер против остаточной сериальной корреляции
     сразу после теста (стандартная практика López de Prado, "Advances in
     Financial Machine Learning" гл.7 — здесь применяется к ВАЛИДАЦИИ
     статистики паттерна, не к обучению модели, но принцип тот же: окно
     обучения не должно видеть НИЧЕГО, что стало известно во время теста
     или сразу после).
  5. Цензурированные строки (`censored=1`) исключаются из знаменателя
     винрейта (не считаются ни WIN, ни LOSS) — тот же принцип, что в
     `breakeven_cost.py` (там же процитирован в докстринге labeler.py).

EMBARGO_BARS=48 (1 сутки на 30m) — [ДОПУЩЕНИЕ], не откалибровано на
измеренной автокорреляции остатков; выбрано как разумный порядок величины
(сутки — стандартная эвристика для дневных данных в литературе), заменить
при появлении измеренной автокорреляции.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.edu_build.pattern_reality import wilson  # WP2.4: переиспользуем, не дублируем

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
RESOLUTION_BAR_SECONDS = 1800  # должно совпадать с analyze.labeler.RESOLUTION_TF ("30m")
EMBARGO_BARS = 48


def resolution_window(row: dict) -> tuple[int, int]:
    """[ts_start, ts_end] окна разрешения метки, в секундах."""
    ts = row["ts"]
    bars = row["bars_to_resolve"] or 0
    return ts, ts + bars * RESOLUTION_BAR_SECONDS


def purge_train(train_rows: list[dict], test_start_ts: int, test_end_ts: int,
                 embargo_bars: int = EMBARGO_BARS) -> list[dict]:
    """Убирает из train все строки, чьё окно разрешения пересекает
    [test_start_ts, test_end_ts + embargo]. Возвращает только "чистые" строки."""
    embargo_end = test_end_ts + embargo_bars * RESOLUTION_BAR_SECONDS
    kept = []
    for row in train_rows:
        win_start, win_end = resolution_window(row)
        if win_end >= test_start_ts and win_start <= embargo_end:
            continue  # окно разрешения пересекает тест+embargo -- purge
        kept.append(row)
    return kept


def walk_forward_folds(rows: list[dict], n_folds: int = 5) -> list[tuple[list[dict], list[dict]]]:
    """rows -- строки labels (произвольного подмножества, напр. один
    pattern_key x symbol x tf x config_key). Возвращает [(train, test), ...]
    по последовательным фолдам, train уже пропущен через purge_train."""
    rows_sorted = sorted(rows, key=lambda r: r["ts"])
    n = len(rows_sorted)
    if n < n_folds * 2:
        return []
    fold_size = n // n_folds
    folds = []
    for i in range(1, n_folds):
        test_start_idx = i * fold_size
        test_end_idx = (i + 1) * fold_size if i < n_folds - 1 else n
        test_rows = rows_sorted[test_start_idx:test_end_idx]
        if not test_rows:
            continue
        test_start_ts = test_rows[0]["ts"]
        test_end_ts = test_rows[-1]["ts"]
        train_candidate = rows_sorted[:test_start_idx]
        train_rows = purge_train(train_candidate, test_start_ts, test_end_ts)
        folds.append((train_rows, test_rows))
    return folds


def _decided(rows: list[dict]) -> list[dict]:
    """Только разрешённые метки (censored=0) -- цензурированные не входят
    ни в числитель, ни в знаменатель винрейта."""
    return [r for r in rows if not r.get("censored")]


def fold_stats(rows: list[dict]) -> dict:
    """n, винрейт, Wilson CI95, ожидание в R (среднее r_realized -- уже
    ПОСЛЕ издержек, r_realized приходит из labeler.py уже с вычтенным cost)."""
    decided = _decided(rows)
    n = len(decided)
    if n == 0:
        return {"n": 0, "wins": 0, "winrate": None, "ci95": [None, None],
                "expectancy_r": None, "profit_factor": None}
    wins = sum(1 for r in decided if r["y"] == 1)
    winrate = wins / n
    ci = wilson(wins, n)
    r_values = [r["r_realized"] for r in decided if r["r_realized"] is not None]
    expectancy = sum(r_values) / len(r_values) if r_values else None
    gains = sum(r for r in r_values if r > 0)
    losses = -sum(r for r in r_values if r < 0)
    profit_factor = (gains / losses) if losses > 0 else (float("inf") if gains > 0 else None)
    return {"n": n, "wins": wins, "winrate": round(winrate, 4), "ci95": ci,
            "expectancy_r": round(expectancy, 4) if expectancy is not None else None,
            "profit_factor": round(profit_factor, 4) if isinstance(profit_factor, float) else profit_factor}


def load_labels(con: sqlite3.Connection, symbol: str | None = None, tf: str | None = None,
                config_key: str | None = None) -> list[dict]:
    q = "SELECT symbol, tf, ts, direction, config_key, y, r_realized, mfe, mae, bars_to_resolve, censored FROM labels"
    conds, params = [], []
    if symbol:
        conds.append("symbol=?"); params.append(symbol)
    if tf:
        conds.append("tf=?"); params.append(tf)
    if config_key:
        conds.append("config_key=?"); params.append(config_key)
    if conds:
        q += " WHERE " + " AND ".join(conds)
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(q, params).fetchall()]


def run_walk_forward(symbol: str, tf: str, config_key: str, n_folds: int = 5) -> dict:
    con = sqlite3.connect(str(_BOT_DB))
    try:
        rows = load_labels(con, symbol=symbol, tf=tf, config_key=config_key)
    finally:
        con.close()
    folds = walk_forward_folds(rows, n_folds)
    fold_results = [{"train_n": len(_decided(train)), "test": fold_stats(test)}
                     for train, test in folds]
    all_test_rows = [r for _, test in folds for r in test]
    return {"symbol": symbol, "tf": tf, "config_key": config_key,
            "n_folds": len(folds), "folds": fold_results,
            "pooled_oos": fold_stats(all_test_rows)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--tf", required=True)
    ap.add_argument("--config-key", required=True)
    ap.add_argument("--folds", type=int, default=5)
    args = ap.parse_args()
    result = run_walk_forward(args.symbol, args.tf, args.config_key, args.folds)
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))
