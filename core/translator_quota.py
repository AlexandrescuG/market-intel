"""core/translator_quota.py — месячные бюджеты переводчиков и их расход.

ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ. У платных переводчиков с бесплатным тарифом есть
месячный лимит в символах. Исчерпание лимита и отказ службы выглядят для
вызывающего одинаково — «не ответил», — но лечатся прямо противоположно:
отказ стоит повторить через десять минут, исчерпанную квоту повторять
бессмысленно до первого числа следующего месяца.

🔴 СОСТОЯНИЕ ЖИВЁТ В БАЗЕ, А НЕ В ПАМЯТИ ПРОЦЕССА.
Предохранитель в news_i18n держит отключённых в словаре — для десяти минут
этого хватает. Для месяца не хватает: sbf-web перезапускается при каждой
правке шаблона, и после перезапуска процесс снова считал бы исчерпанный
DeepL живым. Каждая партия начиналась бы с заведомо провального запроса на
несколько секунд, и так до конца месяца.

🔴 СЧИТАЕМ ОТПРАВЛЕННОЕ, А НЕ ПРИНЯТОЕ. Провайдер тарифицирует вход, и
счётчик обязан совпадать с его счётчиком, иначе мы упрёмся в стену раньше,
чем узнаем об этом. Запас НЕ закладываем: ограничитель на нашей стороне,
который «на всякий случай» режет 5% бесплатного лимита, — это подарок
провайдеру, а не защита.

Бюджеты на 07.10.2026 (их называет сам провайдер, мы их не угадываем):
    azure       2 000 000 знаков в месяц, тариф F0, сбрасывается первого числа
    google_cloud  500 000 знаков в месяц, постоянный бесплатный кредит

🔴 DeepL СЮДА НЕ ВХОДИТ, И ЭТО РЕШЕНИЕ, А НЕ ЗАБЫВЧИВОСТЬ.
Он был первым в плане как лучший по качеству, но в июле 2026 DeepL
перестроил тарифы: прежний API Free с 500 000 знаков КАЖДЫЙ месяц больше
не купить, вместо него Developer — миллион знаков ОДИН РАЗ и навсегда,
без сброса. Для постоянной работы это тупик: несколько недель лучшего
качества, потом ключ гаснет насовсем, и цепочка молча съезжает на
следующего. Решение владельца 07.10.2026 — не подключать вовсе. Вместе с
DeepL убрана и механика разового бюджета: держать особый случай ради
провайдера, которого нет, дороже, чем вернуть десять строк, если
понадобится.

Для google (бесплатный скрапер) и mymemory бюджета нет: у них лимит не в
символах, а в запросах с адреса, и считать его отсюда нечем.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timezone

log = logging.getLogger("translator_quota")

# Сколько знаков в месяц даёт бесплатный тариф. None — лимит есть, но он не
# в знаках и нам его не посчитать.
БЮДЖЕТ: dict[str, int | None] = {
    "azure":      2_000_000,
    "google_cloud": 500_000,
    "google":          None,
    "mymemory":        None,
    # Свой сервер: лимита нет вовсе, считать нечего.
    "libretranslate":  None,
}


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS translator_usage(
            provider   TEXT NOT NULL,
            month      TEXT NOT NULL,   -- 'YYYY-MM' в UTC
            chars      INTEGER NOT NULL DEFAULT 0,
            exhausted  INTEGER NOT NULL DEFAULT 0,  -- 1 = провайдер сам сказал «лимит»
            updated    INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(provider, month)
        );
    """)
    con.commit()


def _месяц() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def потрачено(con: sqlite3.Connection, провайдер: str) -> tuple[int, bool]:
    """(знаков за текущий месяц, объявлен ли исчерпанным)."""
    try:
        строка = con.execute(
            "SELECT chars, exhausted FROM translator_usage "
            "WHERE provider=? AND month=?", (провайдер, _месяц())).fetchone()
    except sqlite3.OperationalError:
        return 0, False
    return (строка[0], bool(строка[1])) if строка else (0, False)


def есть_запас(con: sqlite3.Connection, провайдер: str, знаков: int) -> bool:
    """Хватит ли бюджета на партию. Провайдеры без бюджета — всегда да:
    их ограничивает предохранитель по отказам, а не этот счётчик."""
    бюджет = БЮДЖЕТ.get(провайдер)
    израсходовано, исчерпан = потрачено(con, провайдер)
    if исчерпан:
        return False
    if бюджет is None:
        return True
    return израсходовано + знаков <= бюджет


def записать(con: sqlite3.Connection, провайдер: str, знаков: int) -> None:
    """Прибавить расход. Ошибка записи НЕ роняет перевод: счётчик — это
    учёт, а не условие работы (тот же принцип, что у кэша переводов)."""
    try:
        con.execute("""
            INSERT INTO translator_usage(provider, month, chars, updated)
            VALUES(?,?,?,?)
            ON CONFLICT(provider, month) DO UPDATE
              SET chars = chars + excluded.chars, updated = excluded.updated
        """, (провайдер, _месяц(), знаков, int(time.time())))
        con.commit()
    except Exception as e:                      # noqa: BLE001
        log.warning("расход %s не записан: %s", провайдер, str(e)[:120])


def объявить_исчерпанным(con: sqlite3.Connection, провайдер: str) -> None:
    """Провайдер сам ответил «лимит». Верим ему больше, чем своему счётчику:
    он мог считать и чужой трафик с того же ключа, и округлять иначе."""
    бюджет = БЮДЖЕТ.get(провайдер) or 0
    try:
        con.execute("""
            INSERT INTO translator_usage(provider, month, chars, exhausted, updated)
            VALUES(?,?,?,1,?)
            ON CONFLICT(provider, month) DO UPDATE
              SET exhausted = 1, updated = excluded.updated
        """, (провайдер, _месяц(), бюджет, int(time.time())))
        con.commit()
        log.warning("%s: лимит месяца исчерпан, до первого числа не зовём",
                    провайдер)
    except Exception as e:                      # noqa: BLE001
        log.warning("отметка об исчерпании %s не записана: %s", провайдер, str(e)[:120])


def сводка(con: sqlite3.Connection) -> list[tuple[str, int, int | None, bool]]:
    """[(провайдер, потрачено, бюджет, исчерпан)] — для отчёта и глаз."""
    итог = []
    for п in БЮДЖЕТ:
        израсходовано, исчерпан = потрачено(con, п)
        итог.append((п, израсходовано, БЮДЖЕТ[п], исчерпан))
    return итог
