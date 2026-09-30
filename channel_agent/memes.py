"""channel_agent/memes.py — пул картинок к постам и подбор под тему.

09.09.2026, просьба владельца: «собрать пул из подходящих для новостей
картинок-мемов».

КАК НАПОЛНЯТЬ. Раскладывать файлы по подпапкам /mnt/sbfdata/Контент/Мемы/,
где имя подпапки — тема: нефть, ставка, инфляция, крипта, доллар, паника,
скука, рост, падение. Никакого JSON руками: имя папки и есть тег, а имя файла
можно дополнить словами через дефис — они тоже станут тегами
(«нефть/танкер-горит.jpg» → теги «нефть», «танкер», «горит»).

КАК ПОДБИРАЕТСЯ. Модель, написав пост, отдаёт image_hint — 2–4 слова про
нужный образ. Совпадение считается по пересечению слов с тегами, с учётом
русской морфологии на уровне основы слова (сравниваем первые 5 букв: «нефти»
и «нефть» должны совпасть, а полноценный стеммер сюда тащить незачем).

ПОЧЕМУ НЕ ГЕНЕРИРОВАТЬ КАРТИНКУ КАЖДЫЙ РАЗ. Пул из готовых даёт узнаваемый
вид канала и не требует ни секунды ожидания при публикации. Генерация под
конкретный пост — отдельная история, и она не отменяет пул: одно другому не
мешает.
"""
from __future__ import annotations

import json
import logging
import random
import re
from pathlib import Path

log = logging.getLogger("channel_agent.memes")

MEMES_DIR = Path("/mnt/sbfdata/Контент/Мемы")
INDEX_PATH = MEMES_DIR / "index.json"
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# Сколько букв основы сравниваем. Пять — компромисс на живых словах:
# «инфляция/инфляции» совпадают, «ставка/ставок» тоже, а «нефть/нефтяник»
# уже нет, и это правильно.
_STEM = 5
_SPLIT_RE = re.compile(r"[^\w]+", re.UNICODE)


def _words(text: str) -> set[str]:
    return {w.lower() for w in _SPLIT_RE.split(text or "") if len(w) > 2}


def _stems(words: set[str]) -> set[str]:
    return {w[:_STEM] for w in words}


def scan(write: bool = True) -> list[dict]:
    """Пересобрать индекс из файловой структуры. Возвращает список записей."""
    if not MEMES_DIR.exists():
        log.warning("папка мемов %s не создана — постам картинки не положены", MEMES_DIR)
        return []
    items = []
    for path in sorted(MEMES_DIR.rglob("*")):
        if path.suffix.lower() not in EXTS or not path.is_file():
            continue
        folder_tags = _words(" ".join(p.name for p in path.relative_to(MEMES_DIR).parents
                                      if p.name))
        name_tags = _words(path.stem.replace("-", " ").replace("_", " "))
        items.append({"file": str(path), "tags": sorted(folder_tags | name_tags)})
    if write:
        try:
            INDEX_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        except OSError as e:
            log.warning("индекс мемов не записан: %s", e)
    return items


def _load() -> list[dict]:
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Индекса нет или он побился — пересобираем на лету. Дешевле, чем
        # оставить пост без картинки из-за отсутствующего файла.
        return scan()


def pick(hint: str, rubric: str | None = None) -> str | None:
    """Путь к картинке под подсказку модели. None — картинки нет.

    Пост без картинки публикуется нормально: пул наполняется постепенно, и
    отсутствие подходящего образа не повод задерживать текст.
    """
    items = _load()
    if not items:
        return None
    want = _stems(_words(f"{hint} {rubric or ''}"))
    if not want:
        return None

    scored = []
    for item in items:
        overlap = len(want & _stems(set(item["tags"])))
        if overlap:
            scored.append((overlap, item["file"]))
    if not scored:
        return None
    best = max(s[0] for s in scored)
    # Среди равных — случайный: одна и та же картинка на каждом посте про
    # нефть примелькается за неделю.
    return random.choice([f for s, f in scored if s == best])
