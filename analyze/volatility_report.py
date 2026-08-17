#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/volatility_report.py — WP6.0 SPEC_alpha_engine_wp6_volatility.md.

Отчёт по гипотезе автокорреляции волатильности (положительный контроль) —
и, по тому же образцу, будущих гипотез WP6.2. Не заходит в report.py
(triple-barrier-специфичный: winrate/exp_R/PF от labels с y/r_realized) —
отдельный модуль, симметрично calibration_report.py (тоже своя статистика
поверх другого субстрата).

Две НЕПЕРЕСЕКАЮЩИЕСЯ группы (condition=1 / condition=0), не "condition vs
маргинал" -- маргинал включает в себя condition-подмножество, тест на
пересекающихся группах консервативен (смещён к меньшей значимости), но не
единственно корректный способ; непересекающиеся группы -- обычный
two-sample сравнения.

Brier/BSS -- прямой импорт чистых функций из calibration_report.py (те же
формулы, что уже применяются к forecast-journal схеме, здесь -- к
volatility_labels; проверено разведкой, что сами функции не привязаны к
схеме БД).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze.calibration_report import brier, brier_skill_score
from analyze.report import apply_multiple_comparisons_correction, effective_n, two_proportion_p_value
from analyze.report import cross_instrument_correlation
from tools.edu_build.pattern_reality import wilson

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

# Вердикт-пороги (WP6.0 §0 спеки: "сильный эффект, узкий CI, переживает FDR") --
# [ДОПУЩЕНИЕ], не заимствовано ниоткуда: разница пропорций достаточно велика
# И статистически значима после поправки, чтобы не спутать с шумом.
VERDICT_MIN_DIFF_PP = 10.0
VERDICT_ALPHA = 0.05


def _load_labels(con: sqlite3.Connection, symbol: str, tf: str, event_key: str) -> list[dict]:
    rows = con.execute(
        "SELECT ts, condition, y, censored FROM volatility_labels WHERE symbol=? AND tf=? AND event_key=?",
        (symbol, tf, event_key),
    ).fetchall()
    return [{"ts": r[0], "condition": r[1], "y": r[2], "censored": r[3]} for r in rows]


def _symbols_with_labels(con: sqlite3.Connection, tf: str, event_key: str) -> list[str]:
    rows = con.execute(
        "SELECT DISTINCT symbol FROM volatility_labels WHERE tf=? AND event_key=? ORDER BY symbol",
        (tf, event_key),
    ).fetchall()
    return [r[0] for r in rows]


def volatility_control_report(con: sqlite3.Connection, symbols: list[str], tf: str,
                               event_key: str = "vol_autocorr_control") -> dict:
    """Одна клетка = (event_key, tf), symbols объединены в пул (тот же принцип,
    что report.py::pattern_report -- почему пул, см. её докстринг)."""
    all_rows = []
    per_instrument_n: dict[str, int] = {}
    for sym in symbols:
        rows = [r for r in _load_labels(con, sym, tf, event_key) if not r["censored"]]
        if rows:
            per_instrument_n[sym] = len(rows)
            all_rows.extend(rows)

    n1 = sum(1 for r in all_rows if r["condition"] == 1)
    x1 = sum(1 for r in all_rows if r["condition"] == 1 and r["y"] == 1)
    n2 = sum(1 for r in all_rows if r["condition"] == 0)
    x2 = sum(1 for r in all_rows if r["condition"] == 0 and r["y"] == 1)
    n_total = n1 + n2

    p1 = round(x1 / n1, 4) if n1 else None
    p2 = round(x2 / n2, 4) if n2 else None
    ci1 = wilson(x1, n1) if n1 else [None, None]
    ci2 = wilson(x2, n2) if n2 else [None, None]
    p_value = two_proportion_p_value(x1, n1, x2, n2) if n1 and n2 else None

    avg_corr = cross_instrument_correlation(con, list(per_instrument_n.keys()), tf="1d")
    n_eff = effective_n(per_instrument_n, avg_corr)

    outcomes1 = [r["y"] for r in all_rows if r["condition"] == 1]
    climatology_p = round(x2 / n2, 6) if n2 else None  # безусловная (complement) база -- climatology
    brier1 = brier([p1] * len(outcomes1), outcomes1) if p1 is not None and outcomes1 else None
    bss1 = (brier_skill_score([p1] * len(outcomes1), outcomes1, climatology_p)
            if p1 is not None and climatology_p is not None and outcomes1 else None)

    diff_pp = round((p1 - p2) * 100, 2) if p1 is not None and p2 is not None else None
    # per-cell "candidate" правило, симметрично report.py::pattern_report --
    # FDR-поправка (apply_multiple_comparisons_correction) применяется ПОСЛЕ,
    # вызывающим кодом, не здесь (тот же контракт, что уже принят в проекте).
    status = ("experimental" if p_value is None or diff_pp is None or
              diff_pp < VERDICT_MIN_DIFF_PP or ci1[0] is None or ci2[1] is None or ci1[0] <= ci2[1]
              else "candidate")

    return {
        "event_key": event_key, "tf": tf, "n": n_total, "n_effective": n_eff,
        "avg_cross_instrument_corr": avg_corr,
        "n_condition": n1, "p_condition": p1, "ci95_condition": ci1,
        "n_complement": n2, "p_complement": p2, "ci95_complement": ci2,
        "diff_pp": diff_pp, "p_value": p_value,
        "brier_condition": brier1, "bss_condition": bss1, "climatology_p": climatology_p,
        "status": status,
        # Намеренно БЕЗ "_r_values_for_pvalue" -- нет непрерывного r_realized
        # вообще (событие бинарное), p_value уже посчитан выше через
        # two_proportion_p_value. apply_multiple_comparisons_correction()
        # (report.py, правка 14.08) не трогает p_value при отсутствии ключа.
    }


def _render_md(reports: list[dict], summary: dict) -> str:
    lines = [
        "# WP6.0 -- положительный контроль (автокорреляция волатильности)", "",
        f"**m={summary['m']}, alpha={summary['alpha']}, "
        f"candidate до поправки={summary['n_candidate_before']}, "
        f"после={summary['n_candidate_after']}**", "",
        "| tf | n | n_eff | p(condition) | CI95 | p(complement) | CI95 | diff_pp | p_value | q/holm | Brier | BSS | status |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        q = r.get("q_value", r.get("holm_adjusted_alpha", "—"))
        lines.append(
            f"| {r['tf']} | {r['n']} | {r['n_effective']} | {r['p_condition']} | {r['ci95_condition']} | "
            f"{r['p_complement']} | {r['ci95_complement']} | {r['diff_pp']} | {r['p_value']} | {q} | "
            f"{r['brier_condition']} | {r['bss_condition']} | {r['status']} |"
        )
    n_pass = sum(1 for r in reports if r["status"] == "candidate")
    verdict = ("ПРОХОДИТ" if n_pass >= max(1, len(reports) - 1) else
               "НЕ ПРОХОДИТ" if n_pass == 0 else "ЧАСТИЧНО (проверить по tf отдельно)")
    lines += ["", f"**Вердикт: {verdict}** ({n_pass}/{len(reports)} tf прошли как candidate после FDR)"]
    return "\n".join(lines)


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--tfs", nargs="+", default=["D1", "H4", "H1"])
    ap.add_argument("--event-key", default="vol_autocorr_control")
    ap.add_argument("--method", choices=["fdr_bh", "holm"], default="fdr_bh")
    args = ap.parse_args()

    con = sqlite3.connect(str(_BOT_DB), timeout=10)
    reports = []
    for tf in args.tfs:
        symbols = _symbols_with_labels(con, tf, args.event_key)
        if not symbols:
            continue
        r = volatility_control_report(con, symbols, tf, args.event_key)
        if r["n"] > 0:
            reports.append(r)
    con.close()

    summary = apply_multiple_comparisons_correction(reports, method=args.method)
    print(_render_md(reports, summary))


if __name__ == "__main__":
    main()
