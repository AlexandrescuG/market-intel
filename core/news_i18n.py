"""core/news_i18n.py — заголовок новости на языке читателя.

ЗАЧЕМ. 95% новостного потока приходит на латинице. В ленте упоминаний по
активу русский читатель видел стену английских заголовков.

🔴 ЭТО МАШИННЫЙ ПЕРЕВОД, И ОН ДОЛЖЕН БЫТЬ НАЗВАН ТАК.
Перевод отдаётся отдельным полем `title_local`, оригинал остаётся в `title` и
показывается рядом. Подменять чужой заголовок своей версией молча нельзя:
читатель должен видеть, что именно написало издание, — особенно когда речь о
цифрах и о том, кто что заявил.

🔴 ПЕРЕВОДИМ ЛЕНИВО, ПО ФАКТУ ПРОСМОТРА. Поток — около 4000 новостей в сутки,
языка три. Переводить всё заранее значит 12 000 обращений к бесплатному
переводчику в день; он на это отвечает страницей ошибки (см. ниже). Переводится
то, что человек открыл, и складывается в кэш — повторный заход бесплатный.

ИЗВЕСТНЫЙ РЕЖИМ ОТКАЗА. deep_translator на ответ «Error 500 (Server Error)» от
Google не бросает исключение, а возвращает тело страницы ошибки как будто это
перевод. Тот же случай уже ловится в collectors/twitter.py; проверка повторена
здесь, потому что подпись под новостью «Error 500 (Server Error)» выглядела бы
как перевод заголовка.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import time

log = logging.getLogger("news_i18n")

SUPPORTED = ("ru", "ro", "en")
_GOOGLE_ERROR_SIGNATURE = "Error 500 (Server Error)"
# Дольше ждать нельзя: перевод идёт внутри запроса витрины, и человек смотрит
# на спиннер. Что не успело — приедет при следующем открытии уже из кэша.
TIMEOUT_SEC = 6.0
MAX_PER_REQUEST = 12

_CYR = re.compile(r"[А-Яа-яЁё]")


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS news_titles(
            news_uid TEXT NOT NULL,
            lang     TEXT NOT NULL,
            title    TEXT NOT NULL,
            ts       INTEGER NOT NULL,
            PRIMARY KEY(news_uid, lang)
        );
    """)
    con.commit()


def detect(title: str) -> str:
    """Язык заголовка по письменности: "ru" или "en".

    Румынский тоже латиница, и отличить его от английского по буквам нельзя —
    поэтому всё латинское считается "en". Для нашей задачи этого достаточно:
    решение принимается одно — переводить или нет.
    """
    return "ru" if _CYR.search(title or "") else "en"


def cached(con: sqlite3.Connection, uids: list[str], lang: str) -> dict[str, str]:
    if not uids or lang not in SUPPORTED:
        return {}
    try:
        q = ",".join("?" * len(uids))
        rows = con.execute(
            f"SELECT news_uid, title FROM news_titles "
            f"WHERE lang=? AND news_uid IN ({q})", (lang, *uids)).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {uid: t for uid, t in rows}


def translate_missing(con: sqlite3.Connection, items: list[tuple[str, str]],
                      lang: str) -> dict[str, str]:
    """items = [(uid, оригинальный заголовок)] → {uid: перевод}.

    Переводит и складывает в кэш. Любой сбой — пустой ответ и оригинал на
    витрине: отсутствие перевода это неудобство, подпись «Error 500» вместо
    заголовка — враньё.
    """
    if not items or lang not in SUPPORTED:
        return {}
    items = items[:MAX_PER_REQUEST]
    тексты = [t for _, t in items]
    try:
        from deep_translator import GoogleTranslator
        tr = GoogleTranslator(source="auto", target=lang)
        # translate_batch — один поход вместо N, и это разница между «успели за
        # секунду» и «двенадцать раз по 400 мс».
        переводы = tr.translate_batch(тексты)
    except Exception as e:
        log.debug("перевод не удался: %s", str(e)[:160])
        return {}

    out, now = {}, int(time.time())
    for (uid, оригинал), перевод in zip(items, переводы or []):
        if not перевод or not isinstance(перевод, str):
            continue
        if _GOOGLE_ERROR_SIGNATURE in перевод:
            log.warning("перевод: Google отдал страницу ошибки — пропускаю партию")
            return out
        перевод = перевод.strip()
        if not перевод or перевод == оригинал.strip():
            continue
        out[uid] = перевод
        con.execute(
            "INSERT OR REPLACE INTO news_titles(news_uid, lang, title, ts) "
            "VALUES(?,?,?,?)", (uid, lang, перевод, now))
    if out:
        con.commit()
    return out


def retention(con: sqlite3.Connection, days: int = 30) -> int:
    """Переводы живут не дольше, чем интересны: месяц.

    Сами новости хранятся 180 дней ради истории реакций на события, но
    заголовок месячной давности в ленте «что обсуждают» никто не откроет.
    """
    cur = con.execute("DELETE FROM news_titles WHERE ts < ?",
                      (int(time.time()) - days * 86400,))
    con.commit()
    return cur.rowcount
