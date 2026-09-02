"""core/tg_notify.py — личные сообщения пользователям платформы в Telegram.

ЧЕЙ ЭТО БОТ. Сообщение приходит от @SBFAcademy_bot, а не от @Markgandon_bot.
Причина не в предпочтениях: Telegram разрешает боту писать только тем, кто сам
начал с ним диалог. Наши пользователи входили на платформу через SBFAcademy —
значит, диалог у них есть именно с ним. Отправка от market_intel-бота ушла бы в
403 по каждому адресату, и это выглядело бы как «уведомления не работают», хотя
дело было бы в выборе отправителя.

ГДЕ ВЗЯТЬ АДРЕСАТА. Цепочка: journal.db users.sbfacademy_user_id →
bot.db auth_identities(provider='telegram') → provider_uid и есть chat_id.
Не всякий аккаунт её проходит: кто входил через Google, телеграм-личности не
имеет, и писать ему некуда — это нормальный исход, а не ошибка.

ТОКЕН читаем из SBFAcademy_bot/.env на месте, а не копируем к себе: копия
секрета — это второе место, где он может утечь, и второе место, которое надо
не забыть обновить.
"""
from __future__ import annotations

import logging
import pathlib
import sqlite3
import urllib.parse
import urllib.request

log = logging.getLogger("tg_notify")

ACADEMY_DIR = pathlib.Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot")
BOT_DB = ACADEMY_DIR / "bot.db"
_token_cache: str | None = None


def _token() -> str | None:
    global _token_cache
    if _token_cache is not None:
        return _token_cache or None
    env = ACADEMY_DIR / ".env"
    tok = ""
    try:
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("BOT_TOKEN="):
                tok = line.split("=", 1)[1].strip()
                break
    except Exception as e:
        log.warning("токен бота не прочитан: %s", e)
    _token_cache = tok
    return tok or None


def chat_id_for(sbfacademy_user_id) -> int | None:
    """Chat id пользователя или None, если Telegram к аккаунту не привязан."""
    if not sbfacademy_user_id:
        return None
    try:
        con = sqlite3.connect(f"file:{BOT_DB}?mode=ro", uri=True)
        row = con.execute(
            "SELECT provider_uid FROM auth_identities "
            "WHERE provider='telegram' AND user_id=? LIMIT 1",
            (int(sbfacademy_user_id),)).fetchone()
        con.close()
        return int(row[0]) if row and str(row[0]).lstrip("-").isdigit() else None
    except Exception as e:
        log.warning("поиск telegram-привязки для %s: %s", sbfacademy_user_id, e)
        return None


def send(chat_id: int, text: str, disable_preview: bool = True) -> bool:
    """Отправить сообщение. False — не отправлено, причина в логе.

    Молча глотать отказ нельзя: «уведомления не приходят» и «мы их не отправили»
    для пользователя одинаковы, а для нас это разные поломки.
    """
    tok = _token()
    if not tok:
        log.error("BOT_TOKEN не найден — отправка невозможна")
        return False
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true" if disable_preview else "false",
    }).encode()
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{tok}/sendMessage", data=data)
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except Exception as e:
        # 403 значит «пользователь не начал диалог с ботом или заблокировал его».
        # Это не наша поломка, но и не успех — отмечаем и идём дальше.
        log.warning("не отправлено в чат %s: %s", chat_id, str(e)[:160])
        return False
