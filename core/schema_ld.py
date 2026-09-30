"""
schema_ld.py — разметка schema.org (JSON-LD) для страниц сайта.

🔴 ЗАЧЕМ. Текстовый слой (tools/build_text_layer.js) дал краулеру, который
не исполняет JavaScript, сам текст. Разметка отвечает на второй вопрос:
ЧТО это за текст. Для ИИ-агента разница практическая: «46 абзацев подряд»
против «набор определений, у каждого есть термин, определение и адрес, по
которому на него можно сослаться». Замер 17.09.2026: на всём сайте была
одна разметка — FinancialService на главной, то есть ни курса, ни
глоссария, ни инструкций в машинном виде не существовало.

🔴 Источники — те же, что у живых страниц: заголовки глав из
i18n/site/*.json (ключи eduindex.chapters.N.*), термины из
web/assets/glossary*.json, шаги инструкций из web/data/guides/*.json.
Второй копии текста не заводим: копия расходится с оригиналом на первой
же правке.

🔴 Честность разметки. Платные главы помечаются isAccessibleForFree:false —
анониму сервер отдаёт пейволл, и утверждать обратное значит обещать
краулеру содержимое, которого он не получит. Рейтингов и отзывов о
брокерах здесь нет вовсе: их у нас не собрано, а выдуманный AggregateRating
— самый быстрый способ получить ручную санкцию и потерять доверие
одновременно.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from core import i18n

ДОМЕН = "https://lp.sbfconsult.com"
ОРГ = f"{ДОМЕН}/#org"          # @id организации, описанной на главной
КУРС = f"{ДОМЕН}/edu/#course"  # @id курса: главы ссылаются на него

_КОРЕНЬ = Path(__file__).parent.parent
_СЛОВАРИ = {"ru": "glossary.json", "ro": "glossary.ro.json", "en": "glossary.en.json"}

БРОКЕРЫ = ("xm", "naga", "fxpro", "instaforex", "avatrade")

# Первое звено крошек. Ключа nav.home в словарях нет (в шапке главная
# подписана «Сегодня»), а выдумывать перевод в разметке — плодить строку,
# которой нет на странице. Берём имя сайта: оно совпадает с og:site_name.
ИМЯ_САЙТА = "SBF Intelligence"

_кэш_словаря: dict[str, list] = {}
_кэш_гайда: dict[tuple[str, str], dict] = {}


def адрес(путь: str, язык: str) -> str:
    """Тот же разбор локали, что и в serve.py:_локальный_адрес.

    Дублируется сознательно и в одну сторону: модуль обязан собираться и
    без сервера (его зовут тесты и сборщики), а правило простое и
    проверяется tools/check_schema.py на совпадение с картой сайта.
    """
    if язык == "ru":
        return ДОМЕН + путь
    if путь.startswith("/edu/b"):
        return ДОМЕН + путь.replace("/edu/b", f"/edu/{язык}/b", 1)
    # 🔴 Слэш на конце обязателен и на входе: canonical оглавления —
    # /edu/, и Course.url без слэша для машины уже другая страница.
    # check_schema.py ловит именно это расхождение.
    if путь.rstrip("/") == "/edu":
        return f"{ДОМЕН}/{язык}/edu/"
    return f"{ДОМЕН}/{язык}{путь}"


def _скрипт(граф: list[dict]) -> str:
    данные = {"@context": "https://schema.org", "@graph": граф}
    текст = json.dumps(данные, ensure_ascii=False, indent=1)
    # </script> внутри строки закрыл бы тег раньше времени. В наших данных
    # его нет, но данные правятся людьми, а поломка была бы тихой.
    текст = текст.replace("</", "<\\/")
    return f'<script type="application/ld+json">\n{текст}\n</script>'


def _без_тегов(с: str) -> str:
    return re.sub(r"<[^>]+>", " ", с or "").replace("  ", " ").strip()


def _крошки(звенья: list[tuple[str, str]]) -> dict:
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": имя, "item": url}
            for i, (имя, url) in enumerate(звенья, 1)
        ],
    }


def _словарь(язык: str) -> list:
    if язык not in _кэш_словаря:
        п = _КОРЕНЬ / "web" / "assets" / _СЛОВАРИ.get(язык, _СЛОВАРИ["ru"])
        try:
            _кэш_словаря[язык] = json.loads(п.read_text("utf-8"))
        except Exception:
            _кэш_словаря[язык] = []
    return _кэш_словаря[язык]


def _гайд(брокер: str, язык: str) -> dict:
    ключ = (брокер, язык)
    if ключ not in _кэш_гайда:
        имя = f"{брокер}.json" if язык == "ru" else f"{брокер}.{язык}.json"
        п = _КОРЕНЬ / "web" / "data" / "guides" / имя
        try:
            _кэш_гайда[ключ] = json.loads(п.read_text("utf-8"))
        except Exception:
            _кэш_гайда[ключ] = {}
    return _кэш_гайда[ключ]


# ── страницы ────────────────────────────────────────────────────────────────

def курс(язык: str) -> str:
    """Оглавление курса: сам курс плюс список из пятнадцати глав."""
    главы = []
    for n in range(1, 16):
        название = i18n.t(f"eduindex.chapters.{n}.title", язык)
        главы.append({
            "@type": "ListItem",
            "position": n,
            "name": f"{n}. {название}",
            "item": адрес(f"/edu/b/{n}", язык),
        })
    return _скрипт([
        {
            "@type": "Course",
            "@id": КУРС,
            # <br> в заголовке — вёрстка, в разметке ему делать нечего.
            "name": _без_тегов(i18n.t("eduindex.hero.title", язык)),
            "description": i18n.t("eduindex.hero.desc", язык),
            "url": адрес("/edu/", язык),
            "inLanguage": язык,
            "provider": {"@id": ОРГ},
            "isAccessibleForFree": False,
            "hasPart": [{"@id": адрес(f"/edu/b/{n}", язык) + "#chapter"}
                        for n in range(1, 16)],
        },
        {"@type": "ItemList", "itemListOrder": "https://schema.org/ItemListOrderAscending",
         "numberOfItems": 15, "itemListElement": главы},
        _крошки([(ИМЯ_САЙТА, адрес("/", язык)),
                 (i18n.t("nav.edu", язык), адрес("/edu/", язык))]),
    ])


def глава(n: int, язык: str, бесплатная: bool) -> str:
    """Глава курса.

    🔴 `бесплатная` приходит из маршрута, а не вычисляется здесь по номеру:
    правило «главы с шестой платные» живёт в serve.py и однажды уже
    менялось. Два места с одним правилом разъезжаются молча.
    """
    название = i18n.t(f"eduindex.chapters.{n}.title", язык)
    подзаголовок = i18n.t(f"eduindex.chapters.{n}.sub", язык)
    url = адрес(f"/edu/b/{n}", язык)
    статья = {
        "@type": "LearningResource",
        "@id": url + "#chapter",
        "name": f"{n}. {название}",
        "headline": название,
        "description": подзаголовок,
        "url": url,
        "inLanguage": язык,
        "position": n,
        "learningResourceType": "Chapter",
        "isPartOf": {"@id": КУРС},
        "publisher": {"@id": ОРГ},
        "isAccessibleForFree": бесплатная,
    }
    if not бесплатная:
        # Google требует указать, какая часть страницы за платным доступом.
        # У нас за ним вся глава: анониму отдаётся пейволл целиком.
        статья["hasPart"] = {
            "@type": "WebPageElement",
            "isAccessibleForFree": False,
            "cssSelector": "#sbf-book-root",
        }
    return _скрипт([
        статья,
        _крошки([(ИМЯ_САЙТА, адрес("/", язык)),
                 (i18n.t("nav.edu", язык), адрес("/edu/", язык)),
                 (f"{n}. {название}", url)]),
    ])


def глоссарий(язык: str) -> str:
    """Все термины словаря как DefinedTermSet.

    Это единственный тип на сайте, который ложится на схему без натяжки:
    у термина есть имя, определение и собственный адрес с якорем — ровно
    то, чем агент может сослаться на конкретную статью, а не на страницу.
    """
    база = адрес("/glossary", язык)
    термины = []
    for т in _словарь(язык):
        слаг = т.get("slug") or ""
        определение = т.get("short") or т.get("full") or ""
        if not слаг or not определение:
            continue
        узел = {
            "@type": "DefinedTerm",
            "@id": f"{база}#gl-{слаг}",
            "name": т.get("term") or слаг,
            "description": определение,
            "termCode": слаг,
            "url": f"{база}#gl-{слаг}",
            "inDefinedTermSet": {"@id": база + "#set"},
        }
        синонимы = [с for с in (т.get("aliases") or []) if с]
        if синонимы:
            узел["alternateName"] = синонимы
        термины.append(узел)
    return _скрипт([
        {
            "@type": "DefinedTermSet",
            "@id": база + "#set",
            "name": i18n.t("glossary.h1", язык),
            "description": i18n.t("glossary.subtitle", язык),
            "url": база,
            "inLanguage": язык,
            "publisher": {"@id": ОРГ},
            "hasDefinedTerm": термины,
        },
        _крошки([(ИМЯ_САЙТА, адрес("/", язык)),
                 (i18n.t("glossary.h1", язык), база)]),
    ])


def брокеры(язык: str) -> str:
    """Страница подбора: список инструкций, без оценок и отзывов."""
    база = адрес("/brokers", язык)
    пункты = []
    for i, б in enumerate(БРОКЕРЫ, 1):
        д = _гайд(б, язык)
        пункты.append({
            "@type": "ListItem",
            "position": i,
            "name": д.get("name") or б.upper(),
            "item": адрес(f"/brokers/{б}", язык),
        })
    return _скрипт([
        {"@type": "ItemList", "name": i18n.t("brokers.h1", язык),
         "numberOfItems": len(пункты), "itemListElement": пункты},
        _крошки([(ИМЯ_САЙТА, адрес("/", язык)),
                 (i18n.t("brokers.h1", язык), база)]),
    ])


def инструкция(брокер: str, язык: str) -> str:
    """Инструкция по площадке: по HowTo на каждый процесс.

    Шаги берутся из тех же web/data/guides/*.json, из которых guide.js
    рисует страницу, — включая картинки, снятые вручную и датированные
    полем captured.
    """
    д = _гайд(брокер, язык)
    if not д:
        return ""
    url = адрес(f"/brokers/{брокер}", язык)
    имя = д.get("name") or брокер.upper()
    граф: list[dict] = []
    for процесс in д.get("processes") or []:
        шаги = []
        for блок in процесс.get("blocks") or []:
            if блок.get("type") != "steps":
                continue
            for э in блок.get("items") or []:
                подпись = (э.get("caption") or "").strip()
                if not подпись:
                    continue
                шаг = {"@type": "HowToStep", "position": len(шаги) + 1,
                       "text": подпись}
                if э.get("img"):
                    шаг["image"] = ДОМЕН + э["img"]
                шаги.append(шаг)
        if not шаги:
            continue
        граф.append({
            "@type": "HowTo",
            "@id": f"{url}#{процесс.get('key') or len(граф)}",
            "name": f"{имя} — {процесс.get('label') or ''}".strip(" —"),
            "inLanguage": язык,
            "totalTime": None,
            "step": шаги,
        })
    # totalTime мы не знаем — убираем ключ, а не пишем выдуманное значение.
    for узел in граф:
        узел.pop("totalTime", None)
    граф.append(_крошки([
        (ИМЯ_САЙТА, адрес("/", язык)),
        (i18n.t("brokers.h1", язык), адрес("/brokers", язык)),
        (имя, url),
    ]))
    return _скрипт(граф)
