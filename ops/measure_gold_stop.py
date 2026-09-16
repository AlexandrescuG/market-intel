#!/usr/bin/env python3
"""Сколько стоит узкий стоп по золоту — чтобы решать числом, а не на глаз.

Вопрос владельца 16.09: минимальный лот золота при стопе 1.5 ATR рискует
26.28 USD, а на счёте 1400 при 1% разрешено 14.00. Арифметика говорит, что
влезет стоп до 0.80 ATR. Но «влезет по деньгам» и «работает» — разные вещи:
узкий стоп выбивают чаще, а спред занимает бо́льшую долю риска.

Здесь меряем ровно это: EV в R, винрейт и долю спреда при разной ширине
стопа. R нормирован на дистанцию до стопа, поэтому ряды сравнимы между
собой; в деньгах при этом риск везде одинаковый — в том и смысл расчёта
объёма от риска.

Два контроля, без которых таблицу читать нельзя (те же, что в backtest.py):
  · без издержек  — сколько из результата съедает спред;
  · вход наугад   — отличается ли наш вход от монетки при этой геометрии.

    python3 ops/measure_gold_stop.py
    python3 ops/measure_gold_stop.py --symbol EURUSD --tf 4h
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

sys.path.insert(0, "/mnt/sbfdata/sbf-platform/market_intel")

from analyze.engine import backtest, manage                      # noqa: E402
from analyze.engine.execution import ACTIVE_RULES                # noqa: E402

WIDTHS = (0.6, 0.8, 1.0, 1.5, 2.0, 3.0)


def line(label: str, s: dict, spread_share: float | None = None) -> str:
    if not s or not s.get("n"):
        return f"  {label:22} нет сделок"
    marker = ""
    if s["lo"] > 0:
        marker = "  ↑ нижняя граница выше нуля"
    elif s["hi"] < 0:
        marker = "  ↓ верхняя граница ниже нуля"
    sp = f"{spread_share * 100:5.1f}%" if spread_share is not None else "    —"
    return (f"  {label:22}{s['n']:>7}{s['ev']:>9.4f}{s['lo']:>9.4f}{s['hi']:>9.4f}"
            f"{s['wr'] * 100:>7.1f}%{sp:>8}{marker}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--rr", type=float, default=2.0)
    a = ap.parse_args()

    import core.price_bars as pb
    from analyze.engine import sources
    candles = pb.load_candles(a.symbol, a.tf)
    spread = backtest.SPREAD.get(a.symbol, 0.0)
    # Типичный ATR на хвосте истории — чтобы показать долю спреда в риске.
    atrs = [sources.atr(candles, i) for i in range(len(candles) - 500, len(candles) - 2)]
    atrs = [x for x in atrs if x]
    atr_typ = sorted(atrs)[len(atrs) // 2] if atrs else 0.0

    print(f"{a.symbol} {a.tf}: баров {len(candles)}, спред {spread}, "
          f"типичный ATR {atr_typ:.2f}, RR {a.rr}")
    print(f"Сопровождение: {ACTIVE_RULES.name if hasattr(ACTIVE_RULES, 'name') else 'включено'}")
    print()
    print(f"  {'ширина стопа':22}{'сделок':>7}{'EV в R':>9}{'ниж.':>9}{'верх.':>9}"
          f"{'винрейт':>8}{'спред':>8}")
    print("  " + "─" * 70)

    for w in WIDTHS:
        geom = {"stop_atr": w, "rr": a.rr}
        share = spread / (w * atr_typ) if atr_typ else None
        out = backtest.run_symbol(a.symbol, a.tf, f"{w}atr", geom,
                                  costs=True, with_random=False,
                                  rules=ACTIVE_RULES)
        allt = [t for k, v in out.items() if not k.startswith("_") for t in v]
        print(line(f"{w} ATR", backtest.summarize(allt), share))

    print()
    print("  Контроли при 0.8 и 1.5 ATR:")
    for w in (0.8, 1.5):
        geom = {"stop_atr": w, "rr": a.rr}
        free = backtest.run_symbol(a.symbol, a.tf, f"{w}free", geom,
                                   costs=False, with_random=True,
                                   rules=ACTIVE_RULES)
        allt = [t for k, v in free.items() if not k.startswith("_") for t in v]
        rnd = free.get("_случайный_вход", [])
        print(line(f"{w} ATR без издержек", backtest.summarize(allt)))
        print(line(f"{w} ATR вход наугад", backtest.summarize(rnd)))

    print()
    print("Как читать. EV в R сравним между строками: риск в деньгах везде один")
    print("и тот же, меняется только объём позиции. Если EV при узком стопе")
    print("падает — значит узкий стоп выбивают раньше, чем цена доходит до цели,")
    print("и экономия на объёме оплачена качеством входа.")


if __name__ == "__main__":
    main()
