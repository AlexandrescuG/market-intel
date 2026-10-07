#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ops/measure_geometry.py — подобрать ширину стопа и цель по замеру.

🔴 Зачем. 07.10.2026 владелец сказал: «баланс держится в небольшом минусе».
Разбор показал, что сломано ничего не было — система работала ровно по своей
измеренной мере, а мера была нулевой: при геометрии 1.5 ATR / RR 2.0
EV = +0.0159 R при нижней границе 95% интервала −0.0109. То есть
преимущество было неотличимо от его отсутствия, и «небольшой минус» —
совершенно штатное поведение такой системы.

Этот скрипт перебирает геометрию входа при неизменном правиле сопровождения
и показывает, где преимущество отличимо от нуля.

Как читать и как НЕ обмануться:

  · Решает не EV, а НИЖНЯЯ ГРАНИЦА интервала. EV можно поднять шумом.
  · Интервал уже с поправкой на перекрытие сделок (`backtest._overlap`):
    при 150 тыс. сделок эффективная выборка около 4 тыс., и без поправки
    любой результат выглядел бы значимым.
  · Доверять стоит не лучшей клетке, а ФОРМЕ кривой. Если максимум на краю
    сетки — скорее всего это артефакт, и надо расширять сетку. Если
    максимум внутри (рост, вершина, спад) — за ним стоит механизм.
  · `--по-инструментам` показывает ту же таблицу по каждому инструменту и по
    половинам истории. Правка, которая держится на трёх инструментах и в
    обеих половинах, — это находка; правка, которая держится на одном, —
    это совпадение.

Запуск:
    .venv/bin/python ops/measure_geometry.py
    .venv/bin/python ops/measure_geometry.py --по-инструментам
    .venv/bin/python ops/measure_geometry.py --сетка 2.0:2.0,2.5:3.0

Считает долго (каждая клетка — полный прогон по истории четырёх
инструментов, около минуты). Это цена честного ответа.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

sys.path.insert(0, "/mnt/sbfdata/sbf-platform/market_intel")

from analyze.engine import backtest as bt                           # noqa: E402
from analyze.engine.manage import PRESETS                           # noqa: E402

SYMBOLS = ["EURUSD", "USDJPY", "XAUUSD", "GBPUSD"]
RULES_NAME = "безубыток+трейлинг"

# Сетка по умолчанию. Крайние точки нужны именно для того, чтобы увидеть
# спад: без них нельзя отличить вершину от края.
GRID = [(1.0, 2.0), (1.5, 2.0), (2.0, 2.0), (2.5, 2.0), (3.0, 2.0), (3.5, 2.0),
        (1.5, 3.0), (2.5, 3.0), (2.5, 1.5)]


def run(geom: dict, rules) -> list[dict]:
    pooled: dict[str, list] = defaultdict(list)
    for sym in SYMBOLS:
        for strat, trades in bt.run_symbol(sym, "1h", "geom", geom,
                                           rules=rules).items():
            pooled[strat].extend(trades)
    return [t for v in pooled.values() for t in v]


def shape(trades: list[dict]) -> tuple[float, float, float]:
    """Доля прибыльных, средний выигрыш, средний проигрыш.

    🔴 Не путать с `summarize()['wr']`: там «винрейт» — это доля дошедших до
    ЦЕЛИ среди дошедших до цели или стопа, и выходы по трейлингу в него не
    попадают вовсе. При геометрии 2.5/3.0 тот винрейт равен 2.0%, а
    прибыльных сделок — 48.0%. Разница в 24 раза, и на ней легко
    сказать владельцу неправду."""
    rs = [t["r"] for t in trades]
    pos = [r for r in rs if r > 0]
    neg = [r for r in rs if r <= 0]
    return (len(pos) / len(rs) if rs else 0.0,
            sum(pos) / len(pos) if pos else 0.0,
            sum(neg) / len(neg) if neg else 0.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--сетка", dest="grid", default=None,
                    help="через запятую, вида стоп:RR — например 2.0:2.0,2.5:3.0")
    ap.add_argument("--по-инструментам", dest="per", action="store_true",
                    help="разложить по инструментам и половинам истории")
    a = ap.parse_args()

    grid = GRID
    if a.grid:
        grid = [(float(x.split(":")[0]), float(x.split(":")[1]))
                for x in a.grid.split(",")]

    rules = PRESETS[RULES_NAME]
    print(f"Геометрия входа при правиле сопровождения «{RULES_NAME}»")
    print(f"Инструменты: {', '.join(SYMBOLS)}, ТФ 1h. Одни и те же сигналы везде.")
    print("Решает НИЖНЯЯ ГРАНИЦА интервала, а не EV.\n")
    print(f"{'стоп ATR':>9}{'RR':>6}{'сделок':>9}{'EV,R':>9}{'CI95 низ':>10}"
          f"{'прибыл.':>9}{'ср.выигр':>10}{'ср.проигр':>11}{'перекр':>8}")

    best = None
    for s, rr in grid:
        trades = run({"stop_atr": s, "rr": rr}, rules)
        if not trades:
            continue
        m = bt.summarize(trades)
        wr, w, l = shape(trades)
        mark = ""
        if m["lo"] > 0 and (best is None or m["lo"] > best[1]):
            best = ((s, rr), m["lo"]); mark = "  <-"
        print(f"{s:>9}{rr:>6}{m['n']:>9}{m['ev']:>9.4f}{m['lo']:>10.4f}"
              f"{wr * 100:>8.1f}%{w:>10.3f}{l:>11.3f}{m['overlap']:>8.1f}{mark}")

        if a.per:
            for sym in SYMBOLS:
                tr = [t for v in bt.run_symbol(sym, "1h", "g",
                                               {"stop_atr": s, "rr": rr},
                                               rules=rules).values() for t in v]
                if not tr:
                    continue
                tr.sort(key=lambda t: t.get("ts") or 0)
                h = len(tr) // 2
                x, x1, x2 = (bt.summarize(tr), bt.summarize(tr[:h]),
                             bt.summarize(tr[h:]))
                ok = "держится" if (x1["ev"] > 0) == (x2["ev"] > 0) else "РАЗВАЛ"
                print(f"      {sym:8} n={x['n']:>6} EV={x['ev']:>8.4f} "
                      f"низ={x['lo']:>8.4f} | 1-я {x1['ev']:>8.4f} "
                      f"2-я {x2['ev']:>8.4f}  {ok}")

    print()
    if best:
        print(f"Лучшая по нижней границе: стоп {best[0][0]} ATR, RR {best[0][1]} "
              f"(нижняя граница {best[1]:+.4f}).")
    else:
        print("Ни одна клетка не дала нижнюю границу выше нуля — "
              "преимущества в этой сетке нет, расширять сетку бессмысленно "
              "без другой идеи.")
    print("Перед переносом в бой: вершина должна быть ВНУТРИ сетки, и правка "
          "должна держаться по инструментам (--по-инструментам).")


if __name__ == "__main__":
    main()
