"""Форматтер: FLAG + IMPORTANCE словари, шаблоны постов. Ноль LLM."""
from __future__ import annotations

import hashlib
import re
import time
from urllib.parse import urlparse

# ── Флаги по ISO-коду страны ──────────────────────────────────────────────────
FLAG: dict[str, str] = {
    "US": "🇺🇸", "GB": "🇬🇧", "EU": "🇪🇺", "CA": "🇨🇦", "CN": "🇨🇳",
    "JP": "🇯🇵", "AU": "🇦🇺", "CH": "🇨🇭", "DE": "🇩🇪", "FR": "🇫🇷",
    "UA": "🇺🇦", "IR": "🇮🇷", "SA": "🇸🇦", "BR": "🇧🇷", "IN": "🇮🇳",
    "KR": "🇰🇷", "MX": "🇲🇽", "RU": "🇷🇺", "MD": "🇲🇩", "TR": "🇹🇷",
    "IL": "🇮🇱", "PL": "🇵🇱", "NG": "🇳🇬", "ZA": "🇿🇦", "AR": "🇦🇷",
    "AE": "🇦🇪", "SG": "🇸🇬", "HK": "🇭🇰", "TW": "🇹🇼", "ID": "🇮🇩",
}

# ── Эмодзи важности: (category, keywords) → emoji ─────────────────────────────
# Правило: первое совпадение побеждает.
_IMPORTANCE_RULES: list[tuple[str, list[str], str]] = [
    ("central_bank",  [],                                              "❗️"),
    ("econ_release",  [],                                              "❗️"),
    ("macro_wire",    ["fed", "fomc", "ecb", "rate", "ставк"],        "❗️"),
    ("macro_wire",    ["warning", "risk", "предупрежд", "опасн"],     "⚠️"),
    ("crypto",        [],                                              "✴️"),
    ("price_move",    [],                                              "💥"),
    ("geopolitics",   ["war", "strike", "войн", "атак", "ракет"],     "⚠️"),
    ("geopolitics",   [],                                              "🌐"),
    ("regional",      [],                                              "📌"),
]


def importance_emoji(category: str, text: str = "") -> str:
    tl = text.lower()
    for cat, kws, em in _IMPORTANCE_RULES:
        if cat == category:
            if not kws or any(k in tl for k in kws):
                return em
    return "📰"


# ── Детектор флага из домена/текста ────────────────────────────────────────────
_DOMAIN_TO_COUNTRY: dict[str, str] = {
    "federalreserve.gov": "US", "bls.gov": "US", "bea.gov": "US",
    "ecb.europa.eu": "EU", "eurostat.ec.europa.eu": "EU",
    "bankofengland.co.uk": "GB", "ons.gov.uk": "GB",
    "boc-bce.gc.ca": "CA", "statcan.gc.ca": "CA",
    "reuters.com": "", "ft.com": "", "cnbc.com": "",
    "bloombergmarkets": "", "coindesk.com": "", "cointelegraph.com": "",
    "point.md": "MD", "deschide.md": "MD",
    "aljazeera.com": "",
}

_TEXT_TO_COUNTRY: list[tuple[list[str], str]] = [
    (["federal reserve", "фрс", "fomc", "fed rate"], "US"),
    (["ecb ", "european central bank", "есб"], "EU"),
    (["bank of england", "boe"], "GB"),
    (["bank of canada", "boc", "банк канады"], "CA"),
    (["china ", "pboc", "китай"], "CN"),
    (["japan ", "boj ", "япония"], "JP"),
    (["ukraine ", "украин"], "UA"),
    (["iran ", "иран "], "IR"),
    (["bitcoin", "btc", "ethereum", "eth", "crypto", "крипт"], ""),  # нет флага
    (["gold", "золот", "brent", "opec"], ""),
]


def detect_flag(url: str, text: str) -> str:
    if url:
        host = urlparse(url).netloc.replace("www.", "")
        for domain, cc in _DOMAIN_TO_COUNTRY.items():
            if domain in host:
                return FLAG.get(cc, "")
    tl = text.lower()
    for kws, cc in _TEXT_TO_COUNTRY:
        if any(k in tl for k in kws):
            return FLAG.get(cc, "")
    return ""


# ── Нормализация для дедупа ───────────────────────────────────────────────────
_STRIP_RE = re.compile(r"[^\w\s]|https?://\S+", re.UNICODE)


def normalize_title(title: str) -> str:
    t = title.lower()
    t = _STRIP_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def content_hash(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:20]


def source_label(url: str, source_ref: str) -> str:
    if url:
        host = urlparse(url).netloc.replace("www.", "")
        return host.split(".")[0] if host else source_ref
    return source_ref or "Источник"


# ── Шаблоны ───────────────────────────────────────────────────────────────────

def fmt_free_text(
    *,
    title: str,
    url: str,
    source: dict,
    category: str | None = None,
) -> str | None:
    """
    Тип free_text: заголовок дословно + атрибуция.
    Без ссылки не постится — возвращает None.
    """
    if not url:
        return None

    cat = category or source.get("category", "general")
    imp = importance_emoji(cat, title)
    flag = detect_flag(url, title)
    tags = source.get("default_tags", "")
    lbl = source_label(url, source.get("ref", ""))

    header = f"{imp}{flag}{tags}".strip()
    return f"{header}\n\n{title}\n— {lbl} ({url})"


def fmt_price_move(
    *,
    ticker: str,
    condition: str,
    category: str = "price_move",
) -> str:
    imp = importance_emoji(category)
    gold_prefix = "🌕" if "золот" in ticker.lower() or "gold" in ticker.lower() else ""
    return f"{imp}{gold_prefix}#{ticker} {condition}"


def fmt_upcoming(events: list[dict]) -> str:
    """
    Группировка «ВПЕРЕДИ»:
    events: [{'flag': '🇺🇸', 'country': 'США', 'indicator': '...', 'period': '...', 'time': '14:30'}]
    """
    lines = ["❗️ВПЕРЕДИ"]
    for e in events:
        lines.append(
            f"{e.get('flag','')}{e.get('country','')} — "
            f"{e['indicator']} ({e['period']}) — {e['time']} МД"
        )
    return "\n".join(lines)


def fmt_econ_release(
    *,
    country: str,
    country_code: str,
    indicator: str,
    period: str,
    actual: str,
    unit: str = "",
    forecast: str = "",
    previous: str = "",
    category: str = "econ_release",
    tags: str = "#экономика",
) -> str:
    flag = FLAG.get(country_code.upper(), "")
    imp = importance_emoji(category)
    header = f"{imp}{flag}#{tags} #{country.lower()} #отчётность"
    line = f"{country} — {indicator} ({period}) = {actual}{unit}"
    if forecast:
        line += f" (ожид {forecast}"
        if previous:
            line += f" / ранее {previous}"
        line += ")"
    elif previous:
        line += f" (ранее {previous})"
    return f"{header}\n{line}"
