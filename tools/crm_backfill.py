#!/usr/bin/env python3
"""tools/crm_backfill.py — разовая заливка уже существующих аккаунтов платформы
в SBFCRM.

ЗАЧЕМ. Интеграция core/crm_leads.py отправляет в CRM только НОВЫЕ регистрации.
Те, кто зарегистрировался до её подключения, в CRM отсутствуют. Скрипт
переносит их один раз.

БЕЗОПАСНОСТЬ ПОВТОРНОГО ЗАПУСКА. Перед созданием ищет лида по почте. Если
карточка уже есть — пропускает (или, при --enrich, дополняет ответами опроса).
Так что повторный запуск не плодит дубли.

ЧТО ПРОПУСКАЕТ. Явно тестовые записи: домены example.com/test.com/x.com,
локальные .local, почты без точки в домене, а также удалённых (deleted_at).
Список пропущенных печатается — ничего не исчезает молча.

Запуск:
    python3 tools/crm_backfill.py            # показать, что будет сделано
    python3 tools/crm_backfill.py --apply    # выполнить
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import crm_leads  # noqa: E402

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "data", "journal.db")

FAKE_DOMAINS = {"test.com", "x.com", "example.com", "example.org", "mail.com",
                "local", "localhost"}


def looks_fake(email: str) -> str | None:
    """Причина считать почту тестовой, иначе None."""
    e = (email or "").strip().lower()
    if "@" not in e:
        return "нет @"
    dom = e.rsplit("@", 1)[1]
    if dom in FAKE_DOMAINS:
        return f"тестовый домен {dom}"
    if "." not in dom or dom.endswith(".local"):
        return f"нерабочий домен {dom}"
    return None


def load_users() -> list[dict]:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    users = [dict(r) for r in con.execute(
        "SELECT * FROM users WHERE deleted_at IS NULL OR deleted_at='' "
        "ORDER BY created_at")]
    for u in users:
        u["_answers"] = {}
        for qk, val in con.execute(
                "SELECT qkey, value FROM onboarding_answers WHERE user_id=? ORDER BY id",
                (u["id"],)):
            try:
                val = json.loads(val) if val and val[0] in "[{" else val
            except Exception:
                pass
            u["_answers"][qk] = val
        row = con.execute(
            "SELECT expires_ts FROM entitlements WHERE user_id=? AND tier='pro' "
            "ORDER BY expires_ts DESC LIMIT 1", (u["id"],)).fetchone()
        u["_pro_until"] = row["expires_ts"][:10] if row and row["expires_ts"] else None
    con.close()
    return users


def attrib_of(u: dict) -> dict:
    return {k: u.get(k) for k in ("utm_source", "utm_medium", "utm_campaign",
                                  "utm_content", "utm_term") if u.get(k)} | {
        k: u.get(v) for k, v in (("referrer", "attrib_referrer"),
                                 ("landing", "attrib_landing")) if u.get(v)}


def name_of(u: dict) -> str:
    fio = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x).strip()
    return fio or (u.get("email") or "").split("@")[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="выполнить, а не показать")
    ap.add_argument("--include-fake", action="store_true",
                    help="не пропускать тестовые почты")
    args = ap.parse_args()

    if not crm_leads.is_configured():
        print("SBFCRM не настроен (нет пароля в .env) — см. tools/crm_setup.sh")
        return 1

    users = load_users()
    print(f"аккаунтов на платформе (не удалённых): {len(users)}\n")

    to_send, skipped = [], []
    for u in users:
        reason = None if args.include_fake else looks_fake(u.get("email", ""))
        (skipped if reason else to_send).append((u, reason))

    if skipped:
        print("ПРОПУЩЕНО как тестовые:")
        for u, why in skipped:
            print(f"  {u['email']:<32} — {why}")
        print()

    print("К ЗАЛИВКЕ:")
    for u, _ in to_send:
        a = attrib_of(u)
        print(f"  {u['email']:<32} имя={name_of(u):<20} "
              f"опрос={'да' if u['_answers'] else 'нет':<3} "
              f"pro_до={u['_pro_until'] or '—':<11} "
              f"метки={a or '—'}")
    print()

    if not args.apply:
        print("Это предпросмотр. Для выполнения: python3 tools/crm_backfill.py --apply")
        return 0

    created = enriched = existed = failed = 0
    for u, _ in to_send:
        em = u["email"]
        existing = crm_leads._find_lead_by_email(em)
        if existing:
            existed += 1
            print(f"  {em}: карточка уже есть ({existing})", end="")
            if u["_answers"]:
                ok = crm_leads.enrich_with_survey(em, u["_answers"], u["_pro_until"],
                                                  lead_id=existing)
                enriched += bool(ok)
                print(" → дополнена опросом" if ok else " → дополнить не удалось")
            else:
                print(" → пропуск")
            continue
        lid = crm_leads.create_lead(email=em, name=name_of(u), attrib=attrib_of(u),
                                    answers=u["_answers"], pro_until=u["_pro_until"])
        if lid:
            created += 1
            print(f"  {em}: создана {lid}")
        else:
            failed += 1
            print(f"  {em}: НЕ УДАЛОСЬ")

    print(f"\nитог: создано {created}, дополнено {enriched}, "
          f"уже было {existed}, ошибок {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
