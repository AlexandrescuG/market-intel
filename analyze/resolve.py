#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/resolve.py — WP4.5 SPEC_alpha_engine_wp4_continuous_cycle.md.

Тонкая обёртка, без доизобретения: `calibration_report.build_report()` уже
пересчитывает Brier/BSS/reliability/insufficient_share С НУЛЯ из SQL при
каждом вызове (climatology "по факту на момент отчёта", не перенос старого
значения — см. докстринг того модуля) — кэш не нужен при текущих и
обозримых объёмах (`forecast_outcomes` = 0 на 13.08, горизонты D1 —
недели до первого разрешения).

Каждый прогон закрывает созревшие высказывания прошлых циклов ТОЙ ЖЕ
механикой triple-barrier, что WP2.2 (`forecast_journal.resolve_pending` ->
`analyze.labeler._walk_barriers`) — так журнал наполняется сам, без
отдельного расписания.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze.calibration_report import build_report as _build_report
from analyze.forecast_journal import init_schema, resolve_pending


def run_resolve(con: sqlite3.Connection, verbose: bool = False) -> dict:
    init_schema(con)
    n = resolve_pending(con, verbose)
    report = _build_report(con, family="barrier", since_ts=None)
    return {"n_resolved": n, "calibration": report}


def main() -> None:
    import argparse
    import json
    from pathlib import Path as _P

    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    _bot_db = _P("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
    con = sqlite3.connect(str(_bot_db))
    result = run_resolve(con, args.verbose)
    con.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
