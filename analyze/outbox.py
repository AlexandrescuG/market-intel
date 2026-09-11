#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze/outbox.py — WP6.3 SPEC_alpha_engine_wp6_volatility.md (пересмотр 15.08).

Единый исходящий канал в @gdenigi_bot. Signals (monitor.py) и agent_run
(через notify_gdenigi.py) оба ТОЛЬКО enqueue() — ни один не импортирует
httpx/requests для этого канала напрямую. Один отправщик (send_pending())
забирает из очереди и шлёт. Токен в одном месте, ретраи в одном месте,
история отправок в одном месте — не два кодопути с двумя копиями токена.

status_label NOT NULL — единственное, что обязано пережить весь путь от
генерации до сообщения (см. analyze/notify_gdenigi.py::determine_status_label).

attachment_path — [РАСШИРЕНИЕ исходной схемы спеки, согласовано с владельцем
15.08]: `monitor.py::alert()` всегда шлёт график (sendPhoto), не голый текст —
без этого поля переход на общий outbox тихо терял бы график на каждом
Signals-сигнале.
"""
from __future__ import annotations

import sqlite3
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS outbox (
      id TEXT PRIMARY KEY, created_ts INTEGER, source TEXT,
      status_label TEXT NOT NULL,
      payload TEXT, attachment_path TEXT, sent_ts INTEGER, send_error TEXT
    );
"""


def init_schema(con: sqlite3.Connection) -> None:
    con.executescript(_SCHEMA)
    con.commit()


def enqueue(con: sqlite3.Connection, source: str, status_label: str, payload: str,
            attachment_path: str | None = None) -> str:
    """source: 'signals' | 'agent'. Коммитит сама -- вызывающий код
    (monitor.py, notify_gdenigi.py) не должен знать транзакционных деталей."""
    if not status_label:
        raise ValueError("status_label обязателен, см. докстринг модуля")
    init_schema(con)
    oid = str(uuid.uuid4())
    con.execute(
        "INSERT INTO outbox (id, created_ts, source, status_label, payload, attachment_path) "
        "VALUES (?,?,?,?,?,?)",
        (oid, int(time.time()), source, status_label, payload, attachment_path),
    )
    con.commit()
    return oid


def enqueue_ops(message: str, source: str = "ops") -> str | None:
    """Операционный алерт в тот же канал, что и содержательные сообщения.

    🔴 19.08, по замечанию владельца. До этого действовало разделение WP4.7:
    содержательное — в @gdenigi_bot через эту очередь, операционное — прямым
    вызовом core.telegram, то есть от @Markgandon_bot. Разные назначения,
    разные каналы. На практике оба бота пишут в один и тот же чат владельца,
    и разделение выглядит не как замысел, а как сбой: половина сообщений по
    проекту приходит от постороннего бота.

    Единственный аргумент за прямой канал остаётся в силе, и он здесь учтён:
    если сломается сама очередь, алерт об этом застрянет в очереди, которая
    сломалась. Поэтому при отказе enqueue сообщение уходит прежним путём —
    хуже прийти не от того бота, чем не прийти вовсе."""
    try:
        con = sqlite3.connect(str(_BOT_DB), timeout=60)
        try:
            return enqueue(con, source=source, status_label="операционный алерт",
                           payload=message)
        finally:
            con.close()
    except Exception as e:
        try:
            import asyncio

            from core.config import TELEGRAM_REPORT_CHAT_ID
            from core.telegram import send_text
            asyncio.run(send_text(f"{message}\n\n<i>(запасным каналом: очередь "
                                  f"недоступна — {type(e).__name__})</i>",
                                  chat_id=TELEGRAM_REPORT_CHAT_ID))
        except Exception:
            pass
        return None


def pending(con: sqlite3.Connection) -> list[dict]:
    init_schema(con)
    rows = con.execute(
        "SELECT id, created_ts, source, status_label, payload, attachment_path "
        "FROM outbox WHERE sent_ts IS NULL ORDER BY created_ts ASC"
    ).fetchall()
    return [{"id": r[0], "created_ts": r[1], "source": r[2], "status_label": r[3],
             "payload": r[4], "attachment_path": r[5]} for r in rows]


def mark_sent(con: sqlite3.Connection, oid: str) -> None:
    con.execute("UPDATE outbox SET sent_ts=? WHERE id=?", (int(time.time()), oid))
    con.commit()


def mark_failed(con: sqlite3.Connection, oid: str, error: str) -> None:
    con.execute("UPDATE outbox SET send_error=? WHERE id=?", (error[:2000], oid))
    con.commit()


# Пределы Telegram: 4096 символов на sendMessage, 1024 на подпись к фото.
TG_TEXT_LIMIT = 4096
TG_CAPTION_LIMIT = 1024


def _fit(payload: str | None, has_photo) -> str:
    """Подрезать сообщение под предел Telegram.

    🔴 11.09: три операционных алерта от 05.09 длиной 4835 символов висели в
    очереди неделю и падали на КАЖДОМ прогоне с «400 Bad Request». Отправить
    их нельзя в принципе — предел 4096, — но очередь этого не знала и честно
    пробовала снова. Постоянный отказ, притворяющийся временным: счётчик
    `failed` рос, никто не смотрел, ошибка была вечной.

    Резать, а не отбрасывать: длинный алерт всё ещё несёт причину в начале,
    и лучше доставить его усечённым, чем не доставить вовсе. Причина самой
    длины устранена отдельно — `run_cycle._why` больше не вываливает сырой
    конверт CLI, — но подрезка нужна как последний рубеж: следующий
    многословный алерт придёт откуда-нибудь ещё."""
    text = payload or ""
    limit = TG_CAPTION_LIMIT if has_photo else TG_TEXT_LIMIT
    if len(text) <= limit:
        return text
    tail = f"\n… обрезано, было {len(text)} симв."
    return text[: limit - len(tail)] + tail


def send_pending(con: sqlite3.Connection) -> dict:
    """Тихо не отправляет ничего без токена (симметрично core.telegram.send_text
    и старой notify_gdenigi.send_forecast) -- НЕ ошибка, ожидаемое состояние,
    пока Георгий не создаст бота через @BotFather. Не бросает исключение на
    отдельном failed item -- одно упавшее сообщение не должно блокировать
    остальную очередь."""
    from core.config import GDENIGI_BOT_TOKEN, GDENIGI_CHAT_ID
    if not GDENIGI_BOT_TOKEN or not GDENIGI_CHAT_ID:
        return {"sent": 0, "failed": 0, "skipped_no_token": True}
    import httpx
    sent = failed = 0
    for item in pending(con):
        try:
            item = dict(item)
            item["payload"] = _fit(item["payload"], item["attachment_path"])
            if item["attachment_path"]:
                with open(item["attachment_path"], "rb") as f:
                    resp = httpx.post(
                        f"https://api.telegram.org/bot{GDENIGI_BOT_TOKEN}/sendPhoto",
                        data={"chat_id": GDENIGI_CHAT_ID, "caption": item["payload"] or "",
                              "parse_mode": "HTML"},
                        files={"photo": f}, timeout=30,
                    )
            else:
                resp = httpx.post(
                    f"https://api.telegram.org/bot{GDENIGI_BOT_TOKEN}/sendMessage",
                    json={"chat_id": GDENIGI_CHAT_ID, "text": item["payload"],
                          "parse_mode": "HTML"},
                    timeout=15,
                )
                if resp.status_code == 400:
                    # 🔴 11.09: три алерта от 05.09 падали неделю с «400 Bad
                    # Request». Причина — `<` внутри текста: с parse_mode=HTML
                    # Telegram читает его как открывающий тег и отвергает всё
                    # сообщение. В операционных алертах и чек-листах разметки
                    # нет вовсе, зато сырые куски ответов с `<` попадаются.
                    # Поэтому повтор простым текстом: формат — не повод
                    # потерять сообщение, а угадывать наличие разметки в
                    # чужом payload мы не беремся.
                    resp = httpx.post(
                        f"https://api.telegram.org/bot{GDENIGI_BOT_TOKEN}/sendMessage",
                        json={"chat_id": GDENIGI_CHAT_ID, "text": item["payload"]},
                        timeout=15,
                    )
            resp.raise_for_status()
            mark_sent(con, item["id"])
            sent += 1
        except Exception as e:
            mark_failed(con, item["id"], f"{type(e).__name__}: {e}")
            failed += 1
    return {"sent": sent, "failed": failed, "skipped_no_token": False}


def main() -> None:
    con = sqlite3.connect(str(_BOT_DB), timeout=10)
    result = send_pending(con)
    con.close()
    print(result)


if __name__ == "__main__":
    main()
