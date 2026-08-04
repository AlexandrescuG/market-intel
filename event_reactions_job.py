#!/usr/bin/env python3
"""
event_reactions_job.py — SBF_Charts_Layer1_Spec, Фаза 2 («Прошлые разы»).

Офлайн-джоб (раз в сутки 04:30, см. sbf-event-reactions.timer): для каждого
(event_type, symbol) с weight>=1 в event_instrument_map считает статистику
реакции цены на прошлые публикации по M30 OHLCV из price_bars.

Использование:
  python3 event_reactions_job.py [--verbose]
"""
import argparse
import re
import sqlite3
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core.event_types import normalize_event_type

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

# GOLD на живом графике (chart.html) хранится в price_bars/symbol_map как XAUUSD —
# два разных символьных пространства, см. память project_sbf_charts_layer1.
_CHART_TO_PRICE_BARS_SYMBOL = {"GOLD": "XAUUSD"}

# "Пункт"/"пипс" — разный масштаб для разных классов инструментов: у FX-пар
# сырая разница цены (напр. 0.0006 для EURUSD) выглядит как визуальный "0.00" —
# без масштабирования числа были бы бессмысленны для валютных пар (найдено на
# верификации: EURUSD показывал avg_move=0.00 почти everywhere, хотя реальное
# движение было). 1 пипс EURUSD/GBPUSD = 0.0001, USDJPY = 0.01, золото/индексы/
# крипта/commodities — уже в "долларовых" пунктах, масштаб 1.
_PIP_SCALE = {"EURUSD": 10000, "GBPUSD": 10000, "USDJPY": 100}


def _pip_scale(symbol: str) -> float:
    return _PIP_SCALE.get(symbol, 1)

# Источники econ_events по надёжности/приоритету — при дедупликации одной и той
# же публикации, попавшей в календарь и от FF, и от TV (разные строки, разный
# event_key, т.к. хешируется по точному тексту title), берём одну запись.
_SOURCE_PRIORITY = {"curated_official": 0, "forexfactory": 1, "tradingview": 2}

MIN_CASES = 4
N_TIERS = (6, 12)
WINDOW_30M = 1800
WINDOW_60M = 3600


def _numeric(v):
    if v is None:
        return None
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(v))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "."))
    except ValueError:
        return None


def _fetch_reaction_rows(con):
    """econ_events с actual, для символов из event_instrument_map (weight>=1)."""
    return con.execute("""
        SELECT e.id, e.event_key, e.country, e.title, e.indicator,
               e.actual, e.forecast, e.scheduled_ts, e.source, m.symbol
        FROM econ_events e
        JOIN event_instrument_map m ON m.country = e.country
        WHERE m.weight >= 1
          AND e.actual IS NOT NULL AND e.actual != ''
          AND e.scheduled_ts IS NOT NULL
        ORDER BY e.scheduled_ts ASC
    """).fetchall()


def _dedup_same_release(rows):
    """Несколько источников (FF/TV) часто описывают один и тот же релиз разными
    строками title (разный event_key). Группируем по (symbol, event_type, дата,
    страна) и берём одну запись по приоритету источника — иначе один и тот же
    реальный релиз считается дважды и раздувает статистику."""
    groups = {}
    for r in rows:
        etype = normalize_event_type(r["indicator"] or r["title"])
        day = r["scheduled_ts"] // 86400
        key = (r["symbol"], etype, r["country"], day)
        cur = groups.get(key)
        if cur is None or _SOURCE_PRIORITY.get(r["source"], 9) < _SOURCE_PRIORITY.get(cur["source"], 9):
            groups[key] = r
    return list(groups.values()), {id(r): normalize_event_type(r["indicator"] or r["title"]) for r in groups.values()}


def _bars_by_ts(con, symbol, from_ts, to_ts):
    price_symbol = _CHART_TO_PRICE_BARS_SYMBOL.get(symbol, symbol)
    rows = con.execute(
        "SELECT ts, o, h, l, c FROM price_bars WHERE symbol=? AND tf='30m' AND ts BETWEEN ? AND ? ORDER BY ts",
        (price_symbol, from_ts, to_ts),
    ).fetchall()
    return {r["ts"]: r for r in rows}


def _nearest_bar(bars_by_ts, target_ts, tolerance=900):
    if target_ts in bars_by_ts:
        return bars_by_ts[target_ts]
    best, best_dist = None, None
    for ts, b in bars_by_ts.items():
        d = abs(ts - target_ts)
        if d <= tolerance and (best is None or d < best_dist):
            best, best_dist = b, d
    return best


def _atr14(con, symbol):
    """Текущий дневной ATR(14) — простая (не точечная по времени) оценка
    типичной волатильности инструмента, для метки 'исторически волатильно'."""
    price_symbol = _CHART_TO_PRICE_BARS_SYMBOL.get(symbol, symbol)
    rows = con.execute(
        "SELECT ts, o, h, l, c FROM price_bars WHERE symbol=? AND tf='1d' ORDER BY ts DESC LIMIT 15",
        (price_symbol,),
    ).fetchall()
    if len(rows) < 2:
        return None
    rows = list(reversed(rows))  # ascending
    trs = []
    for i in range(1, len(rows)):
        h, l, prev_c = rows[i]["h"], rows[i]["l"], rows[i - 1]["c"]
        trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
    if not trs:
        return None
    return (sum(trs) / len(trs)) * _pip_scale(symbol)


def _case_metrics(con, symbol, release_ts):
    """Метрики одного случая: ход 30м/60м (пункты), макс. амплитуда, направление."""
    bars = _bars_by_ts(con, symbol, release_ts - 1800, release_ts + 3600 + 1800)
    bar0 = _nearest_bar(bars, release_ts)
    if bar0 is None:
        return None
    bar1 = _nearest_bar(bars, release_ts + WINDOW_30M)
    scale = _pip_scale(symbol)
    move_30m = abs(bar0["c"] - bar0["o"]) * scale
    if bar1 is not None:
        move_60m = abs(bar1["c"] - bar0["o"]) * scale
        true_range = (max(bar0["h"], bar1["h"]) - min(bar0["l"], bar1["l"])) * scale
        close_ref = bar1["c"]
    else:
        move_60m = None
        true_range = (bar0["h"] - bar0["l"]) * scale
        close_ref = bar0["c"]
    direction = "up" if close_ref > bar0["o"] else "down" if close_ref < bar0["o"] else "flat"
    return {
        "move_30m": move_30m, "move_60m": move_60m,
        "true_range": true_range, "dir": direction,
    }


def run(verbose: bool = False) -> int:
    con = sqlite3.connect(str(_BOT_DB))
    con.row_factory = sqlite3.Row

    # Джоб каждый раз пересчитывает ВСЁ с нуля из econ_events+price_bars — чистим
    # старые агрегаты перед записью. Иначе строки с n из прошлых прогонов (когда
    # истории было меньше) остаются в таблице рядом с новыми при другом n
    # (PRIMARY KEY включает n) и API может выбрать устаревшую как "n6"/"n12".
    con.execute("DELETE FROM event_reaction_stats")

    raw_rows, _ = _dedup_same_release(_fetch_reaction_rows(con))
    if verbose:
        print(f"событий-кандидатов после дедупликации источников: {len(raw_rows)}")

    # group -> (event_type, symbol) -> list of (release_ts, event_key, actual, forecast)
    grouped: dict[tuple, list] = {}
    for r in raw_rows:
        etype = normalize_event_type(r["indicator"] or r["title"])
        grouped.setdefault((etype, r["symbol"]), []).append(r)

    atr_cache: dict[str, float | None] = {}
    stats_written = 0
    cases_written = 0

    for (etype, symbol), rows in grouped.items():
        rows.sort(key=lambda r: r["scheduled_ts"])
        cases = []
        for r in rows:
            m = _case_metrics(con, symbol, r["scheduled_ts"])
            if m is None:
                continue
            cases.append((r, m))
            # сырые метрики случая — для ручной сверки (Acceptance спеки)
            for window, move in (("30m", m["move_30m"]), ("60m", m["move_60m"])):
                if move is None:
                    continue
                actual_n, forecast_n = _numeric(r["actual"]), _numeric(r["forecast"])
                close_dir = ("beat" if actual_n > forecast_n else "miss" if actual_n < forecast_n else "inline") \
                    if actual_n is not None and forecast_n is not None else None
                con.execute("""
                    INSERT OR REPLACE INTO event_reactions
                      (event_key, symbol, release_ts, window, pips, true_range, dir, close_dir)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (r["event_key"], symbol, r["scheduled_ts"], window, move, m["true_range"], m["dir"], close_dir))
                cases_written += 1

        if len(cases) < MIN_CASES:
            continue

        if symbol not in atr_cache:
            atr_cache[symbol] = _atr14(con, symbol)
        atr = atr_cache[symbol]
        atr_quarter = (atr / 4) if atr else None

        now_ts = int(time.time())
        for n_target in N_TIERS:
            subset = cases[-n_target:]
            moves_30 = [m["move_30m"] for _, m in subset if m["move_30m"] is not None]
            moves_60 = [m["move_60m"] for _, m in subset if m["move_60m"] is not None]
            if not moves_60:
                continue
            avg_30 = sum(moves_30) / len(moves_30) if moves_30 else None
            avg_60 = sum(moves_60) / len(moves_60)
            max_60 = max(moves_60)
            volatile_share = (
                sum(1 for v in moves_60 if atr_quarter and v > atr_quarter) / len(moves_60)
                if atr_quarter else None
            )
            # SPEC_morning_brief_v2.md блок 1 ("в прошлые разы"): медиана (не среднее
            # -- устойчивее к одному экстремальному релизу) 30-минутного хода,
            # нормированная на дневной ATR14 инструмента (atr уже в пункт-масштабе,
            # см. _atr14() выше) -- "0.31 ATR за 30 мин", а не сырые пункты.
            median_30 = statistics.median(moves_30) if moves_30 else None
            median_atr_30m = (median_30 / atr) if (atr and median_30 is not None) else None
            con.execute("""
                INSERT OR REPLACE INTO event_reaction_stats
                  (event_type, symbol, n, avg_move_30m, avg_move_60m, max_move_60m, volatile_share,
                   median_move_30m, median_atr_30m, computed_ts)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (etype, symbol, len(subset), avg_30, avg_60, max_60, volatile_share,
                  median_30, median_atr_30m, now_ts))
            stats_written += 1
            if verbose:
                print(f"  {etype}×{symbol} n={len(subset)}: avg60={avg_60:.2f} max60={max_60:.2f} "
                      f"vol_share={volatile_share}")

    con.commit()
    con.close()
    if verbose:
        print(f"готово: {stats_written} агрегатов, {cases_written} сырых случаев")
    return stats_written


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    n = run(verbose=args.verbose)
    print(f"event_reactions_job: {n} агрегатов записано", file=sys.stderr)
