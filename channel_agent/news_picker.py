"""channel_agent/news_picker.py — отбор новостей для канала из своих источников.

10.09.2026, разворот замысла. Первая версия агента писала посты из наших
измерений и обходила новости стороной — владелец: «то, что мы сейчас копируем,
такие новости и нужны, но нам нужна система, которая будет находить такие
новости». То есть цель не заменить ленту, а перестать зависеть от чужой:
находить те же события в своём потоке.

ЧТО ПОКАЗАЛА ПРОВЕРКА. Из шести свежих постов markettwits пять нашлись в наших
собственных источниках (rss/twitter) — не нашлась только новость про
российские маркетплейсы, и это ожидаемо, ленты у нас западные. Сырьё есть:
5241 сигнал в сутки. Не хватало отбора.

КАК ОТБИРАЕМ. У сигналов уже есть посчитанные `importance` и `econ_relevance`
(коллекторы), и верх этой шкалы — ровно тот класс событий, что публикует
markettwits: Brent выше $100, удары по танкерам, решение ЦБ по курсу. Дальше
три фильтра: темы-исключения (общий список с переклейкой — вкус владельца),
дубли одной новости из разных лент, и уже опубликованное.

ЧЕМ ЭТО ОТЛИЧАЕТСЯ ОТ РУБРИК В facts.py. Там нельзя было брать числа из чужих
заголовков — пост обязан был опираться на наши измерения. Здесь наоборот:
новость и есть содержание, пересказ — цель, а не грех. Поэтому пост обязан
нести ссылку на источник: читатель должен видеть, откуда факт.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SIGNALS_DB = BASE / "data" / "signals.db"
FILTERS_PATH = BASE / "core" / "topic_filters.json"

log = logging.getLogger("channel_agent.news_picker")

# Порог отбора. За сутки 0,6 и выше набирают ~360 сигналов при 5200 всего —
# это верхние 7%, и по составу они совпадают с тем, что публикует markettwits.
MIN_IMPORTANCE = 0.6
MIN_ECON = 0.5
# Окно поиска. Новость старше нескольких часов уже не новость.
WINDOW_MINUTES = 180

_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)
_STOP = {
    "который", "которые", "после", "перед", "около", "более", "менее", "может",
    "будет", "также", "этого", "этом", "может", "против", "своих", "года",
    "about", "after", "their", "there", "which", "would", "could", "these",
}


def _ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    return con


def _exclusions() -> list[str]:
    """Темы, которые в канал не идут. Список общий с переклейкой markettwits
    (Vorovka2), вынесен в JSON 10.09: два списка одного и того же неизбежно
    разошлись бы, а он выражает вкус владельца, не техническое правило."""
    try:
        data = json.loads(FILTERS_PATH.read_text(encoding="utf-8"))
        return [w.lower() for w in data.get("exclusions", []) if w.strip()]
    except (OSError, json.JSONDecodeError) as e:
        log.error("topic_filters.json не прочитан (%s) — фильтр тем отключён", e)
        return []


def _excluded(text: str, exclusions: list[str]) -> str | None:
    low = text.lower()
    for word in exclusions:
        if word in low:
            return word
    return None


def _tokens(text: str) -> set[str]:
    """Значимые слова для сравнения новостей между собой."""
    return {w for w in _WORD_RE.split((text or "").lower())
            if len(w) > 4 and w not in _STOP}


def _similar(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def candidates(now_ts: int | None = None, limit: int = 40,
               min_importance: float = MIN_IMPORTANCE) -> list[dict]:
    """Новости-кандидаты: свежие, важные, не из запрещённых тем, без дублей.

    Дубли схлопываются, а не отбрасываются: число независимых лент, написавших
    об одном и том же, — это и есть мера значимости события, и она уходит в
    факт-пакет.
    """
    now = int(now_ts or time.time())
    since = datetime.fromtimestamp(now - WINDOW_MINUTES * 60, timezone.utc).isoformat()
    con = _ro(SIGNALS_DB)
    # 🔴 10.09: выборка идёт КВОТАМИ по источникам, а не общим топом по
    # importance. Общий топ дал пять постов подряд из X — а там в верхах
    # сидят агрегаторы (@cryptorover, @EricLDaugh), которые сами пересказывают
    # чужое и ошибаются. Новостная лента (rss) — это Reuters, CNBC, РБК: у
    # них есть редактура. Берём половину оттуда, половину из X, где быстрее
    # появляется срочное.
    sql = ("SELECT uid, source, author, coalesce(nullif(title,''), '') AS title, "
           "text, url, importance, econ_relevance, engagement, first_seen "
           "FROM signals WHERE first_seen >= ? AND importance >= ? AND econ_relevance >= ? "
           "AND source = ? ORDER BY importance DESC, econ_relevance DESC LIMIT 200")
    rows = (con.execute(sql, (since, min_importance, MIN_ECON, "rss")).fetchall()
            + con.execute(sql, (since, min_importance, MIN_ECON, "twitter")).fetchall())
    # Обратно в общий порядок по важности: квота решает, кого вообще брать,
    # а не кто окажется первым в ленте.
    rows.sort(key=lambda r: (r[6] or 0, r[7] or 0), reverse=True)
    con.close()

    exclusions = _exclusions()
    groups: list[dict] = []
    for uid, source, author, title, text, url, imp, econ, eng, seen in rows:
        body = (title or text or "").strip()
        if len(body) < 30:
            continue
        hit = _excluded(f"{title} {text}", exclusions)
        if hit:
            continue
        toks = _tokens(body)

        # Та же новость из другой ленты — добавляем к группе, а не заводим
        # второй пост. Порог 0,5 подобран на живых заголовках: ниже начинают
        # слипаться разные события одной темы.
        placed = False
        for g in groups:
            if _similar(toks, g["_tokens"]) >= 0.5:
                g["sources"].append({"source": source, "author": author, "url": url})
                g["_tokens"] |= toks
                placed = True
                break
        if placed:
            continue

        # Квота на источник внутри выдачи: без неё после сортировки по
        # важности снова получился бы список из одного X.
        if sum(1 for g in groups if g["source"] == source) >= max(2, limit // 2):
            continue

        groups.append({
            "uid": uid,
            "source": source,
            "title": title,
            "text": (text or "")[:900],
            "url": url,
            "importance": round(imp or 0, 2),
            "econ_relevance": round(econ or 0, 2),
            "engagement": eng or 0,
            "first_seen": seen,
            "sources": [{"source": source, "author": author, "url": url}],
            "_tokens": toks,
        })
        if len(groups) >= limit:
            break

    out = []
    for g in groups:
        g.pop("_tokens", None)
        g["publishers"] = len({s["author"] for s in g["sources"] if s["author"]}) or 1
        out.append({
            "rubric": "news",
            # Ключ по uid исходного сигнала: одна новость — один пост, даже
            # если её подхватят другие ленты через час.
            "dedup_key": f"news:{g['uid']}",
            "facts": g,
        })
    return out
