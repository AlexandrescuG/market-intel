"""core/price_bars.py — WP1.2 SPEC_alpha_engine_implementation.md.

Единая точка чтения свечей для факторных джобов (sr_levels_job,
pattern_stats_job, hourly_vol_job, confluence_job). Раньше каждый джоб сам
парсил `web/data/ohlc_{symbol}_{tf}.json` — при этом `ohlc_*.json` были
ВХОДОМ для расчётов, а не проекцией, и джобы не видели ничего, что ohlc-файл
ещё не успел получить (см. §1.2 спеки: два несвязанных пространства цен).

Теперь `price_bars` (bot.db) — единственный источник; `ohlc_*.json`
генерируется из него же отдельным джобом-проекцией (publish.py) и
используется графиком, но не расчётами.

Имена символов везде в этом модуле — КАНОНИЧЕСКИЕ (реестровые, "GOLD", а не
"XAUUSD") — так же, как назывались файлы ohlc_GOLD_D1.json раньше. Внутри
резолвится через symbols_registry.alias_for(canonical, "price_bars").
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.symbols_registry import alias_for as _alias_for, _load as _load_registry

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")


def load_candles(canonical: str, tf: str) -> list[dict] | None:
    """[{"ts","o","h","l","c"}, ...] отсортировано по ts возрастанию, или
    None если для этого символа/ТФ вообще нет строк (эквивалент старого
    "файл не существует" — вызывающий код уже умеет обрабатывать None)."""
    pb_symbol = _alias_for(canonical, "price_bars") or canonical
    con = sqlite3.connect(str(_BOT_DB))
    try:
        rows = con.execute(
            "SELECT ts, o, h, l, c FROM price_bars WHERE symbol=? AND tf=? ORDER BY ts ASC",
            (pb_symbol, tf),
        ).fetchall()
    finally:
        con.close()
    if not rows:
        return None
    return [{"ts": int(ts), "o": float(o), "h": float(h), "l": float(l), "c": float(c)}
            for ts, o, h, l, c in rows]


def available_symbols(tf: str) -> list[str]:
    """Канонические (реестровые) имена символов, у которых есть строки
    price_bars на данном ТФ. Замена glob.glob("ohlc_*_{tf}.json") — раньше
    список выводился из того, какие JSON-файлы существуют на диске, теперь
    из того, что реально есть в price_bars (то же самое множество на
    сегодня — все 30 chart:true символов покрыты, проверено при миграции)."""
    con = sqlite3.connect(str(_BOT_DB))
    try:
        pb_symbols = {r[0] for r in con.execute(
            "SELECT DISTINCT symbol FROM price_bars WHERE tf=?", (tf,))}
    finally:
        con.close()
    registry = _load_registry()
    out = []
    for canonical, entry in registry.items():
        if not isinstance(entry, dict):
            continue
        pb_symbol = entry.get("price_bars", canonical)
        if pb_symbol in pb_symbols:
            out.append(canonical)
    return sorted(out)
