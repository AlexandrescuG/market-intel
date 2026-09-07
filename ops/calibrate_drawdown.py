#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ops/calibrate_drawdown.py — порог стоп-крана из распределения, а не из головы.

ЗАЧЕМ. `MAX_DRAWDOWN_R = 8.0` был выбран 28.08 как «осознанно консервативное
значение на старт». Проверка 07.09 показала, что он не консервативный, а
сломанный: при винрейте 35% и RR 2.0 медианная максимальная просадка на
76 сделках — 11 R. То есть кран остановил бы стратегию в БОЛЬШИНСТВЕ
нормальных прогонов, ни разу не поймав поломки.

Смысл стоп-крана — отличить «стратегия перестала работать» от «стратегия
работает как всегда, просто сейчас полоса». Для этого порог должен лежать
за пределами того, что стратегия делает сама по себе: где-то на 99-м
перцентиле случайной просадки. Всё, что мягче, — ложные срабатывания.

Распределение берётся из ИСТОРИЧЕСКОГО ПРОГОНА с теми же правилами, что
будут включены живьём. Правила сопровождения меняют форму выплаты
радикально (винрейт 29% -> 10%, но с длинным правым хвостом), и порог под
старую форму для новой не годится.
"""
from __future__ import annotations

import random
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, "/mnt/sbfdata/sbf-platform/market_intel")

from analyze.engine import backtest as bt                            # noqa: E402
from analyze.engine.manage import PRESETS                            # noqa: E402

SYMBOLS = ["EURUSD", "USDJPY", "XAUUSD", "GBPUSD"]
WINDOWS = (50, 100, 200)      # сделок на стратегию
SIMS = 5000


def r_pool(rules) -> list[float]:
    geom = bt.GEOMETRIES["rr2.0"]
    out = []
    for sym in SYMBOLS:
        for trades in bt.run_symbol(sym, "1h", "rr2.0", geom, rules=rules).values():
            out.extend(t["r"] for t in trades)
    return out


def max_dd(seq) -> float:
    eq = peak = 0.0
    worst = 0.0
    for r in seq:
        eq += r
        peak = max(peak, eq)
        worst = min(worst, eq - peak)
    return worst


def main() -> None:
    random.seed(20260907)
    for name in ("выключено", "безубыток+трейлинг"):
        pool = r_pool(PRESETS[name])
        wr = sum(1 for r in pool if r > 0) / len(pool)
        print(f"\n{'=' * 70}\n{name}: {len(pool)} исходов, винрейт {wr:.1%}, "
              f"EV {statistics.mean(pool):+.4f} R\n{'=' * 70}")
        print(f"{'окно':>8}{'медиана':>10}{'p95':>8}{'p99':>8}{'p99.9':>9}   порог")
        for w in WINDOWS:
            dds = sorted(max_dd(random.sample(pool, w)) for _ in range(SIMS))
            p50, p95, p99, p999 = (dds[len(dds) // 2], dds[int(len(dds) * 0.05)],
                                   dds[int(len(dds) * 0.01)], dds[int(len(dds) * 0.001)])
            print(f"{w:>8}{p50:>10.1f}{p95:>8.1f}{p99:>8.1f}{p999:>9.1f}   "
                  f"-> кран на {abs(p99):.0f} R сработает ложно в ~1% полос")
    print("\nЧитать так: порог = p99 для окна, соразмерного числу сделок между")
    print("ревизиями. Нынешние 8 R лежат ВНУТРИ медианы — это не предохранитель,")
    print("а генератор ложных остановок.")


if __name__ == "__main__":
    main()
