#!/usr/bin/env python3
"""watchlist_news_job.py — что нового по инструментам, отмеченным звездой.

ЗАЧЕМ. Звезда в списке инструментов теперь привязана к аккаунту, новости
привязаны к инструментам — осталось соединить одно с другим и сказать человеку:
«по вашим инструментам вышло вот это».

ЧТО ДЕЛАЕТ. Раз в несколько минут смотрит, какие новости появились по
инструментам из ватчлистов, и складывает их в таблицу `watchlist_feed` в
journal.db. Сайт читает её через /api/user/watchlist-news и показывает.

🔴 ПОЧЕМУ НЕ ПИСЬМО И НЕ TELEGRAM — СОЗНАТЕЛЬНО.
Почты у market_intel нет вовсе (SMTP настроен в другом проекте), а связи
«аккаунт на сайте ↔ чат в Telegram» не существует: её пришлось бы строить с
кодами привязки и обработчиком в боте. Делать это до того, как понятно, что
лента вообще полезна, — значит потратить день на доставку того, что, может
быть, никому не нужно.
Поэтому первый шаг — лента на сайте: она работает сразу, ничего не требует от
владельца и показывает, есть ли смысл в рассылке. Появится смысл — доставка
добавляется поверх готовой таблицы, не переделывая ничего.

ЧЕГО НЕ ДЕЛАЕТ. Не шлёт ничего наружу и не хранит новость повторно: в таблице
только ссылка на уже существующий сигнал.

Запуск:  python3 watchlist_news_job.py [--verbose]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

JOURNAL_DB = ROOT / "data" / "journal.db"
SIGNALS_DB = ROOT / "data" / "signals.db"

# Насколько назад смотрим при каждом проходе. Шире такта таймера с запасом:
# пропущенный из-за перезагрузки прогон не должен оставлять дыру в ленте.
LOOKBACK_SEC = 3 * 3600
# Сколько новостей на инструмент за проход. Без предела один шумный день по
# золоту забил бы ленту так, что своих инструментов человек бы не нашёл.
PER_SYMBOL_LIMIT = 5


def ensure_schema(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS watchlist_feed(
            user_id   TEXT NOT NULL,
            symbol    TEXT NOT NULL,
            news_uid  TEXT NOT NULL,
            title     TEXT,
            url       TEXT,
            source    TEXT,
            ts        INTEGER NOT NULL,
            seen      INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, news_uid, symbol)
        )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_wf_user_ts ON watchlist_feed(user_id, ts DESC)")
    con.commit()


def _published_ts(raw: str | None, first_seen: str | None) -> int:
    try:
        v = json.loads(raw or "{}").get("published")
        if v:
            return int(float(v))
    except Exception:
        pass
    try:
        return int(datetime.fromisoformat(first_seen).timestamp())
    except Exception:
        return 0


def run(verbose: bool = False) -> int:
    jcon = sqlite3.connect(str(JOURNAL_DB))
    ensure_schema(jcon)

    watch = jcon.execute(
        "SELECT user_id, symbol FROM watchlist "
        "WHERE symbol IS NOT NULL AND symbol <> ''").fetchall()
    if not watch:
        if verbose:
            print("ватчлисты пусты — ничего не делаем")
        jcon.close()
        return 0

    by_symbol: dict[str, list[str]] = {}
    for user_id, symbol in watch:
        by_symbol.setdefault(symbol.upper(), []).append(user_id)

    scon = sqlite3.connect(f"file:{SIGNALS_DB}?mode=ro", uri=True)
    scon.row_factory = sqlite3.Row
    since = int(time.time()) - LOOKBACK_SEC

    added = 0
    for symbol, users in by_symbol.items():
        rows = scon.execute(
            """SELECT s.uid, s.title, s.text, s.url, s.source, s.raw, s.first_seen
               FROM news_instrument_tags t JOIN signals s ON s.uid = t.news_uid
               WHERE t.symbol = ?
               ORDER BY s.first_seen DESC LIMIT 60""",
            (symbol,)).fetchall()
        fresh = []
        for r in rows:
            # 🔴 «Новое» считается по моменту, когда МЫ узнали о новости, а не по
            # дате публикации. Замер: заметка вышла 13 часов назад, а в нашу
            # базу попала 48 минут назад — по дате публикации она бы никогда не
            # попала в ленту, хотя для читателя она новая. Показываем при этом
            # дату публикации: подменять её временем нашего сбора значило бы
            # выдавать вчерашнее за сегодняшнее.
            try:
                seen_ts = int(datetime.fromisoformat(r["first_seen"]).timestamp())
            except Exception:
                seen_ts = 0
            ts = _published_ts(r["raw"], r["first_seen"])
            if seen_ts >= since:
                # У твитов заголовка нет, текст лежит в text — берём то, что
                # есть, иначе в ленте окажется строка без единого слова.
                title = (r["title"] or "").strip() or (r["text"] or "").strip()[:200]
                if title:
                    fresh.append((r["uid"], title, r["url"], r["source"], ts))
        for uid, title, url, source, ts in fresh[:PER_SYMBOL_LIMIT]:
            for user_id in users:
                cur = jcon.execute(
                    "INSERT OR IGNORE INTO watchlist_feed"
                    "(user_id, symbol, news_uid, title, url, source, ts) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (user_id, symbol, uid, title, url, source, ts))
                added += cur.rowcount
    jcon.commit()

    # Чистим старое: лента — это «что нового», а не архив. Архив у нас уже есть
    # в signals.db, дублировать его здесь незачем.
    jcon.execute("DELETE FROM watchlist_feed WHERE ts < ?", (int(time.time()) - 14 * 86400,))
    jcon.commit()

    if verbose:
        total, = jcon.execute("SELECT COUNT(*) FROM watchlist_feed").fetchone()
        print(f"инструментов в ватчлистах: {len(by_symbol)}, добавлено записей: {added}, "
              f"всего в ленте: {total}")
    jcon.close()
    scon.close()
    return added


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    raise SystemExit(0 if run(a.verbose) >= 0 else 1)
