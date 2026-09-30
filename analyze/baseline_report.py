#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/baseline_report.py — постоянный (не ad-hoc) генератор baseline
pattern-отчёта с поправкой на множественные сравнения.

14.08: ревью нашло, что `report.py::apply_multiple_comparisons_correction`
(написана и работала 12.08, дала m=27 в отчёте `ОТЧЁТ_alpha_engine_WP0-WP3_
2026-08-12.md`) физически существует и корректна, но НЕ ВЫЗЫВАЕТСЯ НИГДЕ В
РЕПОЗИТОРИИ — тот прогон был разовым скриптом в терминале, не сохранённым
на диск. Отсюда путаница "FDR нет" при следующей проверке grep'ом: не было
вызова, сохранённого в коде, а не самой функции. Этот файл — тот самый
сохранённый вызов, чтобы baseline можно было переgenerировать в любой
момент и число m не терялось между сессиями.

"Клетка" здесь — (pattern_key, tf) при ОДНОМ фиксированном config_key,
symbols объединены в один пул внутри клетки (см. `report.py::pattern_report`
докстринг — почему пул, не отдельная клетка на символ). config по
умолчанию — тот же `_GATE_CONFIG`, что реально использует живой `gate.py`,
не произвольный: baseline должен описывать РЕАЛЬНО обслуживаемую
постановку, не абстрактную.

ВАЖНО (см. Core-лог 14.08): m=27 в этой схеме — число (pattern×tf) клеток
ПРИ ПУЛЕ инструментов, НЕ полная сетка (pattern×symbol×tf×barrier-config),
которая на порядок больше. Эта поправка защищает от одного класса
множественных сравнений (screening 9 паттернов × 3 tf), не от всех
возможных — `lookup_base_rate()`'s backoff-иерархия по state-buckets
внутри `base_rate.py` — отдельный, более глубокий источник той же болезни,
не решаемый этим файлом.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze.labeler import config_key as _config_key
from analyze.report import apply_multiple_comparisons_correction, pattern_report
from core.patterns import PATTERNS

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
_OUT_DIR = Path(__file__).parent.parent / "data" / "baseline_reports"

# = gate.py::_GATE_CONFIG — тот же, что реально видит живой гейт, не
# произвольный выбор из GRID.
DEFAULT_CONFIG = (1.5, 2.0, 30)
DEFAULT_TFS = ("D1", "H4", "H1")


def _symbols_with_labels(con: sqlite3.Connection, tf: str, config_key: str) -> list[str]:
    rows = con.execute(
        "SELECT DISTINCT symbol FROM labels WHERE tf=? AND config_key=? ORDER BY symbol", (tf, config_key)
    ).fetchall()
    return [r[0] for r in rows]


def build_baseline_report(con: sqlite3.Connection, config: tuple[float, float, int] = DEFAULT_CONFIG,
                           tfs: tuple[str, ...] = DEFAULT_TFS, method: str = "fdr_bh",
                           entry_geometry: str = "close", pool_tfs: bool = False) -> dict:
    """Одна клетка = (pattern_key, tf), symbols объединены в пул. Пустые
    клетки (n=0 — паттерн ни разу не сработал на этом tf с этим config)
    не идут в проверку -- m считает только РЕАЛЬНО протестированные
    гипотезы, не теоретический максимум 9×len(tfs).

    entry_geometry -- см. labeler.py::ENTRY_GEOMETRIES (14.08, ревью п.4).
    "close" -- дефолт, полная GRID. "next_open"/"extreme" -- только на
    _GEOMETRY_PILOT_CONFIG (labeler.py), т.к. только он реально посчитан
    (см. Core-лог 14.08) -- передавать любой другой config с ними бессмысленно,
    labels для такой комбинации физически не существует.

    pool_tfs -- WP6.5 (SPEC_alpha_engine_wp6_volatility.md): одна клетка на
    ПАТТЕРН, symbols И tfs объединены в один пул (m~8-9, не 27) -- per-cell
    FDR по pattern×tf почти не имеет мощности обнаружить реальный, но
    небольшой эффект. Симметрично report.py::pattern_report() -- список tf
    вместо строки пулит и там."""
    ckey = _config_key(*config, entry_geometry)
    reports = []
    if pool_tfs:
        symbols = sorted(set().union(*(_symbols_with_labels(con, tf, ckey) for tf in tfs)))
        for pattern_key in PATTERNS:
            r = pattern_report(con, symbols, list(tfs), ckey, pattern_key)
            if r["n"] > 0:
                reports.append(r)
    else:
        for tf in tfs:
            symbols = _symbols_with_labels(con, tf, ckey)
            if not symbols:
                continue
            for pattern_key in PATTERNS:
                r = pattern_report(con, symbols, tf, ckey, pattern_key)
                if r["n"] > 0:
                    reports.append(r)

    summary = apply_multiple_comparisons_correction(reports, method=method)
    reports.sort(key=lambda r: (r.get("p_value") if r.get("p_value") is not None else 1.0))
    return {
        "generated_at_iso": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "config_key": ckey, "tfs": list(tfs), "method": method,
        "summary": summary, "reports": reports,
    }


def _render_md(report: dict) -> str:
    s = report["summary"]
    lines = [
        f"# Baseline report {report['generated_at_iso']}", "",
        f"config_key={report['config_key']}  tfs={report['tfs']}  method={report['method']}", "",
        f"**m={s['m']} протестированных клеток (pattern×tf, пул инструментов), "
        f"alpha={s['alpha']}, candidate до поправки={s['n_candidate_before']}, "
        f"candidate после поправки={s['n_candidate_after']}**", "",
        "| pattern_key | tf | n | n_eff | winrate | winrate_CI95 | exp_R | exp_R_CI95 | PF | p_value | q/holm | status |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in report["reports"]:
        q = r.get("q_value", r.get("holm_adjusted_alpha", "—"))
        lines.append(
            f"| {r['pattern_key']} | {r['tf']} | {r['n']} | {r['n_effective']} | "
            f"{r['winrate']} | {r['winrate_ci95_pct']} | {r['expectancy_r']} | "
            f"{r['expectancy_ci95_r']} | {r['profit_factor']} | {r.get('p_value')} | {q} | {r['status']} |"
        )
    return "\n".join(lines)


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", nargs=3, type=float, default=list(DEFAULT_CONFIG),
                     metavar=("ATR_MULT", "RR", "HORIZON_BARS"))
    ap.add_argument("--tfs", nargs="+", default=list(DEFAULT_TFS))
    ap.add_argument("--method", choices=["fdr_bh", "holm"], default="fdr_bh")
    ap.add_argument("--entry-geometry", choices=["close", "next_open", "extreme"], default="close")
    ap.add_argument("--pool-tfs", action="store_true",
                     help="WP6.5: одна клетка на паттерн, symbols И tfs в одном пуле (не 27 клеток, ~8-9)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    atr_mult, rr, horizon_bars = args.config
    con = sqlite3.connect(str(_BOT_DB), timeout=10)
    report = build_baseline_report(con, (atr_mult, rr, int(horizon_bars)), tuple(args.tfs), args.method,
                                    args.entry_geometry, args.pool_tfs)
    con.close()

    md = _render_md(report)
    print(md)
    print(f"\nm={report['summary']['m']}", file=sys.stderr)

    if not args.dry_run:
        _OUT_DIR.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        (_OUT_DIR / f"baseline_{ts}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        (_OUT_DIR / f"baseline_{ts}.md").write_text(md)
        (_OUT_DIR / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        (_OUT_DIR / "latest.md").write_text(md)
        print(f"written: {_OUT_DIR}/baseline_{ts}.{{json,md}} (+ latest.*)", file=sys.stderr)


if __name__ == "__main__":
    main()
