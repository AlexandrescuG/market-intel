#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/agent/q_base_rate.py — WP7.2/WP4.2 SPEC_alpha_engine_implementation.md.

Read-only обёртка над `analyze.base_rate.lookup_base_rate` для `analyst`
(WP7.4: "модель МОЖЕТ проверить базовую ставку запросом, но не может
заменить своей оценкой" — вызов, а не изобретение числа). Текущий вектор
состояния берётся live (build_state_vector_live), НЕ передаётся аргументом —
агент не может подсунуть произвольное состояние, только то, что реально есть.

Использование:
  python3 tools/agent/q_base_rate.py --symbol GOLD --tf H4 \
      --pattern bearish_engulfing --direction bearish \
      --atr-mult 1.5 --rr 2.0 --horizon-bars 30
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from analyze.base_rate import lookup_base_rate
from analyze.labeler import config_key as _config_key
from analyze.state_vector import build_state_vector_live, build_indicator_cache
from core.symbols_registry import alias_for
import core.price_bars as _price_bars

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
_TF_TO_PB = {"H1": "1h", "H4": "4h", "D1": "1d"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--tf", required=True, choices=list(_TF_TO_PB))
    ap.add_argument("--pattern", required=True)
    ap.add_argument("--direction", required=True, choices=["bullish", "bearish"])
    ap.add_argument("--atr-mult", required=True, type=float)
    ap.add_argument("--rr", required=True, type=float)
    ap.add_argument("--horizon-bars", required=True, type=int)
    args = ap.parse_args()

    candles = _price_bars.load_candles(args.symbol, _TF_TO_PB[args.tf])
    if not candles:
        print(json.dumps({"error": f"нет данных {args.symbol} {args.tf}"}, ensure_ascii=False))
        return

    con = sqlite3.connect(str(_BOT_DB), timeout=5)
    con.execute("PRAGMA query_only = ON")
    try:
        pb_symbol = alias_for(args.symbol, "price_bars") or args.symbol
        cache = build_indicator_cache(candles)
        target_state = build_state_vector_live(args.symbol, pb_symbol, args.tf, candles, con, cache=cache)
        ckey = _config_key(args.atr_mult, args.rr, args.horizon_bars)
        result = lookup_base_rate(con, args.pattern, args.direction, args.symbol,
                                   args.tf, ckey, target_state)
        print(json.dumps(result, ensure_ascii=False))
    finally:
        con.close()


if __name__ == "__main__":
    main()
