#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ops/measure_management.py — измерить, помогает ли сопровождение позиции.

Перевод стопа в безубыток и трейлинг кажутся бесспорно полезными: они
срезают убытки. Но у них есть и обратная сторона, о которой обычно молчат —
часть будущих выигрышей превращается в нули, потому что цена сходит против
на шум, выбивает подтянутый стоп и уходит к цели без нас.

Что перевесит — вопрос эмпирический, и здесь он решается на тех же
исторических данных и тем же кодом, что и входы. Сравнение честное: одни и
те же сигналы, одни и те же издержки, меняются только правила ведения.
"""
from __future__ import annotations

import sys
from collections import defaultdict

sys.path.insert(0, "/mnt/sbfdata/sbf-platform/market_intel")

from analyze.engine import backtest as bt                            # noqa: E402
from analyze.engine.manage import PRESETS                            # noqa: E402

SYMBOLS = ["EURUSD", "USDJPY", "XAUUSD", "GBPUSD"]
GEOM = "rr2.0"


def main() -> None:
    geom = bt.GEOMETRIES[GEOM]
    print(f"Сопровождение позиции, геометрия {GEOM} "
          f"(стоп {geom['stop_atr']} ATR, цель {geom['stop_atr'] * geom['rr']} ATR)")
    print(f"Инструменты: {', '.join(SYMBOLS)}. Одни и те же сигналы во всех строках.\n")
    print(f"{'правило':22}{'сделок':>8}{'винрейт':>9}{'EV,R':>9}"
          f"{'CI95 низ':>10}{'итог R':>10}{'стоп':>7}{'цель':>7}{'ранн':>6}{'гориз':>7}")

    base_ev = None
    for name, rules in PRESETS.items():
        pooled = defaultdict(list)
        for sym in SYMBOLS:
            for strat, trades in bt.run_symbol(sym, "1h", GEOM, geom,
                                               rules=rules).items():
                pooled[strat].extend(trades)
        allt = [t for v in pooled.values() for t in v]
        if not allt:
            continue
        m = bt.summarize(allt)
        why = defaultdict(int)
        for t in allt:
            why[t["why"]] += 1
        if base_ev is None:
            base_ev = m["ev"]
        delta = "" if name == "выключено" else f"  ({m['ev'] - base_ev:+.4f})"
        print(f"{name:22}{m['n']:>8}{m['wr'] * 100:>8.1f}%{m['ev']:>9.4f}"
              f"{m['lo']:>10.4f}{m['total']:>10.1f}"
              f"{why['stop']:>7}{why['target']:>7}{why['early']:>6}"
              f"{why['horizon']:>7}{delta}")

    print("\nЧитать так: EV — среднее в единицах риска; выигрывает не тот, у кого")
    print("больше винрейт, а тот, у кого выше EV. Правило имеет смысл включать,")
    print("только если оно поднимает EV заметно, а не на уровне шума.")


if __name__ == "__main__":
    main()
