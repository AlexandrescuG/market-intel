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
_alias_index: dict[str, str] | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        _cache = json.loads(_PATH.read_text(encoding="utf-8"))
    return _cache


def _build_alias_index() -> dict[str, str]:
    """alias.upper() -> canonical. Каждый canonical-ключ резолвит сам в себя,
    плюс каждый элемент его "aliases". При коллизии (один alias у двух
    canonical) побеждает первый встреченный по порядку словаря в JSON —
    не ловилось на текущих 74 записях, но явный порядок лучше молчаливого."""
    d = _load()
    idx: dict[str, str] = {}
    for canonical, entry in d.items():
        idx.setdefault(canonical.upper(), canonical)
        if isinstance(entry, dict):
            for a in entry.get("aliases") or []:
                idx.setdefault(str(a).upper(), canonical)
    return idx


def resolve(alias: str) -> str | None:
    """Любой алиас (тикер MT5/Yahoo, разговорное имя, сам canonical) ->
    canonical-ключ реестра (тот, что использует UI/i18n — напр. "GOLD",
    не "XAUUSD"). None, если реестр вообще не знает такого имени.
    WP1.1 SPEC_alpha_engine_implementation.md — раньше это делали 3
    независимых хардкод-словаря (serve.py/core/market.py/build_ch2_fed_2020.py),
    каждый знал только тикеры Yahoo и не знал про алиасы вообще (NDX, XAU,
    OIL, GAS резолвились только потому, что были прописаны там буква в букву)."""
    global _alias_index
    if _alias_index is None:
        _alias_index = _build_alias_index()
    return _alias_index.get(alias.upper())


def alias_for(canonical: str, vendor: str) -> str | None:
    """canonical-ключ реестра -> имя символа у конкретного vendor'а.

    vendor="yahoo"      -> поле "yahoo" записи.
    vendor="price_bars" -> поле "price_bars", если оно есть (сейчас только
                            у GOLD, единственный известный случай расхождения
                            канонического имени и имени в price_bars —
                            остальные 73 совпадают с canonical напрямую).
    vendor="mt5"        -> через mt5_config.SYMBOL_MAP по price_bars-имени
                            (SYMBOL_MAP исторически ключуется по нему же).
    Любой другой vendor  -> прямое поле entry.get(vendor) — задел под
                            TwelveData/Deribit/Bybit/CFTC, когда для них
                            появятся реальные данные (см. §1.8 — не
                            выдумывать значения заранее).
    """
    d = _load()
    entry = d.get(canonical)
    if not isinstance(entry, dict):
        return None
    if vendor == "price_bars":
        return entry.get("price_bars", canonical)
    if vendor == "mt5":
        pb_symbol = entry.get("price_bars", canonical)
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))  # mt5_config.py в корне market_intel
        from mt5_config import SYMBOL_MAP  # локальный импорт: чисто данные, без mt5
        return SYMBOL_MAP.get(pb_symbol)
    return entry.get(vendor)


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
