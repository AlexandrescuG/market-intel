"""core/movers.py — "вчера: кто вышел за свою норму" (SPEC_morning_brief_v2.md, блок 3).

Полная вселенная инструментов, отклонение последнего закрытого дня от
собственной нормы (Wilder ATR14) -- core.focus.yesterday_deviation() делает
арифметику, этот модуль -- чтение ohlc_{symbol}_D1.json (тот же файл/формат,
что focus_batch_job.py::_load_d1_candles(), продублировано здесь: core/ --
библиотечный слой, focus_batch_job.py -- корневой job-скрипт, импортировать
job из core/ было бы противоположным направлением зависимости).

Не привязано к сессионному гейту focus_db.build_candidates() (тот фильтрует
на session_state=='open' -- корректно для живой карточки "В фокусе", неверно
для ретроспективного "вчера" в 06:00, когда многие рынки уже закрыты).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.focus import DEFAULT_UNIVERSE, yesterday_deviation

_WEB_DATA = Path(__file__).parent.parent / "web" / "data"


def _load_d1_candles(symbol: str) -> list[dict] | None:
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


def full_universe_moves(symbols: list[str] | None = None, today: str | None = None) -> list[dict]:
    """[{symbol, bar_date, close, chg_pct, ratio}, ...] для всех символов, у
    которых есть достаточно истории. Не сортирует и не режет top-N --
    вызывающий код (build_brief_v2.py) решает, что делать со списком."""
    symbols = symbols or DEFAULT_UNIVERSE
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = []
    for sym in symbols:
        candles = _load_d1_candles(sym)
        if not candles:
            continue
        d = yesterday_deviation(candles, today)
        if d:
            out.append({"symbol": sym, **d})
    return out
