#!/usr/bin/env python3
"""Разовая чистка: снять теги инструментов с заметок об отчётности фондов.

Сборщик их больше не тегирует (news_burst_job), но в базе остались связи,
проставленные раньше. Они держат две вещи:
  • ленту по активу — десяток карточек «X LLC Sells N Shares of Tesla»;
  • счётчик упоминаний Эпицентра — десять подач формы выглядят всплеском
    внимания к компании.

Удаляются ТОЛЬКО связи новость↔инструмент. Сами новости остаются в signals:
выкидывать собранное незачем, а если правило окажется слишком широким,
восстановить теги можно повторным прогоном тегирования.

Порциями и с commit между ними: по этой базе одновременно работают
коллекторы, один большой DELETE получает «database is locked».
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import news_junk  # noqa: E402
from core.config import DB_PATH  # noqa: E402

con = sqlite3.connect(str(DB_PATH), timeout=60)
con.execute("PRAGMA busy_timeout=60000")

rows = con.execute(
    """SELECT DISTINCT s.uid, s.title FROM news_instrument_tags t
       JOIN signals s ON s.uid = t.news_uid WHERE s.title <> ''""").fetchall()
мусор = [uid for uid, title in rows if news_junk.is_filing_note(title)]
print(f"новостей с тегами: {len(rows)}, из них заметок об отчётности: {len(мусор)}")

снято = 0
for i in range(0, len(мусор), 400):
    порция = мусор[i:i + 400]
    q = ",".join("?" * len(порция))
    cur = con.execute(f"DELETE FROM news_instrument_tags WHERE news_uid IN ({q})", порция)
    con.commit()
    снято += cur.rowcount
print(f"снято связей новость↔инструмент: {снято}")
con.close()
