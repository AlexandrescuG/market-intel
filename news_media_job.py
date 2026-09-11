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

🔴 ПРОПУСКНАЯ СПОСОБНОСТЬ ДОЛЖНА БЫТЬ ВЫШЕ ПРИТОКА, ИНАЧЕ ЗАДАЧА БЕСПОЛЕЗНА.
Замер 11.09.2026: приток — 807 тегированных новостей со ссылкой Google в час,
обрабатывалось 240 (80 за прогон × 3 прогона). Очередь росла на 570 в час, а
на витрине картинка была у 3–7 карточек из 30. При этом прогон длился 14 из
20 минут и тратил 2,75 секунды процессорного времени: задача не считала, а
ждала — по очереди, в один поток.

Отсюда два решения ниже:
  • ожидание распараллелено. Вежливость измеряется паузой между обращениями к
    ОДНОМУ домену — это не повод ждать чужой сайт, пока отвечает другой;
  • в базу пишет только главный поток. Рабочие ходят наружу и возвращают
    результат; sqlite при этом не видит конкуренции внутри задачи.

🔴 «ПРОВЕРЕНО 400» БЫЛО НЕПРАВДОЙ. Старая строка отчёта печатала размер
выборки, а не число обработанных: из 400 кандидатов реально трогалось 106, а
294 молча пропускались по исчерпанию бюджета. Метрика показывала работу,
которой не было. Теперь печатается обработано / осталось в очереди.

Запуск:  python3 news_media_job.py [--limit 150] [--verbose]
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core import gnews_resolve, news_media  # noqa: E402
from core.config import DB_PATH  # noqa: E402

log = logging.getLogger("news_media_job")

FRESH_HOURS = 72
# Потолок на прогон. Считается от притока, а не от ощущения: 807 ссылок в час
# приходит, три прогона в час — значит за прогон нужно закрывать 270, и запас
# сверху, чтобы разбирать накопленное, а не идти вровень.
DEFAULT_LIMIT = 1200
# Прогон обязан закончиться раньше следующего запуска по таймеру (20 минут),
# иначе задачи наслаиваются и ходят наружу вдвоём. Замер 11.09.2026 на живом
# потоке: 699 новостей за 283 секунды, 0,4 с на штуку. Тысяча двести
# укладывается в восемь минут, а потолок ниже страхует от медленного дня.
#
# Приток при этом — около 270 новостей за те же двадцать минут. Запас взят не
# «на всякий случай», а чтобы разбирать накопленные шесть тысяч: когда очередь
# опустеет, выборка просто перестанет набираться до потолка.
MAX_RUNTIME = 900
READ_BYTES = 300_000        # начала страницы хватает на og-теги
REQUEST_TIMEOUT = 12
DOMAIN_DELAY = 1.5          # секунд между двумя обращениями к одному домену
# Пауза у самого Google отдельная и короче. Она нужна не чтобы поберечь
# Google — тут наши сотни запросов в час теряются в его миллиардах, — а чтобы
# не выглядеть всплеском с одного адреса. Для издания на своём хостинге
# полторы секунды остаются.
GNEWS_DELAY = 0.4
# Сколько ссылок Google News разворачиваем за прогон. Потолок остаётся: это
# два запроса на ссылку, и падать в Google всем объёмом очереди незачем.
GNEWS_BUDGET = 1200
# Одновременных походов наружу. Ограничение не в процессоре (прогон тратил
# 2,75 с CPU за 14 минут), а в приличиях: это число разных сайтов, которые мы
# держим открытыми разом.
WORKERS = 8
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


def _attempts_map(con, uids: list[str]) -> dict[str, int]:
    """Сколько раз уже пробовали — одним запросом на всю выборку.

    Раньше это был отдельный SELECT на каждую новость внутри цикла. При
    выборке в девятьсот штук это девятьсот обращений к базе, по которой
    одновременно пишут коллекторы, — лишний повод получить «database is
    locked» на ровном месте.
    """
    out: dict[str, int] = {}
    for i in range(0, len(uids), 400):
        порция = uids[i:i + 400]
        q = ",".join("?" * len(порция))
        rows = con.execute(
            f"SELECT news_uid, attempts FROM news_media WHERE news_uid IN ({q})",
            порция).fetchall()
        out.update(dict(rows))
    return out


class _Вежливость:
    """Пауза между обращениями к одному домену — но не между разными.

    🔴 Старый код держал одну общую очередь: пока мы ждали полторы секунды
    перед вторым обращением к reuters.com, простаивали и все остальные
    издания. Вежливость — свойство пары «мы ↔ этот сайт», и считать её надо
    по домену, иначе она превращается в глобальный тормоз.
    """

    def __init__(self) -> None:
        self._последний: dict[str, float] = defaultdict(float)
        self._замки: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._общий = threading.Lock()

    def ждать(self, domain: str, delay: float) -> None:
        with self._общий:
            замок = self._замки[domain]
        with замок:
            пауза = delay - (time.time() - self._последний[domain])
            if пауза > 0:
                time.sleep(пауза)
            self._последний[domain] = time.time()


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


def _добыть(uid: str, url: str, session, вежливость: _Вежливость,
           бюджет: "_Бюджет", дедлайн: float) -> tuple | None:
    """Один поход наружу. Возвращает (uid, image, final_url, развернули) или None.

    В базу отсюда не пишем: это рабочий поток. Всё, что он узнал, уезжает в
    главный поток одной записью.
    """
    if time.time() > дедлайн:
        return None                # хвост достанется следующему прогону
    domain = news_media.domain_of(url)
    final_url = None
    развернули = False

    if gnews_resolve.is_google_link(url):
        if not бюджет.взять():
            return None            # хвост достанется следующему прогону
        вежливость.ждать(domain, GNEWS_DELAY)
        final_url = gnews_resolve.resolve(url, session)
        if not final_url:
            return (uid, None, None, False)
        развернули = True
        url = final_url
        domain = news_media.domain_of(url)

    вежливость.ждать(domain, DOMAIN_DELAY)
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
    return (uid, image, final_url, развернули)


class _Бюджет:
    """Потолок на походы к Google, общий на все потоки."""

    def __init__(self, сколько: int) -> None:
        self._осталось = сколько
        self._замок = threading.Lock()

    def взять(self) -> bool:
        with self._замок:
            if self._осталось <= 0:
                return False
            self._осталось -= 1
            return True


def _записать(con, партия: list[tuple]) -> None:
    """🔴 Неудачная запись не должна ронять прогон.

    11.09.2026 прогон упал с «database is locked» на save_og и потерял всё,
    что успел собрать за четырнадцать минут походов наружу. По этой базе
    одновременно пишут коллекторы, и блокировка тут — рабочий режим, а не
    исключительная ситуация. Тот же класс ошибки, что и в кэше переводов.
    """
    try:
        con.executemany(
            "INSERT OR REPLACE INTO news_media"
            "(news_uid, kind, url, path, attempts, ts, final_url) "
            "VALUES(?,'og',?,NULL,?,?,?)", партия)
        con.commit()
    except Exception as e:
        log.warning("превью собраны, но не записаны (%d шт.): %s",
                    len(партия), str(e)[:120])


def run(limit: int = DEFAULT_LIMIT, verbose: bool = False) -> int:
    import requests

    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    news_media.ensure_schema(con)

    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "text/html,*/*"})
    # Пул под число рабочих: иначе requests закрывает и переоткрывает
    # соединения, и выигрыш от потоков съедается рукопожатиями TLS.
    адаптер = requests.adapters.HTTPAdapter(pool_connections=WORKERS * 2,
                                            pool_maxsize=WORKERS * 4)
    session.mount("https://", адаптер)
    session.mount("http://", адаптер)

    pairs = _candidates(con, limit)
    if not pairs:
        if verbose:
            print("новостей без картинки нет")
        _fetch_logos(con, session, verbose)
        con.close()
        return 0

    # Домены, куда ходить незачем, закрываем сразу и без сети.
    к_работе, пропущено = [], []
    for uid, url in pairs:
        if _skip_domain(news_media.domain_of(url)):
            пропущено.append((uid, None, news_media.MAX_ATTEMPTS,
                              int(time.time()), None))
        else:
            к_работе.append((uid, url))
    if пропущено:
        _записать(con, пропущено)

    попытки = _attempts_map(con, [uid for uid, _ in к_работе])
    вежливость, бюджет = _Вежливость(), _Бюджет(GNEWS_BUDGET)
    начало = time.time()
    дедлайн = начало + MAX_RUNTIME

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        результаты = list(pool.map(
            lambda p: _добыть(p[0], p[1], session, вежливость, бюджет, дедлайн),
            к_работе))

    found = failed = resolved = 0
    партия = []
    now = int(time.time())
    for r in результаты:
        if r is None:
            continue               # бюджет исчерпан, вернёмся через 20 минут
        uid, image, final_url, развернули = r
        resolved += 1 if развернули else 0
        if image:
            партия.append((uid, image, 0, now, final_url))
            found += 1
        else:
            # Превью не нашлось, но развёрнутый адрес сохраняем: по нему
            # человек попадёт на статью, а не на промежуточную страницу.
            партия.append((uid, None, попытки.get(uid, 0) + 1, now, final_url))
            failed += 1
    if партия:
        _записать(con, партия)

    _fetch_logos(con, session, verbose)
    # 🔴 Отчёт по обработанному и по остатку, а не по размеру выборки: старая
    # строка печатала «проверено 400», когда реально трогалось 106.
    очередь = con.execute(
        """SELECT COUNT(DISTINCT s.uid) FROM news_instrument_tags t
           JOIN signals s ON s.uid = t.news_uid
           LEFT JOIN news_media m ON m.news_uid = s.uid
           WHERE s.first_seen >= datetime('now', ?) AND s.url <> ''
             AND (m.news_uid IS NULL
                  OR (m.url IS NULL AND m.path IS NULL AND m.attempts < ?))""",
        (f"-{FRESH_HOURS} hours", news_media.MAX_ATTEMPTS)).fetchone()[0]
    con.close()
    if verbose:
        print(f"обработано {found + failed} за {time.time() - начало:.0f} с: "
              f"превью найдено {found}, без превью {failed}, "
              f"домен пропущен {len(пропущено)}, "
              f"ссылок Google развёрнуто {resolved}; "
              f"в очереди осталось {очередь}")
    return found


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    raise SystemExit(0 if run(a.limit, a.verbose) >= 0 else 1)
