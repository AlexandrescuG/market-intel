"""channel_agent/facts.py — поводы для постов и факт-пакеты к ним.

ЗДЕСЬ НЕТ НИ ОДНОГО СЛОВА ДЛЯ ЧИТАТЕЛЯ. Модуль отвечает только на два
вопроса: есть ли сейчас повод для поста и какие числа к нему относятся. Текст
пишет модель (compose.py) строго по этому пакету — так число в посте всегда
имеет источник, а не появляется из головы.

Каждый сборщик возвращает список кандидатов:
    {"rubric": ..., "dedup_key": ..., "facts": {...}}
dedup_key защищает от повторов: всплеск по COPPER держится часами, а
генератор ходит по таймеру.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent.parent
BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
SIGNALS_DB = BASE / "data" / "signals.db"
QUOTES_JSON = BASE / "web" / "data" / "quotes.json"
LOCAL_TZ = "Europe/Chisinau"

log = logging.getLogger("channel_agent.facts")

# Сколько прошлых случаев минимум, чтобы вообще говорить «обычно бывало».
# Ниже пяти это не статистика, а анекдот, и в посте ей не место.
MIN_CASES = 5
# Всплеск упоминаний: и во сколько раз выше базовой линии, и сколько
# упоминаний в абсолюте. Только отношение пропускает шум вида «было 0,2 стало
# 3» — формально ×15, по существу ничего.
PULSE_MIN_SCORE = 4.0
PULSE_MIN_MENTIONS = 8

# Тикеры-омонимы: слова, которые ловят пол-ленты, если искать их как обычный
# текст. Тот же список правил, что в news_burst_job (см. память проекта о
# ложных срабатываниях: COST ловил «ETFs Cost You Thousands»).
_STOP_SYMBOLS = {
    "TOTAL", "TARGET", "VISA", "META", "COST", "ALL", "ON", "IT",
    # 09.09: пойманы на первом же живом прогоне. INTEL набирал ×92 нормы на
    # подстроке «intel» внутри «intelligence» — все заголовки были про
    # разведку. Это дефект самого счётчика (матчинг по подстроке), и чинить
    # его надо в pulse-конвейере; здесь — заглушка, чтобы агент не тратил
    # вызов модели на заведомо ложный повод.
    "INTEL", "AMD", "ARM", "NOW", "OPEN", "KEY", "REAL", "GOOD",
}


def _ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    return con


def _quotes() -> dict:
    try:
        return (json.loads(QUOTES_JSON.read_text(encoding="utf-8")) or {}).get("quotes") or {}
    except (OSError, json.JSONDecodeError) as e:
        log.warning("котировки не прочитаны: %s", e)
        return {}


# Соответствие наших тикеров ключам quotes.json. Нужен только для рубрик, где
# рядом с темой уместна цена; отсутствие ключа не повод отменять пост.
_QUOTE_KEYS = {
    "GOLD": "GC=F", "SILVER": "SI=F", "WTI": "CL=F", "NG": "NG=F",
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "DXY": "DX-Y.NYB",
    "SPX": "^GSPC", "NASDAQ": "^NDX", "DJI": "^DJI", "VIX": "^VIX",
    "BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD",
    "COPPER": "HG=F",
}


def _quote_for(symbol: str) -> dict | None:
    q = _quotes()
    key = _QUOTE_KEYS.get(symbol.upper().lstrip("#"))
    if key and key in q:
        return {"symbol": symbol, "price": q[key].get("price"),
                "chg_pct": q[key].get("change_pct")}
    return None


def _local_hhmm(ts_utc: str | None) -> str:
    if not ts_utc:
        return "--:--"
    try:
        dt = datetime.fromisoformat(ts_utc.replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo(LOCAL_TZ)).strftime("%H:%M")
    except ValueError:
        return "--:--"


# ─────────────────────────── 1. Что обычно бывало ───────────────────────────

def before_event(now_ts: int | None = None, horizon_hours: int = 6) -> list[dict]:
    """Событие календаря на подходе — и как рынок ходил на прошлых выпусках.

    Рубрика, которую переклейка чужой ленты дать не может в принципе: цифры
    считаны по нашим M30-барам, с нормировкой на типичный ход того же часа
    суток (38 пунктов в 15:30 и в 03:00 — разные события).
    """
    import sys
    sys.path.insert(0, str(BASE))
    from core.calendar_api import query_events
    from core.event_types import normalize_event_type

    now = int(now_ts or time.time())
    now_dt = datetime.fromtimestamp(now, timezone.utc)
    horizon = now_dt + timedelta(hours=horizon_hours)

    events = []
    for day in {now_dt.strftime("%Y-%m-%d"), horizon.strftime("%Y-%m-%d")}:
        events += query_events(date=day, limit=200)

    out = []
    con = _ro(BOT_DB)
    for e in sorted(events, key=lambda x: x.get("ts_utc") or ""):
        if e.get("impact") != "high":
            continue
        try:
            ts = datetime.fromisoformat((e.get("ts_utc") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        # Только то, что ещё впереди: «как ходило раньше» имеет смысл до
        # выхода цифры, а не после.
        if not (now_dt < ts <= horizon):
            continue

        etype = normalize_event_type(e.get("indicator") or e.get("title") or "")
        rows = con.execute(
            "SELECT symbol, n, median_move_30m, baseline_ratio_30m, volatile_share, "
            "period_from, period_to FROM event_reaction_stats "
            "WHERE event_type = ? AND n >= ? AND baseline_ratio_30m IS NOT NULL "
            "ORDER BY baseline_ratio_30m DESC LIMIT 5",
            (etype, MIN_CASES),
        ).fetchall()
        if len(rows) < 2:
            continue

        out.append({
            "rubric": "before_event",
            "dedup_key": f"before_event:{etype}:{ts:%Y-%m-%d}",
            "facts": {
                "event_title": e.get("title"),
                "event_type": etype,
                "country": e.get("country"),
                "at_local": _local_hhmm(e.get("ts_utc")),
                "forecast": e.get("forecast"),
                "previous": e.get("previous"),
                "reactions": [{
                    "symbol": r[0], "cases": r[1],
                    "median_move_points": round(r[2], 1) if r[2] is not None else None,
                    "times_normal": round(r[3], 2),
                    "volatile_share_pct": round((r[4] or 0) * 100),
                } for r in rows],
                "period": f"{rows[0][5]} — {rows[0][6]}",
            },
        })
    con.close()
    return out


# ──────────────────────── 2. О чём вдруг заговорили ─────────────────────────

def pulse_spike(now_ts: int | None = None, window_hours: int = 3) -> list[dict]:
    """Всплеск упоминаний инструмента против его собственной базовой линии."""
    now = int(now_ts or time.time())
    con = _ro(SIGNALS_DB)
    rows = con.execute(
        "SELECT symbol, category, max(mentions), max(baseline), max(score) "
        "FROM pulse_scores WHERE ts >= ? AND score >= ? AND mentions >= ? "
        "GROUP BY symbol ORDER BY max(score) DESC LIMIT 5",
        (now - window_hours * 3600, PULSE_MIN_SCORE, PULSE_MIN_MENTIONS),
    ).fetchall()

    out = []
    for symbol, category, mentions, baseline, score in rows:
        clean = (symbol or "").lstrip("#").upper()
        if not clean or clean in _STOP_SYMBOLS:
            continue
        # 🔴 Заголовки здесь ОБЯЗАТЕЛЬНЫ, и не для красоты. 09.09 первый же
        # прогон дал «#AMAZON ×104 нормы» — но всплеск оказался не про акции,
        # а про крушение грузового самолёта Amazon в Майами. Счётчик считает
        # упоминания слова, а не события про инструмент, и без темы пост
        # получился бы рыночным разбором авиакатастрофы. Тема уходит модели, и
        # промпт разрешает ей отказаться от поста.
        heads = con.execute(
            "SELECT s.title FROM news_instrument_tags t JOIN signals s ON s.uid = t.news_uid "
            "WHERE t.symbol = ? AND s.title != '' ORDER BY s.first_seen DESC LIMIT 4",
            (clean,),
        ).fetchall()
        if not heads:
            # Тега нет (в словаре 245 символов, всплеск бывает и по другим) —
            # ищем по тексту. Поиск по слову целиком, а не по подстроке
            # тикера: тикеры-омонимы ловят пол-ленты.
            heads = con.execute(
                "SELECT coalesce(nullif(title,''), substr(text,1,120)) FROM signals "
                "WHERE first_seen >= datetime('now','-12 hours') "
                "AND (title LIKE ? OR text LIKE ?) ORDER BY engagement DESC LIMIT 4",
                (f"%{clean.title()}%", f"%{clean.title()}%"),
            ).fetchall()
        out.append({
            "rubric": "pulse_spike",
            "dedup_key": f"pulse:{clean}:{datetime.fromtimestamp(now, timezone.utc):%Y-%m-%d}",
            "facts": {
                "symbol": clean,
                "category": category,
                "mentions_now": mentions,
                "baseline": round(baseline, 2) if baseline is not None else None,
                "times_normal": round(score, 1),
                "window_hours": window_hours,
                "headlines": [h[0] for h in heads],
                "quote": _quote_for(clean),
            },
        })
    con.close()
    return out


# ─────────────────────────── 3. Сюжет дня ───────────────────────────────────

def top_story(now_ts: int | None = None) -> list[dict]:
    """Главный сюжет по нашей кластеризации — с числом источников.

    Число независимых публикаторов здесь не украшение: сюжет попадает в пост
    по охвату, посчитанному кодом, а не по чьей-то оценке важности.

    🔴 09.09: сначала пересобираем кластеры. `publish_stories` убрали 02.09
    как «никем не читаемый», и вместе с ним перестал вызываться
    rebuild_stories — таблица замерла на 2 сентября. Тогда это было верно:
    потребителя не было. Теперь он есть — эта рубрика.
    """
    try:
        import sys
        sys.path.insert(0, str(BASE))
        from core.stories import rebuild_stories
        rebuild_stories(48)
    except Exception as e:
        # Кластеры не пересобрались — работаем на том, что уже лежит:
        # вчерашний сюжет хуже свежего, но лучше отсутствия рубрики.
        log.warning("сюжеты не пересобраны: %s", e)

    con = _ro(SIGNALS_DB)
    rows = con.execute(
        "SELECT id, title, summary, momentum, source_diversity, market_tickers, status "
        "FROM stories WHERE last_seen >= datetime('now','-1 day') "
        "AND source_diversity >= 2 ORDER BY momentum DESC, source_diversity DESC LIMIT 2"
    ).fetchall()
    out = []
    for sid, title, summary, momentum, diversity, tickers, status in rows:
        symbols = [t.strip() for t in (tickers or "").split(",") if t.strip()][:4]
        # title кластера — это набор ключевых слов («federal reserve · exchange
        # rate · interest rate»), а summary у большинства сюжетов пуст. Писать
        # по ним пост нельзя: получится текст про ключевые слова. Даём модели
        # сами заголовки, вошедшие в кластер, — суть она возьмёт оттуда.
        heads = con.execute(
            "SELECT coalesce(nullif(s.title,''), substr(s.text,1,140)) "
            "FROM story_signals ss JOIN signals s ON s.uid = ss.signal_uid "
            "WHERE ss.story_id = ? ORDER BY s.engagement DESC LIMIT 5",
            (sid,),
        ).fetchall()
        out.append({
            "rubric": "top_story",
            "dedup_key": f"story:{sid}",
            "facts": {
                "keywords": title,
                "headlines": [h[0] for h in heads if h[0]],
                "summary": summary,
                "publishers": diversity,
                "momentum": round(momentum, 2) if momentum is not None else None,
                "status": status,
                "quotes": [q for q in (_quote_for(s) for s in symbols) if q],
            },
        })
    con.close()
    return out


# ─────────────────────────── 4. Проверка слухов ─────────────────────────────

def rumor_check(now_ts: int | None = None, window_hours: int = 12) -> list[dict]:
    """Громкое утверждение из соцсетей + наша котировка того же инструмента.

    Смысл рубрики — не спор с автором, а сверка: в ленте пишут одно, в наших
    барах видно другое. Оба числа наши: engagement из signals, цена из
    quotes.json. Вывод делает модель, но выдумать ей нечего.
    """
    now = int(now_ts or time.time())
    since = datetime.fromtimestamp(now - window_hours * 3600, timezone.utc).isoformat()
    con = _ro(SIGNALS_DB)
    rows = con.execute(
        "SELECT s.uid, s.title, s.text, s.author, s.engagement, t.symbol "
        "FROM signals s JOIN news_instrument_tags t ON t.news_uid = s.uid "
        "WHERE s.source = 'twitter' AND s.first_seen >= ? AND s.engagement >= 500 "
        "ORDER BY s.engagement DESC LIMIT 12",
        (since,),
    ).fetchall()

    out, seen = [], set()
    for uid, title, text, author, engagement, symbol in rows:
        clean = (symbol or "").lstrip("#").upper()
        if clean in seen or clean in _STOP_SYMBOLS:
            continue
        quote = _quote_for(clean)
        if not quote or quote.get("chg_pct") is None:
            # Без своей котировки сверять нечего — это была бы просто цитата
            # из соцсетей, то есть ровно та переклейка, от которой уходим.
            continue
        seen.add(clean)
        out.append({
            "rubric": "rumor_check",
            "dedup_key": f"rumor:{uid}",
            "facts": {
                "symbol": clean,
                "claim_text": (title or text or "")[:400],
                "author": author,
                "engagement": engagement,
                "our_quote": quote,
                "window_hours": window_hours,
            },
        })
        if len(out) >= 2:
            break
    con.close()
    return out


ALL_RUBRICS = {
    "before_event": before_event,
    "pulse_spike": pulse_spike,
    "top_story": top_story,
    "rumor_check": rumor_check,
}


def collect(rubrics: list[str] | None = None, now_ts: int | None = None) -> list[dict]:
    """Все поводы, какие есть прямо сейчас. Пустой список — штатный ответ:
    нет повода — нет поста."""
    out = []
    for name, fn in ALL_RUBRICS.items():
        if rubrics and name not in rubrics:
            continue
        try:
            out += fn(now_ts)
        except Exception as e:
            log.error("рубрика %s: сбор поводов упал: %s", name, e)
    return out
