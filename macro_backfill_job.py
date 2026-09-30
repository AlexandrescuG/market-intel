#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_backfill_job.py — полная история фундаментальных рядов FRED в factor_values.

ЗАЧЕМ. Фундаментальные факторы были заведены в реестре, но фактически
пусты: `core.fred.series()` просит limit=12, и в factor_values лежало по 11
значений на показатель против 1.27 млн ценовых. С такой историей макро не
могло участвовать ни в бэктесте, ни в базовых ставках — то есть
фундаментального анализа в контуре не было, несмотря на семь строк в
factor_registry.

ГЛАВНОЕ — ЧЕСТНОЕ ВРЕМЯ. `asof_ts` ставится по дате ПУБЛИКАЦИИ FRED
(`realtime_start`), а не по дате периода. CPI за 1 июля публикуется 12
августа — задержка стабильно 38-53 дня. Значение, взятое по дате периода,
даёт наблюдателю полтора месяца знания будущего; `history_guard` в
factor_store отсечёт такое только если asof_ts проставлен верно.

Пересмотры игнорируются намеренно: берётся ПЕРВАЯ опубликованная версия,
та, которую видели в тот момент. Пересмотренное значение — тоже знание
будущего, просто менее очевидное.

Запуск:  python3 macro_backfill_job.py [--verbose]
Частота: раз в сутки достаточно — быстрее эти ряды не выходят.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import core.factor_store as fs
from core.fred import KEY_SERIES, series_full

log = logging.getLogger("macro_backfill")

# Типичная задержка публикации, дней — для factor_registry.publish_lag.
# Не используется в расчётах (там честный asof_ts), нужна как метаданные
# каталога: по ней видно, какой фактор насколько запаздывает.
TYPICAL_LAG_DAYS = {
    "CPIAUCSL": 42, "UNRATE": 7, "DFF": 1, "T10Y2Y": 1,
    "T10YIE": 1, "DCOILWTICO": 4, "DTWEXBGS": 4,
}


def _ts(day: str) -> int:
    return int(datetime.strptime(day, "%Y-%m-%d")
               .replace(tzinfo=timezone.utc).timestamp())


def backfill_series(code: str, label: str, verbose: bool = False) -> int:
    obs = series_full(code)
    if not obs:
        log.warning("%s: пусто (нет ключа FRED или ряд недоступен)", code)
        return 0

    key = f"macro.{code}"
    fs.register_factor(key, "macro", label, "index",
                       tf_native="1d", publish_lag=TYPICAL_LAG_DAYS.get(code, 0),
                       source_job="macro_backfill_job", history=True)

    batch = [{"symbol": fs.GLOBAL_SYMBOL, "tf": "1d", "ts": _ts(o["date"]),
              "factor_key": key, "value": float(o["value"]),
              "asof_ts": _ts(o["published"])}
             for o in obs if o.get("published")]
    n = fs.put_many(batch)
    if verbose:
        lag = (_ts(obs[-1]["published"]) - _ts(obs[-1]["date"])) // 86400
        log.info("%-12s %5d значений, %s .. %s, задержка последнего %d дн",
                 code, n, obs[0]["date"], obs[-1]["date"], lag)
    return n


def run(verbose: bool = False) -> int:
    total = 0
    for code, label in KEY_SERIES.items():
        total += backfill_series(code, label, verbose)
    return total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | [macro_backfill] %(message)s")
    total = run(args.verbose)
    print(f"macro_backfill: записано {total} значений")
    sys.exit(0 if total else 2)


if __name__ == "__main__":
    main()
