#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ops/compare_bars.py — сверить бары FxPro (cTrader) с барами Ava (MT5).

ЗАЧЕМ ЭТО ДЕЛАЕТСЯ ДО ПЕРЕПИСЫВАНИЯ, А НЕ ПОСЛЕ.

Весь трек-рекорд движка, бэктест на 90 тыс. сделок и калибровка издержек
посчитаны на барах Ava. Если бары FxPro заметно другие, то после переезда
эта история перестанет описывать то, чем мы торгуем, и накопленное придётся
считать заново. Это нормально — но знать об этом надо заранее, а не
обнаружить через месяц по расхождению статистики.

Сравниваем по совпадающим меткам времени: закрытие, размах и ATR. Разница в
доли пункта — обычное дело, у площадок разные пулы ликвидности. Разница в
проценты означает, что бары описывают разный рынок.
"""
from __future__ import annotations

import statistics
import sys

sys.path.insert(0, "/mnt/sbfdata/sbf-platform/market_intel")

import core.price_bars as _pb                                        # noqa: E402
from analyze.ctrader import bars as ct_bars                          # noqa: E402
from analyze.ctrader.session import CTraderError, Session            # noqa: E402

# наше каноническое имя -> имя у FxPro. У Ava золото `GOLD`, здесь `XAUUSD`.
PAIRS = [("XAUUSD", "XAUUSD"), ("EURUSD", "EURUSD"),
         ("GBPUSD", "GBPUSD"), ("USDJPY", "USDJPY")]
TF = "1h"


def atr(c, n=14):
    if len(c) < n + 1:
        return None
    tr = [max(c[i]["h"] - c[i]["l"], abs(c[i]["h"] - c[i - 1]["c"]),
              abs(c[i]["l"] - c[i - 1]["c"])) for i in range(len(c) - n, len(c))]
    return sum(tr) / n


def main() -> int:
    print(f"Сверка баров {TF}: FxPro (cTrader) против Ava (MT5, наш price_bars)\n")
    bad = 0
    with Session() as s:
        t = s.trader()
        print(f"счёт {s.account_id} · {getattr(t, 'brokerName', '?')} · "
              f"{'ДЕМО' if s.is_demo else 'РЕАЛ'}\n")
        print(f"{'инструмент':11}{'общих':>7}{'ср.|Δclose|':>13}{'макс':>10}"
              f"{'ATR FxPro':>11}{'ATR Ava':>10}{'ATR Δ%':>9}")
        for canon, fx in PAIRS:
            try:
                new = ct_bars.fetch(s, fx, TF, count=400)
            except CTraderError as e:
                print(f"{canon:11}✗ {e}")
                bad += 1
                continue
            old = _pb.load_candles(canon, TF) or []
            if not old:
                print(f"{canon:11}— в price_bars нет данных")
                continue
            o = {c["ts"]: c for c in old}
            common = [(n, o[n["ts"]]) for n in new if n["ts"] in o]
            if len(common) < 20:
                print(f"{canon:11}общих баров всего {len(common)} — сравнивать нечего")
                bad += 1
                continue
            rel = [abs(a["c"] - b["c"]) / b["c"] for a, b in common]
            a_new, a_old = atr(new), atr(old)
            d_atr = (a_new - a_old) / a_old * 100 if a_new and a_old else float("nan")
            print(f"{canon:11}{len(common):>7}{statistics.mean(rel) * 100:>12.4f}%"
                  f"{max(rel) * 100:>9.3f}%{a_new:>11.5f}{a_old:>10.5f}{d_atr:>8.1f}%")
            if statistics.mean(rel) > 0.001:      # 0.1% — уже другой рынок
                print(f"{'':11}⚠ среднее расхождение выше 0.1% — это не шум площадок")
                bad += 1
    print("\nВывод:", "расхождения в пределах нормы, историю можно считать сопоставимой"
          if not bad else "есть расхождения — читать выше, историю придётся пересчитать")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
