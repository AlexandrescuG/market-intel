"""extract.py — детерминированный слой извлечения событий.

Пайплайн: parse_feed → cluster → [rollup] → run

Никакого инференса, никаких внешних API. Весь модуль офлайн.
Выход — JSON-сериализуемый список Event для передачи в LLM-промпт.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime
from typing import Any

# ─── Конфиг (расширяй руками) ─────────────────────────────────────────────────

TIER: dict[str, int] = {
    # T1 — первичные источники / надёжные данные
    "investing.com": 1, "theguardian.com": 1, "rbc.ru": 1, "KobeissiLetter": 1,
    # T2 — надёжные вторичные
    "WatcherGuru": 2, "AshCrypto": 2, "WallStreetMav": 2, "saylor": 2, "BoringBiz_": 2,
    # T3 — осторожно
    "X22Report": 3, "NiohBerg": 3, "ImBreckWorsham": 3, "SpencerHakimian": 3,
    "TheDailyShow": 3, "BRICSinfo": 3, "MrImranPk": 3, "ShaykhSulaiman": 3,
}

DEFAULT_TIER = 3
CLUSTER_WINDOW_H = 6
CLUSTER_THRESH = 0.3
PROMO_KEYWORDS = ["купить", "buy", "деньги на бит", "HODL", "стейблкоин"]

# ─── Типы ─────────────────────────────────────────────────────────────────────

Post  = dict[str, Any]   # src, text, ts, url
Event = dict[str, Any]   # cluster_id, size, t1_sources, flag, assets, facts,
                         # first_ts, lead_sec, post_type, posts

_FLAG_PRIORITY = {"CORROBORATED": 0, "SINGLE-SOURCE": 1, "UNVERIFIED": 2}
_TYPE_PRIORITY = {"price_data": 0, "news_claim": 1, "opinion": 2, "promo": 3}

# ─── tier ─────────────────────────────────────────────────────────────────────

def _norm_src(src: str) -> str:
    """Lower-case, срезать @, для доменов оставить host без www."""
    s = src.lower().lstrip("@")
    if "://" in s:
        s = s.split("://", 1)[1]
    if "." in s:
        s = s.split("/")[0]
        if s.startswith("www."):
            s = s[4:]
    return s

def tier(src: str) -> int:
    norm = _norm_src(src)
    for k, v in TIER.items():
        if _norm_src(k) == norm:
            return v
    return DEFAULT_TIER

# ─── signature ────────────────────────────────────────────────────────────────

_TICKER_RE  = re.compile(r'\$[A-Z]{1,5}\b')
_NUMBER_RE  = re.compile(r'\d[\d.,]*')

def signature(text: str) -> set[str]:
    """Инвариантные к переводу токены: тикеры ∪ числа.
    Кластеризовать ТОЛЬКО по этой сигнатуре, не по тексту.
    """
    return set(_TICKER_RE.findall(text)) | set(_NUMBER_RE.findall(text))

# ─── cluster (union-find) ─────────────────────────────────────────────────────

def cluster(posts: list[Post]) -> list[list[Post]]:
    """Склейка постов по Jaccard сигнатур + временное окно.

    Посты с пустой сигнатурой → каждый в свой синглтон (не сливать пустые).
    """
    n = len(posts)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]   # path compression
            i = parent[i]
        return i

    sigs = [signature(p["text"]) for p in posts]

    for i in range(n):
        for j in range(i + 1, n):
            if abs(posts[i]["ts"] - posts[j]["ts"]) > CLUSTER_WINDOW_H * 3600:
                continue
            a, b = sigs[i], sigs[j]
            if not a or not b:
                continue   # пустые не сливаем
            if len(a & b) / len(a | b) >= CLUSTER_THRESH:
                parent[find(i)] = find(j)

    groups: dict[int, list[Post]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(posts[i])
    return list(groups.values())

# ─── extract_facts ────────────────────────────────────────────────────────────

_SIGNED_NUM_RE = re.compile(r'([+-]?\d[\d.,]*)')
_UNIT_RE       = re.compile(r'(%|bps|pb|млрд|bn|trn|million|billion|\$|€|£|барр\.?)', re.I)
_NEAR_RE       = re.compile(
    r'\$[A-Z]{1,5}\b|WTI|Brent|BTC|ETH|S&P|NASDAQ|нефт[ьи]|gold|нефть|oil', re.I
)

def extract_facts(text: str) -> list[dict]:
    """Числа с привязанной единицей/тикером в окне ±20 символов.

    Это эвристика, не идеальный парсер. Цель — дать LLM числа, не интерпретировать.
    """
    facts = []
    for m in _SIGNED_NUM_RE.finditer(text):
        raw = m.group(1)
        try:
            value = float(raw.replace(",", "."))
        except ValueError:
            continue
        start = max(0, m.start() - 20)
        end   = min(len(text), m.end() + 20)
        window = text[start:end]

        unit_m = _UNIT_RE.search(window)
        near_m = _NEAR_RE.search(window)
        facts.append({
            "raw":   raw,
            "value": value,
            "unit":  unit_m.group(0) if unit_m else None,
            "near":  near_m.group(0) if near_m else None,
        })
    return facts

# ─── classify ─────────────────────────────────────────────────────────────────

def classify(post: Post) -> str:
    """Эвристика. Порядок проверок важен."""
    lc = post["text"].lower()

    if any(kw.lower() in lc for kw in PROMO_KEYWORDS):
        return "promo"

    t = tier(post["src"])
    has_numbers = bool(_NUMBER_RE.search(post["text"]))

    if has_numbers and t <= 2:
        return "price_data"
    if has_numbers and t == 3:
        return "news_claim"
    if t <= 2:
        return "news_claim"
    return "opinion"

# ─── rollup ───────────────────────────────────────────────────────────────────

def rollup(group: list[Post]) -> Event:
    """Собирает Event из кластера постов."""
    # assets — union тикеров, порядок первого появления
    seen_assets: set[str] = set()
    assets: list[str] = []
    for p in group:
        for t in _TICKER_RE.findall(p["text"]):
            if t not in seen_assets:
                seen_assets.add(t)
                assets.append(t)

    facts = [f for p in group for f in extract_facts(p["text"])]

    timestamps = [p["ts"] for p in group]
    first_ts = min(timestamps)
    lead_sec  = max(timestamps) - first_ts

    # t1_sources — различные T1-источники, не число постов
    t1_sources = len({p["src"] for p in group if tier(p["src"]) == 1})

    if t1_sources >= 2:
        flag = "CORROBORATED"
    elif t1_sources == 1:
        flag = "SINGLE-SOURCE"
    else:
        flag = "UNVERIFIED"

    # post_type — мода; при равенстве приоритет price_data > news_claim > opinion > promo
    types = [classify(p) for p in group]
    type_counts = Counter(types)
    post_type = min(
        type_counts,
        key=lambda t: (_TYPE_PRIORITY.get(t, 99), -type_counts[t])
    )

    # cluster_id — sha1 от отсортированной объединённой сигнатуры (первые 8 символов)
    combined_sig = sorted({tok for p in group for tok in signature(p["text"])})
    cluster_id = hashlib.sha1("|".join(combined_sig).encode()).hexdigest()[:8]

    return {
        "cluster_id": cluster_id,
        "size":       len(group),
        "t1_sources": t1_sources,
        "flag":       flag,
        "assets":     assets,
        "facts":      facts,
        "first_ts":   first_ts,
        "lead_sec":   lead_sec,
        "post_type":  post_type,
        "posts":      group,
    }

# ─── parse_feed ───────────────────────────────────────────────────────────────
# TODO: адаптировать под реальный формат (подтвердить у George: JSON / строки из
#       телеги / дамп БД). Сейчас парсит строки вида:
#   [6/17/26 6:39 AM] Markgandonbon: 💰 @KobeissiLetter … text … url

_LINE_RE   = re.compile(
    r'\[(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{1,2}:\d{2})\s*(AM|PM)?\]\s*\S+:\s*(.+)',
    re.S,
)
_URL_RE    = re.compile(r'https?://\S+')
_HANDLE_RE = re.compile(r'@([A-Za-z0-9_]{1,50})')
_DOMAIN_RE = re.compile(r'https?://(?:www\.)?([a-zA-Z0-9.-]+\.[a-z]{2,})')


def _parse_ts(date_s: str, time_s: str, ampm: str) -> int:
    try:
        mo, day, yr = map(int, date_s.split("/"))
        if yr < 100:
            yr += 2000
        h, m = map(int, time_s.split(":"))
        if ampm.upper() == "PM" and h != 12:
            h += 12
        elif ampm.upper() == "AM" and h == 12:
            h = 0
        return int(datetime(yr, mo, day, h, m).timestamp())
    except Exception:
        import time as _t
        return int(_t.time())


def _src_from(text: str, url: str) -> str:
    m = _HANDLE_RE.search(text)
    if m:
        return m.group(1)
    if url:
        dm = _DOMAIN_RE.match(url)
        if dm:
            return dm.group(1)
    return "unknown"


def parse_feed(raw: str) -> list[Post]:
    """Парсит строки Telegram-ленты в список Post."""
    posts: list[Post] = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        date_s, time_s, ampm, body = m.group(1), m.group(2), m.group(3) or "", m.group(4).strip()
        ts  = _parse_ts(date_s, time_s, ampm)
        url_m = _URL_RE.search(body)
        url = url_m.group(0) if url_m else ""
        text = body.replace(url, "").strip() if url else body
        src = _src_from(text, url)
        posts.append({"src": src, "text": text, "ts": ts, "url": url})
    return posts

# ─── run ──────────────────────────────────────────────────────────────────────

def run(raw_feed: str) -> list[Event]:
    """Полный пайплайн: parse → cluster → rollup → фильтр → сортировка."""
    posts  = parse_feed(raw_feed)
    groups = cluster(posts)

    events: list[Event] = []
    for group in groups:
        ev = rollup(group)
        # promo — выбросить
        if ev["post_type"] == "promo":
            continue
        # пустой синглтон-opinion без ассетов — выбросить
        if ev["size"] == 1 and ev["post_type"] == "opinion" and not ev["assets"]:
            continue
        events.append(ev)

    events.sort(key=lambda e: (_FLAG_PRIORITY.get(e["flag"], 99), e["first_ts"]))
    return events


if __name__ == "__main__":
    import json, sys
    for ev in run(sys.stdin.read()):
        # posts убираем из stdout для читаемости
        out = {k: v for k, v in ev.items() if k != "posts"}
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
