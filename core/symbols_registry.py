"""core/symbols_registry.py — СПЕКА_графики_и_починка_календаря.md §2.

symbols.json как единственный источник истины для списка инструментов.
Раньше было 4 независимых списка (publish.py::WATCH, core/market.py::
DASHBOARD, serve.py::_M5_YF_TICKERS, focus_live.py::LABEL_TO_TICKER),
расходившихся друг с другом (USDJPY был в файлах баров и в symbols.json,
но не в WATCH — комментарий в serve.py прямо называл это обходным путём).

Флаги в самой записи symbols.json:
  "chart": true  — инструмент строит статические OHLC-файлы (publish_charts,
                   focus_live LABEL_TO_TICKER)
  "quote":  true — инструмент входит в дашборд котировок/реакции рынка
                   (core.market.DASHBOARD)
  "yahoo": "..." — тикер Yahoo Finance. Записан явно, а не выведен из
                   aliases[0]: позиция настоящего Yahoo-тикера внутри
                   aliases непостоянна (у EURUSD он первый, у GOLD —
                   последний) — угадывать positional было бы хрупко.

_M5_YF_TICKERS (serve.py) сюда сознательно НЕ включён: это самостоятельный
подмножественный список (WATCH + USDJPY, минус USDRUB/USDKZT, для которых
у yfinance нет надёжного 5-минутного покрытия) — пятым независимым списком
это не считается, он явно выводится из chart_watch() на месте использования.
"""
from __future__ import annotations

import json
from pathlib import Path

_PATH = Path(__file__).parent.parent / "web" / "data" / "symbols.json"
_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        _cache = json.loads(_PATH.read_text(encoding="utf-8"))
    return _cache


def chart_watch() -> dict[str, str]:
    """{label: yahoo_ticker} для всех инструментов с "chart": true.
    Замена захардкоженного publish.py::WATCH / focus_live.py::LABEL_TO_TICKER."""
    d = _load()
    return {k: v["yahoo"] for k, v in d.items()
            if isinstance(v, dict) and v.get("chart") and v.get("yahoo")}


def quote_dashboard() -> list[str]:
    """[yahoo_ticker, ...] для всех инструментов с "quote": true.
    Замена захардкоженного core/market.py::DASHBOARD."""
    d = _load()
    return [v["yahoo"] for k, v in d.items()
            if isinstance(v, dict) and v.get("quote") and v.get("yahoo")]


def yahoo_ticker(label: str) -> str | None:
    """Тикер Yahoo для site-метки, если он вообще известен реестру (не
    только у chart:true/quote:true записей — у любой с полем "yahoo").
    Используется core.market.to_ticker() как фоллбек для FX-пар: раньше
    to_ticker("USDCAD") возвращал "USDCAD" как есть (обычная акция), а не
    "USDCAD=X" — Yahoo такого тикера не знает. Пока пары были только
    в _ALIAS, это не всплывало (§2 спеки)."""
    d = _load()
    entry = d.get(label.upper())
    return entry.get("yahoo") if isinstance(entry, dict) else None
