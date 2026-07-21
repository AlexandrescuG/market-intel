#!/usr/bin/env python3
"""
focus_batch_job.py — SPEC_focus_engine.md, batch-контекст (§3).

Раз в день, ДО утреннего отчёта (см. sbf-focus-batch.timer в 05:50 + явный
вызов из analyze/run_daily.sh шагом 0 — см. план): для каждого инструмента
из instrument считает ATR(14) по Уайлдеру на закрытых дневных барах
(ohlc_{symbol}_D1.json), пишет atr_cache; сидит instrument_live текущим
(ещё формирующимся) диапазоном дня + session_state; затем выбирает
начальный фокус дня для scope='default' (DEFAULT_UNIVERSE) —
select_focus(..., current=None, new_source="batch") — и коммитит его в
focus_state. Именно этот коммит с source="batch" — то, для чего
build_brief.py/prompt.md позже пишут LLM-разбор (§9).

Использование:
  python3 focus_batch_job.py [--verbose]
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core import focus_db  # noqa: E402
from core.focus import DEFAULT_UNIVERSE, select_focus, wilder_atr  # noqa: E402

_WEB_DATA = Path(__file__).parent / "web" / "data"
ATR_N = 14


def _load_d1_candles(symbol: str) -> list[dict] | None:
    """Тот же файл/формат, что sr_levels_job.py:_load_d1_candles() читает —
    ohlc_{symbol}_D1.json's "candles" — но с полем 'date' (не unix ts),
    т.к. wilder_atr()'s as_of_date сравнивает строки 'YYYY-MM-DD'."""
    f = _WEB_DATA / f"ohlc_{symbol}_D1.json"
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    out = []
    for c in data.get("candles") or []:
        t = c.get("time")
        try:
            date_str = t if isinstance(t, str) else \
                datetime.fromtimestamp(int(t), tz=timezone.utc).strftime("%Y-%m-%d")
            out.append({
                "date": date_str,
                "o": float(c["open"]), "h": float(c["high"]),
                "l": float(c["low"]), "c": float(c["close"]),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return out or None


def process_symbol(symbol: str, today: str, now_ts: int, verbose: bool) -> bool:
    candles = _load_d1_candles(symbol)
    if not candles:
        if verbose:
            print(f"  {symbol}: нет ohlc_{symbol}_D1.json / пусто")
        return False

    atr = wilder_atr(candles, n=ATR_N, as_of_date=today)
    closed = [c for c in candles if c["date"] < today]
    prev_close = closed[-1]["c"] if closed else None
    focus_db.save_atr_cache(symbol, today, ATR_N, atr, prev_close)

    inst = focus_db.load_instrument(symbol)
    if inst is None:
        if verbose:
            print(f"  {symbol}: не в instrument (не засеян)")
        return False
    now_dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)
    session_state = focus_db.compute_session_state(inst["asset_class"], now_dt)

    today_candle = next((c for c in candles if c["date"] == today), None)
    if today_candle:
        day_open, day_high, day_low, last = (
            today_candle["o"], today_candle["h"], today_candle["l"], today_candle["c"]
        )
    elif prev_close is not None:
        # §11 "гэп без внутридневного диапазона (только открылся)" -- ещё нет
        # сегодняшней свечи вообще, сидим одной точкой на вчерашнем закрытии;
        # runningTR при этом отражает только гэп, если появится тик за пределы.
        day_open = day_high = day_low = last = prev_close
    else:
        if verbose:
            print(f"  {symbol}: нет ни сегодняшней свечи, ни prev_close")
        return False

    focus_db.save_instrument_live(symbol, now_ts, day_open, day_high, day_low, last, session_state)
    if verbose:
        print(f"  {symbol}: ATR={atr}, prev_close={prev_close}, session={session_state}")
    return True


def run(verbose: bool = False) -> int:
    focus_db.ensure_schema()
    now_ts = int(time.time())
    today = focus_db.today_str(datetime.fromtimestamp(now_ts, tz=timezone.utc))

    processed = 0
    for row in focus_db.all_instruments():
        if process_symbol(row["symbol"], today, now_ts, verbose):
            processed += 1

    candidates = focus_db.build_candidates(DEFAULT_UNIVERSE, today)
    pinned = None  # scope='default' -- нет пользователя, пин не применим
    current = focus_db.load_focus_state("default")
    state = select_focus("default", candidates, pinned, current, now_ts, new_source="batch")
    focus_db.save_focus_state(state)

    if verbose:
        print(f"Обработано инструментов: {processed}/{len(DEFAULT_UNIVERSE)}")
        print(f"Фокус дня (default): {state.symbol} anomaly={state.anomaly} source={state.source}")
    return processed


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    run(verbose=args.verbose)
