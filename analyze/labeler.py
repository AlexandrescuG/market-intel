#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/labeler.py — WP2.2 SPEC_alpha_engine_implementation.md.

Оффлайн-разметчик triple-barrier по всей истории price_bars — обобщение
Signals/tracker.py (форвард-трекер: один сигнал за раз, резолюция на ТФ
самого сигнала) в разметку ЛЮБОГО (symbol,tf,ts,direction) по СЕТКЕ
конфигураций, с честными правилами:

  1. Резолюция барьеров — на минимальном доступном ТФ (RESOLUTION_TF),
     не на ТФ сигнала. Signals/tracker.py резолвит на том же ТФ, на
     котором сигнал создан (H4/D1) — внутрибарный путь между барьерами
     неизвестен, при широких барьерах на D1 это может быть значимо.
     30m — минимальный ТФ, который есть у ВСЕХ 31 инструментов (проверено
     при миграции WP1.2); честная M1 для крипты недоступна (её у price_bars
     просто нет), не выдумываем более мелкий ТФ, которого нет на диске.
  2. r_realized — ПОСЛЕ издержек (core.costs.entry_cost_price).
  3. Цензурирование — отдельный флаг `censored`, НЕ `0.0` в r_realized
     (Signals/reporter.py:44-57 считает EXPIRED как 0.0R — это молчаливое
     допущение, искажающее ожидание, см. §2.2 спеки).
  4. Оба барьера в одном баре — LOSS (та же логика, что уже в
     Signals/tracker.py — консервативно, это честно).
  5. Сетка конфигураций (atr_mult × rr × horizon) вместо жёстких 1.5/2.0/30.

Использование:
  python3 analyze/labeler.py --symbols GOLD EURUSD --tf D1 H1 [--verbose]
  python3 analyze/labeler.py --all --verbose
"""
import argparse
import sqlite3
import sys
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.patterns import PATTERNS, detect as detect_patterns
from core import costs as _costs
import core.price_bars as _price_bars

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

RESOLUTION_TF = "30m"
SIGNAL_TFS = ["D1", "H4", "H1"]
_SIGNAL_TF_TO_PB = {"H1": "1h", "H4": "4h", "D1": "1d"}
_SIGNAL_TF_SECONDS = {"H1": 3600, "H4": 14400, "D1": 86400}
_SECONDS_TO_SIGNAL_TF = {v: k for k, v in _SIGNAL_TF_SECONDS.items()}

GRID = {
    "atr_mult": (1.0, 1.5, 2.0),
    "rr": (1.5, 2.0, 3.0),
    "horizon_bars": (20, 30, 60),
}


def config_key(atr_mult: float, rr: float, horizon_bars: int) -> str:
    return f"a{atr_mult}_r{rr}_h{horizon_bars}_{_costs.config_key_suffix()}"


def all_configs():
    for atr_mult, rr, horizon_bars in product(GRID["atr_mult"], GRID["rr"], GRID["horizon_bars"]):
        yield atr_mult, rr, horizon_bars, config_key(atr_mult, rr, horizon_bars)


def init_schema(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS labels (
          symbol TEXT, tf TEXT, ts INTEGER, direction TEXT, config_key TEXT,
          y INTEGER, r_realized REAL, mfe REAL, mae REAL,
          bars_to_resolve INTEGER, censored INTEGER,
          PRIMARY KEY (symbol, tf, ts, direction, config_key)
        )
    """)
    con.commit()


def _atr14(candles: list[dict], i: int) -> float | None:
    """ATR(14) на баре i — только бары <= i, честный ноль lookahead."""
    if i < 14:
        return None
    trs = []
    for k in range(i - 13, i + 1):
        h, l, pc = candles[k]["h"], candles[k]["l"], candles[k - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / 14


def _barriers(entry: float, direction: str, atr_val: float, atr_mult: float, rr: float):
    stop_dist = atr_mult * atr_val
    target_dist = rr * stop_dist
    if direction == "bullish":
        return entry + target_dist, entry - stop_dist  # upper=target, lower=stop
    return entry + stop_dist, entry - target_dist       # upper=stop, lower=target


def _walk_barriers(res_candles: list[dict], i0: int, upper: float, lower: float,
                    deadline_ts: int, direction: str) -> dict:
    """Чистая механика хождения по res_candles от i0+1 до deadline_ts:
    первое касание upper/lower -- WIN/LOSS по direction, оба барьера одним
    баром -- LOSS (консервативно, см. Signals/tracker.py). Не считает
    cost/swap/r_realized -- у каждого вызывающего свой источник правды на
    риск (label_one — atr_mult*atr_val, резолвер WP4 forecasts — явные
    entry/stop/target), смешивать их сюда было бы неверно. Вынесено из
    label_one (WP4.1, «резолвер — тот же движок, что в WP2.2» по спеке) —
    без этого пришлось бы завести вторую копию той же механики хождения."""
    last_i, k = i0, 0
    while i0 + k + 1 < len(res_candles):
        k += 1
        i = i0 + k
        bar = res_candles[i]
        if bar["ts"] > deadline_ts:
            k -= 1
            break
        last_i = i
        hit_up, hit_dn = bar["h"] >= upper, bar["l"] <= lower
        if hit_up and hit_dn:
            y = 0  # оба барьера одним баром -- LOSS, консервативно (Signals/tracker.py)
            exit_price = lower if direction == "bullish" else upper
        elif hit_up:
            y, exit_price = (1, upper) if direction == "bullish" else (0, upper)
        elif hit_dn:
            y, exit_price = (0, lower) if direction == "bullish" else (1, lower)
        else:
            continue
        return {"y": y, "exit_price": exit_price, "bars_to_resolve": k,
                "censored": 0, "last_i": i}
    # не разрешилось за horizon -- цензурировано, НЕ 0.0R (§2.2 спеки)
    return {"y": None, "exit_price": None, "bars_to_resolve": max(k, 0),
            "censored": 1, "last_i": last_i}


def _mfe_mae(candles: list[dict], i0: int, i_end: int, direction: str, entry: float, risk: float) -> tuple[float, float]:
    """MFE/MAE в R, окно [i0+1, i_end] включительно."""
    if risk <= 0:
        return 0.0, 0.0
    best_fav, worst_adv = 0.0, 0.0
    for i in range(i0 + 1, i_end + 1):
        h, l = candles[i]["h"], candles[i]["l"]
        if direction == "bullish":
            fav, adv = (h - entry) / risk, (entry - l) / risk
        else:
            fav, adv = (entry - l) / risk, (h - entry) / risk
        best_fav = max(best_fav, fav)
        worst_adv = max(worst_adv, adv)
    return round(best_fav, 4), round(worst_adv, 4)


def label_one(canonical_symbol: str, direction: str, signal_ts: int, signal_tf_seconds: int,
              res_candles: list[dict], ts_to_idx: dict[int, int], atr_val: float | None,
              atr_mult: float, rr: float, horizon_bars: int) -> dict | None:
    """Одна метка на одну (occurrence, config). direction: 'bullish'/'bearish'
    (neutral-паттерны, напр. inside_bar/doji, размечать нечем — нет
    направленной гипотезы, см. WP3.1 спеки).

    🔴 Найдено в ревью (REVIEW_alpha_engine_WP0-WP3.md, 12.08): раньше ATR
    для барьеров считался ЗДЕСЬ, на res_candles (RESOLUTION_TF=30m) —
    для D1-сигнала это давало ATR14(30m) вместо ATR14(D1), расхождение
    в РАЗЫ (проверено на GOLD: 17.6 vs 85.5, т.е. барьеры были ~5x теснее
    задуманного). Экстремальные результаты WP2.5 (винрейт 4.9% на
    pin_bar_bottom) объясняются этим, а не геометрией паттерна и не
    рыночной неэффективностью. Теперь atr_val — параметр, вызывающий код
    (label_symbol) считает его на ТФ САМОГО СИГНАЛА. res_candles здесь
    используется ТОЛЬКО для честной внутрибарной резолюции пути между
    барьерами (§2.2 спеки), не для их размера.

    horizon_bars — в барах ТФ СИГНАЛА (как и задумывалось: "30" для D1
    значит 30 дней, не 30×30-минуток). Конвертируется в реальное время
    (signal_tf_seconds) для честного поиска по res_candles.

    🔴 Ревью §3 (12.08): издержка (спред) и своп теперь тоже зависят от
    signal_tf, не только от символа — цена спреда не меняется с ТФ
    графика, а ATR растёт с ТФ, так что доля от ATR падает с H1 к D1
    (см. core.costs.DAOTI_SPREAD_ATR). signal_tf восстанавливается из
    signal_tf_seconds (не отдельный параметр — та же информация, второй
    источник истины не заводим)."""
    if direction not in ("bullish", "bearish"):
        return None
    if atr_val is None or atr_val <= 0:
        return None
    signal_tf = _SECONDS_TO_SIGNAL_TF.get(signal_tf_seconds)
    i0 = ts_to_idx.get(signal_ts)
    if i0 is None:
        # сигнал на грубом ТФ (H1/H4/D1) — его ts может не совпасть ровно с
        # баром RESOLUTION_TF; вход не раньше, чем сигнал стал известен.
        i0 = next((i for i, c in enumerate(res_candles) if c["ts"] >= signal_ts), None)
        if i0 is None:
            return None
        # 🔴 Найдено на реальных данных WP2.5: у XAUUSD 30m начинается
        # 2024-07-16, а D1-сигналы есть с 2018 -- без этой проверки ВСЕ
        # сигналы 2018-2024 молча привязывались к одному и тому же первому
        # 30m-бару (2024 год) -- см. Core-лог 11.08. Резолюция честна
        # только если найденный бар реально близко к моменту сигнала.
        if abs(res_candles[i0]["ts"] - signal_ts) > 3 * 86400:
            return None
    entry = res_candles[i0]["c"]
    upper, lower = _barriers(entry, direction, atr_val, atr_mult, rr)
    cost = _costs.entry_cost_price(canonical_symbol, atr_val, signal_tf)
    risk = abs(entry - (lower if direction == "bullish" else upper))
    if risk <= 0:
        return None

    deadline_ts = signal_ts + horizon_bars * signal_tf_seconds
    walk = _walk_barriers(res_candles, i0, upper, lower, deadline_ts, direction)
    if walk["censored"]:
        mfe, mae = _mfe_mae(res_candles, i0, walk["last_i"], direction, entry, risk)
        return {"y": None, "r_realized": None, "mfe": mfe, "mae": mae,
                "bars_to_resolve": walk["bars_to_resolve"], "censored": 1}

    gross = (walk["exit_price"] - entry) if direction == "bullish" else (entry - walk["exit_price"])
    nights_held = (res_candles[walk["last_i"]]["ts"] - signal_ts) // 86400
    swap_pnl = _costs.swap_cost_price(canonical_symbol, direction, nights_held)
    r_realized = round((gross - cost + swap_pnl) / risk, 4)
    mfe, mae = _mfe_mae(res_candles, i0, walk["last_i"], direction, entry, risk)
    return {"y": walk["y"], "r_realized": r_realized, "mfe": mfe, "mae": mae,
            "bars_to_resolve": walk["bars_to_resolve"], "censored": 0}


def _load_levels(con: sqlite3.Connection, canonical_symbol: str) -> list[dict]:
    """Симметрично pattern_stats_job.py._load_levels — без этого
    _detect_break_retest(ohlcv, levels=None) внутри core.patterns.detect()
    не находит ничего (нет уровней, от которых мерить пробой/ретест) —
    настоящий баг, поймано при разборе baseline WP2.5 (break_retest давал
    n=0 везде, см. Core-лог 11.08)."""
    try:
        rows = con.execute(
            "SELECT price, tolerance, kind FROM sr_levels WHERE symbol=? AND broken=0", (canonical_symbol,)
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [{"price": r[0], "tolerance": r[1], "kind": r[2]} for r in rows]


def label_symbol(canonical_symbol: str, signal_tfs: list[str] = SIGNAL_TFS, verbose: bool = False) -> list[dict]:
    """Все метки для одного символа: 8 паттернов × запрошенные signal_tf ×
    вся сетка конфигураций. Возвращает готовые к put_many-style INSERT строки."""
    res_candles = _price_bars.load_candles(canonical_symbol, RESOLUTION_TF)
    if not res_candles:
        return []
    ts_to_idx = {c["ts"]: i for i, c in enumerate(res_candles)}
    configs = list(all_configs())
    con = sqlite3.connect(str(_BOT_DB))
    levels = _load_levels(con, canonical_symbol)
    con.close()
    rows = []
    for signal_tf in signal_tfs:
        pb_tf = _SIGNAL_TF_TO_PB[signal_tf]
        signal_tf_seconds = _SIGNAL_TF_SECONDS[signal_tf]
        signal_candles = _price_bars.load_candles(canonical_symbol, pb_tf)
        if not signal_candles or len(signal_candles) < 30:
            continue
        signal_ts_to_idx = {c["ts"]: i for i, c in enumerate(signal_candles)}
        events = detect_patterns(signal_candles, levels)
        # Исход барьера зависит только от (symbol,tf,ts,direction,config) —
        # НЕ от того, какой паттерн предложил направление (та же цена, тот
        # же ATR, те же барьеры). Поэтому в схеме labels нет pattern_key
        # (см. Core-лог 11.08) — если два паттерна согласны по направлению
        # на одном баре, размечаем это ОДИН раз, а не дважды тем же числом.
        occ_keys = {(e["ts"], e["direction"]) for e in events if e["direction"] in ("bullish", "bearish")}
        for ts, direction in occ_keys:
            # ATR — на ТФ САМОГО СИГНАЛА (signal_candles), не на res_candles
            # (30m) -- см. докстринг label_one про 5x-расхождение, найденное
            # в ревью 12.08.
            signal_i = signal_ts_to_idx.get(ts)
            atr_val = _atr14(signal_candles, signal_i) if signal_i is not None else None
            for atr_mult, rr, horizon_bars, ckey in configs:
                lbl = label_one(canonical_symbol, direction, ts, signal_tf_seconds,
                                 res_candles, ts_to_idx, atr_val, atr_mult, rr, horizon_bars)
                if lbl is None:
                    continue
                rows.append({
                    "symbol": canonical_symbol, "tf": signal_tf, "ts": ts,
                    "direction": direction, "config_key": ckey, **lbl,
                })
        if verbose:
            print(f"  {canonical_symbol} {signal_tf}: {len(occ_keys)} уникальных (ts,direction) x {len(configs)} configs")
    return rows


def write_labels(con: sqlite3.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    con.executemany(
        """INSERT OR REPLACE INTO labels
           (symbol, tf, ts, direction, config_key, y, r_realized, mfe, mae, bars_to_resolve, censored)
           VALUES (:symbol, :tf, :ts, :direction, :config_key, :y, :r_realized, :mfe, :mae,
                   :bars_to_resolve, :censored)""",
        rows,
    )
    con.commit()
    return len(rows)


def run(symbols: list[str] | None, signal_tfs: list[str], verbose: bool = False) -> int:
    con = sqlite3.connect(str(_BOT_DB))
    init_schema(con)
    syms = symbols or _price_bars.available_symbols("1d")
    total = 0
    for sym in syms:
        rows = label_symbol(sym, signal_tfs, verbose)
        n = write_labels(con, rows)
        total += n
        if verbose:
            print(f"{sym}: {n} строк labels")
    con.close()
    return total


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", help="Канонические имена (GOLD, EURUSD, ...)")
    ap.add_argument("--all", action="store_true", help="Все доступные символы")
    ap.add_argument("--tf", nargs="+", default=SIGNAL_TFS, choices=SIGNAL_TFS)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    symbols = None if args.all else args.symbols
    total = run(symbols, args.tf, args.verbose)
    print(f"готово: {total} строк labels")
