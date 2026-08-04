#!/usr/bin/env python3
"""
sbfeconomics_pull.py — ингест сообщений Telegram-канала "sbfeconomics" (SBF
Экономика, Геополитика, Деньги) в общую таблицу signals (source='telegram'),
доп. источник для SBF_Charts_Layer3_Spec Фазы 3 (сентимент толпы) наравне с
твитами. Переиспользует уже настроенную и авторизованную Telethon-сессию
news_pipeline (аккаунт "воровки" — используется там для репоста в другой
канал; здесь ТОЛЬКО на чтение, ничего не постим и не меняем).

Настоящая дата сообщения сохраняется в raw.published (Telegram msg.date) —
db.upsert() иначе проставил бы first_seen/last_seen как "сейчас" при любом
отложенном/повторном прогоне, что сломало бы почасовую разбивку в
sentiment_job.py (тот же паттерн, что news_burst_job._published_ts()).

Использование:
  python3 sbfeconomics_pull.py [--limit 500] [--verbose]
"""
import argparse
import asyncio
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core import db  # noqa: E402
from news_pipeline.config import TG_API_ID, TG_API_HASH, TG_SESSION  # noqa: E402

CHANNEL = "sbfeconomics"


def _upsert_with_retry(*, retries: int = 6, **kwargs) -> None:
    """core/db.py:upsert() открывает своё sqlite3-соединение с дефолтным
    5с busy_timeout — под конкурентной записью от rss/twitter/stocktwits
    коллекторов (крутятся каждые 15-20 мин) этого не хватает при пачке из
    сотен upsert подряд (наблюдалось живьём при бэкафилле). Не трогаем
    core/db.py (общий код для живых коллекторов) — ретраим здесь."""
    for attempt in range(retries):
        try:
            db.upsert(**kwargs)
            return
        except sqlite3.OperationalError as e:
            if "locked" not in str(e) or attempt == retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))


async def pull(limit: int = 500, verbose: bool = False) -> int:
    from telethon import TelegramClient

    client = TelegramClient(TG_SESSION, TG_API_ID, TG_API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        if verbose:
            print("сессия Telethon не авторизована — пропуск")
        await client.disconnect()
        return 0

    db.init_db()
    entity = await client.get_entity(CHANNEL)
    saved = 0
    async for msg in client.iter_messages(entity, limit=limit):
        if not msg.text:
            continue
        _upsert_with_retry(
            source="telegram", source_id=str(msg.id),
            author=CHANNEL, text=msg.text, url=f"https://t.me/{CHANNEL}/{msg.id}",
            topic_hint=CHANNEL, lang="ru",
            raw={"published": int(msg.date.timestamp())},
        )
        saved += 1
        if verbose and saved % 50 == 0:
            print(f"  ...{saved} обработано")
    await client.disconnect()
    if verbose:
        print(f"sbfeconomics: {saved} сообщений обработано (limit={limit})")
    return saved


def run(limit: int = 500, verbose: bool = False) -> int:
    return asyncio.run(pull(limit, verbose))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    run(limit=args.limit, verbose=args.verbose)
