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
                    json={"chat_id": GDENIGI_CHAT_ID, "text": item["payload"], "parse_mode": "HTML"},
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
