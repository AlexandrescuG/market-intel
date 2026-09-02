"""core/mailer.py — отправка писем пользователям платформы.

ОТКУДА НАСТРОЙКИ. SMTP настроен в SBFAcademy_bot/.env и уже используется там для
кодов входа — то есть проверен в бою. Читаем оттуда на месте, а не копируем к
себе: копия пароля это второе место, где он может утечь, и второе место, которое
надо не забыть обновить при смене.

🔴 ПИСЬМО — ЭТО ДЕЙСТВИЕ НАРУЖУ, И ОНО НЕОБРАТИМО.
Отправленное не отзовёшь, а адрес человека — не наш черновик. Поэтому здесь:
  • список получателей всегда приходит снаружи, модуль сам никого не выбирает;
  • есть режим предпросмотра (send=False), в котором письмо собирается и
    печатается, но не уходит — им пользуются все вызывающие джобы на прогонах;
  • отказ отправки возвращается, а не глотается: «письмо не дошло» и «мы его не
    отправили» для получателя одинаковы, для нас — разные поломки.
"""
from __future__ import annotations

import logging
import pathlib
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger("mailer")

ACADEMY_ENV = pathlib.Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/.env")
_cfg: dict | None = None


def config() -> dict:
    global _cfg
    if _cfg is not None:
        return _cfg
    d = {}
    try:
        for line in ACADEMY_ENV.read_text(encoding="utf-8").splitlines():
            if line.startswith("SMTP_") and "=" in line:
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    except Exception as e:
        log.warning("настройки SMTP не прочитаны: %s", e)
    _cfg = d
    return d


def is_configured() -> bool:
    c = config()
    return bool(c.get("SMTP_HOST") and c.get("SMTP_USER") and c.get("SMTP_PASS"))


def send(to: str, subject: str, html: str, text: str = "", send: bool = True,
         unsubscribe: str = "") -> bool:
    """Отправить письмо. send=False — только собрать и не отправлять."""
    c = config()
    if not is_configured():
        log.error("SMTP не настроен — письмо не отправлено")
        return False
    msg = EmailMessage()
    msg["From"] = c.get("SMTP_FROM") or c["SMTP_USER"]
    msg["To"] = to
    msg["Subject"] = subject
    if unsubscribe:
        # Заголовки List-Unsubscribe — то, из чего Gmail и почтовые клиенты
        # рисуют собственную кнопку «Отписаться» рядом с отправителем. Без них
        # человек, которому надоела рассылка, жмёт «Спам», и страдает домен, с
        # которого мы шлём коды входа. Ссылка в подвале письма это не заменяет.
        msg["List-Unsubscribe"] = f"<{unsubscribe}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(text or "Письмо в формате HTML.")
    msg.add_alternative(html, subtype="html")

    if not send:
        print(f"[предпросмотр] кому: {to} | тема: {subject} | {len(html)} символов")
        return True

    port = int(c.get("SMTP_PORT") or 465)
    try:
        if port == 465:
            with smtplib.SMTP_SSL(c["SMTP_HOST"], port,
                                  context=ssl.create_default_context(), timeout=30) as s:
                s.login(c["SMTP_USER"], c["SMTP_PASS"])
                s.send_message(msg)
        else:
            with smtplib.SMTP(c["SMTP_HOST"], port, timeout=30) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(c["SMTP_USER"], c["SMTP_PASS"])
                s.send_message(msg)
        return True
    except Exception as e:
        log.error("письмо на %s не отправлено: %s", to, str(e)[:200])
        return False
