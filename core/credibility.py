"""WP2 — Самокалибрующееся доверие к источникам.

Байесовское обновление trust по подтверждённым/опровергнутым наблюдениям.
Калибруется месяцами — начинаем копить сразу.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from core.config import DB_PATH

# Стартовые тиры доверия
_TIER1 = {
    "kobeissiletter", "unusual_whales", "federalreserve", "ecb", "imf",
    "worldbank", "bls_gov", "uscensusbureau", "reuters", "bloomberg",
    "ft", "wsj", "nytimes", "rbc", "interfax",
}
_TIER3 = {
    "x22report", "zerohedge_anon", "cryptomoonshots", "wallstreetsilver",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    return sqlite3.connect(DB_PATH)


def seed_sources() -> None:
    """Засеять стартовые тир-значения. Идемпотентно."""
    with _db() as db:
        def _upsert(handle: str, tier: int):
            db.execute(
                """INSERT INTO sources (handle, source_type, seed_tier, trust, updated)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(handle) DO UPDATE SET seed_tier=excluded.seed_tier""",
                (handle, "twitter", tier, 0.5 + (1 - tier) * 0.15, _now())
            )
        for h in _TIER1:
            _upsert(h, 1)
        for h in _TIER3:
            _upsert(h, 3)
        db.commit()


def is_tier1_source(handle: str) -> bool:
    """Признанный СМИ/официальный источник (Reuters, ФРС, ЕЦБ...), даже если
    попал в БД через твиттер-коллектор -- твит Reuters всё ещё "сообщают СМИ",
    а не анонимный соцсети-пост. Используется лентой сигналов для маркера
    достоверности (P0-2 §2.2 шаг 2)."""
    return (handle or "").lower().lstrip("@") in _TIER1


def trust_of(handle: str) -> float:
    """Вернуть trust 0..1. Default 0.5."""
    handle = (handle or "").lower().lstrip("@")
    with _db() as db:
        row = db.execute(
            "SELECT trust, seed_tier FROM sources WHERE handle=?", (handle,)
        ).fetchone()
    if row is None:
        return 0.5
    trust, tier = row
    # Если ни разу не откалиброван — вернуть seed-дефолт
    return float(trust)


def record_outcome(handle: str, confirmed: bool) -> None:
    """Байесовское обновление trust после верифицированного наблюдения."""
    handle = (handle or "").lower().lstrip("@")
    with _db() as db:
        row = db.execute(
            "SELECT claims_total, claims_confirmed, trust FROM sources WHERE handle=?",
            (handle,)
        ).fetchone()
        if row is None:
            db.execute(
                """INSERT INTO sources (handle, source_type, seed_tier, claims_total,
                   claims_confirmed, trust, updated)
                   VALUES (?,?,?,?,?,?,?)""",
                (handle, "unknown", 2, 1, int(confirmed),
                 0.6 if confirmed else 0.4, _now())
            )
        else:
            total, conf, old_trust = row
            total += 1
            conf += int(confirmed)
            # Байес-сглаживание: prior 0.5, alpha=2
            new_trust = (conf + 2) / (total + 4)
            db.execute(
                """UPDATE sources SET claims_total=?, claims_confirmed=?,
                   trust=?, updated=? WHERE handle=?""",
                (total, conf, round(new_trust, 4), _now(), handle)
            )
        db.commit()


def trust_multiplier(handle: str) -> float:
    """Множитель 0.7..1.3 для importance."""
    t = trust_of(handle)
    # Линейное: 0 trust → 0.7, 0.5 → 1.0, 1.0 → 1.3
    return round(0.7 + t * 0.6, 3)
