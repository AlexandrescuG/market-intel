#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/base_rate.py — WP4.2 SPEC_alpha_engine_implementation.md.

Поиск базовой ставки с иерархическим откатом: полное условие → при n<30
отбрасывается самое слабое условие → повтор. Возврат обязан содержать
уровень отката и n; при недостатке данных на самом грубом уровне —
`insufficient=True`, НЕ «≈50%».

BACKOFF_ORDER — порядок реально фильтруемых полей вектора состояния,
от «дропается первым» до «дропается последним». `pattern_key`/`direction`
НЕ входят сюда как шаги цикла — это не поля вектора состояния для фильтра,
а сам вопрос (уже зафиксирован через `occ_keys` до сбора строк). Дойти до
необходимости отбросить их означало бы подменить вопрос более широким под
видом того же самого — спека прямо запрещает это («корректный ответ
«недостаточно данных», а не подстановка»). Поэтому исчерпание
BACKOFF_ORDER даёт терминальный `insufficient`, а не «дроп pattern_key».

`level_dist_atr_bucket` не участвует вообще — `state_vector.py` его
физически не считает в историческом режиме (нет point-in-time истории
уровней, см. докстринг этого модуля).

Порядок (обоснование — REVIEW-ответ 12.08, зафиксировано, не абстрактная
"важность"):
  1. calendar_prox_bucket — сильно skewed к "далеко", эффект pattern-зависим.
  2. session — избыточен относительно vol_bucket (тот же сигнал числом).
  3. trend_regime — грубая, редко меняющаяся метка (кусочно-постоянна).
  4. vol_bucket — реален, но барьеры УЖЕ в единицах ATR (эффект 2-го порядка).
  5. ema20_side — бинарный, дёшево держать до последнего из фильтруемых.
  6. symbol_or_class — расширяет выборку на весь класс ликвидности инструмента
     (core.costs.INSTRUMENT_CLASS) — крайняя мера перед "недостаточно данных".
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze.backtest import _decided, load_labels
from analyze.report import _pattern_occurrence_keys
from analyze.state_vector import build_indicator_cache, build_state_vector_historical, load_high_impact_events
from core.costs import INSTRUMENT_CLASS, _DEFAULT_CLASS
from tools.edu_build.pattern_reality import wilson
import core.price_bars as _price_bars

_TF_TO_PB = {"H1": "1h", "H4": "4h", "D1": "1d"}
MIN_N = 30

BACKOFF_ORDER = [
    "calendar_prox_bucket",
    "session",
    "trend_regime",
    "vol_bucket",
    "ema20_side",
    "symbol_or_class",
]


def _symbols_in_class(canonical_symbol: str) -> list[str]:
    cls = INSTRUMENT_CLASS.get(canonical_symbol, _DEFAULT_CLASS)
    members = [s for s, c in INSTRUMENT_CLASS.items() if c == cls]
    return members or [canonical_symbol]


def _collect_rows(con: sqlite3.Connection, pattern_key: str, direction: str,
                   symbols: list[str], tf: str, config_key: str) -> list[tuple[dict, dict, str]]:
    """[(labels_row, historical_state_vector, symbol)] — censored исключены
    (_decided), только occurrence этого pattern_key+direction (join по
    (ts,direction), как report.py._pattern_occurrence_keys).

    🔴 REVIEW_wp4_cycle_2026-08-13.md §5: events загружается ОДИН раз для
    ВСЕХ symbols/строк (не на каждую строку) -- раньше build_state_vector_
    historical сама дёргала SQL на econ_events per-row (N+1, живой замер:
    15.8с на один lookup_base_rate() на H1 -- при H1/H4 это на порядки
    хуже, чем на D1). Экономика для H1/H4/более широкого universe была
    непроверенной именно из-за этого."""
    events = load_high_impact_events(con)
    out = []
    for sym in symbols:
        candles = _price_bars.load_candles(sym, _TF_TO_PB[tf])
        if not candles:
            continue
        ts_to_idx = {c["ts"]: i for i, c in enumerate(candles)}
        cache = build_indicator_cache(candles)
        occ_keys = _pattern_occurrence_keys(con, sym, tf, pattern_key)
        rows = load_labels(con, symbol=sym, tf=tf, config_key=config_key)
        for r in _decided(rows):
            # 🔴 (r["ts"], direction) с ФИКСИРОВАННЫМ параметром давало бы
            # ложное совпадение, если на этом же баре сработал ДРУГОЙ
            # паттерн противоположного направления -- нужно направление
            # ИЗ САМОЙ СТРОКИ (симметрично report.py._pattern_occurrence_keys
            # использованию), не входной параметр.
            if r["direction"] != direction or (r["ts"], direction) not in occ_keys:
                continue
            i = ts_to_idx.get(r["ts"])
            if i is None:
                continue
            sv = build_state_vector_historical(sym, tf, i, candles, cache, events)
            out.append((r, sv, sym))
    return out


def lookup_base_rate(con: sqlite3.Connection, pattern_key: str, direction: str,
                      canonical_symbol: str, tf: str, config_key: str,
                      target_state: dict) -> dict:
    """Иерархический откат (WP4.2). target_state — historical-style вектор
    ТЕКУЩЕГО (live) сетапа (напр. из state_vector.build_state_vector_live,
    без level_dist_atr_bucket — он не сравнивается, т.к. историческая
    сторона его физически не имеет).

    Возврат: insufficient=True|{p, n, ci95, backoff_level, conditions_used, dropped}."""
    symbols_wide = _symbols_in_class(canonical_symbol)
    all_rows = _collect_rows(con, pattern_key, direction, symbols_wide, tf, config_key)

    dropped: list[str] = []
    matched: list[dict] = []
    level = 0
    while True:
        conds_active = [c for c in BACKOFF_ORDER if c != "symbol_or_class" and c not in dropped]
        narrow = "symbol_or_class" not in dropped
        matched = [
            r for (r, sv, sym) in all_rows
            if (sym == canonical_symbol or not narrow)
            and all(sv.get(c) == target_state.get(c) for c in conds_active)
        ]
        n = len(matched)
        if n >= MIN_N or level >= len(BACKOFF_ORDER):
            break
        dropped.append(BACKOFF_ORDER[level])
        level += 1

    n = len(matched)
    if n < MIN_N:
        return {"insufficient": True, "n": n, "backoff_level": level, "dropped": dropped}

    wins = sum(1 for r in matched if r["y"] == 1)
    ci_lo, ci_hi = wilson(wins, n)
    conditions_used = [c for c in BACKOFF_ORDER if c not in dropped] + ["pattern_key", "direction"]
    return {"insufficient": False, "p": round(wins / n, 4), "n": n,
            "ci95_lo": ci_lo, "ci95_hi": ci_hi, "backoff_level": level,
            "dropped": dropped, "conditions_used": conditions_used}
