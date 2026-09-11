"""core/gnews_resolve.py — настоящий адрес статьи из ссылки Google News.

ЗАЧЕМ. 43% новостей приходят ссылками news.google.com. Такая ссылка в
браузере доезжает до издания, но сервером не разворачивается: редиректа нет,
страница отдаёт 200 и рисуется скриптом. Из-за этого у почти половины ленты
не было ни превью (og-теги лежат на странице издания), ни честной ссылки —
клик вёл на промежуточную страницу Google.

КАК ЭТО РАБОТАЕТ. Ровно так же, как в браузере, только без браузера:

  1. Забираем страницу ссылки. В ней у элемента c-wiz лежат два атрибута —
     `data-n-a-sg` (подпись) и `data-n-a-ts` (метка времени). Токен статьи
     берётся из самого адреса.
  2. Этими тремя значениями обращаемся к той же ручке, к которой обращается
     страница: news.google.com/_/DotsSplashUi/data/batchexecute. В ответе —
     адрес издания.

🔴 ЭТО НЕДОКУМЕНТИРОВАННАЯ РУЧКА. Она может измениться в любой день, и тогда
resolve() начнёт возвращать None. Поэтому:

  • неудача — штатный исход, а не исключение: вызывающий помечает попытку и
    живёт дальше, показывая логотип издания вместо фотографии;
  • сюда встроен счётчик подряд идущих неудач. Если механизм сломается
    целиком, в логах появится явное сообщение, а не тихое падение доли
    превью, которое заметят через месяц (класс ошибки «молчаливая
    деградация», встречался в этом проекте уже трижды);
  • два запроса на ссылку — это дорого. Темп ограничивает вызывающий,
    и обрабатываются только свежие новости, которые реально показываются.

Ничего, кроме адреса, отсюда не берётся: ни содержимое статьи, ни обход
платного доступа. Ссылка у нас уже есть — мы лишь узнаём, куда она ведёт.
"""
from __future__ import annotations

import json
import logging
import re

log = logging.getLogger("gnews")

BATCH_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

_RE_SIG = re.compile(r'data-n-a-sg="([^"]+)"')
_RE_TS = re.compile(r'data-n-a-ts="(\d+)"')
_RE_URL = re.compile(r'https?://(?!\S*(?:google\.com|gstatic\.com))[\w\-./%?=&#:+~,]{16,}')

# Сколько неудач подряд считаем поломкой механизма, а не невезением.
_ПОРОГ_ТРЕВОГИ = 25
_подряд_неудач = 0
_предупредили = False


def is_google_link(url: str) -> bool:
    return "news.google.com" in (url or "")


def _token(url: str) -> str:
    return url.rstrip("/").split("/")[-1].split("?")[0]


def resolve(url: str, session) -> str | None:
    """Адрес издания или None. None — обычный результат, не ошибка."""
    global _подряд_неудач, _предупредили
    try:
        r = session.get(url, timeout=20, headers={"User-Agent": UA,
                                                  "Accept-Language": "en-US,en;q=0.9"})
        if r.status_code != 200:
            return _неудача(f"страница отдала {r.status_code}")
        sig = _RE_SIG.search(r.text)
        ts = _RE_TS.search(r.text)
        if not (sig and ts):
            return _неудача("на странице нет подписи или метки времени")

        payload = ["Fbv4je", json.dumps([
            "garturlreq",
            [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None,
              None, None, None, None, 0, 1],
             "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
            _token(url), int(ts.group(1)), sig.group(1)])]
        rr = session.post(
            BATCH_URL, data={"f.req": json.dumps([[payload]])}, timeout=20,
            headers={"User-Agent": UA,
                     "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        if rr.status_code != 200:
            return _неудача(f"batchexecute отдал {rr.status_code}")
        m = _RE_URL.search(rr.text)
        if not m:
            return _неудача("в ответе нет адреса издания")
        _подряд_неудач = 0
        _предупредили = False
        return m.group(0)[:600]
    except Exception as e:
        return _неудача(str(e)[:90])


def _неудача(почему: str) -> None:
    """🔴 Молчаливая деградация ловится здесь, а не глазами через месяц."""
    global _подряд_неудач, _предупредили
    _подряд_неудач += 1
    log.debug("не развернул ссылку: %s", почему)
    if _подряд_неудач >= _ПОРОГ_ТРЕВОГИ and not _предупредили:
        _предупредили = True
        log.error("Google News: %d неудач подряд (последняя — %s). Похоже, ручка "
                  "изменилась: превью и прямые ссылки для половины ленты "
                  "перестанут появляться. Смотреть core/gnews_resolve.py",
                  _подряд_неудач, почему)
    return None
