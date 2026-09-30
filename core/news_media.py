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
# 🔴 news.google.com ОТСЮДА УБРАН 11.09.2026, и это стоит объяснить.
#
# 10.09 я записал здесь «адрес издания из ссылки не достать» и отсёк домен
# целиком. Вывод был сделан из двух проверок: страница отдаёт 200 без
# og-тегов, а внутри base64 не URL, а идентификатор. Обе проверки верны — и
# вывод из них неверен. Я искал адрес там, где его нет, и не посмотрел, что
# делает сама страница: она забирает адрес отдельным запросом, имея подпись и
# метку времени из своей же разметки. То же самое умеет делать и сервер —
# см. core/gnews_resolve.py.
#
# Урок не про Google. «Я проверил два места и не нашёл» — это не то же самое,
# что «этого нет»: браузер-то ссылку открывал, и это было видно с самого
# начала.
SKIP_DOMAINS = {"x.com", "twitter.com", "t.me", "telegram.me"}

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
    # Настоящий адрес статьи, если исходная ссылка вела через Google News.
    # Колонка добавлена позже таблицы: у развёрнутой базы её нет, а
    # пересоздавать таблицу ради неё — терять уже найденные превью.
    cols = {r[1] for r in con.execute("PRAGMA table_info(news_media)")}
    if "final_url" not in cols:
        con.execute("ALTER TABLE news_media ADD COLUMN final_url TEXT")
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
            attempts: int, final_url: str | None = None) -> None:
    """Записать найденное превью — или неудачу, чтобы не ходить сюда вечно.

    final_url — настоящий адрес статьи, если исходная ссылка вела через
    Google News. Сохраняется даже когда превью не нашлось: сама по себе
    прямая ссылка ценна, по ней человек попадает на статью, а не на
    промежуточную страницу.
    """
    con.execute(
        "INSERT OR REPLACE INTO news_media"
        "(news_uid, kind, url, path, attempts, ts, final_url) VALUES(?,'og',?,NULL,?,?,?)",
        (news_uid, url, attempts, int(time.time()), final_url))


def links_for(con: sqlite3.Connection, uids: list[str]) -> dict[str, str]:
    """{uid: настоящий адрес} — для тех новостей, чью ссылку удалось развернуть."""
    if not uids:
        return {}
    try:
        q = ",".join("?" * len(uids))
        rows = con.execute(
            f"SELECT news_uid, final_url FROM news_media "
            f"WHERE final_url IS NOT NULL AND news_uid IN ({q})", uids).fetchall()
    except sqlite3.OperationalError:
        return {}
    return dict(rows)


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
