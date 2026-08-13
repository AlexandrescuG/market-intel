#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/report.py — WP2.4 SPEC_alpha_engine_implementation.md.

Отчётность по гипотезе/фактору: n, эффективный n (поправка на корреляцию
инструментов), винрейт+CI95, ожидание в R после издержек (+CI95 на само
ожидание — нужен для правила отсечения ниже), profit factor, максимальная
просадка, разбивка по инструменту (диагностика вместо кривой калибровки —
см. обоснование в докстринге `pattern_report`).

Правило отсечения (спека, WP2.4): если нижняя граница CI95 ожидания <= 0 —
`status='experimental'`, в прод-прогнозы не идёт. Записывается в
factor_registry.status при регистрации (WP1.3).

🔴 Ревью §2 (12.08, REVIEW_alpha_engine_WP0-WP3.md): это per-cell правило
само по себе не учитывает, СКОЛЬКО клеток (паттерн×ТФ×конфиг) проверяется
за один прогон — при типичной сетке WP2.5 (24+ клетки) это гарантированно
даёт случайные "candidate" даже если весь эффект — шум. Вызывающий код
ОБЯЗАН прогнать весь батч через `apply_multiple_comparisons_correction`
ПЕРЕД тем, как доверять status='candidate' — она понижает часть кандидатов
до 'experimental' с учётом числа m проверенных клеток (BH-FDR по
умолчанию, Holm — по запросу). Одноклеточный вызов `pattern_report` без
этого шага годится для разведки/дебага, не для решения "в прод".
"""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze.backtest import _decided, load_labels, resolution_window
from tools.edu_build.pattern_reality import wilson
from core.patterns import detect as detect_patterns
import core.price_bars as _price_bars

_TF_TO_PB = {"H1": "1h", "H4": "4h", "D1": "1d"}

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")


def _norm_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def expectancy_p_value(r_values: list[float]) -> float | None:
    """Одностороннее p-value для H0: E[r_realized] <= 0 (нормальное
    приближение, та же механика, что и expectancy_ci95, но как p, не CI —
    нужно для поправки на множественные сравнения, см.
    `apply_multiple_comparisons_correction`). При n<2 не определено."""
    n = len(r_values)
    if n < 2:
        return None
    mean = sum(r_values) / n
    var = sum((x - mean) ** 2 for x in r_values) / (n - 1)
    if var <= 0:
        return 0.0 if mean > 0 else 1.0
    se = math.sqrt(var / n)
    return round(1 - _norm_cdf(mean / se), 6)


def apply_multiple_comparisons_correction(reports: list[dict], alpha: float = 0.05,
                                           method: str = "fdr_bh") -> dict:
    """🔴 Ревью §2 (12.08): без поправки на число проверенных клеток
    (`pattern_report` per-cell правило "CI95 ожидания > 0 -> candidate")
    при типичной сетке WP2.5 (8 паттернов × 3 ТФ = 24 клетки) и alpha=0.05
    следует ожидать ~1 случайный "candidate" даже если ВСЕ гипотезы на
    самом деле нулевые -- множественные сравнения задирают долю ложных
    "открытий" пропорционально m (числу клеток), не пропорционально
    одной alpha.

    Мутирует reports IN PLACE — добавляет `p_value` (см. `expectancy_p_value`)
    и `q_value` (BH) или `holm_adjusted_alpha`, и ПОНИЖАЕТ status с
    'candidate' до 'experimental' у клеток, не выживших после поправки
    (per-cell CI95-правило остаётся первым фильтром -- 'candidate' может
    стать только 'experimental', никогда не наоборот: поправка ужимает
    множество находок, не расширяет его).

    method: 'fdr_bh' (Бенджамини-Хохберг, контроль ДОЛИ ложных открытий —
    мягче, больше power) или 'holm' (контроль ВЕРОЯТНОСТИ хотя бы одной
    ложной находки — строже, меньше power). BH — разумный дефолт для
    разведочного скрининга факторов (это WP2.5 и есть), Holm — если нужна
    более консервативная гарантия перед тем, как что-то пойдёт в прод.

    Возвращает summary: {m, method, alpha, n_candidate_before, n_candidate_after}."""
    for r in reports:
        r_values = r.get("_r_values_for_pvalue")
        r["p_value"] = expectancy_p_value(r_values) if r_values else None

    testable = [r for r in reports if r["p_value"] is not None]
    m = len(testable)
    n_before = sum(1 for r in testable if r["status"] == "candidate")
    summary = {"m": m, "method": method, "alpha": alpha,
               "n_candidate_before": n_before, "n_candidate_after": n_before}
    if m == 0:
        return summary

    ranked = sorted(testable, key=lambda r: r["p_value"])
    if method == "holm":
        survived = []
        for k, r in enumerate(ranked, start=1):
            adj_alpha = alpha / (m - k + 1)
            r["holm_adjusted_alpha"] = round(adj_alpha, 6)
            if r["p_value"] <= adj_alpha:
                survived.append(r)
            else:
                break  # Holm — шаговая процедура, p дальше только растут по построению
        survived_ids = {id(r) for r in survived}
    else:  # fdr_bh
        max_k = 0
        for k, r in enumerate(ranked, start=1):
            if r["p_value"] <= (k / m) * alpha:
                max_k = k
        for rank, r in enumerate(ranked, start=1):
            r["q_value"] = round(min(1.0, r["p_value"] * m / rank), 6)
        survived_ids = {id(r) for r in ranked[:max_k]}

    for r in testable:
        if r["status"] == "candidate" and id(r) not in survived_ids:
            r["status"] = "experimental"
        r.pop("_r_values_for_pvalue", None)

    summary["n_candidate_after"] = sum(1 for r in testable if r["status"] == "candidate")
    return summary


def expectancy_ci95(r_values: list[float]) -> tuple[float | None, float | None]:
    """CI95 на СРЕДНЕЕ r_realized — нормальное приближение (mean ± 1.96*SE),
    не Wilson (тот для доли/винрейта, не для непрерывной величины). При n<2
    СКО не определено -- [None, None], честно, не 0."""
    n = len(r_values)
    if n < 2:
        return None, None
    mean = sum(r_values) / n
    var = sum((x - mean) ** 2 for x in r_values) / (n - 1)
    se = math.sqrt(var / n)
    return round(mean - 1.96 * se, 4), round(mean + 1.96 * se, 4)


def max_drawdown_r(r_values_in_order: list[float]) -> float:
    """Максимальная просадка накопленной суммы R (в порядке ts — порядок
    важен, это не статичная выборка, а путь). Возвращает положительное
    число (величина просадки, не отрицательное)."""
    if not r_values_in_order:
        return 0.0
    equity, peak, max_dd = 0.0, 0.0, 0.0
    for r in r_values_in_order:
        equity += r
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return round(max_dd, 4)


def effective_n(per_instrument_n: dict[str, int], avg_cross_instrument_corr: float) -> float:
    """Design-effect поправка на корреляцию между инструментами (кластерная
    поправка, аналог clustered standard errors): пул из K инструментов с
    парной корреляцией rho даёт эффективный n = n_total / (1 + (K-1)*rho),
    а НЕ n_total — иначе n искусственно завышен, если инструменты двигаются
    вместе (EURUSD и GBPUSD коррелируют, это не K независимых наблюдений).
    rho усредняется по ПАРАМ инструментов (см. `cross_instrument_correlation`),
    берётся один средний коэффициент, не полная матрица — упрощение,
    задокументировано, не выдаётся за точный расчёт."""
    n_total = sum(per_instrument_n.values())
    k = len(per_instrument_n)
    if k <= 1 or n_total == 0:
        return float(n_total)
    design_effect = 1 + (k - 1) * max(0.0, avg_cross_instrument_corr)
    return round(n_total / design_effect, 1)


def cross_instrument_correlation(con: sqlite3.Connection, symbols: list[str], tf: str = "1d") -> float:
    """Средняя парная корреляция дневных доходностей close-to-close по
    ОБЩЕЙ пересекающейся истории. Возвращает 0.0, если данных недостаточно
    (симметрично duty "честно, не выдумывать" — лучше недооценить
    корреляцию нулём, чем взять произвольное число)."""
    if len(symbols) < 2:
        return 0.0
    series = {}
    for sym in symbols:
        rows = con.execute(
            "SELECT ts, c FROM price_bars WHERE symbol=? AND tf=? ORDER BY ts ASC", (sym, tf)
        ).fetchall()
        if len(rows) < 30:
            continue
        closes = {ts: c for ts, c in rows}
        series[sym] = closes
    pairs = [(a, b) for i, a in enumerate(symbols) for b in symbols[i + 1:]
             if a in series and b in series]
    if not pairs:
        return 0.0
    corrs = []
    for a, b in pairs:
        common_ts = sorted(set(series[a]) & set(series[b]))
        if len(common_ts) < 30:
            continue
        ra = [(series[a][common_ts[i]] / series[a][common_ts[i - 1]] - 1) for i in range(1, len(common_ts))]
        rb = [(series[b][common_ts[i]] / series[b][common_ts[i - 1]] - 1) for i in range(1, len(common_ts))]
        n = len(ra)
        ma, mb = sum(ra) / n, sum(rb) / n
        cov = sum((ra[i] - ma) * (rb[i] - mb) for i in range(n)) / n
        sa = math.sqrt(sum((x - ma) ** 2 for x in ra) / n)
        sb = math.sqrt(sum((x - mb) ** 2 for x in rb) / n)
        if sa > 0 and sb > 0:
            corrs.append(cov / (sa * sb))
    return round(sum(corrs) / len(corrs), 4) if corrs else 0.0


def _load_levels(con: sqlite3.Connection, canonical_symbol: str) -> list[dict]:
    """Симметрично labeler.py._load_levels / pattern_stats_job.py._load_levels."""
    try:
        rows = con.execute(
            "SELECT price, tolerance, kind FROM sr_levels WHERE symbol=? AND broken=0", (canonical_symbol,)
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [{"price": r[0], "tolerance": r[1], "kind": r[2]} for r in rows]


def _pattern_occurrence_keys(con: sqlite3.Connection, canonical_symbol: str, tf: str, pattern_key: str) -> set[tuple[int, str]]:
    """{(ts,direction)} срабатываний ОДНОГО pattern_key на символе/ТФ —
    живой вызов core.patterns.detect() (тот же источник, что и в labeler.py
    и pattern_stats_job.py — единый детектор, не третья копия правил).
    levels обязателен -- без него break_retest молча даёт 0 срабатываний
    (см. Core-лог 11.08, тот же баг, что был в labeler.py)."""
    candles = _price_bars.load_candles(canonical_symbol, _TF_TO_PB[tf])
    if not candles:
        return set()
    levels = _load_levels(con, canonical_symbol)
    return {(e["ts"], e["direction"]) for e in detect_patterns(candles, levels) if e["pattern_key"] == pattern_key}


def pattern_report(con: sqlite3.Connection, symbols: list[str], tf: str, config_key: str,
                    pattern_key: str | None = None) -> dict:
    """Отчёт по одной гипотезе (набору символов на одном ТФ/конфиге),
    сшитый по всем нужным метрикам. "Кривая калибровки" спеки заменена на
    разбивку по инструменту -- у детерминированного детектора паттерна нет
    предсказанной вероятности на срабатывание (это не модель, выдающая p),
    поэтому классическая калибровочная кривая (predicted vs realized bucket)
    здесь вырождена в одну точку; разбивка по инструменту -- содержательный
    эквивалент: показывает, расходятся ли отдельные инструменты с пулом,
    что и есть практический смысл калибровки на этом уровне.

    pattern_key: labels НЕ хранит его (исход барьера не зависит от того,
    какой детектор предложил направление — см. Core-лог 11.08), поэтому
    фильтрация по паттерну — это join с живым detect() по (ts,direction),
    не столбец в WHERE."""
    per_symbol_rows = {}
    all_rows = []
    for sym in symbols:
        rows = load_labels(con, symbol=sym, tf=tf, config_key=config_key)
        if pattern_key is not None:
            occ_keys = _pattern_occurrence_keys(con, sym, tf, pattern_key)
            rows = [r for r in rows if (r["ts"], r["direction"]) in occ_keys]
        if rows:
            per_symbol_rows[sym] = rows
            all_rows.extend(rows)

    decided_all = _decided(all_rows)
    decided_all_sorted = sorted(decided_all, key=lambda r: r["ts"])
    r_values = [r["r_realized"] for r in decided_all_sorted if r["r_realized"] is not None]

    n = len(decided_all)
    wins = sum(1 for r in decided_all if r["y"] == 1)
    winrate = round(wins / n, 4) if n else None
    ci95_winrate = wilson(wins, n) if n else [None, None]
    expectancy = round(sum(r_values) / len(r_values), 4) if r_values else None
    exp_ci_lo, exp_ci_hi = expectancy_ci95(r_values) if r_values else (None, None)
    gains = sum(r for r in r_values if r > 0)
    losses = -sum(r for r in r_values if r < 0)
    profit_factor = round(gains / losses, 4) if losses > 0 else (float("inf") if gains > 0 else None)

    per_instrument_n = {sym: len(_decided(rows)) for sym, rows in per_symbol_rows.items()}
    avg_corr = cross_instrument_correlation(con, list(per_instrument_n.keys()), tf="1d")
    n_eff = effective_n(per_instrument_n, avg_corr)

    per_instrument_breakdown = {}
    for sym, rows in per_symbol_rows.items():
        d = _decided(rows)
        w = sum(1 for r in d if r["y"] == 1)
        per_instrument_breakdown[sym] = {
            "n": len(d), "winrate": round(w / len(d), 4) if d else None,
        }

    # Правило отсечения WP2.4: нижняя граница CI95 ожидания <= 0 -> experimental
    status = "experimental" if (exp_ci_lo is None or exp_ci_lo <= 0) else "candidate"

    return {
        "pattern_key": pattern_key, "symbols": symbols, "tf": tf, "config_key": config_key,
        "n": n, "n_effective": n_eff, "avg_cross_instrument_corr": avg_corr,
        "winrate": winrate, "winrate_ci95_pct": ci95_winrate,
        "expectancy_r": expectancy, "expectancy_ci95_r": [exp_ci_lo, exp_ci_hi],
        "profit_factor": profit_factor,
        "max_drawdown_r": max_drawdown_r([r["r_realized"] for r in decided_all_sorted if r["r_realized"] is not None]),
        "per_instrument": per_instrument_breakdown,
        "status": status,
        "_r_values_for_pvalue": r_values,  # для apply_multiple_comparisons_correction; убирается там же
    }
