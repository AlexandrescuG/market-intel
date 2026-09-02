#!/usr/bin/env python3
"""watchlist_news_job.py — что нового по инструментам, отмеченным звездой.

ЗАЧЕМ. Звезда в списке инструментов теперь привязана к аккаунту, новости
привязаны к инструментам — осталось соединить одно с другим и сказать человеку:
«по вашим инструментам вышло вот это».

ЧТО ДЕЛАЕТ. Раз в несколько минут смотрит, какие новости появились по
инструментам из ватчлистов, и складывает их в таблицу `watchlist_feed` в
journal.db. Сайт читает её через /api/user/watchlist-news и показывает.

ДОСТАВКА. Кому привязан Telegram — уходит одним сообщением от @SBFAcademy_bot
(именно от него: Telegram разрешает писать только тем, кто сам начал диалог с
этим ботом, а вход на платформу идёт через SBFAcademy). Привязку ищем по цепочке
users.sbfacademy_user_id → auth_identities(provider='telegram'). Кто входил через
почту или Google, телеграм-адреса не имеет — для него остаётся лента на сайте, и
это нормальный исход, а не ошибка.

ЧЕГО НЕ ДЕЛАЕТ. Не хранит новость повторно: в таблице только заголовок и ссылка
на уже существующий сигнал. Не пишет ночью (тихие часы) и не шлёт по сообщению
на каждую заметку — всё за проход собирается в один список.

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
# Сколько заголовков помещаем в одно сообщение. Больше десяти — простыня,
# которую не читают; остальное считаем и зовём на сайт.
MAX_PER_MESSAGE = 10
# Тихие часы по местному времени: ночью не пишем, накопленное уйдёт утром.
QUIET_UNTIL_HOUR = 8
QUIET_FROM_HOUR = 23


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


def deliver_telegram(jcon: sqlite3.Connection, verbose: bool = False) -> int:
    """Разослать непрочитанное тем, у кого привязан Telegram.

    🔴 Одно письмо на человека за проход, а не сообщение на каждую новость.
    По золоту в шумный день выходит два десятка заметок; двадцать уведомлений
    подряд — это не забота, а повод отписаться. Собираем в один список.

    Отправленное сразу помечаем прочитанным: иначе следующий проход пришлёт то
    же самое, и лента на сайте будет вечно показывать непрочитанное, которое
    человек уже видел в телеграме.

    Тихие часы соблюдаем: ночью не пишем вовсе, накопленное уйдёт утром.
    """
    from core import tg_notify

    hour = datetime.now().hour
    if hour < QUIET_UNTIL_HOUR or hour >= QUIET_FROM_HOUR:
        if verbose:
            print(f"тихие часы ({hour}:00) — рассылку не делаем")
        return 0

    users = jcon.execute(
        "SELECT DISTINCT f.user_id, u.sbfacademy_user_id FROM watchlist_feed f "
        "JOIN users u ON u.id = f.user_id WHERE f.seen = 0").fetchall()
    sent_total = 0
    for user_id, sbf_uid in users:
        chat_id = tg_notify.chat_id_for(sbf_uid)
        if not chat_id:
            continue  # Telegram не привязан — это нормальный исход, не ошибка
        rows = jcon.execute(
            "SELECT symbol, title, url FROM watchlist_feed "
            "WHERE user_id = ? AND seen = 0 ORDER BY ts DESC LIMIT ?",
            (user_id, MAX_PER_MESSAGE)).fetchall()
        if not rows:
            continue
        lines = ["<b>Новое по вашим инструментам</b>", ""]
        for symbol, title, url in rows:
            title = (title or "").strip()
            if len(title) > 150:
                title = title[:147] + "…"
            safe = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            lines.append(f"<b>{symbol}</b> — " + (f'<a href="{url}">{safe}</a>' if url else safe))
        left = jcon.execute(
            "SELECT COUNT(*) FROM watchlist_feed WHERE user_id=? AND seen=0",
            (user_id,)).fetchone()[0] - len(rows)
        if left > 0:
            lines.append(f"\n…и ещё {left} — на lp.sbfconsult.com")
        if tg_notify.send(chat_id, "\n".join(lines)):
            jcon.execute("UPDATE watchlist_feed SET seen=1 WHERE user_id=? AND seen=0",
                         (user_id,))
            sent_total += 1
        # Не отправилось — seen не трогаем: попробуем в следующий проход.
    jcon.commit()
    if verbose:
        print(f"уведомлений отправлено: {sent_total} (кандидатов: {len(users)})")
    return sent_total


def run(verbose: bool = False) -> int:
    jcon = sqlite3.connect(str(JOURNAL_DB))
    jcon.execute("PRAGMA busy_timeout=60000")
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

    deliver_telegram(jcon, verbose)

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
