"""
i18n.py — переводы "шапки" сайта (навигация/кнопки/формы/дисклеймеры/глоссарий).

НЕ для контента курса (15 глав) — там свой механизм (STRINGS-объект внутри
каждой JSX-главы, см. web/book/edu_book_*.html и _build_edu_page в serve.py).
Здесь — короткие переиспользуемые строки, отдаём и в Jinja (server-side), и
в браузер (assets/i18n.js достаёт /i18n/site.json и использует тот же t()
на клиенте — единый набор ключей, два места использования).

Формат словаря: плоский dict[key] -> str, файлы i18n/site/{lang}.json.
Добавление нового языка = новый JSON-файл с теми же ключами, без изменений
в этом модуле или в вызывающем коде.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("i18n")

DEFAULT_LANG = "ru"
SUPPORTED_LANGS = ("ru", "ro", "en")

_I18N_DIR = Path(__file__).parent.parent / "i18n" / "site"
_cache: dict[str, dict[str, str]] = {}
_missing_logged: set[tuple[str, str]] = set()


def _load(lang: str) -> dict[str, str]:
    if lang in _cache:
        return _cache[lang]
    path = _I18N_DIR / f"{lang}.json"
    try:
        data = json.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        data = {}
    except Exception as e:
        log.error("Не удалось прочитать %s: %s", path, e)
        data = {}
    _cache[lang] = data
    return data


def reload_cache() -> None:
    """Для разработки/после правки JSON без рестарта процесса."""
    _cache.clear()


def t(key: str, lang: str = DEFAULT_LANG, **kwargs) -> str:
    """Строка по ключу на языке lang. Если ключа нет в целевом языке —
    молча (но с логом) откатываемся на русский, а если и там нет — возвращаем
    сам ключ (заметно в интерфейсе, но не ломает страницу пустым местом)."""
    lang = lang if lang in SUPPORTED_LANGS else DEFAULT_LANG
    val = _load(lang).get(key)
    if val is None and lang != DEFAULT_LANG:
        val = _load(DEFAULT_LANG).get(key)
        if val is not None and (lang, key) not in _missing_logged:
            _missing_logged.add((lang, key))
            log.warning("i18n: ключ %r отсутствует для lang=%s, откат на %s", key, lang, DEFAULT_LANG)
    if val is None:
        if (lang, key) not in _missing_logged:
            _missing_logged.add((lang, key))
            log.error("i18n: ключ %r отсутствует нигде (lang=%s)", key, lang)
        return key
    if kwargs:
        try:
            return val.format(**kwargs)
        except Exception:
            return val
    return val


def lang_from_path(path: str) -> tuple[str, str]:
    """'/ro/register' -> ('ro', '/register'). '/register' -> ('ru', '/register').
    Единая точка разбора префикса языка — используется в serve.py's do_GET/do_POST
    вместо разбросанных проверок startswith('/ro/') по всему роутеру."""
    for lang in SUPPORTED_LANGS:
        if lang == DEFAULT_LANG:
            continue
        prefix = f"/{lang}"
        if path == prefix:
            return lang, "/"
        if path.startswith(prefix + "/"):
            return lang, path[len(prefix):]
    return DEFAULT_LANG, path


def all_dict(lang: str) -> dict[str, str]:
    """Русский словарь + поверх него — переопределения целевого языка (там,
    где перевод есть). Используется для отдачи полного JSON клиенту
    (assets/i18n.js) — на клиенте те же самые правила fallback, без лишнего
    сетевого похода за русским словарём отдельно."""
    lang = lang if lang in SUPPORTED_LANGS else DEFAULT_LANG
    merged = dict(_load(DEFAULT_LANG))
    if lang != DEFAULT_LANG:
        merged.update(_load(lang))
    return merged
