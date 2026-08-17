#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/volatility_labeler.py — WP6.0 SPEC_alpha_engine_wp6_volatility.md.

Положительный контроль ("прибор способен увидеть истинный положительный
результат?") перед тем, как строить семейство «волатильность/диапазон» —
и переиспользуется тем же контуром впоследствии. НЕ triple-barrier: нет
entry/stop/target/costs/direction — только «диапазон следующего бара выше
порога или нет», разрешается на СЛЕДУЮЩЕМ баре, однозначно и без внутрибарной
резолюции.

Гипотеза (WP6.0): P(range(t+1) > медианы скользящего окна | range(t) в
верхнем квинтиле ТОГО ЖЕ окна) против безусловной базовой ставки.

Честный ноль lookahead: окно для порога на баре i и медианы для проверки
i+1 — ОДНО И ТО ЖЕ [i-window+1, i] (включает i, НЕ включает i+1) — решение
принимается на данных, доступных на момент i, до того как i+1 сформировался
(симметрично _atr14/_vol_percentile в analyze/labeler.py и
analyze/state_vector.py — тот же класс дисциплины, не новая идея).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import core.price_bars as _price_bars

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

CONTROL_EVENT_KEY = "vol_autocorr_control"
DEFAULT_WINDOW = 60
DEFAULT_QUINTILE_PCT = 80  # "верхний квинтиль" = выше 80-го перцентиля

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS volatility_labels (
      symbol TEXT, tf TEXT, ts INTEGER, event_key TEXT,
      condition INTEGER, y INTEGER, bars_to_resolve INTEGER, censored INTEGER,
      PRIMARY KEY (symbol, tf, ts, event_key)
    );
"""


def init_schema(con: sqlite3.Connection) -> None:
    con.executescript(_SCHEMA)
    con.commit()


def _range(candles: list[dict], i: int) -> float:
    return candles[i]["h"] - candles[i]["l"]


def _percentile(values: list[float], pct: float) -> float:
    """Линейная интерполяция (та же семантика, что numpy.percentile по
    умолчанию) -- без numpy-зависимости, список маленький (window<=~250)."""
    if not values:
        return float("nan")
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    rank = (pct / 100.0) * (len(s) - 1)
    lo, hi = int(rank), min(int(rank) + 1, len(s) - 1)
    frac = rank - lo
    return s[lo] + (s[hi] - s[lo]) * frac


def _median(values: list[float]) -> float:
    return _percentile(values, 50.0)


def label_autocorr_control(candles: list[dict], window: int = DEFAULT_WINDOW,
                            quintile_pct: float = DEFAULT_QUINTILE_PCT) -> list[dict]:
    """Одна строка на бар i (i от window-1 до len(candles)-1). condition/y
    определены выше в докстринге модуля. censored=1 (y=None), если i+1 не
    существует -- честно "не проверено", а не подставленный 0."""
    rows = []
    for i in range(window - 1, len(candles)):
        window_ranges = [_range(candles, k) for k in range(i - window + 1, i + 1)]
        today_range = _range(candles, i)
        threshold = _percentile(window_ranges, quintile_pct)
        median_window = _median(window_ranges)
        condition = 1 if today_range > threshold else 0

        if i + 1 >= len(candles):
            rows.append({"ts": candles[i]["ts"], "condition": condition, "y": None,
                         "bars_to_resolve": 0, "censored": 1})
            continue
        tomorrow_range = _range(candles, i + 1)
        y = 1 if tomorrow_range > median_window else 0
        rows.append({"ts": candles[i]["ts"], "condition": condition, "y": y,
                     "bars_to_resolve": 1, "censored": 0})
    return rows


def label_symbol(canonical_symbol: str, tf: str, event_key: str = CONTROL_EVENT_KEY,
                  window: int = DEFAULT_WINDOW, quintile_pct: float = DEFAULT_QUINTILE_PCT) -> list[dict]:
    _TF_TO_PB = {"H1": "1h", "H4": "4h", "D1": "1d"}
    candles = _price_bars.load_candles(canonical_symbol, _TF_TO_PB[tf])
    if not candles or len(candles) < window + 1:
        return []
    labelled = label_autocorr_control(candles, window, quintile_pct)
    return [{"symbol": canonical_symbol, "tf": tf, "event_key": event_key, **r} for r in labelled]


def write_labels(con: sqlite3.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    con.executemany(
        """INSERT OR REPLACE INTO volatility_labels
           (symbol, tf, ts, event_key, condition, y, bars_to_resolve, censored)
           VALUES (:symbol, :tf, :ts, :event_key, :condition, :y, :bars_to_resolve, :censored)""",
        rows,
    )
    con.commit()
    return len(rows)


def run(symbols: list[str] | None, tfs: list[str], verbose: bool = False) -> int:
    con = sqlite3.connect(str(_BOT_DB))
    init_schema(con)
    syms = symbols or _price_bars.available_symbols("1d")
    total = 0
    for sym in syms:
        for tf in tfs:
            rows = label_symbol(sym, tf)
            n = write_labels(con, rows)
            total += n
            if verbose and n:
                print(f"{sym} {tf}: {n} строк volatility_labels")
    con.close()
    return total


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", help="Канонические имена (GOLD, EURUSD, ...)")
    ap.add_argument("--all", action="store_true", help="Все доступные символы")
    ap.add_argument("--tf", nargs="+", default=["D1", "H4", "H1"], choices=["D1", "H4", "H1"])
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    symbols = None if args.all else args.symbols
    total = run(symbols, args.tf, args.verbose)
    print(f"готово: {total} строк volatility_labels")
