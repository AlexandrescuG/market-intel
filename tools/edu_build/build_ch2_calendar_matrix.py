#!/usr/bin/env python3
"""
Матрица влияния (NFP/CPI/FOMC/GDP × GOLD/DXY/SPX/BTC) — глава 2 «Крупнейшие
организации», §3.5 спеки (SPEC_edu_level2_central_banks.md), пункт, отложенный
при закрытии главы 27.07.2026 ("Матрица влияния... сознательно НЕ сделана").

Вход:  bot.db (econ_events, event_reaction_stats — уже считает Layer1 Фаза 2,
       tools/../event_reactions_job.py, крон раз в сутки) + web/data/ohlc_*_M30.json
Выход: web/data/edu_stats/calendar_matrix.json

──────────────────────────────────────────────────────────────────────────────
ПОЧЕМУ ДВА ИСТОЧНИКА ДАННЫХ, А НЕ ОДИН
──────────────────────────────────────────────────────────────────────────────
Спека просит "числа считает движок, не редактор" и явно указывает переиспользовать
статистику реакций Layer 1 (event_reaction_stats). Эта таблица уже полна и жива
(971 строка на 27.07.2026, крон sbf-event-reactions.timer) — но только для тех
символов, для которых в price_bars (БД chart.html/бота) вообще есть 30m-бары:
EURUSD/USDJPY/USDCNY/USDZAR/USDRUB/XAUUSD. Ни DXY, ни SPX, ни BTC там не хранятся
вообще (проверено: SELECT COUNT(*) FROM price_bars WHERE symbol IN
('DXY','SPX','BTC') → 0 у всех трёх). Расширять сам event_reactions_job.py здесь
не стали: это отдельный работающий продакшен-пайплайн Layer1 с собственным
кроном — трогать его ради контента одной главы курса неоправданно рискованно.

Поэтому: колонка GOLD берётся ГОТОВОЙ из event_reaction_stats (там реальная
история глубже — XAUUSD в price_bars с 2024-07, т.е. ~2 года, n доходит до 12).
Колонки DXY/SPX/BTC считаются заново, тем же методом (см. _case_metrics ниже,
сознательно копирует логику event_reactions_job.py, а не импортирует её — тот
модуль жёстко привязан к своей SQLite-схеме price_bars), но на данных из
web/data/ohlc_{SYM}_M30.json — том же бэкфилле MT5, что и в hourly_profile.py
(глава 5). Этот бэкфилл короче (~2.5-3 месяца) — соответственно и n там честно
маленький (1-5 в большинстве ячеек), что и попадает в small_sample-флаг.

Ни одна ячейка не публикуется без n. Ячейка с n=0 — это "—" на фронте, а не
пропуск строки: пользователь должен видеть, что для BTC на GDP реакций пока
просто нет в нашей истории, а не решить, что мы забыли клетку.

──────────────────────────────────────────────────────────────────────────────
НОРМИРОВКА НА ATR (SPEC_ch2_debug_and_chart_engine.md §2.2)
──────────────────────────────────────────────────────────────────────────────
Абсолютные пункты (57.8 у GOLD, 0.3 у DXY, 994.8 у BTC) несопоставимы между
колонками — читатель делает вывод "BTC двигается в 17 раз сильнее", хотя это
просто другая единица измерения. Чиним тем же приёмом, что уже применён в
главе 6 (surprise_reaction.py, median_daily_range): делим средний ход цены на
медианный ДНЕВНОЙ диапазон (H-L) инструмента за последний год, а не на весь
исторический период, — иначе для GOLD (цена выросла втрое с 2018-го) знаменатель
занижается в разы и норма улетает за пределы разумного (тот же баг, что уже
пойман в surprise_reaction.py и hourly_profile.py). Для DXY/SPX/BTC своих
дневных баров в price_bars нет вообще (см. выше) — денормалайзер считается
прямо из того же M30-бэкфилла, что и сами ячейки: группировка по UTC-дню,
H-L дня, медиана по всем доступным дням (~2.5-3 месяца, короче года, но это
честный порог для короткого бэкфилла, не искусственное сокращение).

Запуск: python3 tools/edu_build/build_ch2_calendar_matrix.py
"""
import datetime
import json
import pathlib
import sqlite3
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
OUT = WEB / "data" / "edu_stats" / "calendar_matrix.json"
BOT_DB = pathlib.Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
RECENT_DAYS_FOR_RANGE = 250  # ~год торговых дней, как в surprise_reaction.py

sys.path.insert(0, str(ROOT))
from core.event_types import normalize_event_type  # noqa: E402

EVENT_TYPES = ["nfp", "cpi", "rate", "gdp"]
EVENT_LABELS = {"nfp": "NFP", "cpi": "CPI", "rate": "FOMC", "gdp": "GDP"}
# rate = normalize_event_type() ковш для "interest rate"/"rate decision" —
# в econ_events это FOMC Rate Decision / Fed Interest Rate Decision и т.п.,
# поэтому в матрице подписан как FOMC (спека называет ось так).

FRESH_SYMBOLS = ["DXY", "SPX", "BTC"]  # считаем заново из MT5 M30
GOLD_SYMBOL = "GOLD"                     # берём готовым из event_reaction_stats

MIN_CASES = 4  # тот же порог, что в event_reactions_job.py — единообразие «мало данных»
WINDOW_30M = 1800
WINDOW_60M = 3600

_SOURCE_PRIORITY = {"curated_official": 0, "forexfactory": 1, "tradingview": 2}


# ─────────────────────────────────────────────────────────── MT5 M30 loader

def load_candles(symbol):
    p = WEB / "data" / f"ohlc_{symbol}_M30.json"
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    candles = raw["candles"] if isinstance(raw, dict) else raw
    out = []
    for c in candles:
        out.append({"ts": c["time"], "o": c["open"], "h": c["high"], "l": c["low"], "c": c["close"]})
    out.sort(key=lambda b: b["ts"])
    return out


def median_daily_range_gold(con):
    """Медианный дневной H-L по XAUUSD за последний год price_bars -- тот же
    метод и то же окно, что surprise_reaction.py::median_daily_range (глава 6),
    здесь не импортируется намеренно (тот модуль не экспортирует функцию как
    публичный API, дублирование дешевле, чем завязка на внутренности чужого
    скрипта)."""
    rows = con.execute(
        "SELECT h,l FROM price_bars WHERE symbol='XAUUSD' AND tf='1d' ORDER BY ts DESC LIMIT ?",
        (RECENT_DAYS_FOR_RANGE,),
    ).fetchall()
    rngs = [r["h"] - r["l"] for r in rows if r["h"] is not None and r["l"] is not None]
    return statistics.median(rngs) if rngs else None


def median_daily_range_from_m30(candles):
    """То же самое, но для DXY/SPX/BTC — у них нет дневных баров в price_bars,
    только M30-бэкфилл (web/data/ohlc_*_M30.json). Группируем по UTC-дню,
    берём H-L дня, медиана по всем доступным дням бэкфилла."""
    if not candles:
        return None
    by_day = {}
    for c in candles:
        day = c["ts"] // 86400
        d = by_day.setdefault(day, {"h": c["h"], "l": c["l"]})
        d["h"] = max(d["h"], c["h"])
        d["l"] = min(d["l"], c["l"])
    rngs = [d["h"] - d["l"] for d in by_day.values()]
    return statistics.median(rngs) if rngs else None


def nearest_bar(by_ts, target_ts, tolerance=900):
    if target_ts in by_ts:
        return by_ts[target_ts]
    best, best_d = None, None
    for ts, b in by_ts.items():
        d = abs(ts - target_ts)
        if d <= tolerance and (best is None or d < best_d):
            best, best_d = b, d
    return best


def case_metrics(by_ts, release_ts):
    bar0 = nearest_bar(by_ts, release_ts)
    if bar0 is None:
        return None
    bar1 = nearest_bar(by_ts, release_ts + WINDOW_60M)
    move_30m = abs(bar0["c"] - bar0["o"])
    if bar1 is not None:
        move_60m = abs(bar1["c"] - bar0["o"])
    else:
        move_60m = None
    return {"move_30m": move_30m, "move_60m": move_60m}


# ─────────────────────────────────────────────────────────────── econ_events

def fetch_us_events(con):
    rows = con.execute("""
        SELECT event_key, title, indicator, actual, scheduled_ts, source
        FROM econ_events
        WHERE country='US' AND actual IS NOT NULL AND actual != '' AND scheduled_ts IS NOT NULL
        ORDER BY scheduled_ts ASC
    """).fetchall()
    return rows


def dedup_by_day(rows):
    groups = {}
    for r in rows:
        etype = normalize_event_type(r["indicator"] or r["title"])
        if etype not in EVENT_TYPES:
            continue
        day = r["scheduled_ts"] // 86400
        key = (etype, day)
        cur = groups.get(key)
        if cur is None or _SOURCE_PRIORITY.get(r["source"], 9) < _SOURCE_PRIORITY.get(cur["source"], 9):
            groups[key] = r
    return list(groups.values())


def compute_fresh_cell(events_by_type, etype, candles):
    if not candles:
        return {"n": 0, "avg_move_30m": None, "avg_move_60m": None, "max_move_60m": None,
                "source": "mt5_backfill", "coverage_first": None, "coverage_last": None}
    by_ts = {b["ts"]: b for b in candles}
    t0, t1 = candles[0]["ts"], candles[-1]["ts"]
    rows = [r for r in events_by_type.get(etype, []) if t0 <= r["scheduled_ts"] <= t1]
    moves_30, moves_60 = [], []
    for r in rows:
        m = case_metrics(by_ts, r["scheduled_ts"])
        if m is None:
            continue
        if m["move_30m"] is not None:
            moves_30.append(m["move_30m"])
        if m["move_60m"] is not None:
            moves_60.append(m["move_60m"])
    n = len(moves_60)
    return {
        "n": n,
        "avg_move_30m": round(sum(moves_30) / len(moves_30), 3) if moves_30 else None,
        "avg_move_60m": round(sum(moves_60) / len(moves_60), 3) if moves_60 else None,
        "max_move_60m": round(max(moves_60), 3) if moves_60 else None,
        "source": "mt5_backfill",
        "coverage_first": datetime.datetime.utcfromtimestamp(t0).strftime("%Y-%m-%d"),
        "coverage_last": datetime.datetime.utcfromtimestamp(t1).strftime("%Y-%m-%d"),
    }


def fetch_gold_cells(con):
    rows = con.execute("""
        SELECT event_type, n, avg_move_30m, avg_move_60m, max_move_60m
        FROM event_reaction_stats WHERE symbol='GOLD' AND event_type IN ({})
        ORDER BY event_type, n DESC
    """.format(",".join("?" * len(EVENT_TYPES))), EVENT_TYPES).fetchall()
    best = {}
    for r in rows:
        et = r["event_type"]
        if et not in best or r["n"] > best[et]["n"]:  # берём максимальный n-tier (6 или 12)
            best[et] = {
                "n": r["n"],
                "avg_move_30m": round(r["avg_move_30m"], 3) if r["avg_move_30m"] is not None else None,
                "avg_move_60m": round(r["avg_move_60m"], 3) if r["avg_move_60m"] is not None else None,
                "max_move_60m": round(r["max_move_60m"], 3) if r["max_move_60m"] is not None else None,
                "source": "live_engine_xauusd",
            }
    return best


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(str(BOT_DB))
    con.row_factory = sqlite3.Row

    gold_cells = fetch_gold_cells(con)
    gold_range = median_daily_range_gold(con)

    us_rows = fetch_us_events(con)
    deduped = dedup_by_day(us_rows)
    events_by_type = {}
    for r in deduped:
        et = normalize_event_type(r["indicator"] or r["title"])
        events_by_type.setdefault(et, []).append(r)
    con.close()

    fresh_candles = {sym: load_candles(sym) for sym in FRESH_SYMBOLS}
    daily_range = {"GOLD": gold_range}
    daily_range.update({sym: median_daily_range_from_m30(fresh_candles[sym]) for sym in FRESH_SYMBOLS})
    print("медианный дневной диапазон: " + " · ".join(f"{s}={daily_range[s]:.3f}" if daily_range[s] else f"{s}=—" for s in ["GOLD"] + FRESH_SYMBOLS))

    rows_out = []
    for et in EVENT_TYPES:
        cells = {}
        gc = gold_cells.get(et)
        cells["GOLD"] = gc if gc else {"n": 0, "avg_move_30m": None, "avg_move_60m": None,
                                        "max_move_60m": None, "source": "live_engine_xauusd"}
        for sym in FRESH_SYMBOLS:
            cells[sym] = compute_fresh_cell(events_by_type, et, fresh_candles[sym])
        for sym, cell in cells.items():
            rr = daily_range.get(sym)
            cell["norm"] = round(cell["avg_move_60m"] / rr, 4) if (cell.get("avg_move_60m") is not None and rr) else None
        rows_out.append({"event_type": et, "label": EVENT_LABELS[et], "cells": cells})
        cell_summary = " · ".join(f"{s}:n={cells[s]['n']}" for s in ["GOLD"] + FRESH_SYMBOLS)
        print(f"  {EVENT_LABELS[et]:5s} {cell_summary}")

    payload = {
        "rows": rows_out,
        "meta": {
            "built": datetime.date.today().isoformat(),
            "min_cases": MIN_CASES,
            "metric": "средний абсолютный ход цены (|close-open| бара M30) за 30 и 60 минут после публикации, в единицах цены инструмента",
            "norm_metric": "avg_move_60m, делённый на медианный дневной диапазон (H-L) инструмента за последний год/бэкфилл — сопоставимая между колонками величина, как в главе 6 (surprise_reaction.py)",
            "daily_range": {s: (round(daily_range[s], 3) if daily_range[s] else None) for s in ["GOLD"] + FRESH_SYMBOLS},
            "gold_note": "колонка GOLD — из живого движка Layer1 (event_reaction_stats, XAUUSD, история price_bars с 2024-07), пересчитывается кроном раз в сутки",
            "fresh_note": "колонки DXY/SPX/BTC посчитаны этим скриптом по бэкфиллу web/data/ohlc_*_M30.json — короче, поэтому n там честно маленький",
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
