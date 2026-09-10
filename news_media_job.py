#!/usr/bin/env python3
"""news_media_job.py — превью к новостям для ленты по активу.

Ходит по свежим новостям, у которых есть тег инструмента, и достаёт со
страницы издания og:image — ту самую картинку, которую издание само отдаёт
соцсетям. Ссылка складывается в news_media и потом отдаётся витриной.

🔴 ЭТО ЗАДАЧА, КОТОРАЯ ХОДИТ НАРУЖУ, НА ЧУЖИЕ САЙТЫ. Отсюда правила:

  • читаем только начало страницы (og-теги живут в <head>), а не весь
    документ: заголовок статьи весит килобайты, сама статья — мегабайты;
  • пауза между обращениями к ОДНОМУ домену: половина ленты приходит с
    десятка изданий, и без паузы это выглядело бы как маленький ддос;
  • честный User-Agent с адресом сайта, чтобы админ издания видел, кто
    пришёл, и мог написать;
  • потолок на прогон. Задача не обязана закрыть всё за раз — что не успела,
    возьмёт через 20 минут.

🔴 НЕУДАЧА ЗАПОМИНАЕТСЯ. Без счётчика попыток задача каждый прогон долбилась
бы в одни и те же мёртвые ссылки вместо новых новостей — тихая деградация,
при которой процесс работает, а результат не растёт.

Запуск:  python3 news_media_job.py [--limit 150] [--verbose]
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core import news_media  # noqa: E402
from core.config import DB_PATH  # noqa: E402

log = logging.getLogger("news_media_job")

FRESH_HOURS = 72
# Потолок на прогон. Держится высоким сознательно: 43% кандидатов отсеиваются
# по домену БЕЗ похода наружу (см. SKIP_DOMAINS), так что реальных запросов
# выходит впятеро меньше числа в лимите.
DEFAULT_LIMIT = 400
READ_BYTES = 300_000        # начала страницы хватает на og-теги
REQUEST_TIMEOUT = 12
DOMAIN_DELAY = 1.5          # секунд между двумя обращениями к одному домену
UA = ("Mozilla/5.0 (compatible; SBFPreviewBot/1.0; "
      "+https://lp.sbfconsult.com/ - preview images only)")


def _candidates(con, limit: int) -> list[tuple[str, str]]:
    """Свежие новости с тегом инструмента, у которых картинки ещё нет."""
    return con.execute(
        """SELECT s.uid, s.url
           FROM news_instrument_tags t
           JOIN signals s ON s.uid = t.news_uid
           LEFT JOIN news_media m ON m.news_uid = s.uid
           WHERE s.first_seen >= datetime('now', ?)
             AND s.url <> ''
             AND (m.news_uid IS NULL
                  OR (m.url IS NULL AND m.path IS NULL AND m.attempts < ?))
           GROUP BY s.uid
           ORDER BY s.first_seen DESC
           LIMIT ?""",
        (f"-{FRESH_HOURS} hours", news_media.MAX_ATTEMPTS, limit)).fetchall()


def _attempts_so_far(con, uid: str) -> int:
    row = con.execute("SELECT attempts FROM news_media WHERE news_uid=?", (uid,)).fetchone()
    return row[0] if row else 0


def _skip_domain(domain: str) -> bool:
    """Домены, где превью нет или оно за логином (X, Telegram)."""
    return not domain or domain in news_media.SKIP_DOMAINS


_LOGO_MAX_BYTES = 220_000
_LOGO_EXT = {"image/png": ".png", "image/x-icon": ".ico", "image/vnd.microsoft.icon": ".ico",
             "image/svg+xml": ".svg", "image/jpeg": ".jpg", "image/webp": ".webp"}


def _fetch_logos(con, session, verbose: bool) -> int:
    """Логотип издания — для новостей, у которых фотографии не будет никогда.

    43% ленты приходит ссылками news.google.com: адрес статьи оттуда не
    достать, страница рисуется скриптом, og-тегов нет. Логотип не притворяется
    иллюстрацией к событию, он говорит «это написал Reuters» — и домен издания
    у нас уже сохранён сборщиком в raw.domain.
    """
    news_media.ensure_logo_schema(con)
    rows = con.execute(
        """SELECT DISTINCT json_extract(s.raw, '$.domain') AS d
           FROM news_instrument_tags t JOIN signals s ON s.uid = t.news_uid
           LEFT JOIN source_logos g ON g.domain = json_extract(s.raw, '$.domain')
           WHERE s.first_seen >= datetime('now', ?)
             AND d IS NOT NULL AND d <> ''
             AND (g.domain IS NULL OR (g.path IS NULL AND g.attempts < ?))
           LIMIT 60""",
        (f"-{FRESH_HOURS} hours", news_media.MAX_ATTEMPTS)).fetchall()

    out_dir = ROOT / "web" / news_media.LOGO_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    got = 0
    for (domain,) in rows:
        icon_url = None
        try:
            home = f"https://{domain}/"
            with session.get(home, timeout=REQUEST_TIMEOUT, stream=True,
                             allow_redirects=True) as r:
                if r.status_code == 200 and "html" in (r.headers.get("Content-Type") or "").lower():
                    chunk = r.raw.read(READ_BYTES, decode_content=True) or b""
                    icon_url = news_media.extract_icon(
                        chunk.decode(r.encoding or "utf-8", errors="replace"), r.url)
            # /favicon.ico существует почти везде и когда <link rel=icon> нет.
            icon_url = icon_url or f"https://{domain}/favicon.ico"
            ri = session.get(icon_url, timeout=REQUEST_TIMEOUT)
            ctype = (ri.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            ext = _LOGO_EXT.get(ctype)
            if ri.status_code == 200 and ext and 0 < len(ri.content) <= _LOGO_MAX_BYTES:
                name = domain.replace("/", "_") + ext
                (out_dir / name).write_bytes(ri.content)
                con.execute(
                    "INSERT OR REPLACE INTO source_logos(domain, path, attempts, ts) "
                    "VALUES(?,?,0,?)",
                    (domain, f"/{news_media.LOGO_DIR}/{name}", int(time.time())))
                got += 1
                continue
        except Exception as e:
            log.debug("логотип %s: %s", domain, str(e)[:100])
        con.execute(
            "INSERT INTO source_logos(domain, path, attempts, ts) VALUES(?,NULL,1,?) "
            "ON CONFLICT(domain) DO UPDATE SET attempts=attempts+1, ts=excluded.ts",
            (domain, int(time.time())))
    con.commit()
    if verbose:
        print(f"логотипы: проверено {len(rows)} доменов, получено {got}")
    return got


def run(limit: int = DEFAULT_LIMIT, verbose: bool = False) -> int:
    import requests

    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    news_media.ensure_schema(con)

    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "text/html,*/*"})

    pairs = _candidates(con, limit)
    if not pairs:
        if verbose:
            print("новостей без картинки нет")
        _fetch_logos(con, session, verbose)
        con.close()
        return 0

    last_hit: dict[str, float] = defaultdict(float)
    found = skipped = failed = 0

    for uid, url in pairs:
        domain = news_media.domain_of(url)
        if _skip_domain(domain):
            news_media.save_og(con, uid, None, news_media.MAX_ATTEMPTS)
            skipped += 1
            continue

        wait = DOMAIN_DELAY - (time.time() - last_hit[domain])
        if wait > 0:
            time.sleep(wait)
        last_hit[domain] = time.time()

        image = None
        try:
            # stream=True + чтение куска: без него requests тянет статью целиком.
            with session.get(url, timeout=REQUEST_TIMEOUT, stream=True,
                             allow_redirects=True) as r:
                ctype = (r.headers.get("Content-Type") or "").lower()
                if r.status_code == 200 and "html" in ctype:
                    chunk = r.raw.read(READ_BYTES, decode_content=True) or b""
                    html = chunk.decode(r.encoding or "utf-8", errors="replace")
                    image = news_media.extract(html, r.url)
        except Exception as e:
            log.debug("%s: %s", domain, str(e)[:120])

        if image:
            news_media.save_og(con, uid, image, 0)
            found += 1
        else:
            news_media.save_og(con, uid, None, _attempts_so_far(con, uid) + 1)
            failed += 1
        con.commit()

    _fetch_logos(con, session, verbose)
    con.close()
    if verbose:
        print(f"проверено {len(pairs)}: превью найдено {found}, "
              f"без превью {failed}, домен пропущен {skipped}")
    return found


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    raise SystemExit(0 if run(a.limit, a.verbose) >= 0 else 1)
