"""core/mailer.py — отправка писем пользователям платформы.

ОТКУДА НАСТРОЙКИ. Сначала свой market_intel/.env (его заполняет владелец через
tools/mail_setup.sh), запасной вариант — SBFAcademy_bot/.env, где SMTP уже
работает на кодах входа. Подробности выбора — в config() ниже.

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

OWN_ENV = pathlib.Path(__file__).resolve().parent.parent / ".env"
ACADEMY_ENV = pathlib.Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/.env")
_cfg: dict | None = None


def config() -> dict:
    """Настройки почты: сначала свои, потом чужие.

    🔴 Порядок важен. Свой .env читается ПЕРВЫМ, и если там есть SMTP_HOST —
    берём его целиком, не подмешивая ничего из SBFAcademy. Иначе получилась бы
    смесь: наш адрес отправителя с чужим паролем, и письмо бы не ушло с
    непонятной ошибкой аутентификации.

    Запасной вариант — почта SBFAcademy, с которой уходят коды входа. Она
    работает, но это личный gmail: получатель видит личный адрес вместо
    компании, у Gmail предел около 500 писем в сутки, а жалоба на спам из-за
    рассылки бьёт по доставке кодов входа. Настроить свою — tools/mail_setup.sh.
    """
    global _cfg
    if _cfg is not None:
        return _cfg

    def _read(path: pathlib.Path) -> dict:
        d = {}
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("SMTP_") and "=" in line:
                    k, v = line.split("=", 1)
                    if v.strip():
                        d[k.strip()] = v.strip()
        except Exception:
            pass
        return d

    own = _read(OWN_ENV)
    if own.get("SMTP_HOST") and own.get("SMTP_PASS"):
        _cfg = own
        return _cfg
    fallback = _read(ACADEMY_ENV)
    if not fallback:
        log.warning("настройки SMTP не найдены ни в %s, ни в %s", OWN_ENV, ACADEMY_ENV)
    elif own.get("SMTP_HOST") or own.get("SMTP_USER"):
        # 🔴 Переход на запасной ящик должен быть СЛЫШНЫМ.
        #
        # 09.09.2026 из market_intel/.env пропал блок SMTP_* (файл переписали
        # шаблоном .env.example, восстановили из копии, где этого блока ещё не
        # было). Рассылка при этом не сломалась: она молча уехала на личный
        # gmail SBFAcademy — тот самый, от которого уходили 02.09. Владелец
        # утром получил бы письма от личного адреса и не узнал бы, почему.
        #
        # Условие «свой ящик настроен наполовину» отличает эту ситуацию от
        # честного «свой ящик не настраивали вовсе», когда запасной — норма.
        log.error("SMTP: свой ящик настроен НЕ полностью (%s), письма уйдут с "
                  "запасного адреса %s. Пароль приложения задаётся через "
                  "tools/mail_setup.sh",
                  OWN_ENV, fallback.get("SMTP_FROM") or fallback.get("SMTP_USER"))
    _cfg = fallback
    return _cfg


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
