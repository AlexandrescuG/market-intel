#!/usr/bin/env python3
"""
pattern_stats_job.py — SBF_Charts_Layer2_Spec, Фаза 3, Шаг 2 (бэктест-джоб).

Еженедельно (вс 05:00, см. sbf-pattern-stats.timer): для каждой тройки
(pattern_key, symbol, tf ∈ {H1,H4,D1}) прогоняет core/patterns.detect() по
всей доступной истории OHLCV и считает согласованность с направлением
паттерна через 3/5/10 свечей.

Использование:
  python3 pattern_stats_job.py [--verbose]
"""
import argparse
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core.patterns import PATTERNS, detect
import core.price_bars as _price_bars
from event_reactions_job import _pip_scale

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
TIMEFRAMES = ["H1", "H4", "D1"]
# наш код ТФ -> код в price_bars. Шире, чем TIMEFRAMES (бэктест-петля выше) --
# 🔴 живой /api/chart/patterns (serve.py:_handle_chart_patterns) зовёт ЭТУ ЖЕ
# _load_candles() с любым ТФ кнопок графика (M15/M30/W1 тоже), не только тремя
# бэктестируемыми -- KeyError на M30 не был пойман curl'ом по H1, нашёлся
# только кликом по вкладке (см. Core-лог WP1.2). M5 намеренно не сюда -- у
# price_bars нет '5m', честный None лучше падения.
_TF_TO_PB = {"M15": "15m", "M30": "30m", "H1": "1h", "H4": "4h", "D1": "1d", "W1": "1w"}
CHECKPOINTS = (3, 5, 10)
MIN_GAP_BARS = 6  # дедупликация — симметрично chart.html:436-442 ("не ближе 6 баров")


def _dedup_by_gap(occs, ts_to_idx, min_gap_bars=MIN_GAP_BARS):
    """Не ближе min_gap_bars баров подряд на один pattern_key.

    Якорь — индекс ПОСЛЕДНЕГО ОСТАВЛЕННОГО срабатывания (не последнего вообще),
    та же логика, что в chart.html:438-440 и что уже описана как правильная
    в confluence_job.py._cluster_factors — цепочка по последнему элементу
    (а не по якорю) занижает разрыв и завышает n.
    """
    kept = []
    last_kept_idx = None
    for occ in occs:
        i = ts_to_idx.get(occ["ts"])
        if i is None:
            continue
        if last_kept_idx is not None and (i - last_kept_idx) < min_gap_bars:
            continue
        last_kept_idx = i
        kept.append(occ)
    return kept


def _load_candles(symbol: str, tf: str):
    """WP1.2 SPEC_alpha_engine_implementation.md: раньше D1 шёл через
    sr_levels_job._load_d1_candles (JSON), H1/H4 — свой парсинг того же
    ohlc_{symbol}_{tf}.json. Один источник (price_bars) убирает саму
    развилку -- обе ветки были одним и тем же чтением из разных файлов."""
    pb_tf = _TF_TO_PB.get(tf)
    if pb_tf is None:
        return None
    return _price_bars.load_candles(symbol, pb_tf)


def _load_levels(con, symbol: str):
    try:
        rows = con.execute(
            "SELECT price, tolerance, kind FROM sr_levels WHERE symbol=? AND broken=0", (symbol,)
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [{"price": r[0], "tolerance": r[1], "kind": r[2]} for r in rows]


def backtest_symbol_tf(symbol: str, tf: str, levels, verbose=False):
    candles = _load_candles(symbol, tf)
    if not candles or len(candles) < 30:
        return []
    events = detect(candles, levels)
    if not events:
        return []

    ts_to_idx = {c["ts"]: i for i, c in enumerate(candles)}
    scale = _pip_scale(symbol)

    # group occurrences by pattern_key, каждая со своим направлением
    by_pattern: dict[str, list] = {}
    for e in events:
        if PATTERNS.get(e["pattern_key"], {}).get("direction") == "neutral" and e["direction"] == "neutral":
            continue  # inside_bar и подобные без направления — тестировать нечего
        by_pattern.setdefault(e["pattern_key"], []).append(e)

    results = []
    for pattern_key, occs in by_pattern.items():
        occs = sorted(occs, key=lambda e: e["ts"])
        occs = _dedup_by_gap(occs, ts_to_idx)
        agree = {3: [], 5: [], 10: []}
        moves_5, adverse_5 = [], []
        history_from_ts = candles[0]["ts"]
        n = 0
        for occ in occs:
            i = ts_to_idx.get(occ["ts"])
            if i is None or i + max(CHECKPOINTS) >= len(candles):
                continue
            direction = occ["direction"]
            if direction not in ("bullish", "bearish"):
                continue
            base_close = candles[i]["c"]
            n += 1
            for k in CHECKPOINTS:
                delta = candles[i + k]["c"] - base_close
                agreed = (delta > 0) if direction == "bullish" else (delta < 0)
                agree[k].append(1 if agreed else 0)
            window = candles[i + 1:i + 6]
            move5 = abs(candles[i + 5]["c"] - base_close) * scale
            moves_5.append(move5)
            if direction == "bullish":
                adverse = base_close - min(c["l"] for c in window)
            else:
                adverse = max(c["h"] for c in window) - base_close
            adverse_5.append(max(0.0, adverse) * scale)

        if n == 0:
            continue
        results.append({
            "pattern_key": pattern_key, "symbol": symbol, "tf": tf, "n": n,
            "agree_share_3": round(sum(agree[3]) / len(agree[3]), 4) if agree[3] else None,
            "agree_share_5": round(sum(agree[5]) / len(agree[5]), 4) if agree[5] else None,
            "agree_share_10": round(sum(agree[10]) / len(agree[10]), 4) if agree[10] else None,
            "avg_move_5": round(sum(moves_5) / len(moves_5), 4) if moves_5 else None,
            "max_adverse_5": round(sum(adverse_5) / len(adverse_5), 4) if adverse_5 else None,
            "history_from_ts": history_from_ts,
        })
        if verbose:
            print(f"  {symbol} {tf} {pattern_key}: n={n} agree5={results[-1]['agree_share_5']}")
    return results


def run(verbose: bool = False) -> int:
    con = sqlite3.connect(str(_BOT_DB))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS pattern_stats(
          pattern_key TEXT, symbol TEXT, tf TEXT, n INT,
          agree_share_3 REAL, agree_share_5 REAL, agree_share_10 REAL,
          avg_move_5 REAL, max_adverse_5 REAL, history_from_ts INT, computed_ts INT,
          PRIMARY KEY(pattern_key, symbol, tf));
    """)
    con.commit()

    now_ts = int(time.time())
    symbols = _price_bars.available_symbols("1d")

    written = 0
    for symbol in symbols:
        # WP1.2 SPEC_alpha_engine_implementation.md: полный пересчёт символа с
        # нуля -- без этого DELETE строки H1/H4, посчитанные раньше из
        # ohlc_*.json (Yahoo-проекция), остаются в таблице протухшими для
        # символов, у которых price_bars честно не имеет этого ТФ (см. Core-лог
        # 07-08.08: только 6 инструментов Daoti-покрытия дают H1/H4 нативно).
        con.execute("DELETE FROM pattern_stats WHERE symbol=?", (symbol,))
        levels = _load_levels(con, symbol)
        for tf in TIMEFRAMES:
            for r in backtest_symbol_tf(symbol, tf, levels, verbose):
                con.execute(
                    """INSERT OR REPLACE INTO pattern_stats
                       (pattern_key, symbol, tf, n, agree_share_3, agree_share_5, agree_share_10,
                        avg_move_5, max_adverse_5, history_from_ts, computed_ts)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (r["pattern_key"], r["symbol"], r["tf"], r["n"],
                     r["agree_share_3"], r["agree_share_5"], r["agree_share_10"],
                     r["avg_move_5"], r["max_adverse_5"], r["history_from_ts"], now_ts),
                )
                written += 1
    con.commit()
    con.close()
    if verbose:
        print(f"готово: {written} (pattern,symbol,tf) агрегатов записано")
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    run(verbose=args.verbose)
