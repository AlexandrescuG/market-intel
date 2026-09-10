"""core/news_media.py — картинка к новости.

ЗАЧЕМ. Лента упоминаний по активу была списком синих ссылок. Руководитель:
«при нажатии на актив должен открываться не просто список новостей, а
подтягивались картинки с автопереводом заголовков».

ОТКУДА БЕРЁТСЯ КАРТИНКА, в порядке предпочтения:

  shot — наш собственный скриншот твита. Он и так снимается в
         collectors/twitter.py для отправки в Telegram; раньше байты
         выбрасывались сразу после отправки, теперь сохраняются на диск.
  og   — превью, которое издание само отдаёт соцсетям (og:image). Это
         разрешённое использование: тег для того и существует, а картинка
         остаётся на серверах издания — мы кладём у себя только ссылку.

🔴 ЧЕГО ЗДЕСЬ НЕТ И НЕ БУДЕТ: скачивания чужих фотографий к себе и подстановки
случайной картинки «чтобы не пусто». Карточка без картинки — это карточка без
картинки; выдуманная иллюстрация к новости хуже её отсутствия.

🔴 ОТКАЗ — ЭТО НОРМА, И ОН ЗАПОМИНАЕТСЯ. Издания блокируют, отдают 403,
таймаутят. Каждая неудача пишется в attempts, и после трёх попыток мы к этой
ссылке больше не возвращаемся: иначе фоновая задача каждый прогон долбилась бы
в одни и те же мёртвые адреса вместо новых новостей.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import time
from html import unescape
from urllib.parse import urljoin, urlparse

log = logging.getLogger("news_media")

# Сколько раз пробуем достать превью, прежде чем оставить новость без картинки.
MAX_ATTEMPTS = 3
# Домены, по которым ходить бессмысленно: превью там нет или оно за логином.
#
# 🔴 news.google.com отсекается сразу, а не после трёх попыток. Замер
# 10.09.2026: 19 ссылок из 20 отдали 200 OK и HTML без единого og-тега —
# страница рисуется скриптом. Адрес издания из ссылки тоже не достать: внутри
# base64 лежит не URL, а идентификатор `AU_yqL…`, и в RSS-записи Google отдаёт
# только домашнюю страницу издания. Это 43% ленты; без этой строки задача
# тратила бы на них три захода каждую, то есть больше половины всех походов
# наружу — на заведомо пустой результат. Таким новостям показываем логотип
# издания, домен которого сборщик уже сохранил в raw.domain.
SKIP_DOMAINS = {"x.com", "twitter.com", "t.me", "telegram.me", "news.google.com"}

_META_RE = re.compile(
    r"<meta[^>]+(?:property|name)\s*=\s*[\"'](og:image(?::url)?|twitter:image(?::src)?)[\"']"
    r"[^>]*?content\s*=\s*[\"']([^\"']+)[\"']", re.I)
# Порядок атрибутов в разметке произвольный: у части изданий content идёт
# первым. Второе выражение ловит этот случай — без него терялось примерно
# каждое пятое превью.
_META_RE_REV = re.compile(
    r"<meta[^>]+content\s*=\s*[\"']([^\"']+)[\"'][^>]*?(?:property|name)\s*=\s*"
    r"[\"'](og:image(?::url)?|twitter:image(?::src)?)[\"']", re.I)


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS news_media(
            news_uid TEXT PRIMARY KEY,
            kind     TEXT NOT NULL,          -- 'og' | 'shot'
            url      TEXT,                   -- ссылка на превью издания
            path     TEXT,                   -- наш файл под web/, если kind='shot'
            attempts INTEGER NOT NULL DEFAULT 0,
            ts       INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_news_media_ts ON news_media(ts DESC);
    """)
    con.commit()


def domain_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def extract(html: str, base_url: str) -> str | None:
    """og:image из HTML страницы. None — если издание его не отдаёт."""
    for rx, группа in ((_META_RE, 2), (_META_RE_REV, 1)):
        m = rx.search(html)
        if m:
            raw = unescape(m.group(группа)).strip()
            if not raw:
                continue
            # Относительный путь встречается редко, но встречается; без urljoin
            # такая ссылка на витрине превращалась бы в битую картинку.
            full = urljoin(base_url, raw)
            if full.startswith(("http://", "https://")):
                return full[:600]
    return None


def save_shot(con: sqlite3.Connection, news_uid: str, rel_path: str) -> None:
    """Записать наш скриншот. Вызывается сборщиком твитов."""
    ensure_schema(con)
    con.execute(
        "INSERT OR REPLACE INTO news_media(news_uid, kind, url, path, attempts, ts) "
        "VALUES(?,'shot',NULL,?,0,?)", (news_uid, rel_path, int(time.time())))
    con.commit()


def save_og(con: sqlite3.Connection, news_uid: str, url: str | None,
            attempts: int) -> None:
    """Записать найденное превью — или неудачу, чтобы не ходить сюда вечно."""
    con.execute(
        "INSERT OR REPLACE INTO news_media(news_uid, kind, url, path, attempts, ts) "
        "VALUES(?,'og',?,NULL,?,?)", (news_uid, url, attempts, int(time.time())))


# ── логотип издания ─────────────────────────────────────────────────────────
#
# 🔴 Зачем он вообще нужен. 43% ленты приходит ссылками news.google.com, и это
# непрозрачный токен: адрес статьи из него не достать (проверено 10.09.2026 —
# внутри base64 лежит не URL, а идентификатор `AU_yqL…`), сама страница
# отрисовывается скриптом и og-тегов не содержит, а в RSS-записи Google отдаёт
# только домашнюю страницу издания. Фотографии к таким новостям у нас не будет
# никогда.
#
# Логотип издания — честная замена: он не притворяется иллюстрацией к событию,
# он говорит «это написал Reuters». Домен издания при этом у нас уже есть —
# collectors/rss.py кладёт его в raw.domain.

LOGO_DIR = "media/logos"
_ICON_RE = re.compile(
    r"<link[^>]+rel\s*=\s*[\"'][^\"']*(?:apple-touch-icon|shortcut icon|icon)[^\"']*[\"']"
    r"[^>]*?href\s*=\s*[\"']([^\"']+)[\"']", re.I)


def ensure_logo_schema(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS source_logos(
            domain   TEXT PRIMARY KEY,
            path     TEXT,               -- наш файл под web/, если получилось
            attempts INTEGER NOT NULL DEFAULT 0,
            ts       INTEGER NOT NULL
        );
    """)
    con.commit()


def extract_icon(html: str, base_url: str) -> str | None:
    """Адрес иконки из <head> домашней страницы издания."""
    m = _ICON_RE.search(html)
    if m:
        full = urljoin(base_url, unescape(m.group(1)).strip())
        if full.startswith(("http://", "https://")):
            return full[:600]
    return None


def logos_for(con: sqlite3.Connection, domains: list[str]) -> dict[str, str]:
    if not domains:
        return {}
    try:
        q = ",".join("?" * len(domains))
        rows = con.execute(
            f"SELECT domain, path FROM source_logos "
            f"WHERE path IS NOT NULL AND domain IN ({q})", domains).fetchall()
    except sqlite3.OperationalError:
        return {}
    return dict(rows)


def media_for(con: sqlite3.Connection, uids: list[str]) -> dict[str, str]:
    """{uid: адрес картинки} — свой файл или ссылка издания, что нашлось."""
    if not uids:
        return {}
    try:
        q = ",".join("?" * len(uids))
        rows = con.execute(
            f"SELECT news_uid, kind, url, path FROM news_media "
            f"WHERE news_uid IN ({q})", uids).fetchall()
    except sqlite3.OperationalError:
        return {}
    out = {}
    for uid, kind, url, path in rows:
        адрес = path if kind == "shot" else url
        if адрес:
            out[uid] = адрес
    return out
