#!/usr/bin/env python3
"""Оркестратор коллекторов. Гоняет источники по кругу: real-time алерты в Telegram
(для контента) + накопление сигналов в БД (для дневного дайджеста).

  python3 -m collectors.run            # бесконечный цикл
  python3 -m collectors.run --once     # один прогон
  python3 -m collectors.run --only rss # только один источник (rss|reddit|twitter)
"""
from __future__ import annotations

import argparse
import asyncio

import cloakbrowser

from core import db
from core.config import CHECK_INTERVAL, HEADLESS, PROFILE_DIR
from core.logging_setup import setup
from core.telegram import send_text

log = setup("orchestrator")


async def one_cycle(only: str | None = None) -> None:
    db.init_db()

    # RSS — без браузера, дёшево, делаем всегда первым
    if only in (None, "rss"):
        from collectors import rss
        from core.telegram import send_text
        try:
            loop = asyncio.get_event_loop()
            _, rss_alerts = await loop.run_in_executor(None, rss.collect)
            for item in rss_alerts:
                icon = {"economy": "💰", "geopolitics": "🌍"}.get(item["dimension"], "📰")
                await send_text(
                    f"{icon} <b>{item['source']}</b>\n{item['title']}\n\n🔗 {item['url']}"
                )
                await asyncio.sleep(0.5)
        except Exception as e:
            log.error("rss failed: %s", e)

    # Twitter + Reddit делят один stealth-контекст
    if only in (None, "twitter", "reddit"):
        ctx = await cloakbrowser.launch_persistent_context_async(
            user_data_dir=str(PROFILE_DIR), headless=HEADLESS,
            locale="en-US", timezone="Europe/Moscow",
            viewport={"width": 1280, "height": 900})
        try:
            if only in (None, "twitter"):
                from collectors import twitter
                try:
                    await twitter.collect_with_context(ctx)
                except Exception as e:
                    log.error("twitter failed: %s", e, exc_info=True)
            if only in (None, "reddit"):
                from collectors import reddit
                try:
                    await reddit.collect_with_context(ctx)
                except Exception as e:
                    log.error("reddit failed: %s", e, exc_info=True)
        finally:
            await ctx.close()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--only", choices=["rss", "reddit", "twitter"])
    args = ap.parse_args()

    if args.once:
        await one_cycle(args.only)
        return

    while True:
        try:
            await one_cycle(args.only)
        except Exception as e:
            log.error("cycle error: %s", e, exc_info=True)
            await send_text(f"⚠️ Monitor error: {e}")
        log.info("следующий прогон через %d мин", CHECK_INTERVAL // 60)
        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
