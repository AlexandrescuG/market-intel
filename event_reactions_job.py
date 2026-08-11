#!/usr/bin/env python3
"""
event_reactions_job.py — SBF_Charts_Layer1_Spec, Фаза 2 («Прошлые разы»)
+ СПЕКА_календарь_и_движения_рынка.md §3 (нормировка на фон часа суток, период
выборки, 4-часовое окно для сверки с Recognia).

Офлайн-джоб (раз в сутки 04:30, см. sbf-event-reactions.timer): для каждого
(event_type, symbol) с weight>=1 в event_instrument_map считает статистику
реакции цены на прошлые публикации по M30 OHLCV из price_bars.

Нормировка на фон часа суток (§3, "самое важное"): 38 пипс в 15:30 UTC и
38 пипс в 03:00 UTC — разные события, во втором случае это аномалия. Берём
типичный (без разбора событие/не событие) ход того же часа из уже
посчитанного tools/edu_build/hourly_profile.py (глава 5) — не считаем заново.
baseline_ratio_30m = медиана по случаям (ход/типичный ход ЭТОГО часа), не
общий ход/общий типичный час — так каждый случай сравнивается со своим часом,
а не усредняется вслепую по событиям, которые могут выходить в разное время.

Использование:
  python3 event_reactions_job.py [--verbose]
"""
import argparse
import json
import re
import sqlite3
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core.event_types import normalize_event_type

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
_HOURLY_PROFILE = Path(__file__).parent / "web" / "data" / "edu_stats" / "hourly_profile.json"
WINDOW_4H = 4 * 3600

# GOLD на живом графике (chart.html) хранится в price_bars/symbol_map как XAUUSD —
# два разных символьных пространства, см. память project_sbf_charts_layer1.
_CHART_TO_PRICE_BARS_SYMBOL = {"GOLD": "XAUUSD"}

# "Пункт"/"пипс" — разный масштаб для разных классов инструментов: у FX-пар
# сырая разница цены (напр. 0.0006 для EURUSD) выглядит как визуальный "0.00" —
# без масштабирования числа были бы бессмысленны для валютных пар (найдено на
# верификации: EURUSD показывал avg_move=0.00 почти everywhere, хотя реальное
# движение было). 1 пипс EURUSD/GBPUSD = 0.0001, USDJPY = 0.01, золото/индексы/
# крипта/commodities — уже в "долларовых" пунктах, масштаб 1.
# SPEC_графики_и_починка_календаря.md §2: 12 новых пар (06.08) без масштаба
# показывали move в "0 п." (.toFixed(0) от сырой цены 0.xxxx) -- тот же класс
# бага, что уже был найден для EURUSD/GBPUSD/USDJPY (см. комментарий выше про
# avg_move=0.00). Курсы < ~50 -- 4-значный пункт (×10000), как у majors;
# HUF/CZK/KRW котируются с ценой в сотнях-тысячах -- 2-значный пункт (×100),
# та же конвенция, что уже применена к USDJPY.
_PIP_SCALE = {
    "EURUSD": 10000, "GBPUSD": 10000, "USDJPY": 100,
    "EURGBP": 10000, "USDCAD": 10000, "USDCHF": 10000, "AUDUSD": 10000, "NZDUSD": 10000,
    "USDBRL": 10000, "USDMXN": 10000, "USDTRY": 10000, "USDPLN": 10000,
    "USDHUF": 100, "USDCZK": 100, "USDKRW": 100,
}


def _pip_scale(symbol: str) -> float:
    return _PIP_SCALE.get(symbol, 1)

# Источники econ_events по надёжности/приоритету — при дедупликации одной и той
# же публикации, попавшей в календарь и от FF, и от TV (разные строки, разный
# event_key, т.к. хешируется по точному тексту title), берём одну запись.
_SOURCE_PRIORITY = {"curated_official": 0, "forexfactory": 1, "tradingview": 2}

MIN_CASES = 4
N_TIERS = (6, 12)
MIN_DIR_CASES = 3  # мин. случаев beat/miss отдельно, чтобы показать долю направления (§"Влияние")
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


def _load_hourly_baseline():
    """symbol -> {hour_utc(int) -> typical M30-бар range (в тех же "пунктах",
    что hourly_profile.py считает — сырая цена, БЕЗ _PIP_SCALE) усреднённый
    по всем доступным периодам (месяцы/годы) — история короткая (2-3 месяца
    у GOLD/EURUSD), матчить период события точь-в-точь избыточно, честнее
    взять типичный ход часа по всему, что есть, чем молча пропустить событие,
    для которого нет ровно того же месяца в hourly_profile.json.
    Источник — tools/edu_build/hourly_profile.py, не пересчитываем заново
    (§3 спеки: "брать делитель оттуда, не изобретать заново")."""
    if not _HOURLY_PROFILE.exists():
        return {}
    try:
        data = json.loads(_HOURLY_PROFILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, dict[int, float]] = {}
    for symbol, payload in data.items():
        if symbol == "_meta" or not isinstance(payload, dict):
            continue
        by_period = payload.get("by_period") or {}
        acc: dict[int, list[float]] = {}
        for _period, hours in by_period.items():
            for hh, cell in hours.items():
                mp = cell.get("median_pts")
                if mp is None:
                    continue
                acc.setdefault(int(hh), []).append(mp)
        out[symbol] = {hh: statistics.mean(vals) for hh, vals in acc.items() if vals}
    return out


def _case_metrics(con, symbol, release_ts, hourly_baseline):
    """Метрики одного случая: ход 30м/60м/4ч (пункты), макс. амплитуда,
    направление, плюс нормировка 30-минутного хода на типичный ход ЭТОГО часа
    суток (baseline_ratio) без разбора событие/не событие (§3 спеки)."""
    bars = _bars_by_ts(con, symbol, release_ts - 1800, release_ts + WINDOW_4H + 1800)
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

    # 4-часовое окно -- тот же горизонт, что у контрольных цифр Recognia (§0),
    # используется для одноразовой сверки порядка величины, не для карточки.
    window_bars = {ts: b for ts, b in bars.items() if release_ts <= ts <= release_ts + WINDOW_4H}
    if window_bars:
        true_range_4h = (max(b["h"] for b in window_bars.values())
                          - min(b["l"] for b in window_bars.values())) * scale
    else:
        true_range_4h = None

    hour_utc = datetime.fromtimestamp(release_ts, tz=timezone.utc).hour
    baseline_30m = (hourly_baseline.get(symbol) or {}).get(hour_utc)
    baseline_ratio = (move_30m / (baseline_30m * scale)) if baseline_30m else None

    return {
        "move_30m": move_30m, "move_60m": move_60m, "true_range_4h": true_range_4h,
        "true_range": true_range, "dir": direction,
        "baseline_30m": (baseline_30m * scale) if baseline_30m else None,
        "baseline_ratio": baseline_ratio,
    }


def _migrate(con: sqlite3.Connection) -> None:
    """WP1.4 SPEC_alpha_engine_implementation.md: раньше был свой список
    ALTER TABLE, независимый от serve.py::_ensure_schema -- и уже разошёлся
    (тут не было median_move_30m/median_atr_30m). core.db_migrations —
    общий версионированный источник, идемпотентен сам по себе."""
    from core.db_migrations import apply_all
    apply_all(con)


def run(verbose: bool = False) -> int:
    con = sqlite3.connect(str(_BOT_DB))
    con.row_factory = sqlite3.Row
    _migrate(con)

    hourly_baseline = _load_hourly_baseline()
    if verbose:
        print(f"hourly_profile.json: фон часа суток загружен для {len(hourly_baseline)} символов"
              + (" (файл не найден — нормировка на фон часа отключена)" if not hourly_baseline else ""))

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
            m = _case_metrics(con, symbol, r["scheduled_ts"], hourly_baseline)
            if m is None:
                continue
            actual_n, forecast_n = _numeric(r["actual"]), _numeric(r["forecast"])
            m["close_dir"] = ("beat" if actual_n > forecast_n else "miss" if actual_n < forecast_n else "inline") \
                if actual_n is not None and forecast_n is not None else None
            cases.append((r, m))
            # сырые метрики случая — для ручной сверки (Acceptance спеки).
            # 4ч записывается тоже — тот же охват, что у контрольных цифр
            # Recognia (§0), для одноразовой сверки порядка величины скриптом
            # compare_recognia.py, не для показа на карточке.
            for window, move, tr in (("30m", m["move_30m"], m["true_range"]),
                                      ("60m", m["move_60m"], m["true_range"]),
                                      ("4h", m["true_range_4h"], m["true_range_4h"])):
                if move is None:
                    continue
                con.execute("""
                    INSERT OR REPLACE INTO event_reactions
                      (event_key, symbol, release_ts, window, pips, true_range, dir, close_dir)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (r["event_key"], symbol, r["scheduled_ts"], window, move, tr, m["dir"], m["close_dir"]))
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
            moves_4h = [m["true_range_4h"] for _, m in subset if m["true_range_4h"] is not None]
            ratios_30 = [m["baseline_ratio"] for _, m in subset if m["baseline_ratio"] is not None]
            baselines_30 = [m["baseline_30m"] for _, m in subset if m["baseline_30m"] is not None]
            if not moves_60:
                continue
            avg_30 = sum(moves_30) / len(moves_30) if moves_30 else None
            avg_60 = sum(moves_60) / len(moves_60)
            max_60 = max(moves_60)
            avg_4h = sum(moves_4h) / len(moves_4h) if moves_4h else None
            max_4h = max(moves_4h) if moves_4h else None
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
            # СПЕКА_календарь §3, "самое важное": медиана ПО СЛУЧАЯМ отношения
            # (ход / типичный ход ЭТОГО часа) -- каждый случай нормирован на
            # фон своего собственного часа выхода, а не одного общего часа.
            baseline_ratio_30m = statistics.median(ratios_30) if ratios_30 else None
            hourly_baseline_30m = statistics.median(baselines_30) if baselines_30 else None
            dates = [datetime.fromtimestamp(r["scheduled_ts"], tz=timezone.utc).strftime("%Y-%m-%d")
                     for r, _ in subset]
            period_from, period_to = min(dates), max(dates)

            # "Влияние": доля up/down/flat ОТДЕЛЬНО среди случаев beat и miss —
            # без предположения, в какую сторону "должно" двигать курс (у нас
            # нет общей таблицы полярности индикаторов по всем странам, только
            # то, что видно в самих данных). Описательно: что происходило,
            # не что "должно" происходить.
            beat_dirs = [m["dir"] for _, m in subset if m.get("close_dir") == "beat" and m["dir"]]
            miss_dirs = [m["dir"] for _, m in subset if m.get("close_dir") == "miss" and m["dir"]]
            n_beat, n_miss = len(beat_dirs), len(miss_dirs)
            beat_up_share = beat_dirs.count("up") / n_beat if n_beat >= MIN_DIR_CASES else None
            beat_down_share = beat_dirs.count("down") / n_beat if n_beat >= MIN_DIR_CASES else None
            miss_up_share = miss_dirs.count("up") / n_miss if n_miss >= MIN_DIR_CASES else None
            miss_down_share = miss_dirs.count("down") / n_miss if n_miss >= MIN_DIR_CASES else None

            con.execute("""
                INSERT OR REPLACE INTO event_reaction_stats
                  (event_type, symbol, n, avg_move_30m, avg_move_60m, max_move_60m, volatile_share,
                   median_move_30m, median_atr_30m, hourly_baseline_30m, baseline_ratio_30m,
                   period_from, period_to, avg_move_4h, max_move_4h,
                   n_beat, beat_up_share, beat_down_share, n_miss, miss_up_share, miss_down_share,
                   computed_ts)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (etype, symbol, len(subset), avg_30, avg_60, max_60, volatile_share,
                  median_30, median_atr_30m, hourly_baseline_30m, baseline_ratio_30m,
                  period_from, period_to, avg_4h, max_4h,
                  n_beat, beat_up_share, beat_down_share, n_miss, miss_up_share, miss_down_share,
                  now_ts))
            stats_written += 1
            if verbose:
                ratio_s = f"{baseline_ratio_30m:.2f}×" if baseline_ratio_30m is not None else "—"
                print(f"  {etype}×{symbol} n={len(subset)} [{period_from}→{period_to}]: avg60={avg_60:.2f} "
                      f"max60={max_60:.2f} vol_share={volatile_share} baseline_ratio_30m={ratio_s}")

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
