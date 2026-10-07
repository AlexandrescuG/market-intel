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

from core import translator_quota

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
# 🔴 Замер 30.09.2026, оба переводчика на живых текстах:
#     google   en→ru  ОТКАЗ  TooManyRequests («you made too many requests»)
#     google   ru→en  ОТКАЗ  то же
#     mymemory en→ru  ОК 1.49 с  «Золото падает, поскольку доллар укрепляется…»
#     mymemory ru→en  ОК 0.65 с  «Metals under pressure: gold 4 179, silver 61.08»
#     mymemory ru→ro  ОК 0.56 с  «Metale sub presiune: aur 4 179, argint 61,08»
# То есть цепочка РАБОТАЕТ, и отказ Google теперь другого рода: это лимит
# запросов, а не страница ошибки. Пустой кэш переводов объяснялся не
# поломкой, а тем, что единственный вызывающий (/api/pulse/translate) стоит
# за регистрацией и его просто никто не открывал.
#
# Квота MyMemory без представления — около 5000 символов в сутки на адрес,
# с параметром `de=<почта>` поднимается до 50 000. Почту в запрос НЕ
# подставляем: это персональные данные в URL, и решение не моё.
#
# Поэтому переводчик не один, а список. Google остаётся первым — он быстрее и
# может вернуться; когда он отказывает, его на время выключает предохранитель
# ниже, и работа идёт через запасной.
_МЁРТВ_НА_СЕК = 600
_отключён_до: dict[str, float] = {}

# MyMemory требует коды вида en-GB, а не en.
_MYMEMORY_КОД = {"ru": "ru-RU", "ro": "ro-RO", "en": "en-GB"}


# ── Платные службы с бесплатным тарифом ─────────────────────────────────────
#
# 🔴 DeepL В ЦЕПОЧКЕ НЕТ, ХОТЯ ПО КАЧЕСТВУ ОН БЫЛ БЫ ПЕРВЫМ.
# В июле 2026 DeepL закрыл тариф API Free (500 тыс. знаков КАЖДЫЙ месяц) и
# заменил его на Developer: миллион знаков ОДИН РАЗ, без сброса. Для
# постоянной работы это тупик — несколько недель лучшего качества, потом
# ключ гаснет навсегда, и цепочка молча съезжает на следующего. Решение
# владельца 07.10.2026: не подключать.
#
# Остаются два платных с настоящей месячной квотой. Azure первым не только
# по качеству: у него 2 млн знаков в месяц против 500 тыс. у Google Cloud,
# и начиная с него мы бережём более скудный бюджет на потом.
#
# Ключи берутся из окружения и НИКОГДА не попадают ни в аргументы команд,
# ни в логи. Вводит их владелец сам — ops/translators_setup.sh.
# Нет ключа — провайдер молча пропускается: это штатное состояние до
# настройки, а не ошибка.
_КЛЮЧ = {
    "azure":        "AZURE_TRANSLATOR_KEY",
    "google_cloud": "GOOGLE_TRANSLATE_API_KEY",
}

# Признаки «кончилась месячная квота» в ответе службы. Отличать это от
# обычного отказа обязательно: отказ стоит повторить через десять минут,
# исчерпанную квоту — только первого числа.
_ПРИЗНАК_КВОТЫ = (
    "456",                      # DeepL: Quota Exceeded, отдельный код
    "quota",                    # DeepL и Google: «quota exceeded»
    "exceeded",                 # Azure: «exceeded free tier»
    "out of credits",
    "403001",                   # Azure: ключ заблокирован по превышению
    "dailylimitexceeded",       # Google Cloud
    "userratelimitexceeded",
)


class ИсчерпанаКвота(RuntimeError):
    """Служба сказала, что месячный лимит выбран. Не повторять до месяца."""


def _это_квота(e: Exception) -> bool:
    сообщение = f"{type(e).__name__} {e}".lower()
    return any(п in сообщение for п in _ПРИЗНАК_КВОТЫ)


def _azure(тексты: list[str], lang: str) -> list[str]:
    """Azure Translator, тариф F0 — два миллиона знаков в месяц."""
    import os

    from deep_translator import MicrosoftTranslator
    tr = MicrosoftTranslator(source="auto", target=lang,
                             api_key=os.environ["AZURE_TRANSLATOR_KEY"],
                             region=os.environ.get("AZURE_TRANSLATOR_REGION") or None)
    out = []
    for t in тексты:
        try:
            out.append(tr.translate(t) or "")
        except Exception as e:                  # noqa: BLE001
            if _это_квота(e):
                raise ИсчерпанаКвота(str(e)[:200]) from e
            out.append("")
    return out


def _google_cloud(тексты: list[str], lang: str) -> list[str]:
    """Google Cloud Translation v2 — голым REST, без новой зависимости.

    🔴 В deep_translator есть GoogleTranslator, но это НЕ Cloud API: он
    скрапит публичную страницу и живёт по лимиту запросов с адреса (с
    11.09 отвечает TooManyRequests). Cloud API — другая служба, с ключом и
    месячной квотой, и путать их нельзя.

    v2 принимает партию целиком: одним запросом на все двенадцать
    заголовков вместо двенадцати запросов.
    """
    import json as _json
    import os
    import urllib.error
    import urllib.parse
    import urllib.request

    тело = urllib.parse.urlencode(
        [("q", t) for t in тексты] + [("target", lang), ("format", "text")]
    ).encode("utf-8")
    запрос = urllib.request.Request(
        # 🔴 Ключ уходит заголовком, а не параметром в URL: параметр осел бы
        # в журналах прокси и в истории. Google принимает оба способа.
        "https://translation.googleapis.com/language/translate/v2",
        data=тело, method="POST",
        headers={"X-Goog-Api-Key": os.environ["GOOGLE_TRANSLATE_API_KEY"],
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(запрос, timeout=TIMEOUT_SEC * 2) as r:
            ответ = _json.loads(r.read())
    except urllib.error.HTTPError as e:
        текст = e.read().decode("utf-8", "replace")[:300]
        if e.code == 403 or _это_квота(Exception(текст)):
            raise ИсчерпанаКвота(f"{e.code} {текст}") from e
        raise
    строки = ответ.get("data", {}).get("translations", [])
    return [(с.get("translatedText") or "") for с in строки] or [""] * len(тексты)


def _google(тексты: list[str], lang: str) -> list[str]:
    from deep_translator import GoogleTranslator
    return GoogleTranslator(source="auto", target=lang).translate_batch(тексты)


def _mymemory(тексты: list[str], lang: str) -> list[str]:
    """Переводит партию параллельно: своего batch у MyMemory нет.

    Четыре потока, а не двенадцать: сервис бесплатный и общий, и выжимать из
    него всё — верный способ получить блокировку по адресу. При 700 мс на
    заголовок дюжина укладывается примерно в две секунды.

    🔴 ЯЗЫК ИСТОЧНИКА ОПРЕДЕЛЯЕТСЯ ПО КАЖДОМУ ТЕКСТУ, А НЕ ЗАШИТ.
    До 30.09.2026 здесь стояло `source="en-GB"` намертво. У MyMemory нет
    режима "auto", и русский заголовок уезжал к нему с пометкой «это
    английский» — то есть перевод С русского был сломан по построению, ещё
    до всякого отказа службы. Заметить это было неоткуда: запасной
    переводчик включается, только когда отказал Google, а к тому моменту
    ленту уже никто не открывал.
    Партия бывает смешанной (русские и английские заголовки рядом), поэтому
    решение принимается на текст, а переводчик заводится на пару языков.
    """
    from concurrent.futures import ThreadPoolExecutor

    from deep_translator import MyMemoryTranslator

    цель = _MYMEMORY_КОД.get(lang, "ru-RU")

    def один(t: str) -> str:
        источник = _MYMEMORY_КОД.get(detect(t), "en-GB")
        if источник == цель:
            return ""   # переводить нечего: текст уже на нужном языке
        try:
            # 🔴 ОБЪЕКТ ПЕРЕВОДЧИКА СОЗДАЁТСЯ НА КАЖДЫЙ ТЕКСТ, А НЕ ОДИН НА
            # ПАРТИЮ. Первая версия держала его в lru_cache — то есть четыре
            # потока звали .translate() на ОДНОМ экземпляре. deep_translator
            # хранит параметры запроса в полях объекта, и они перетирались
            # между потоками: в брифе 30.09 первый пункт контекста приехал с
            # переводом ВТОРОГО, и по-русски это выглядело осмысленным
            # текстом — просто не тем. Тот же класс ошибки уже был с
            # yfinance, который при конкурентных вызовах отдавал всем
            # активам серебро. Создание объекта стоит микросекунды, гонка —
            # подменённого факта в утреннем брифе.
            return MyMemoryTranslator(source=источник, target=цель).translate(t)
        except Exception:
            return ""

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(один, тексты))


# Порядок = порядок попыток. Платные с ключом идут первыми, бесплатные
# остаются последней линией: они не кончаются, но и качество у них ниже.
def _libretranslate(тексты: list[str], lang: str) -> list[str]:
    """Свой LibreTranslate в Docker — последняя линия, которая не кончается.

    🔴 ПОЧЕМУ ПОСЛЕДНИМ, А НЕ ПЕРВЫМ, ХОТЯ ОН БЕСПЛАТНЫЙ И БЫСТРЫЙ.
    Замер 07.10.2026 на пяти живых заголовках против MyMemory показал три
    вида порчи, которых у остальных не было:
      • «нефть WTI» → «ITC brut»: имя инструмента искажено. Для сайта про
        рынки это хуже отсутствия перевода — читатель ищет WTI и не найдёт.
      • «Strait Of Hormuz Uncertainty Offsets…» → «Ормузский пролив СНИМАЕТ
        неопределённость»: смысл перевёрнут на противоположный.
      • «выше ₽84» → «выше  84»: знак валюты потерян.
    🔴 НИ ОДИН из трёх не ловится проверкой чисел: цифры везде на месте.
    Поэтому место ему там, где его ответ виден только если молчат ВСЕ
    остальные, — а не там, где он подменяет собой рабочую службу.

    Зачем он тогда нужен: он единственный, кого нельзя выключить снаружи.
    Вся история отказов этого проекта — умершие чужие бесплатные службы
    (подписка Claude, Google, скрапинг Reddit, RSS Bloomberg, квота
    MyMemory). Плохой перевод лучше пустого места, и у нижнего звена
    цепочки надёжность важнее качества.

    Язык источника указываем явно: "auto" у LibreTranslate есть, но на
    коротком заголовке с числами он ошибается чаще, чем наш detect().
    """
    import json as _json
    import os
    import urllib.request

    адрес = os.environ.get("LIBRETRANSLATE_URL", "http://127.0.0.1:5055")
    out = []
    for t in тексты:
        источник = detect(t)
        if источник == lang:
            out.append("")
            continue
        тело = _json.dumps({"q": t, "source": источник, "target": lang,
                            "format": "text"}).encode("utf-8")
        запрос = urllib.request.Request(
            адрес.rstrip("/") + "/translate", data=тело,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(запрос, timeout=TIMEOUT_SEC * 2) as r:
                out.append(_json.load(r).get("translatedText") or "")
        except Exception:                       # noqa: BLE001
            out.append("")
    return out


_ПЕРЕВОДЧИКИ = (
    ("azure",          _azure),
    ("google_cloud",   _google_cloud),
    ("google",         _google),
    ("mymemory",       _mymemory),
    ("libretranslate", _libretranslate),
)


def _настроен(имя: str) -> bool:
    """Есть ли ключ. Нет ключа — не ошибка, а «этим не пользуемся»."""
    import os
    перем = _КЛЮЧ.get(имя)
    return перем is None or bool(os.environ.get(перем, "").strip())


def _квота_база() -> sqlite3.Connection | None:
    """Своё подключение для учёта квот.

    🔴 Отдельное, а не то, что передают в translate_missing: сюда ходит и
    утренний бриф, у которого подключения нет вовсе. Отказ открыть базу
    НЕ ломает перевод — вернём None, и цепочка отработает без учёта.
    Счётчик это учёт, а не условие работы.

    timeout=30 и busy_timeout — по тому же правилу, из-за которого publish
    падал в 18% прогонов: по этой базе одновременно работают коллекторы.
    """
    try:
        from core.config import DB_PATH
        con = sqlite3.connect(str(DB_PATH), timeout=30)
        con.execute("PRAGMA busy_timeout=30000")
        translator_quota.ensure_schema(con)
        return con
    except Exception as e:                      # noqa: BLE001
        log.debug("учёт квот недоступен: %s", str(e)[:120])
        return None


# ── Контроль: числа обязаны пережить перевод ────────────────────────────────
#
# 🔴 Бесплатный переводчик умеет отвечать НЕ ТЕМ, а не только отказывать.
# MyMemory — это память переводов, и на текст, который ему не по зубам, он
# способен вернуть похожий кусок из чужого запроса. 30.09.2026 в брифе так
# уехал целый пункт контекста: вместо котировок пришёл текст про курс ЦБ —
# грамматически безупречный румынский, просто про другое. Пустой перевод
# заметен сразу, подменённый — нет; поэтому проверка не на «ответил ли», а
# на «то ли ответил».
#
# Линейка — цифры. Разделители разрядов и дробная часть при переводе законно
# меняются (4 179,46 → 4,179.46 → 4.179,46), поэтому их склеиваем и сравниваем
# голые цепочки цифр. Если из «золото 4179,46, серебро 61,08» пропали или
# появились числа — это не перевод, а другой текст.
_РАЗДЕЛИТЕЛЬ_В_ЧИСЛЕ = re.compile(r"(?<=\d)[\s  .,](?=\d)")
_ЧИСЛО = re.compile(r"\d+")


def _цифры(текст: str) -> list[str]:
    return sorted(_ЧИСЛО.findall(_РАЗДЕЛИТЕЛЬ_В_ЧИСЛЕ.sub("", текст or "")))


def числа_совпадают(оригинал: str, перевод: str) -> bool:
    """False — перевод потерял или выдумал числа, доверять ему нельзя.

    Тексты без чисел проверить нечем, и для них ответ всегда True: контроль
    должен молчать там, где ему не за что зацепиться, а не запрещать перевод.
    """
    было = _цифры(оригинал)
    if not было:
        return True
    return было == _цифры(перевод)


def _плох(переводы, тексты) -> bool:
    """Ответ бесполезен: пусто, страница ошибки или текст вернулся как есть."""
    if not переводы:
        return True
    годных = sum(1 for п, ор in zip(переводы, тексты)
                 if п and isinstance(п, str)
                 and _GOOGLE_ERROR_SIGNATURE not in п
                 and п.strip() != ор.strip())
    return годных == 0


def translate_texts(тексты: list[str], lang: str) -> list[str] | None:
    """Перевести партию текстов. None — НИ ОДИН переводчик не ответил.

    Вынесено из translate_missing 30.09.2026, чтобы тем же путём мог ходить
    утренний бриф: у него нет news_uid и незачем заводить вторую цепочку
    переводчиков со своим предохранителем. Разница между None и списком с
    пустыми строками существенная: None — служба отказала, пустая строка —
    отказал один конкретный текст.
    """
    if not тексты or lang not in SUPPORTED:
        return None
    тексты = тексты[:MAX_PER_REQUEST]
    знаков = sum(len(t) for t in тексты)
    квота = _квота_база()
    for имя, fn in _ПЕРЕВОДЧИКИ:
        if _отключён_до.get(имя, 0) > time.time():
            continue
        if not _настроен(имя):
            continue                    # ключа нет — это не отказ, а «не наш»
        if квота is not None and not translator_quota.есть_запас(квота, имя, знаков):
            continue                    # бюджет месяца выбран, ждём первого числа
        try:
            ответ = fn(тексты, lang)
        except ИсчерпанаКвота as e:
            # 🔴 Исчерпание квоты — НЕ отказ службы, и десятиминутный
            # предохранитель тут вреден: через десять минут квота не
            # появится, а мы снова потратим секунды на заведомо провальный
            # запрос, и так до конца месяца. Отметка живёт в базе и
            # переживает перезапуск сервера.
            log.warning("%s: %s", имя, str(e)[:160])
            if квота is not None:
                translator_quota.объявить_исчерпанным(квота, имя)
            continue
        except Exception as e:
            log.debug("%s не ответил: %s", имя, str(e)[:120])
            ответ = None
        else:
            # Считаем ОТПРАВЛЕННОЕ и только при удачном ответе: провайдер
            # тарифицирует вход, но за упавший запрос денег не берёт.
            if квота is not None and not _плох(ответ, тексты):
                translator_quota.записать(квота, имя, знаков)
        if _плох(ответ, тексты):
            _отключён_до[имя] = time.time() + _МЁРТВ_НА_СЕК
            log.warning("переводчик %s не работает, отключаю на %d мин",
                        имя, _МЁРТВ_НА_СЕК // 60)
            continue
        # Подменённые тексты выбрасываем поштучно, а не бракуем всю партию:
        # остальные переводы в ней настоящие.
        проверенные = []
        for ор, пер in zip(тексты, ответ):
            if пер and not числа_совпадают(ор, пер):
                log.warning("%s вернул текст с другими числами, отброшено: %.60s",
                            имя, пер)
                пер = ""
            проверенные.append(пер)
        return проверенные
    # 🔴 Все переводчики отказали — это событие, а не тишина.
    log.error("ни один переводчик не ответил: текст остаётся на языке "
              "оригинала. Проверять core/news_i18n.py")
    return None


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
    переводы = translate_texts([t for _, t in items], lang)
    if переводы is None:
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
