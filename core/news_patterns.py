"""core/news_patterns.py — «какая новость к какому инструменту относится».

Один словарь на три потребителя: сборщик RSS (что вообще сохранять),
news_burst_job (кому проставить тег) и всё, что считает упоминания.

ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ. Выражения жили внутри news_burst_job, и сборщик о них
не знал. Из-за этого решение «сохранять ли новость» принималось вслепую: гейт
econ_relevance оценивает «похоже ли на макроэкономику» по общим словам, и
заголовок «DAX closes lower as German industrial output disappoints» получал
**0.00** при пороге 0.25 — то есть новость ровно про наш инструмент
выбрасывалась до того, как её кто-либо мог пометить. То же с «Cocoa prices hit
three-month low» (0.00) и «Nike cuts full-year outlook» (0.10).

ТРИ СЛОЯ, ПОРЯДОК = ПРИОРИТЕТ:
  1. встроенный словарь — пятнадцать символов реестра, исторически первый;
  2. сгенерированный из каталога (data/news_symbol_patterns.json) — широкий,
     но буквальный: у AUDUSD получается \\bAUDUSD\\b;
  3. рукописный (data/news_patterns_core.json) — «AUD/USD», «Australian
     dollar», «DAX», «Nikkei». Побеждает при совпадении ключей.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Встроенный словарь: пятнадцать символов реестра. Оставлен здесь, а не в
# файле, намеренно — это последняя линия обороны: даже если оба файла с диска
# не прочитаются, золото, нефть и биткоин продолжат тегироваться.
BUILTIN = {
    "GOLD":   r"\bgold\b|золот|\bxau\b",
    "SILVER": r"\bsilver\b|серебр|\bxag\b",
    "BTC":    r"\bbitcoin\b|биткои|биткойн|\bbtc\b",
    "ETH":    r"\bethereum\b|эфириум|\beth\b",
    "SOL":    r"\bsolana\b",
    "SPX":    r"s&p\s*500|\bs&p\b|\bspx\b|standard\s*&\s*poor",
    "NASDAQ": r"\bnasdaq\b|\bnas100\b",
    "DJI":    r"dow\s+jones|\bdow\s*30\b|\bus30\b",
    "VIX":    r"\bvix\b|volatility index|индекс волатильности",
    "WTI":    r"\bwti\b|crude oil|нефт[ьи]",
    "NG":     r"natural gas|природн\w*\s*газ|henry hub",
    "EURUSD": r"eur\s*/\s*usd|\beurusd\b|евро.{0,15}доллар",
    "GBPUSD": r"gbp\s*/\s*usd|\bgbpusd\b|\bcable\b|фунт.{0,15}доллар",
    "USDJPY": r"usd\s*/\s*jpy|\busdjpy\b|доллар.{0,15}йен",
    "DXY":    r"\bdxy\b|dollar index|индекс доллара",
}

_TAG_RE = re.compile(r"<[^>]+>")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")

_cache: dict | None = None
_cache_mtimes: tuple = ()


def searchable(title: str | None, text: str | None) -> str:
    """Заголовок + текст без разметки и без ссылок.

    🔴 Убираем именно ссылки, а не только теги. Поле text у RSS-сигналов
    хранит сырой HTML вместе со ссылкой вида news.google.com/rss/... — и
    выражение \\bGOOGLE\\b находило «google» в КАЖДОЙ новости, пришедшей через
    Google News. Замер 07.09: 4692 тега у #GOOGLE, второе место после
    биткоина, и ни в одном заголовке Google не упоминался.
    """
    import html as _html
    blob = f"{title or ''}\n{text or ''}"
    blob = _URL_RE.sub(" ", blob)
    blob = _TAG_RE.sub(" ", blob)
    return _html.unescape(blob)


def _load_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"{path.name} не прочитан ({e})", file=sys.stderr)
        return {}
    out = {}
    for sym, meta in raw.items():
        if sym.startswith("_") or not isinstance(meta, dict):
            continue
        pat = meta.get("pattern")
        if not pat:
            continue
        try:
            out[sym] = re.compile(pat, re.I)
        except re.error as e:
            # Битое выражение пропускаем поимённо: одна опечатка не повод
            # остаться без остальных.
            print(f"выражение для {sym} не скомпилировалось: {e}", file=sys.stderr)
    return out


def load_all() -> dict:
    """{символ: скомпилированное выражение}. Кэш сбрасывается при правке файлов."""
    global _cache, _cache_mtimes
    paths = [ROOT / "data" / "news_symbol_patterns.json",
             ROOT / "data" / "news_patterns_core.json"]
    mtimes = tuple(p.stat().st_mtime if p.exists() else 0 for p in paths)
    if _cache is not None and mtimes == _cache_mtimes:
        return _cache
    merged = {k: re.compile(v, re.I) for k, v in BUILTIN.items()}
    merged.update(_load_file(paths[0]))
    merged.update(_load_file(paths[1]))
    _cache, _cache_mtimes = merged, mtimes
    return merged


def match_symbols(title: str | None, text: str | None) -> list:
    """Символы, к которым относится новость. Пустой список — ни к одному."""
    blob = searchable(title, text)
    return [sym for sym, pat in load_all().items() if pat.search(blob)]


def mentions_instrument(title: str | None, text: str | None) -> bool:
    """Быстрая проверка «эта новость вообще про какой-нибудь наш инструмент».

    Отдельно от match_symbols: сборщику не нужен список, нужен ответ да/нет, и
    на первом же совпадении можно выйти. На 800 выражениях разница заметна —
    сборщик прогоняет через это каждую запись каждой ленты.
    """
    blob = searchable(title, text)
    for pat in load_all().values():
        if pat.search(blob):
            return True
    return False
