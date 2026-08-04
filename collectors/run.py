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

TWITTER_TIMEOUT = 300   # сек — предел на весь твиттер-шаг одного цикла
CYCLE_TIMEOUT   = 900   # сек — предел на цикл целиком (запас до CHECK_INTERVAL)


async def one_cycle(only: str | None = None) -> None:
    db.init_db()

    # RSS — без браузера, дёшево, делаем всегда первым
    if only in (None, "rss"):
        from collectors import rss
        try:
            await asyncio.get_event_loop().run_in_executor(None, rss.collect)
        except Exception as e:
            log.error("rss failed: %s", e)

    # StockTwits — тоже без браузера (замена Reddit)
    if only in (None, "stocktwits"):
        from collectors import stocktwits
        try:
            await stocktwits.collect()
        except Exception as e:
            log.error("stocktwits failed: %s", e)

    # Twitter делает stealth-контекст
    if only in (None, "twitter"):
        ctx = await cloakbrowser.launch_persistent_context_async(
            user_data_dir=str(PROFILE_DIR), headless=HEADLESS,
            locale="en-US", timezone="Europe/Moscow",
            viewport={"width": 1280, "height": 900})
        try:
            from collectors import twitter
            try:
                # x.com иногда вешает страницу без исключения (не только таймаут
                # goto) — без внешнего предела это стопорит весь оркестратор на
                # часы, как случилось 09.07 (BUG: посты из X перестали приходить).
                await asyncio.wait_for(twitter.collect_with_context(ctx), timeout=TWITTER_TIMEOUT)
            except asyncio.TimeoutError:
                log.error("twitter timed out after %ds — пропускаем этот цикл", TWITTER_TIMEOUT)
            except Exception as e:
                log.error("twitter failed: %s", e, exc_info=True)
        finally:
            await ctx.close()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--only", choices=["rss", "stocktwits", "twitter"])
    args = ap.parse_args()

    if args.once:
        await one_cycle(args.only)
        return

    while True:
        try:
            await asyncio.wait_for(one_cycle(args.only), timeout=CYCLE_TIMEOUT)
        except asyncio.TimeoutError:
            log.error("cycle timed out after %ds — переходим к следующему прогону", CYCLE_TIMEOUT)
            await send_text(f"⚠️ Monitor: цикл завис дольше {CYCLE_TIMEOUT}s, прерван")
        except Exception as e:
            log.error("cycle error: %s", e, exc_info=True)
            await send_text(f"⚠️ Monitor error: {e}")
        log.info("следующий прогон через %d мин", CHECK_INTERVAL // 60)
        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
