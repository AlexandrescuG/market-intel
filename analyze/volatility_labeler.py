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


# ─── WP6.2: полное семейство ────────────────────────────────────────────────
#
# Пререгистрация: analyze/preregistration/2026-08-17_volatility.md, коммит
# 12fb40b (ДО этого прогона). Все пороги, окна и множители ниже взяты оттуда
# и здесь не варьируются — подгонка любой из этих констант превратила бы
# результат в разведочный.
#
# Ключ клетки — составной, "<гипотеза>@<условие>". Схема volatility_labels
# имеет PRIMARY KEY (symbol, tf, ts, event_key), то есть на один бар может
# лечь ровно одна строка на event_key; условий три, и каждое даёт свой
# condition/y-срез. Составной ключ решает это без миграции таблицы и не
# трогает 412 371 строку положительного контроля, которая должна остаться
# воспроизводимой.
KEY_SEP = "@"

P75_PCT, P25_PCT, TOP_QUINTILE_PCT = 75.0, 25.0, 80.0
ATR_PERIOD = 14
ATR_EXPANSION_BARS = 5
ATR_EXPANSION_MULT = 1.2
EVENT_MOVE_BARS = 2          # 2 бара по 30m = окно 60 минут
EVENT_MOVE_ATR_MULT = 1.0
DOJI_MAX_BODY_SHARE = 0.1    # core/patterns.py::_detect_doji, та же константа
MIN_N_PER_GROUP = 500        # §5 пререгистрации


def _true_range(candles: list[dict], i: int) -> float:
    if i == 0:
        return candles[0]["h"] - candles[0]["l"]
    pc = candles[i - 1]["c"]
    return max(candles[i]["h"] - candles[i]["l"],
               abs(candles[i]["h"] - pc), abs(candles[i]["l"] - pc))


def _atr(candles: list[dict], i: int, period: int = ATR_PERIOD) -> float | None:
    """ATR за period баров, ОКАНЧИВАЮЩИХСЯ на i. Не пересчитывается задним
    числом: для условия на баре i берутся только бары <= i."""
    if i < period:
        return None
    trs = [_true_range(candles, k) for k in range(i - period + 1, i + 1)]
    return sum(trs) / period


def _body(c: dict) -> float:
    return abs(c["c"] - c["o"])


# --- условия (считаются на баре i, только по данным <= i) -------------------

def _cond_range_top_quintile(candles, i, window_ranges) -> int:
    return 1 if _range(candles, i) > _percentile(window_ranges, TOP_QUINTILE_PCT) else 0


def _cond_doji(candles, i, window_ranges) -> int:
    r = _range(candles, i)
    return 1 if r > 0 and _body(candles[i]) <= DOJI_MAX_BODY_SHARE * r else 0


def _cond_inside_bar(candles, i, window_ranges) -> int:
    if i == 0:
        return 0
    p, c = candles[i - 1], candles[i]
    return 1 if (c["h"] <= p["h"] and c["l"] >= p["l"]) else 0


CONDITIONS = {
    "range_top_quintile": _cond_range_top_quintile,
    "doji": _cond_doji,
    "inside_bar": _cond_inside_bar,
}


# --- исходы (могут смотреть в будущее -- это и есть исход) ------------------

def _y_range_gt_p75(candles, i, window_ranges):
    if i + 1 >= len(candles):
        return None, 0
    return (1 if _range(candles, i + 1) > _percentile(window_ranges, P75_PCT) else 0), 1


def _y_range_lt_p25(candles, i, window_ranges):
    if i + 1 >= len(candles):
        return None, 0
    return (1 if _range(candles, i + 1) < _percentile(window_ranges, P25_PCT) else 0), 1


def _y_atr_expansion_5(candles, i, window_ranges):
    j = i + ATR_EXPANSION_BARS
    if j >= len(candles):
        return None, 0
    a_now, a_then = _atr(candles, i), _atr(candles, j)
    if a_now is None or a_then is None or a_now <= 0:
        return None, 0
    return (1 if a_then > ATR_EXPANSION_MULT * a_now else 0), ATR_EXPANSION_BARS


HYPOTHESES = {
    "range_gt_p75": _y_range_gt_p75,
    "range_lt_p25": _y_range_lt_p25,
    "atr_expansion_5": _y_atr_expansion_5,
}


def label_family(candles: list[dict], hypothesis: str, condition: str,
                 window: int = DEFAULT_WINDOW) -> list[dict]:
    """Одна строка на бар i для пары (гипотеза, условие).

    censored=1 (y=None) -- честное «не проверено», когда будущего бара ещё
    нет; подставленный 0 был бы враньём в пользу отрицательного исхода."""
    y_fn, cond_fn = HYPOTHESES[hypothesis], CONDITIONS[condition]
    rows = []
    for i in range(window - 1, len(candles)):
        window_ranges = [_range(candles, k) for k in range(i - window + 1, i + 1)]
        cond = cond_fn(candles, i, window_ranges)
        y, bars = y_fn(candles, i, window_ranges)
        rows.append({"ts": candles[i]["ts"], "condition": cond, "y": y,
                     "bars_to_resolve": bars, "censored": 1 if y is None else 0})
    return rows


def label_all_pairs(candles: list[dict], window: int = DEFAULT_WINDOW) -> dict:
    """Все 9 пар (гипотеза × условие) за ОДИН проход по барам.

    label_family() считает окно [i-59..i] заново для каждой пары — на H1
    (291 тыс. баров × 9 пар) это тот же расчёт девять раз. Результат
    идентичен по построению: та же функция окна, те же условия; проверено
    сверкой с label_family() на EURUSD/1d."""
    out = {(h, c): [] for h in HYPOTHESES for c in CONDITIONS}
    for i in range(window - 1, len(candles)):
        window_ranges = [_range(candles, k) for k in range(i - window + 1, i + 1)]
        conds = {c: fn(candles, i, window_ranges) for c, fn in CONDITIONS.items()}
        ys = {h: fn(candles, i, window_ranges) for h, fn in HYPOTHESES.items()}
        ts = candles[i]["ts"]
        for h, (y, bars) in ys.items():
            for c, cond in conds.items():
                out[(h, c)].append({"ts": ts, "condition": cond, "y": y,
                                    "bars_to_resolve": bars,
                                    "censored": 1 if y is None else 0})
    return out


def label_event_move(candles: list[dict], event_ts: list[int], condition: str,
                     bar_seconds: int, window: int = DEFAULT_WINDOW) -> list[dict]:
    """H4 пререгистрации: |c(t+2) − c(t)| > 1.0·ATR14(t) на барах, содержащих
    high-impact релиз. Магнитуда, не направление — берётся модуль.

    Календарь честен point-in-time именно потому, что это календарь: время
    релиза опубликовано заранее и известно на момент t. Это принципиально
    отличает его от event_reaction_stats — ежедневно пересчитываемого
    агрегата, который в исторический бэктест брать нельзя."""
    cond_fn = CONDITIONS[condition]
    ev = sorted(event_ts)
    rows = []
    for i in range(window - 1, len(candles)):
        ts = candles[i]["ts"]
        # релиз внутри бара i
        has_event = any(ts <= e < ts + bar_seconds for e in ev)
        if not has_event:
            continue
        window_ranges = [_range(candles, k) for k in range(i - window + 1, i + 1)]
        cond = cond_fn(candles, i, window_ranges)
        j = i + EVENT_MOVE_BARS
        a = _atr(candles, i)
        if j >= len(candles) or a is None or a <= 0:
            rows.append({"ts": ts, "condition": cond, "y": None,
                         "bars_to_resolve": 0, "censored": 1})
            continue
        moved = abs(candles[j]["c"] - candles[i]["c"])
        rows.append({"ts": ts, "condition": cond,
                     "y": 1 if moved > EVENT_MOVE_ATR_MULT * a else 0,
                     "bars_to_resolve": EVENT_MOVE_BARS, "censored": 0})
    return rows


def high_impact_event_ts(con: sqlite3.Connection) -> list[int]:
    """scheduled_ts high-impact событий календаря. is_primary=1 — дедупликация
    источников, уже принятая в проекте."""
    rows = con.execute(
        "SELECT scheduled_ts FROM econ_events "
        "WHERE impact='high' AND is_primary=1 AND scheduled_ts IS NOT NULL"
    ).fetchall()
    return [r[0] for r in rows]


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


_TF_TO_PB_ALL = {"H1": "1h", "H4": "4h", "D1": "1d", "M30": "30m"}
_BAR_SECONDS = {"H1": 3600, "H4": 14400, "D1": 86400, "M30": 1800}


def run_family(verbose: bool = False) -> dict:
    """WP6.2 — полное семейство по пререгистрации 2026-08-17_volatility.md.

    m = 30 клеток: 3 гипотезы × 3 условия × 3 ТФ + event_move × 3 условия × M30.
    Число фиксировано пререгистрацией и НЕ пересчитывается по факту того,
    сколько клеток наберёт n."""
    con = sqlite3.connect(str(_BOT_DB), timeout=30)
    init_schema(con)
    event_ts = high_impact_event_ts(con)
    if verbose:
        print(f"high-impact событий календаря: {len(event_ts)}")

    written = {}
    for tf in ["D1", "H4", "H1"]:
        pb_tf = _TF_TO_PB_ALL[tf]
        for sym in _price_bars.available_symbols(pb_tf):
            candles = _price_bars.load_candles(sym, pb_tf)
            if not candles or len(candles) < DEFAULT_WINDOW + ATR_EXPANSION_BARS + 1:
                continue
            pairs = label_all_pairs(candles)
            for (hyp, cond), rows in pairs.items():
                key = f"{hyp}{KEY_SEP}{cond}"
                n = write_labels(con, [{"symbol": sym, "tf": tf, "event_key": key, **r}
                                       for r in rows])
                written[f"{key}|{tf}"] = written.get(f"{key}|{tf}", 0) + n

    # H4 пререгистрации -- только 30m, только бары с high-impact релизом
    for sym in _price_bars.available_symbols("30m"):
        candles = _price_bars.load_candles(sym, "30m")
        if not candles or len(candles) < DEFAULT_WINDOW + EVENT_MOVE_BARS + 1:
            continue
        for cond in CONDITIONS:
            key = f"event_move_gt_1atr{KEY_SEP}{cond}"
            rows = label_event_move(candles, event_ts, cond, _BAR_SECONDS["M30"])
            n = write_labels(con, [{"symbol": sym, "tf": "M30", "event_key": key, **r}
                                   for r in rows])
            written[f"{key}|M30"] = written.get(f"{key}|M30", 0) + n

    con.close()
    if verbose:
        for k in sorted(written):
            print(f"  {k}: {written[k]}")
    return written


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", help="Канонические имена (GOLD, EURUSD, ...)")
    ap.add_argument("--all", action="store_true", help="Все доступные символы")
    ap.add_argument("--tf", nargs="+", default=["D1", "H4", "H1"], choices=["D1", "H4", "H1"])
    ap.add_argument("--family", action="store_true",
                    help="WP6.2: полное семейство по пререгистрации (вместо контроля WP6.0)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    if args.family:
        written = run_family(args.verbose)
        print(f"готово: {sum(written.values())} строк, {len(written)} клеток")
    else:
        symbols = None if args.all else args.symbols
        total = run(symbols, args.tf, args.verbose)
        print(f"готово: {total} строк volatility_labels")
