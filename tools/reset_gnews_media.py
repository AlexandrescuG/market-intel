#!/usr/bin/env python3
"""Разовый сброс: дать задаче превью ещё раз взяться за ссылки Google News.

10.09 домен news.google.com был в списке пропускаемых, и задача помечала
такие новости как «проверено, попыток 3» БЕЗ единого похода наружу. После
того как ссылки научились разворачиваться (core/gnews_resolve.py), эти
отметки держат задачу: кандидатов не остаётся, потому что все давно
«проверены».

Скрипт снимает отметки ровно с тех записей, где:
  • ссылка ведёт на news.google.com,
  • картинки так и нет (url и path пусты).

Записи с найденным превью не трогаются: перепроверять то, что работает,
незачем. Идемпотентно.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.config import DB_PATH  # noqa: E402

con = sqlite3.connect(str(DB_PATH), timeout=60)
con.execute("PRAGMA busy_timeout=60000")

# 🔴 Порциями, а не одним DELETE. По этой базе одновременно работают
# коллекторы и джобы; один большой запрос с подзапросом по джойну держит
# блокировку достаточно долго, чтобы получить «database is locked» — что и
# случилось при первом прогоне. Порция в пятьсот строк с отдельным commit
# отдаёт базу другим между шагами.
снято = 0
while True:
    uids = [r[0] for r in con.execute(
        """SELECT m.news_uid FROM news_media m JOIN signals s ON s.uid = m.news_uid
           WHERE s.url LIKE '%news.google.com%'
             AND m.url IS NULL AND m.path IS NULL LIMIT 500""").fetchall()]
    if not uids:
        break
    q = ",".join("?" * len(uids))
    con.execute(f"DELETE FROM news_media WHERE news_uid IN ({q})", uids)
    con.commit()
    снято += len(uids)
    print(f"  снято {снято}…", flush=True)
print(f"снято отметок: {снято}")
осталось = con.execute(
    """SELECT COUNT(DISTINCT s.uid) FROM news_instrument_tags t
       JOIN signals s ON s.uid=t.news_uid LEFT JOIN news_media m ON m.news_uid=s.uid
       WHERE s.first_seen >= datetime('now','-3 days') AND s.url<>''
         AND (m.news_uid IS NULL OR (m.url IS NULL AND m.path IS NULL
                                     AND m.attempts < 3))""").fetchone()[0]
print(f"кандидатов для задачи превью теперь: {осталось}")
con.close()
