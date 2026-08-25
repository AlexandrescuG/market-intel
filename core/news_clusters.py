"""core/news_clusters.py — новости, выбивающиеся из контекста (SPEC §3.1).

ЗАЧЕМ. Нынешний критерий ленты — «релевантно нашим инструментам»
(feed_filter.require_cashtag). Он по построению не пропустит важное вне
контекста: новость про биотех не совпадает ни с одним из 12 алиасов. Нужен
ВТОРОЙ критерий рядом, а не сдвиг порога у первого.

ПРИЗНАК СЧИТАЕМЫЙ, А НЕ ОЦЕНОЧНЫЙ. Тема, о которой за сутки написало N и
более РАЗНЫХ публикаторов, при этом ни один наш тикер в ней не упомянут.
Считаем по разным публикаторам (`topic_hint` в signals — реальное издание,
«Reuters», а не имя фида), а не по числу публикаций: иначе один многословный
фид даёт «всплеск» в одиночку. Замер 25.08: 902 свежих заголовка за сутки от
196 изданий, причём у FXStreet и Investing.com по сотне штук — то есть
считать публикации было бы прямо вредно.

ДВЕ СТУПЕНИ, ОТ ДЕШЁВОЙ К ДОРОГОЙ:

1. Связь через скринер. У подсистемы A есть аномальные инструменты С
   НАЗВАНИЯМИ КОМПАНИЙ. Ищем названия в заголовках суток: совпало — это и
   есть тема, и она сразу объяснена движением цены. Кейс Moderna закрывается
   здесь: рост в моменте + заголовки с названием компании.
2. Общие редкие токены — для тем без движения цены. Грубо, но для вопроса
   «о чём сегодня пишут все» достаточно; полноценную кластеризацию тут
   заводить незачем.

Время публикации берём из `raw.published`, а НЕ из `last_seen`: RSS-агрегаторы
отдают одни и те же топ-статьи много циклов подряд, и каждый upsert двигает
last_seen на «сейчас» независимо от возраста статьи. Та же ловушка уже
описана в news_digest_job.py::_recent_rss — здесь тот же приём, не второй.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.config import BASE_DIR
from core.feed_filter import mentions_known_instrument

log = logging.getLogger("news_clusters")

SIGNALS_DB = BASE_DIR / "data" / "signals.db"

MIN_PUBLISHERS = 5          # стартовое N, §3.1
_MIN_TOKEN_LEN = 4
_MIN_TOKEN_DOCS = 3         # реже — это не тема, а опечатка
_MAX_TOKEN_SHARE = 0.12     # чаще — это общее слово вроде "market", не тема
_OVERLAP_KILL = 0.7         # темы с таким пересечением заголовков — одна и та же

# Юридические хвосты в названиях компаний: "Moderna, Inc." -> "Moderna".
_LEGAL_TAIL = re.compile(
    r"[,\s]+(inc|corp|corporation|co|company|ltd|limited|plc|llc|lp|nv|n\.v|sa|s\.a"
    r"|ag|group|holdings?|holding|technologies|technology|therapeutics|pharmaceuticals"
    r"|international|industries|systems|solutions|enterprises)\.?$",
    re.IGNORECASE)

_WORD_RE = re.compile(r"[a-zа-яё][a-zа-яё\-']+", re.IGNORECASE)

# Не лингвистика, а список слов, которые в финансовых заголовках стоят всегда
# и темы не образуют. Пополняется по факту, как и словари в core/scoring.py.
_STOPWORDS = {
    "after", "again", "against", "amid", "among", "another", "about", "above",
    "back", "been", "before", "being", "best", "between", "billion", "both",
    "close", "could", "data", "down", "during", "each", "even", "every",
    "first", "from", "growth", "have", "here", "high", "higher", "hits",
    "into", "just", "know", "last", "less", "like", "long", "look", "loss",
    "losses", "lower", "made", "make", "market", "markets", "million", "more",
    "most", "much", "near", "need", "news", "next", "only", "open", "over",
    "part", "past", "plan", "plans", "price", "prices", "quarter", "rate",
    "rates", "report", "reports", "rise", "rises", "said", "says", "sees",
    "shares", "should", "since", "some", "stock", "stocks", "such", "than",
    "that", "their", "them", "there", "these", "they", "this", "those",
    "three", "through", "time", "today", "trade", "under", "used", "very",
    "week", "weekly", "were", "what", "when", "where", "which", "while",
    "will", "with", "within", "without", "would", "year", "years", "your",
    # Добавлено 25.08 по первому прогону на живых данных: эти слова дали
    # «темы» из ничего — gains/bank/hike/earnings стоят в финансовых
    # заголовках всегда и сюжета не образуют. Список и рассчитан на
    # пополнение по факту, как словари в core/scoring.py.
    "gains", "bank", "banks", "hike", "hikes", "earnings", "outlook",
    "deal", "deals", "fund", "funds", "chief", "boost", "boosts", "drop",
    "drops", "jump", "jumps", "slide", "surge", "surges", "talks", "sale",
    "sales", "shows", "start", "starts", "call", "calls", "move", "moves",
    "может", "после", "более", "будет", "может", "года", "году", "если",
    "этом", "また", "рынок", "рынка", "цена", "цены", "доля",
}


def recent_headlines(hours: int = 24, now_ts: float | None = None) -> list[dict]:
    """[{title, publisher, url, published_ts}] за окно."""
    now = now_ts or time.time()
    con = sqlite3.connect(str(SIGNALS_DB), timeout=10)
    con.execute("PRAGMA busy_timeout=10000")
    con.row_factory = sqlite3.Row
    # last_seen — только широкий SQL-предфильтр, чтобы не сканировать 96 тыс.
    # строк; настоящее время публикации ниже. Запас в 6 часов сверх окна: у
    # свежей статьи last_seen не может быть СТАРШЕ published.
    prefilter = (datetime.fromtimestamp(now, timezone.utc)
                 - timedelta(hours=hours + 6)).isoformat()
    rows = con.execute(
        "SELECT title, topic_hint, url, raw FROM signals "
        "WHERE source='rss' AND last_seen >= ? ORDER BY last_seen DESC",
        (prefilter,),
    ).fetchall()
    con.close()

    cutoff = now - hours * 3600
    out = []
    for r in rows:
        try:
            raw = json.loads(r["raw"] or "{}")
        except (json.JSONDecodeError, TypeError):
            raw = {}
        published = raw.get("published")
        if not published or published < cutoff:
            continue
        title = (r["title"] or "").strip()
        if not title:
            continue
        out.append({"title": title, "publisher": (r["topic_hint"] or "").strip() or "—",
                    "url": r["url"], "published_ts": published})
    return out


def core_name(company: str) -> str:
    """«Moderna, Inc.» -> «Moderna». Рекурсивно: «TOP Financial Group Limited»
    теряет и Limited, и Group."""
    name = (company or "").strip()
    for _ in range(4):
        stripped = _LEGAL_TAIL.sub("", name).strip(" ,.")
        if stripped == name:
            break
        name = stripped
    return name


def _name_hits(name: str, headlines: list[dict]) -> list[dict]:
    """Заголовки, где название встречается ЦЕЛЫМ словом.

    Короткие названия отбрасываем: тикер SA («Seabridge Gold») или TOP дали бы
    совпадение в половине заголовков рынка. Лучше пропустить связь, чем
    приписать движению чужую новость — придумывать причину нельзя.
    """
    core = core_name(name)
    if len(core) < 4:
        return []
    pat = re.compile(r"(?<![\w'])" + re.escape(core) + r"(?![\w'])", re.IGNORECASE)
    return [h for h in headlines if pat.search(h["title"])]


def best_headline(name: str, hits: list[dict]) -> dict:
    """Какой из заголовков показать как объяснение движения.

    🔴 Не «самый свежий». Первый прогон 25.08 на живых данных выбрал для NVDA
    заголовок «Bitcoin Beats Nvidia to Become Top-Performing Major Asset» — он
    про биткоин и компанию лишь упоминает. Подставить такое к скачку цены —
    это и есть «придумать причину», против чего спека предупреждает прямо.

    Порядок предпочтений:
      1. заголовок НЕ про другой наш инструмент (иначе он про него, не про нас);
      2. имя компании ближе к началу — признак того, что она подлежащее;
      3. при равенстве — свежее.
    """
    core = core_name(name).lower()

    def rank(h):
        title = h["title"]
        pos = title.lower().find(core)
        return (0 if mentions_known_instrument(title) is None else 1,
                pos if pos >= 0 else 999,
                -h["published_ts"])

    return min(hits, key=rank)


def link_outliers(bot_con: sqlite3.Connection, outlier_rows: list[dict],
                  headlines: list[dict], day: str, now_ts: int | None = None) -> int:
    """Ступень 1. Проставляет market_outliers.news_cluster_id. Возвращает
    число связанных инструментов."""
    now = int(now_ts or time.time())
    linked = 0
    for r in outlier_rows:
        if r.get("news_cluster_id"):
            continue
        hits = _name_hits(r.get("name") or "", headlines)
        if not hits:
            continue
        publishers = {h["publisher"] for h in hits}
        top = best_headline(r.get("name") or "", hits)
        cid = _upsert_cluster(
            bot_con, day=day, kind="company", key=r["symbol"],
            label=core_name(r.get("name") or r["symbol"]),
            publishers=len(publishers), items=len(hits),
            sample_title=top["title"], sample_url=top["url"],
            outlier_symbol=r["symbol"], now_ts=now)
        bot_con.execute("UPDATE market_outliers SET news_cluster_id=? WHERE id=?",
                        (cid, r["id"]))
        linked += 1
    bot_con.commit()
    return linked


def _tokens(title: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(title)
            if len(w) >= _MIN_TOKEN_LEN and w.lower() not in _STOPWORDS}


def topic_bursts(headlines: list[dict], min_publishers: int = MIN_PUBLISHERS) -> list[dict]:
    """Ступень 2: темы без движения цены. [{key, label, items, publishers, ...}].

    Только заголовки, где НЕ упомянут ни один наш инструмент: про них уже есть
    и лента, и блок движений — «выбивается из контекста» по определению про
    остальное.
    """
    pool = [h for h in headlines if not mentions_known_instrument(h["title"])]
    if not pool:
        return []

    by_token: dict[str, list[dict]] = {}
    for h in pool:
        for t in _tokens(h["title"]):
            by_token.setdefault(t, []).append(h)

    max_docs = max(_MIN_TOKEN_DOCS, int(len(pool) * _MAX_TOKEN_SHARE))
    cands = []
    for token, hits in by_token.items():
        if not (_MIN_TOKEN_DOCS <= len(hits) <= max_docs):
            continue
        publishers = {h["publisher"] for h in hits}
        if len(publishers) < min_publishers:
            continue
        top = best_headline(token, hits)
        cands.append({"key": token, "label": token, "items": len(hits),
                      "publishers": len(publishers), "sample_title": top["title"],
                      "sample_url": top["url"],
                      "_ids": {id(h) for h in hits}})

    # Один сюжет даёт несколько редких токенов сразу («moderna», «vaccine»).
    # Оставляем самый охватный, остальные с тем же набором заголовков гасим —
    # иначе одна тема займёт весь блок брифинга собой.
    cands.sort(key=lambda c: (c["publishers"], c["items"]), reverse=True)
    kept: list[dict] = []
    for c in cands:
        if any(len(c["_ids"] & k["_ids"]) / max(1, min(len(c["_ids"]), len(k["_ids"])))
               >= _OVERLAP_KILL for k in kept):
            continue
        kept.append(c)
    for c in kept:
        c.pop("_ids", None)
    return kept


def _upsert_cluster(con, *, day, kind, key, label, publishers, items,
                    sample_title, sample_url, outlier_symbol, now_ts) -> int:
    cur = con.execute("SELECT id FROM news_clusters WHERE day=? AND kind=? AND key=?",
                      (day, kind, key)).fetchone()
    if cur:
        con.execute(
            "UPDATE news_clusters SET publishers=?, items=?, sample_title=?, "
            "sample_url=?, outlier_symbol=? WHERE id=?",
            (publishers, items, sample_title, sample_url, outlier_symbol, cur[0]))
        return cur[0]
    cur = con.execute(
        "INSERT INTO news_clusters (created_ts, day, kind, key, label, publishers, "
        "items, sample_title, sample_url, outlier_symbol) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (now_ts, day, kind, key, label, publishers, items, sample_title,
         sample_url, outlier_symbol))
    return cur.lastrowid


def store_topics(bot_con: sqlite3.Connection, topics: list[dict], day: str,
                 now_ts: int | None = None) -> int:
    now = int(now_ts or time.time())
    for t in topics:
        _upsert_cluster(bot_con, day=day, kind="topic", key=t["key"], label=t["label"],
                        publishers=t["publishers"], items=t["items"],
                        sample_title=t["sample_title"], sample_url=t["sample_url"],
                        outlier_symbol=None, now_ts=now)
    bot_con.commit()
    return len(topics)
