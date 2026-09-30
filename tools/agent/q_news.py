#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/agent/q_news.py — WP7.2 SPEC_alpha_engine_implementation.md.

Read-only обёртка: последние заголовки по инструменту за N часов + sentiment
(если есть). Переиспользует `news_instrument_tags` (news_burst_job.py) —
тот же джойн, не третья копия тегирования. Живёт в `data/signals.db`
(core.config.DB_PATH), не в bot.db — символ там price_bars-пространства
(регистр может отличаться от канонического), сверка через alias_for
опциональна и не критична: тегирование news_burst_job.py само по себе
использует свой список _SYMBOL_PATTERNS, не наш реестр — если тег не
совпал, вернётся пустой список, честно, не ошибка.

Использование: python3 tools/agent/q_news.py --symbol GOLD --hours 6
"""
import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.config import DB_PATH  # signals.db

MAX_ROWS = 30


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--hours", type=int, default=6)
    args = ap.parse_args()

    con = sqlite3.connect(str(DB_PATH), timeout=5)
    con.execute("PRAGMA query_only = ON")
    try:
        sql_prefilter = (datetime.now(timezone.utc) - timedelta(hours=max(args.hours, 24))).isoformat()
        rows = con.execute(
            """SELECT s.title, s.url, s.first_seen FROM news_instrument_tags t
               JOIN signals s ON s.uid = t.news_uid
               WHERE t.symbol = ? AND s.last_seen >= ?
               ORDER BY s.first_seen DESC LIMIT ?""",
            (args.symbol, sql_prefilter, MAX_ROWS),
        ).fetchall()
    except sqlite3.OperationalError as e:
        print(json.dumps({"error": str(e), "headlines": []}, ensure_ascii=False))
        return
    finally:
        con.close()

    cutoff_ts = time.time() - args.hours * 3600
    headlines = []
    for title, url, first_seen in rows:
        try:
            ts = datetime.fromisoformat(first_seen).timestamp()
        except (ValueError, TypeError):
            continue
        if ts < cutoff_ts:
            continue
        headlines.append({"title": title, "url": url, "ts": int(ts)})

    print(json.dumps({"symbol": args.symbol, "hours": args.hours, "headlines": headlines}, ensure_ascii=False))


if __name__ == "__main__":
    main()
