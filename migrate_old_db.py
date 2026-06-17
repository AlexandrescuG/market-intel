#!/usr/bin/env python3
"""Перенос истории из старой threads.db в новую signals.db (со скорингом).

  python3 migrate_old_db.py /path/to/old/threads.db
"""
import sqlite3
import sys

from core import db


def migrate(old_path: str) -> None:
    db.init_db()
    old = sqlite3.connect(old_path)
    rows = old.execute(
        "SELECT tweet_id, author, text, url, likes, retweets, replies, "
        "first_seen FROM tweets"
    ).fetchall()
    n = 0
    for tid, author, text, url, likes, rt, replies, _seen in rows:
        db.upsert(
            source="twitter", source_id=tid, author=author or "",
            text=text or "", url=url or "",
            engagement=(likes or 0) + (rt or 0), replies=replies or 0,
            topic_hint="migrated",
        )
        n += 1
    old.close()
    print(f"Перенесено {n} записей в signals.db")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 migrate_old_db.py /path/to/threads.db")
        sys.exit(1)
    migrate(sys.argv[1])
