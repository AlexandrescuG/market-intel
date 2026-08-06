"""symbols.py — единый реестр понятных названий инструментов.

Один источник истины для бэкенда (этот модуль) и фронта (assets/sbf-symbols.js) —
оба читают web/data/symbols.json. См. SPEC_symbol_names.md §3.

symbol_name(sym, lang='ru', mode='name'):
    mode 'name'         → «Золото»          (проза, бриф, движения, фигуры)
    mode 'name+ticker'  → «Золото · GOLD»   (шапка графика, журнал, свитчеры)
    mode 'raw'          → «GOLD»            (URL, ключи данных — не для вывода)
Инструмент без записи в реестре возвращает исходный тикер как есть — честный
фолбэк, не выдумываем название (см. §1, категория C и приёмка §6).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("symbols")

DEFAULT_LANG = "ru"
SUPPORTED_LANGS = ("ru", "ro", "en")

_SYMBOLS_PATH = Path(__file__).parent.parent / "web" / "data" / "symbols.json"
_registry: dict[str, dict] | None = None
_alias_to_canon: dict[str, str] | None = None


def _load() -> dict[str, dict]:
    global _registry, _alias_to_canon
    if _registry is not None:
        return _registry
    try:
        _registry = json.loads(_SYMBOLS_PATH.read_text("utf-8"))
    except Exception as e:
        log.error("Не удалось прочитать %s: %s", _SYMBOLS_PATH, e)
        _registry = {}
    alias_map: dict[str, str] = {}
    for canon, entry in _registry.items():
        alias_map[canon.upper()] = canon
        for alias in entry.get("aliases", []):
            alias_map[str(alias).upper()] = canon
    _alias_to_canon = alias_map
    return _registry


def reload_cache() -> None:
    """Для разработки/после правки symbols.json без рестарта процесса."""
    global _registry, _alias_to_canon
    _registry = None
    _alias_to_canon = None


def canon_of(sym: str | None) -> str | None:
    """Сырой тикер/алиас (любого регистра) -> канонический ключ реестра, или
    None если инструмент в реестре не значится."""
    if not sym:
        return None
    _load()
    return _alias_to_canon.get(str(sym).upper())


def symbol_class(sym: str) -> str | None:
    canon = canon_of(sym)
    reg = _load()
    return reg[canon]["class"] if canon else None


def symbol_name(sym: str, lang: str = DEFAULT_LANG, mode: str = "name") -> str:
    if not sym or mode == "raw":
        return sym
    lang = lang if lang in SUPPORTED_LANGS else DEFAULT_LANG
    reg = _load()
    canon = canon_of(sym)
    entry = reg.get(canon) if canon else None
    name = (entry.get(lang) or entry.get(DEFAULT_LANG) or sym) if entry else sym
    ticker = canon or sym
    if mode == "name+ticker":
        return name if name.upper() == str(ticker).upper() else f"{name} · {ticker}"
    return name
