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


# ── Переводчики: цепочка, а не один ─────────────────────────────────────────
#
# 🔴 11.09.2026 бесплатный Google перестал нам отвечать: и одиночный запрос, и
# партия возвращают страницу «Error 500 (Server Error)». Защита от этой
# страницы стояла (иначе подпись под новостью гласила бы «Error 500»), и
# именно поэтому поломка выглядела не как ошибка, а как «перевод просто не
# появляется». Замер показал: MyMemory на том же заголовке отвечает за 705 мс.
#
# Поэтому переводчик не один, а список. Google остаётся первым — он быстрее и
# может вернуться; когда он отказывает, его на время выключает предохранитель
# ниже, и работа идёт через запасной.
_МЁРТВ_НА_СЕК = 600
_отключён_до: dict[str, float] = {}

# MyMemory требует коды вида en-GB, а не en.
_MYMEMORY_КОД = {"ru": "ru-RU", "ro": "ro-RO", "en": "en-GB"}


def _google(тексты: list[str], lang: str) -> list[str]:
    from deep_translator import GoogleTranslator
    return GoogleTranslator(source="auto", target=lang).translate_batch(тексты)


def _mymemory(тексты: list[str], lang: str) -> list[str]:
    """Переводит партию параллельно: своего batch у MyMemory нет.

    Четыре потока, а не двенадцать: сервис бесплатный и общий, и выжимать из
    него всё — верный способ получить блокировку по адресу. При 700 мс на
    заголовок дюжина укладывается примерно в две секунды.
    """
    from concurrent.futures import ThreadPoolExecutor

    from deep_translator import MyMemoryTranslator
    tr = MyMemoryTranslator(source="en-GB", target=_MYMEMORY_КОД.get(lang, "ru-RU"))

    def один(t: str) -> str:
        try:
            return tr.translate(t)
        except Exception:
            return ""

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(один, тексты))


_ПЕРЕВОДЧИКИ = (("google", _google), ("mymemory", _mymemory))


def _плох(переводы, тексты) -> bool:
    """Ответ бесполезен: пусто, страница ошибки или текст вернулся как есть."""
    if not переводы:
        return True
    годных = sum(1 for п, ор in zip(переводы, тексты)
                 if п and isinstance(п, str)
                 and _GOOGLE_ERROR_SIGNATURE not in п
                 and п.strip() != ор.strip())
    return годных == 0


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

    переводы = None
    for имя, fn in _ПЕРЕВОДЧИКИ:
        if _отключён_до.get(имя, 0) > time.time():
            continue
        try:
            ответ = fn(тексты, lang)
        except Exception as e:
            log.debug("%s не ответил: %s", имя, str(e)[:120])
            ответ = None
        if _плох(ответ, тексты):
            _отключён_до[имя] = time.time() + _МЁРТВ_НА_СЕК
            log.warning("переводчик %s не работает, отключаю на %d мин",
                        имя, _МЁРТВ_НА_СЕК // 60)
            continue
        переводы = ответ
        break

    if переводы is None:
        # 🔴 Все переводчики отказали — это событие, а не тишина.
        log.error("ни один переводчик не ответил: заголовки остаются на языке "
                  "оригинала. Проверять core/news_i18n.py")
        return {}

    out, now, готовые = {}, int(time.time()), []
    for (uid, оригинал), перевод in zip(items, переводы or []):
        if not перевод or not isinstance(перевод, str):
            continue
        if _GOOGLE_ERROR_SIGNATURE in перевод:
            # Отдельные строки партии могут прийти страницей ошибки, даже
            # когда партия в целом признана годной. Такую пропускаем, а не
            # выходим из цикла: остальные переводы в ней хорошие.
            continue
        перевод = перевод.strip()
        if not перевод or перевод == оригинал.strip():
            continue
        out[uid] = перевод
        готовые.append((uid, lang, перевод, now))

    # 🔴 Неудачная запись в кэш НЕ должна выбрасывать уже готовый перевод.
    # По этой базе одновременно работают коллекторы, и «database is locked»
    # здесь — обычное дело. Раньше исключение улетало наверх и человек не
    # получал ничего, хотя перевод был на руках: кэш — это ускорение, а не
    # условие работы.
    if готовые:
        try:
            con.executemany(
                "INSERT OR REPLACE INTO news_titles(news_uid, lang, title, ts) "
                "VALUES(?,?,?,?)", готовые)
            con.commit()
        except Exception as e:
            log.warning("перевод получен, но в кэш не записан: %s", str(e)[:120])
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
