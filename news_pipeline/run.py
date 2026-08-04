"""
SBF News Pipeline v1 — main loop.

Запуск:
    cd /home/sbf/market_intel
    .venv/bin/python -m news_pipeline.run

Первый запуск: Telethon попросит телефон + SMS-код.
Сессия сохранится в data/nevorovka_session.session — последующие запуски без кода.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time

from telethon import TelegramClient, events

from news_pipeline import config
from news_pipeline.db import init as db_init
from news_pipeline.ingest import ingest_rss, ingest_tg_history, ingest_tg_message
from news_pipeline.poster import flush_queue, process_raw
from news_pipeline.sources import get_active, seed

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("newspipe")

# отключаем болтовню Telethon
logging.getLogger("telethon").setLevel(logging.WARNING)


async def _rss_loop(client):
    while True:
        try:
            ingest_rss()
            process_raw()
            await flush_queue(client)
        except Exception as e:
            log.error("rss_loop error: %s", e)
        await asyncio.sleep(config.RSS_POLL_SEC)


async def main():
    if not config.TG_API_ID or not config.TG_API_HASH:
        log.error("TELNEWS_API_ID / TELNEWS_API_HASH не заданы в .env — выход")
        sys.exit(1)

    # init БД + seed whitelist
    db_init()
    seed()

    client = TelegramClient(config.TG_SESSION, config.TG_API_ID, config.TG_API_HASH)
    await client.start()
    log.info("✅ Telethon подключён. Целевой канал: @%s", config.TARGET_CHANNEL)

    tg_sources = {src["ref"]: src for src in get_active("tg")}

    # подгружаем историю каждого TG-канала
    for src in tg_sources.values():
        n = await ingest_tg_history(client, src, limit=50)
        log.info("TG history @%s: +%d items", src["ref"], n)

    # первый flush RSS + очередь после истории
    ingest_rss()
    process_raw()
    await flush_queue(client)

    # слушаем новые сообщения из TG-источников whitelist
    @client.on(events.NewMessage(chats=list(tg_sources.keys())))
    async def on_tg_msg(event):
        chat = event.chat
        username = getattr(chat, "username", None) or str(chat.id)
        src = tg_sources.get(username) or tg_sources.get(str(chat.id))
        if not src:
            return
        is_new = await ingest_tg_message(client, event.message, src)
        if is_new:
            process_raw()
            await flush_queue(client)

    log.info("🚀 SBF News Pipeline v1 запущен. RSS каждые %ds.", config.RSS_POLL_SEC)

    # RSS polling в фоне
    asyncio.create_task(_rss_loop(client))

    await client.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("👋 Остановлен вручную.")
