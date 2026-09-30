#!/usr/bin/env python3
"""channel_agent/run.py — прогон агента-редактора.

    python3 -m channel_agent.run                 # штатный прогон
    python3 -m channel_agent.run --dry-run       # показать, ничего не публикуя
    python3 -m channel_agent.run --rubric pulse_spike --limit 1
    python3 -m channel_agent.run --target main   # в основной канал (после обкатки)

Порядок: поводы (facts) → отсев уже опубликованных → текст (compose) →
очередь channel_posts. Публикует не этот процесс, а Vorovka2: в канал пишет
Telethon-юзербот, у него единственная авторизованная сессия.
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from channel_agent import compose, facts, memes    # noqa: E402
from channel_agent import news_compose, news_picker  # noqa: E402
from core.db_migrations import apply_all          # noqa: E402

log = logging.getLogger("channel_agent.run")

BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

# Сколько постов агент выпускает за один прогон. Ограничение не про нагрузку,
# а про ленту: четыре повода подряд в канале читаются как спам.
DEFAULT_LIMIT = 2

# Приоритет рубрик при выборе. Событие календаря ждать не может — оно выйдет
# через час и повод исчезнет; сюжет дня и слух живут дольше.
RUBRIC_ORDER = ["before_event", "rumor_check", "pulse_spike", "top_story"]


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(BOT_DB), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    apply_all(con)
    return con


def _already_used(con, dedup_key: str) -> bool:
    return con.execute(
        "SELECT 1 FROM channel_posts WHERE dedup_key = ? LIMIT 1", (dedup_key,)
    ).fetchone() is not None


def run_news(limit: int = 4, target: str = "test", dry_run: bool = False) -> int:
    """Новостная лента: отбор из своего потока + написание постов.

    10.09: основная работа канала. Рубрики из facts.py остаются, но они дают
    один-два повода в день, а лента — десятки; ради ленты канал и читают.
    """
    con = _connect()
    cands = news_picker.candidates(limit=30)
    if not cands:
        log.info("новостей-кандидатов нет")
        con.close()
        return 0

    fresh = [c for c in cands if dry_run or not _already_used(con, c["dedup_key"])]
    log.info("кандидатов %d, из них новых %d", len(cands), len(fresh))
    posts = news_compose.write_news(fresh, limit=limit)

    by_uid = {c["facts"]["uid"]: c for c in fresh}
    published = 0
    for post in posts:
        cand = by_uid.get(post["uid"])
        if cand is None:
            continue
        image = memes.pick(post["image_hint"], "news")
        if dry_run:
            print(f"\n=== [news] {cand['dedup_key']}")
            print(post["text"])
            print(f"--- образ: {post['image_hint']!r} → картинка: {image or 'нет'}")
            published += 1
            continue
        try:
            con.execute(
                "INSERT INTO channel_posts (created_ts, rubric, dedup_key, target, "
                "text, image_path, facts_json) VALUES (?,?,?,?,?,?,?)",
                (int(time.time()), "news", cand["dedup_key"], target, post["text"],
                 image, json.dumps({"facts": cand["facts"],
                                    "image_hint": post["image_hint"]}, ensure_ascii=False)),
            )
            con.commit()
        except sqlite3.IntegrityError:
            continue
        published += 1
    con.close()
    return published


def run(limit: int = DEFAULT_LIMIT, rubrics: list[str] | None = None,
        target: str = "test", dry_run: bool = False) -> int:
    con = _connect()
    candidates = facts.collect(rubrics)
    if not candidates:
        log.info("поводов нет — постов не будет")
        return 0

    by_rubric: dict[str, list[dict]] = {}
    for c in candidates:
        by_rubric.setdefault(c["rubric"], []).append(c)

    published = 0
    # Обходим рубрики по приоритету и берём по одному поводу из каждой: два
    # поста подряд об одном и том же типе — это уже не канал, а отчёт.
    for rubric in RUBRIC_ORDER:
        if published >= limit:
            break
        for cand in by_rubric.get(rubric, []):
            if published >= limit:
                break
            key = cand["dedup_key"]
            if not dry_run and _already_used(con, key):
                log.info("повод %s уже был — пропуск", key)
                continue

            post = compose.write_post(rubric, cand["facts"])
            if post is None:
                continue

            image = memes.pick(post["image_hint"], rubric)

            if dry_run:
                print(f"\n=== [{rubric}] {key}")
                print(post["text"])
                print(f"--- образ: {post['image_hint']!r} → картинка: {image or 'нет'}")
                published += 1
                # break, а не continue: в боевом режиме из одной рубрики
                # берётся ровно один пост за прогон, и превью обязано
                # показывать то же самое. С continue первый же прогон выдал
                # четыре поста подряд одной рубрики — картина, которой в
                # канале никогда не будет.
                break

            try:
                con.execute(
                    "INSERT INTO channel_posts (created_ts, rubric, dedup_key, target, "
                    "text, image_path, facts_json) VALUES (?,?,?,?,?,?,?)",
                    (int(time.time()), rubric, key, target, post["text"], image,
                     json.dumps({"facts": cand["facts"], "image_hint": post["image_hint"]},
                                ensure_ascii=False)),
                )
                con.commit()
            except sqlite3.IntegrityError:
                # Уникальный индекс по dedup_key: повод успел уйти в очередь в
                # параллельном прогоне. Не ошибка, ровно то, ради чего индекс.
                log.info("повод %s уже в очереди", key)
                continue
            log.info("рубрика %s: пост поставлен в очередь (%s)", rubric, target)
            published += 1
            break

    con.close()
    return published


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--rubric", action="append", choices=list(facts.ALL_RUBRICS))
    ap.add_argument("--target", default="test", choices=["test", "main"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--news", action="store_true",
                    help="новостная лента вместо рубрик на своих измерениях")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.news:
        n = run_news(args.limit, args.target, args.dry_run)
    else:
        n = run(args.limit, args.rubric, args.target, args.dry_run)
    print(f"channel_agent: постов {'показано' if args.dry_run else 'в очереди'} — {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
