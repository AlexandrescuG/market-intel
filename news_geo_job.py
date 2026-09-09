#!/usr/bin/env python3
"""news_geo_job.py — где на карте место этой новости.

ЗАЧЕМ. На sbfconsult.com первый экран — карта, а раздел контактов — глобус.
На обоих должна идти живая лента рынка, и точка на карте это утверждение
«вот здесь это произошло». У события календаря страна есть в данных, у
новости не было ничего: сайт ставил тикеры на первые свободные города, и
Amazon оказывался в Гонконге, Intel во Франкфурте, а биткоин в Дубае.

🔴 ГЛАВНОЕ ПРАВИЛО: ложная точка хуже отсутствующей. Пропущенная новость —
это на одну отметку меньше. Ложная — публичное утверждение, что событие
произошло не там, где произошло, и проверяется оно одним взглядом. Поэтому
привязка ставится только когда для неё есть основание, а «не знаю» —
нормальный и частый ответ.

ЧЕТЫРЕ ИСТОЧНИКА, В ПОРЯДКЕ УБЫВАНИЯ ДОСТОВЕРНОСТИ:

  event    — новость привязана к событию макро-календаря, у события есть
             страна. Это факт из данных, а не догадка.
  headline — страна названа в ЗАГОЛОВКЕ. Заголовок говорит, о чём новость;
             в теле страна попадается вскользь («спрос из Китая» в статье про
             медь не делает новость китайской), поэтому тело не смотрим.
  symbol   — страна инструмента: валютная пара, индекс, акция с известной
             биржей. Слабее заголовка, но защитимо.
  —        — не ставим ничего. У крипты и золота страны нет по природе.

Запуск:  python3 news_geo_job.py [--verbose] [--hours 48]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from core import news_patterns  # noqa: E402

SIGNALS_DB = ROOT / "data" / "signals.db"
BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
PLACES = ROOT / "data" / "geo_places.json"
CATALOG = ROOT / "web" / "data" / "broker_catalog.json"

# Инструменты без собственной географии. Точка для биткоина будет выдумкой в
# любом месте, куда её ни поставь, поэтому по символу их не размещаем — только
# если страна названа в самом заголовке («SEC одобрила ETF» → US).
NO_GEO_CATEGORIES = {"crypto", "commodity"}

DEFAULT_HOURS = 48


def load_places() -> tuple[dict, re.Pattern | None]:
    raw = json.loads(PLACES.read_text(encoding="utf-8"))
    excl = raw.get("_исключения", {}).get("pattern")
    places = {}
    for code, meta in raw.items():
        if code.startswith("_") or not isinstance(meta, dict):
            continue
        try:
            places[code] = {
                "lon": float(meta["lon"]), "lat": float(meta["lat"]),
                "city": meta.get("город", code),
                "re": re.compile(meta["pattern"], re.I),
            }
        except (KeyError, ValueError, re.error) as e:
            print(f"место {code} пропущено: {e}", file=sys.stderr)
    return places, (re.compile(excl, re.I) if excl else None)


def load_symbol_countries() -> dict:
    """{символ: [страны]} из каталога — та же логика, что у слоя событий."""
    from build_event_map import countries_for
    raw = json.loads(CATALOG.read_text(encoding="utf-8"))
    items = raw.get("items", raw) if isinstance(raw, dict) else raw
    out = {}
    for it in items:
        if it.get("category") in NO_GEO_CATEGORIES:
            continue
        cs = countries_for(it["symbol"], it.get("category"), it.get("name"))
        # Страна-затычка US стоит у всего неопознанного — для карты это
        # означало бы пол-ленты в Нью-Йорке. Берём её только там, где США
        # действительно определены формой имени: решётка = листинг в США.
        if cs == ["US"] and not it["symbol"].startswith("#"):
            continue
        if not cs:
            continue
        out[it["symbol"]] = cs
        if it.get("canonical"):
            out.setdefault(it["canonical"], cs)
    return out


def ensure_schema(con) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS news_geo(
            news_uid TEXT PRIMARY KEY,
            country  TEXT NOT NULL,
            lon      REAL NOT NULL,
            lat      REAL NOT NULL,
            rule     TEXT NOT NULL,
            ts       INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_news_geo_ts ON news_geo(ts DESC);
    """)
    con.commit()


def _event_countries(bot_con, hours: int) -> dict:
    """{ключ события: страна} — для новостей, привязанных к календарю.

    Привязка новость↔событие в базе не хранится, поэтому сопоставляем по
    названию индикатора в заголовке. Работает только для явных совпадений и
    именно поэтому даёт самый достоверный ярус: если в заголовке дословно
    стоит название показателя, страна события — это факт, а не догадка.
    """
    rows = bot_con.execute(
        "SELECT DISTINCT indicator, country FROM econ_events "
        "WHERE scheduled_ts > strftime('%s','now', ?) AND indicator IS NOT NULL "
        "AND length(indicator) >= 8",
        (f"-{hours} hours",)).fetchall()
    out = {}
    for indicator, country in rows:
        if country:
            out.setdefault(indicator.strip().lower(), country)
    return out


def run(hours: int = DEFAULT_HOURS, verbose: bool = False) -> int:
    places, excl = load_places()
    sym_countries = load_symbol_countries()

    con = sqlite3.connect(str(SIGNALS_DB), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    ensure_schema(con)

    bot = sqlite3.connect(f"file:{BOT_DB}?mode=ro", uri=True, timeout=30)
    bot.execute("PRAGMA busy_timeout=30000")
    events = _event_countries(bot, hours)
    bot.close()

    rows = con.execute(
        "SELECT uid, title, text FROM signals "
        "WHERE last_seen >= datetime('now', ?) ", (f"-{hours} hours",)).fetchall()

    tags = {}
    for uid, sym in con.execute(
            "SELECT t.news_uid, t.symbol FROM news_instrument_tags t "
            "JOIN signals s ON s.uid = t.news_uid "
            "WHERE s.last_seen >= datetime('now', ?)", (f"-{hours} hours",)):
        tags.setdefault(uid, []).append(sym)

    now = int(time.time())
    stats = {"event": 0, "headline": 0, "symbol": 0, "нет": 0}
    written = 0
    for uid, title, text in rows:
        title = (title or "").strip()
        country = rule = None

        # 1. Событие календаря, названное в заголовке дословно.
        low = title.lower()
        for indicator, c in events.items():
            if indicator in low:
                country, rule = c, "event"
                break

        # 2. Место, названное в заголовке.
        if not country:
            clean = news_patterns.searchable(title, None)
            if not (excl and excl.search(clean)):
                for code, p in places.items():
                    if p["re"].search(clean):
                        country, rule = code, "headline"
                        break

        # 3. Страна инструмента.
        if not country:
            for sym in tags.get(uid, []):
                cs = sym_countries.get(sym)
                if cs:
                    country, rule = cs[0], "symbol"
                    break

        if not country or country not in places:
            stats["нет"] += 1
            continue
        p = places[country]
        con.execute(
            "INSERT OR REPLACE INTO news_geo(news_uid, country, lon, lat, rule, ts) "
            "VALUES(?,?,?,?,?,?)", (uid, country, p["lon"], p["lat"], rule, now))
        stats[rule] += 1
        written += 1

    # Чистим привязки к новостям, которых уже нет: news_geo ссылается на uid, а
    # сами новости удаляются по сроку хранения (news_burst_job._retention).
    con.execute("DELETE FROM news_geo WHERE news_uid NOT IN (SELECT uid FROM signals)")
    con.commit()
    con.close()

    if verbose:
        total = sum(stats.values())
        print(f"новостей за {hours} ч: {total}")
        for k in ("event", "headline", "symbol", "нет"):
            share = stats[k] / total * 100 if total else 0
            print(f"  {k:9s} {stats[k]:5d}  {share:4.0f}%")
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=DEFAULT_HOURS)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    raise SystemExit(0 if run(a.hours, a.verbose) >= 0 else 1)
