"""core/crm_leads.py — отправка новых регистраций платформы в SBFCRM.

ЗАЧЕМ. До 27.08.2026 регистрации на lp.sbfconsult.com жили только в
data/journal.db. В CRM они не попадали вообще, то есть менеджер не видел
человека, пришедшего с рекламы, пока тот сам не написал. Отдельная память
проекта фиксирует ту же дыру со стороны рекламы: «UTM в воронке не
собирались никогда — лиды с sbfconsult.com не получали материал».

ЧТО ДЕЛАЕТ. Два события:
  1. Регистрация  → создаётся лид со статусом NEW.
  2. Опрос пройден → карточка ДОПОЛНЯЕТСЯ ответами (PATCH, не второй лид).

ПОЧЕМУ НЕ ПЕРЕИСПОЛЬЗУЕМ SBFAcademy_bot/sbfacademy/core/crm.py. Тот клиент
живёт в другом проекте, другом процессе и другом venv, шлёт телеграм-
уведомления менеджеру и не умеет ни email, ни assignedUserId, ни обновление
карточки — у него payload из name/phone/tags/notes/status. Импортировать его
через границу проектов значило бы завести зависимость market_intel от
SBFAcademy_bot ради четырёх полей. Логика логина и обновления токена
повторена сознательно, она короткая.

НАСТРОЙКА (.env в корне market_intel):
    SBFCRM_URL=https://crm.sbf.md
    SBFCRM_EMAIL=gheorgiialexandrescu@gmail.com
    SBFCRM_PASSWORD=...        # ставит владелец, см. tools/crm_setup.sh
    SBFCRM_ASSIGNEE_ID=...     # id пользователя CRM, на кого вешать лид

Без SBFCRM_PASSWORD модуль молча выключен — это НЕ тихий отказ, а
неконфигурированное состояние: is_configured() отвечает честно, и
healthcheck может о нём сообщить.
"""
from __future__ import annotations

import json
import logging
import threading
import time

import requests

from core.config import (SBFCRM_ASSIGNEE_ID, SBFCRM_EMAIL, SBFCRM_PASSWORD,
                         SBFCRM_URL)

log = logging.getLogger("crm_leads")

_token: str | None = None
_token_expiry: float = 0.0
_lock = threading.Lock()
_TOKEN_TTL = 3600 * 20          # JWT в SBFCRM живёт сутки, берём с запасом
_TIMEOUT = 10


def is_configured() -> bool:
    return bool(SBFCRM_URL and SBFCRM_EMAIL and SBFCRM_PASSWORD)


def _login() -> str | None:
    if not is_configured():
        return None
    try:
        r = requests.post(f"{SBFCRM_URL}/api/auth/login",
                          json={"email": SBFCRM_EMAIL, "password": SBFCRM_PASSWORD},
                          timeout=_TIMEOUT)
        r.raise_for_status()
        tok = r.json().get("token")
        if not tok:
            log.error("SBFCRM login: в ответе нет token")
            return None
        return tok
    except Exception as e:
        log.error("SBFCRM login не удался: %s", e)
        return None


def _get_token() -> str | None:
    global _token, _token_expiry
    with _lock:
        if _token and time.time() < _token_expiry:
            return _token
        _token = _login()
        _token_expiry = time.time() + _TOKEN_TTL if _token else 0.0
        return _token


def _invalidate() -> None:
    global _token, _token_expiry
    with _lock:
        _token, _token_expiry = None, 0.0


def _request(method: str, path: str, payload: dict) -> dict | None:
    """Один повтор при 401 — JWT мог протухнуть раньше нашего TTL."""
    for attempt in (0, 1):
        tok = _get_token()
        if not tok:
            return None
        try:
            r = requests.request(method, f"{SBFCRM_URL}{path}", json=payload,
                                 headers={"Authorization": f"Bearer {tok}"},
                                 timeout=_TIMEOUT)
            if r.status_code == 401 and attempt == 0:
                _invalidate()
                continue
            if r.status_code in (200, 201):
                return r.json()
            log.error("SBFCRM %s %s → %d: %s", method, path, r.status_code, r.text[:200])
            return None
        except Exception as e:
            log.error("SBFCRM %s %s — ошибка запроса: %s", method, path, e)
            return None
    return None


def _find_lead_by_email(email: str) -> str | None:
    """id существующего лида с этой почтой, иначе None.

    Нужен, чтобы опрос дополнял карточку, а не плодил вторую: на /survey
    регистрация и опрос идут одним запросом, но с /register человек может
    зарегистрироваться сегодня, а опрос пройти завтра."""
    tok = _get_token()
    if not tok or not email:
        return None
    try:
        r = requests.get(f"{SBFCRM_URL}/api/leads",
                         params={"search": email, "limit": 5},
                         headers={"Authorization": f"Bearer {tok}"},
                         timeout=_TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json()
        items = data.get("items") if isinstance(data, dict) else data
        for it in (items or []):
            if (it.get("email") or "").lower() == email.lower():
                return it.get("id")
    except Exception as e:
        log.error("SBFCRM поиск лида по почте: %s", e)
    return None


def _answers_to_lines(answers: dict) -> list[str]:
    """Ответы опроса — человекочитаемо, по строке на вопрос."""
    out = []
    for k, v in (answers or {}).items():
        if v is None or v == "":
            continue
        if isinstance(v, (list, tuple)):
            v = ", ".join(str(x) for x in v)
        out.append(f"  {k}: {v}")
    return out


def create_lead(email: str, name: str = "", attrib: dict | None = None,
                answers: dict | None = None, pro_until: str | None = None) -> str | None:
    """Новая регистрация → лид в CRM. Возвращает id лида или None.

    Никогда не бросает: регистрация человека важнее записи в CRM, и падение
    интеграции не должно отменять создание аккаунта. Вызывающий уже
    оборачивает вызов, здесь — вторая линия.
    """
    if not is_configured():
        return None
    attrib = attrib or {}
    answers = answers or {}

    tags = ["lp.sbfconsult.com", "self-signup"]
    camp = attrib.get("utm_campaign")
    src = attrib.get("utm_source")
    if src:
        tags.append(f"src:{src}")
    if camp:
        tags.append(f"camp:{camp}")
    if answers:
        tags.append("survey-done")
    if pro_until:
        tags.append("pro-30d")

    notes = ["Регистрация на платформе lp.sbfconsult.com"]
    if attrib:
        notes.append("Источник перехода:")
        for k in ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
                  "referrer", "landing"):
            if attrib.get(k):
                notes.append(f"  {k}: {attrib[k]}")
    else:
        notes.append("Источник перехода: прямой заход, меток нет")
    if pro_until:
        notes.append(f"PRO выдан до: {pro_until}")
    if answers:
        notes.append("Ответы опроса:")
        notes += _answers_to_lines(answers)

    payload = {
        "name": (name or email.split("@")[0])[:200],
        "email": email,
        "status": "NEW",
        "tags": tags[:20],
        "notes": "\n".join(notes)[:5000],
    }
    if SBFCRM_ASSIGNEE_ID:
        payload["assignedUserId"] = SBFCRM_ASSIGNEE_ID

    res = _request("POST", "/api/leads", payload)
    if res:
        log.info("CRM: лид создан id=%s email=%s камп=%s", res.get("id"), email, camp or "—")
        return res.get("id")
    return None


def enrich_with_survey(email: str, answers: dict, pro_until: str | None = None,
                       lead_id: str | None = None) -> bool:
    """Опрос пройден → дополнить карточку, не создавая вторую.

    Если лида нет (регистрация прошла до подключения интеграции или
    сорвалась) — создаём его сейчас, чтобы ответы не потерялись.
    """
    if not is_configured():
        return False
    lead_id = lead_id or _find_lead_by_email(email)
    if not lead_id:
        return bool(create_lead(email=email, answers=answers, pro_until=pro_until))

    lines = ["Опрос пройден."]
    if pro_until:
        lines.append(f"PRO выдан до: {pro_until}")
    lines.append("Ответы:")
    lines += _answers_to_lines(answers)

    payload = {"notes": "\n".join(lines)[:5000],
               "tags": ["lp.sbfconsult.com", "survey-done"]}
    ok = _request("PATCH", f"/api/leads/{lead_id}", payload) is not None
    log.info("CRM: карточка %s дополнена опросом: %s", lead_id, ok)
    return ok
