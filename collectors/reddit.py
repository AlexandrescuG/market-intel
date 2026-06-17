"""Reddit-коллектор без кредов: грузим .json-эндпоинты Reddit через stealth-контекст.

Почему так, а не DOM-скрапинг: Reddit отдаёт чистый JSON на /r/<sub>/<sort>/.json —
это структурно и не ломается от смены вёрстки. cloakbrowser нужен только чтобы
обойти анти-бот (Reddit режет «голые» датацентр-запросы). Логин не требуется.

Что считаем «полезным трейдеру»:
  - пост с тикерами ($NVDA…) и высоким importance
  - rising-посты (взлетающие прямо сейчас) с заметным score/комментами
  - DD / News / Discussion флейры
Скоринг и отсев — общий (core.scoring), как у всех источников.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

import cloakbrowser

from core import db, scoring
from core.config import (ALERT_MIN_IMPORTANCE, PROFILE_DIR, REDDIT_LIMIT,
                         REDDIT_SORTS, REDDIT_SUBS, STORE_MIN_ECON_RELEVANCE)
from core.telegram import send_text

log = logging.getLogger("reddit")

ACTIONABLE_FLAIRS = {"dd", "news", "discussion", "chart", "gain", "loss",
                     "fundamentals", "macro", "technicals"}


async def _fetch_json(page, url: str) -> dict | None:
    """Открыть .json-URL в браузере и распарсить тело как JSON."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        body = await page.inner_text("body")
        return json.loads(body)
    except Exception as e:
        log.warning("reddit fetch %s: %s", url, e)
        return None


def _is_actionable(post: dict, cashtags: list[str]) -> bool:
    flair = (post.get("link_flair_text") or "").lower()
    if any(f in flair for f in ACTIONABLE_FLAIRS):
        return True
    if cashtags:
        return True
    if post.get("num_comments", 0) > 200 and post.get("upvote_ratio", 0) > 0.7:
        return True
    return False


async def collect_with_context(ctx) -> int:
    """Использует уже открытый cloakbrowser-контекст (общий с twitter)."""
    db.init_db()
    page = await ctx.new_page()
    saved = 0
    try:
        for sub in REDDIT_SUBS:
            for sort in REDDIT_SORTS:
                url = f"https://old.reddit.com/r/{sub}/{sort}/.json?limit={REDDIT_LIMIT}"
                data = await _fetch_json(page, url)
                if not data or "data" not in data:
                    continue
                cutoff = time.time() - 86400  # только за последние 24 часа
                for child in data["data"].get("children", []):
                    p = child.get("data", {})
                    if float(p.get("created_utc") or 0) < cutoff:
                        continue
                    title = (p.get("title") or "").strip()
                    body = (p.get("selftext") or "")[:600]
                    blob = f"{title}\n{body}"
                    cashtags = scoring.cashtags(blob)
                    if scoring.econ_relevance(blob) < STORE_MIN_ECON_RELEVANCE \
                       and not cashtags:
                        continue
                    res = db.upsert(
                        source="reddit",
                        source_id=p.get("id", ""),
                        author=p.get("author", ""),
                        title=title,
                        text=body,
                        url=f"https://reddit.com{p.get('permalink', '')}",
                        engagement=int(p.get("score", 0)),
                        replies=int(p.get("num_comments", 0)),
                        topic_hint=f"r/{sub}/{sort}",
                        raw={
                            "flair": p.get("link_flair_text"),
                            "upvote_ratio": p.get("upvote_ratio"),
                            "actionable": _is_actionable(p, cashtags),
                            "created_utc": p.get("created_utc"),
                        },
                    )
                    saved += 1
                    if res["is_new"] and res["importance"] >= ALERT_MIN_IMPORTANCE \
                       and _is_actionable(p, scoring.cashtags(blob)):
                        sub_hint = p.get("subreddit_name_prefixed", f"r/{sub}")
                        icon = {"economy": "💰", "geopolitics": "🌍"}.get(
                            res.get("dimension", ""), "💬")
                        tags = " ".join(f"${t}" for t in res.get("cashtags", [])[:4])
                        caption = (f"{icon} <b>{sub_hint}</b>  {tags}\n"
                                   f"{title[:200]}\n\n"
                                   f"🔗 https://reddit.com{p.get('permalink', '')}")
                        await send_text(caption)
                        await asyncio.sleep(0.5)
                await asyncio.sleep(1.0)  # вежливо к Reddit
            log.info("reddit r/%-20s scanned", sub)
    finally:
        await page.close()
    log.info("reddit collect done: %d signals", saved)
    return saved


async def collect() -> int:
    """Самостоятельный запуск (свой контекст)."""
    ctx = await cloakbrowser.launch_persistent_context_async(
        user_data_dir=str(PROFILE_DIR),
        headless=True,
        locale="en-US",
        viewport={"width": 1280, "height": 900},
    )
    try:
        return await collect_with_context(ctx)
    finally:
        await ctx.close()


if __name__ == "__main__":
    from core.logging_setup import setup
    setup("reddit")
    print("saved:", asyncio.run(collect()))
