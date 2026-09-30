#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/calibration_report.py — WP4.5 SPEC_alpha_engine_implementation.md.

Brier общий и по семействам; кривая надёжности; Brier Skill Score против
БЕЗУСЛОВНОЙ базовой ставки (климатологии); раздельно для базовой ставки и
базовой ставки-с-поправкой LLM (главный ответ WP4: помогает ли агент);
доля «недостаточно данных».

climatology_rate() считает винрейт ПО ФАКТУ на момент отчёта (заново из
forecast_outcomes), НЕ то число, что легло в forecast_factors в момент
создания прогноза — иначе BSS сравнивал бы прогноз с самим собой на
floor-уровне отката, что обесценивает саму метрику (проектная спека §4.E:
"против безусловной базовой ставки" — это климатология, отдельная величина).

Использование: python3 -m analyze.calibration_report [--family barrier] [--since 2026-01-01]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze.forecast_journal import init_schema

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
_RELIABILITY_EDGES = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]


def brier(probs: list[float], outcomes: list[int]) -> float | None:
    if not probs or len(probs) != len(outcomes):
        return None
    return round(sum((p - o) ** 2 for p, o in zip(probs, outcomes)) / len(probs), 4)


def brier_skill_score(probs: list[float], outcomes: list[int], climatology_p: float) -> float | None:
    b = brier(probs, outcomes)
    b_clim = brier([climatology_p] * len(outcomes), outcomes) if outcomes else None
    if b is None or not b_clim:
        return None
    return round(1 - b / b_clim, 4)


def reliability_curve(probs: list[float], outcomes: list[int],
                       edges: list[float] = _RELIABILITY_EDGES) -> list[dict]:
    buckets = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        idx = [i for i, p in enumerate(probs) if (lo <= p < hi) or (hi == edges[-1] and p == hi)]
        if not idx:
            buckets.append({"range": [lo, hi], "n": 0, "mean_p": None, "actual_rate": None})
            continue
        mean_p = sum(probs[i] for i in idx) / len(idx)
        actual = sum(outcomes[i] for i in idx) / len(idx)
        buckets.append({"range": [lo, hi], "n": len(idx), "mean_p": round(mean_p, 4),
                         "actual_rate": round(actual, 4)})
    return buckets


def climatology_rate(con: sqlite3.Connection, family: str | None = None,
                      since_ts: int | None = None) -> tuple[float | None, int]:
    """Винрейт RESOLVED (censored исключены) по фактическим исходам на
    момент отчёта — безусловный ноль-мерный baseline."""
    q = ("SELECT o.status FROM forecast_outcomes o JOIN forecasts f ON f.id = o.forecast_id "
         "WHERE o.status IN ('win','loss')")
    params: list = []
    if family:
        q += " AND f.event_key LIKE ?"
        params.append(f"{family}:%")
    if since_ts:
        q += " AND f.created_ts >= ?"
        params.append(since_ts)
    rows = con.execute(q, params).fetchall()
    n = len(rows)
    if n == 0:
        return None, 0
    wins = sum(1 for (s,) in rows if s == "win")
    return round(wins / n, 4), n


def _resolved_rows(con: sqlite3.Connection, family: str | None, since_ts: int | None) -> list[dict]:
    q = """SELECT f.id, f.event_key, f.conviction, o.status,
                  (SELECT value FROM forecast_factors ff
                   WHERE ff.forecast_id = f.id AND ff.factor_key = '_meta.base_rate') AS base_rate
           FROM forecasts f JOIN forecast_outcomes o ON f.id = o.forecast_id
           WHERE o.status IN ('win','loss')"""
    params: list = []
    if family:
        q += " AND f.event_key LIKE ?"
        params.append(f"{family}:%")
    if since_ts:
        q += " AND f.created_ts >= ?"
        params.append(since_ts)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(q, params).fetchall()]
    con.row_factory = None
    return rows


def insufficient_share(con: sqlite3.Connection, family: str | None = None) -> tuple[float, int]:
    """Доля ВСЕХ forecasts (включая ещё не resolved — это метрика входного
    потока/честности, не исхода), у которых base_rate был "недостаточно
    данных" на момент создания (нет строки _meta.base_rate)."""
    q = "SELECT f.id FROM forecasts f"
    params: list = []
    if family:
        q += " WHERE f.event_key LIKE ?"
        params.append(f"{family}:%")
    all_ids = [r[0] for r in con.execute(q, params).fetchall()]
    if not all_ids:
        return 0.0, 0
    with_base = {r[0] for r in con.execute(
        "SELECT DISTINCT forecast_id FROM forecast_factors WHERE factor_key='_meta.base_rate'"
    ).fetchall()}
    insufficient = sum(1 for fid in all_ids if fid not in with_base)
    return round(insufficient / len(all_ids), 4), len(all_ids)


def build_report(con: sqlite3.Connection, family: str | None = None, since_ts: int | None = None) -> dict:
    rows = _resolved_rows(con, family, since_ts)
    outcomes = [1 if r["status"] == "win" else 0 for r in rows]
    base_probs = [r["base_rate"] for r in rows if r["base_rate"] is not None]
    base_outcomes = [o for r, o in zip(rows, outcomes) if r["base_rate"] is not None]
    final_probs = [r["conviction"] for r in rows if r["conviction"] is not None]
    final_outcomes = [o for r, o in zip(rows, outcomes) if r["conviction"] is not None]

    clim_p, clim_n = climatology_rate(con, family, since_ts)
    ins_share, ins_total = insufficient_share(con, family)

    return {
        "family": family or "all", "n_resolved": len(rows),
        "climatology": {"p": clim_p, "n": clim_n},
        "insufficient_share": {"share": ins_share, "n_total": ins_total},
        "brier_base_rate": brier(base_probs, base_outcomes),
        "brier_final_p": brier(final_probs, final_outcomes),
        "bss_base_rate": brier_skill_score(base_probs, base_outcomes, clim_p) if clim_p else None,
        "bss_final_p": brier_skill_score(final_probs, final_outcomes, clim_p) if clim_p else None,
        "reliability_curve_final_p": reliability_curve(final_probs, final_outcomes) if final_probs else [],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", default=None)
    ap.add_argument("--since", default=None, help="YYYY-MM-DD")
    args = ap.parse_args()
    since_ts = None
    if args.since:
        since_ts = int(datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())

    con = sqlite3.connect(str(_BOT_DB))
    init_schema(con)
    report = build_report(con, args.family, since_ts)
    con.close()

    print(f"Калибровочный отчёт WP4.5 — family={report['family']}, n_resolved={report['n_resolved']}")
    print(f"Климатология (безусловный винрейт resolved): {report['climatology']}")
    print(f"Доля 'недостаточно данных' на входе: {report['insufficient_share']}")
    print(f"Brier(base_rate)={report['brier_base_rate']}  Brier(final_p)={report['brier_final_p']}")
    print(f"BSS(base_rate)={report['bss_base_rate']}  BSS(final_p)={report['bss_final_p']}")
    if report['bss_final_p'] is not None and report['bss_base_rate'] is not None:
        delta = report['bss_final_p'] - report['bss_base_rate']
        print(f"Поправка LLM меняет BSS на {delta:+.4f} ({'помогает' if delta > 0 else 'не помогает' if delta < 0 else 'нейтрально'})")
    print("Кривая надёжности (final_p):")
    for b in report["reliability_curve_final_p"]:
        print(f"  {b['range']}: n={b['n']} mean_p={b['mean_p']} actual_rate={b['actual_rate']}")


if __name__ == "__main__":
    main()
