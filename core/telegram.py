"""Telegram: алерты (фото+подпись) и отправка дайджеста (длинный markdown).

Сохранено как у тебя: лента для контента живёт на TELEGRAM_CHAT_ID.
Дайджест уходит на TELEGRAM_REPORT_CHAT_ID (по умолчанию = CHAT_ID).
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from core.config import (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                         TELEGRAM_REPORT_CHAT_ID)

log = logging.getLogger("telegram")
_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
TG_LIMIT = 4000  # лимит Telegram 4096, берём с запасом


async def send_text(text: str, chat_id: str | None = None) -> None:
    chat = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not chat:
        return
    async with httpx.AsyncClient(timeout=15) as c:
        try:
            r = await c.post(f"{_API}/sendMessage", json={
                "chat_id": chat, "text": text,
                "parse_mode": "HTML", "disable_web_page_preview": True,
            })
            if r.status_code != 200:
                log.error("sendMessage %s: %s", r.status_code, r.text[:200])
        except Exception as e:
            log.error("send_text failed: %s", e)


async def send_photo(photo: bytes, caption: str, chat_id: str | None = None) -> None:
    chat = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not chat:
        return
    async with httpx.AsyncClient(timeout=30) as c:
        try:
            r = await c.post(f"{_API}/sendPhoto",
                             data={"chat_id": chat, "caption": caption[:1024],
                                   "parse_mode": "HTML"},
                             files={"photo": ("s.png", photo, "image/png")})
            if r.status_code != 200:
                log.error("sendPhoto %s: %s", r.status_code, r.text[:200])
        except Exception as e:
            log.error("send_photo failed: %s", e)


def _chunk(text: str, size: int = TG_LIMIT) -> list[str]:
    """Режем по абзацам, не разрывая строки."""
    out, buf = [], ""
    for line in text.splitlines(keepends=True):
        if len(buf) + len(line) > size:
            out.append(buf)
            buf = ""
        buf += line
    if buf:
        out.append(buf)
    return out or [text]


async def send_report(markdown: str, chat_id: str | None = None) -> None:
    """Длинный markdown-дайджест → несколькими сообщениями."""
    chat = chat_id or TELEGRAM_REPORT_CHAT_ID or TELEGRAM_CHAT_ID
    for part in _chunk(markdown):
        await send_text(part, chat_id=chat)
        await asyncio.sleep(0.5)


# CLI: python3 -m core.telegram --send-file data/reports/report_2026-06-16.md
if __name__ == "__main__":
    import argparse
    from core.logging_setup import setup
    setup("telegram")
    ap = argparse.ArgumentParser()
    ap.add_argument("--send-file", required=True)
    args = ap.parse_args()
    md = open(args.send_file, encoding="utf-8").read()
    asyncio.run(send_report(md))
    print("sent", args.send_file)
