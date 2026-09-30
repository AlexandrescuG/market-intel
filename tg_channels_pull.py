#!/usr/bin/env python3
"""tg_channels_pull.py — сбор сигналов из списка Telegram-каналов.

09.09.2026. До сих пор единственным Telegram-источником в signals был наш
собственный канал (sbfeconomics_pull.py): 512 сообщений за неделю, и все —
наша же переклейка markettwits. То есть мы читали сами себя, круг замыкался,
а новой информации сбор не давал.

Здесь тот же приём, что в sbfeconomics_pull.py (Telethon на readonly, дата
сообщения кладётся в raw.published), но по СПИСКУ каналов из
core/tg_sources.json. Список правится без кода — это данные, а не логика.

Использование:
  python3 tg_channels_pull.py                 # все включённые каналы
  python3 tg_channels_pull.py --limit 200
  python3 tg_channels_pull.py --channel markettwits
  python3 tg_channels_pull.py --list          # что настроено
"""
import argparse
import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core import db  # noqa: E402
from news_pipeline.config import TG_API_ID, TG_API_HASH, TG_SESSION  # noqa: E402

SOURCES_PATH = Path(__file__).parent / "core" / "tg_sources.json"
DEFAULT_LIMIT = 200


def load_sources() -> list[dict]:
    try:
        data = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"tg_sources.json не прочитан: {e}", file=sys.stderr)
        return []
    return [c for c in data.get("channels", []) if c.get("enabled", True)]


def _upsert_with_retry(*, retries: int = 6, **kwargs) -> None:
    """Тот же ретрай, что в sbfeconomics_pull: core/db.py открывает своё
    соединение с 5-секундным busy_timeout, а рядом пишут rss/twitter."""
    for attempt in range(retries):
        try:
            db.upsert(**kwargs)
            return
        except sqlite3.OperationalError as e:
            if "locked" not in str(e) or attempt == retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))


async def pull_all(limit: int, only: str | None, verbose: bool) -> int:
    from telethon import TelegramClient

    channels = load_sources()
    if only:
        channels = [c for c in channels if c["name"] == only]
    if not channels:
        print("нет включённых каналов", file=sys.stderr)
        return 0

    client = TelegramClient(TG_SESSION, TG_API_ID, TG_API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("сессия Telethon не авторизована — пропуск", file=sys.stderr)
        await client.disconnect()
        return 0

    db.init_db()
    total = 0
    for ch in channels:
        name = ch["name"]
        try:
            entity = await client.get_entity(name)
        except Exception as e:
            # Недоступный канал не должен ронять сбор из остальных: список
            # правится руками, и опечатка или закрытый канал — рядовой случай.
            print(f"  {name}: не открыт ({e})", file=sys.stderr)
            continue
        saved = 0
        try:
            async for msg in client.iter_messages(entity, limit=limit):
                if not msg.text:
                    continue
                _upsert_with_retry(
                    source="telegram", source_id=f"{name}:{msg.id}",
                    author=name, text=msg.text,
                    url=f"https://t.me/{name}/{msg.id}",
                    topic_hint=ch.get("topic") or name,
                    lang=ch.get("lang", "ru"),
                    raw={"published": int(msg.date.timestamp())},
                )
                saved += 1
        except Exception as e:
            print(f"  {name}: чтение прервано ({e})", file=sys.stderr)
        total += saved
        if verbose:
            print(f"  {name}: {saved}")
    await client.disconnect()
    print(f"tg_channels_pull: сохранено {total} сообщений из {len(channels)} каналов")
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--channel", default=None)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.list:
        for c in load_sources():
            print(f"  {c['name']:<22} {c.get('topic','')}")
        return 0
    asyncio.run(pull_all(args.limit, args.channel, args.verbose))
    return 0


if __name__ == "__main__":
    sys.exit(main())
