#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/agent/q_snapshot.py — WP7.2 SPEC_alpha_engine_implementation.md.

Read-only обёртка для `analyst`-роли (WP7.1): текущий вектор состояния
(symbol,tf) на stdout как JSON. Параметры только через argparse — никакой
склейки в SQL. Фиксированный таймаут на подключение к БД.

Использование: python3 tools/agent/q_snapshot.py --symbol GOLD --tf H1
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from analyze.state_vector import build_state_vector_live, build_indicator_cache
from core.symbols_registry import alias_for
import core.price_bars as _price_bars

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
_TF_TO_PB = {"H1": "1h", "H4": "4h", "D1": "1d"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--tf", required=True, choices=list(_TF_TO_PB))
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
        sv = build_state_vector_live(args.symbol, pb_symbol, args.tf, candles, con, cache=cache)
        print(json.dumps(sv, ensure_ascii=False))
    finally:
        con.close()


if __name__ == "__main__":
    main()
