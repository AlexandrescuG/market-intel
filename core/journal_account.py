"""
Part 10 — Account Hub: subscriptions, referrals, broker links, GDPR.
Single-user SQLite adaptation of the PostgreSQL spec §10.
"""

import json
import logging
import secrets
import string
from datetime import datetime, timezone, timedelta
from pathlib import Path

import sqlite3

log = logging.getLogger("journal_account")

DB_PATH = Path(__file__).parent.parent / "data" / "journal.db"

VALID_TIERS    = ("free", "pro", "mentor_mam")
VALID_STATUSES = ("active", "past_due", "canceled", "expired")
# АУДИТ_легаси_market_intel_2026-08-06.md §3.9: было ("avatrade", "naga") против
# пяти партнёров в web/data/partners.json — link_broker() отклонял xm/fxpro/instaforex.
VALID_BROKERS  = ("avatrade", "naga", "xm", "fxpro", "instaforex")

BROKER_LABELS = {
    "avatrade":   "AvaTrade",
    "naga":       "NAGA",
    "xm":         "XM",
    "fxpro":      "FxPro",
    "instaforex": "InstaForex",
}

# Реальные партнёрские ссылки — сверено с web/data/partners.json::links.affiliate
# (06.08.2026, страница /brokers). Было placeholder ?tag=sbf_consult для двух брокеров.
BROKER_IB_LINKS = {
    "avatrade":   "https://www.avatrade.com/?tag=184200",
    "naga":       "https://go.joinnaga.com/29LSS44/23JF6C/",
    "xm":         "https://clicks.pipaffiliates.com/c?c=1258918&l=ru&p=1",
    "fxpro":      "https://www.fxpro-direct.org/en/register/md/cri/32TQQFd7H",
    "instaforex": "https://www.instaforex.com/en/fast_open_live_account?x=TTVDG",
}

_CODE_CHARS = string.ascii_uppercase + string.digits


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_schema() -> None:
    conn = _get_conn()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id              TEXT NOT NULL DEFAULT 'default',
            tier                 TEXT NOT NULL DEFAULT 'free'
                                 CHECK(tier IN ('free','pro','mentor_mam')),
            status               TEXT NOT NULL DEFAULT 'expired'
                                 CHECK(status IN ('active','past_due','canceled','expired')),
            current_period_start TEXT NOT NULL
                                 DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
            renew_ts             TEXT NOT NULL
                                 DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
            updated_at           TEXT NOT NULL
                                 DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
            UNIQUE(user_id)
        );

        CREATE TABLE IF NOT EXISTS referrals (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         TEXT NOT NULL DEFAULT 'default',
            code            TEXT NOT NULL UNIQUE,
            invited_user_id TEXT,
            bonus_status    TEXT NOT NULL DEFAULT 'pending'
                            CHECK(bonus_status IN ('pending','applied','rejected')),
            created_at      TEXT NOT NULL
                            DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_referrals_code ON referrals(code);

        CREATE TABLE IF NOT EXISTS broker_links (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        TEXT NOT NULL DEFAULT 'default',
            -- 🔴 Список обязан совпадать с VALID_BROKERS выше. Он разошёлся
            -- однажды: кортеж в Python расширили до пяти партнёров, а CHECK
            -- остался на двух, и привязка счёта XM/FxPro/InstaForex падала —
            -- при том что проверка на входе её пропускала. Меняешь одно —
            -- меняй другое, иначе база и код снова разойдутся молча.
            broker         TEXT NOT NULL
                           CHECK(broker IN ('avatrade','naga','xm','fxpro','instaforex')),
            account_number TEXT NOT NULL,
            status         TEXT NOT NULL DEFAULT 'pending_verification',
            linked_at      TEXT,
            UNIQUE(user_id, broker, account_number)
        );
        CREATE INDEX IF NOT EXISTS idx_broker_links_lookup
            ON broker_links(broker, account_number);

        CREATE TABLE IF NOT EXISTS account_deletion_requests (
            user_id                 TEXT PRIMARY KEY,
            requested_at            TEXT NOT NULL
                                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
            scheduled_hard_delete_at TEXT NOT NULL
        );
        """)

        # 🔴 CREATE TABLE IF NOT EXISTS не меняет уже созданную таблицу, а
        # ALTER TABLE в SQLite не умеет менять CHECK. Поэтому расширение
        # списка брокеров в схеме выше на существующей базе не сработает
        # само: там останется старое ограничение на двух партнёров, и
        # привязка счёта XM будет падать ровно так же. Единственный путь —
        # пересоздать таблицу и перенести строки.
        стар = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='broker_links'"
        ).fetchone()
        if стар and "'xm'" not in (стар[0] or ""):
            log.info("broker_links: мигрирую CHECK под %d партнёров", len(VALID_BROKERS))
            conn.executescript("""
            PRAGMA foreign_keys=off;
            BEGIN;
            CREATE TABLE broker_links__new (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id        TEXT NOT NULL DEFAULT 'default',
                broker         TEXT NOT NULL
                               CHECK(broker IN ('avatrade','naga','xm','fxpro','instaforex')),
                account_number TEXT NOT NULL,
                status         TEXT NOT NULL DEFAULT 'pending_verification',
                linked_at      TEXT,
                UNIQUE(user_id, broker, account_number)
            );
            INSERT INTO broker_links__new (id, user_id, broker, account_number, status, linked_at)
                SELECT id, user_id, broker, account_number, status, linked_at FROM broker_links;
            DROP TABLE broker_links;
            ALTER TABLE broker_links__new RENAME TO broker_links;
            CREATE INDEX IF NOT EXISTS idx_broker_links_lookup
                ON broker_links(broker, account_number);
            COMMIT;
            PRAGMA foreign_keys=on;
            """)
        conn.commit()
    finally:
        conn.close()


# ── Subscription ──────────────────────────────────────────────────────────────

def get_subscription(user_id: str = "default") -> dict:
    ensure_schema()
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not row:
            return {
                "tier": "free", "status": "expired",
                "renew_ts": None, "current_period_start": None,
            }
        d = dict(row)
        # Auto-expire if past renew_ts
        if d["status"] == "active" and d["renew_ts"]:
            try:
                renew_dt = datetime.fromisoformat(d["renew_ts"])
                if renew_dt.tzinfo is None:
                    renew_dt = renew_dt.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > renew_dt:
                    conn2 = _get_conn()
                    try:
                        conn2.execute(
                            "UPDATE subscriptions SET status='expired', tier='free' WHERE user_id=?",
                            (user_id,)
                        )
                        conn2.commit()
                    finally:
                        conn2.close()
                    d["status"] = "expired"
                    d["tier"] = "free"
            except ValueError:
                pass
        return d
    finally:
        conn.close()


def upsert_subscription(user_id: str = "default", tier: str = "pro",
                        add_days: int = 7) -> dict:
    """§10.2 Продлевает подписку на add_days дней (от текущего renew_ts если активна)."""
    ensure_schema()
    conn = _get_conn()
    try:
        now = datetime.now(timezone.utc)
        row = conn.execute(
            "SELECT renew_ts FROM subscriptions WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row and row["renew_ts"]:
            try:
                existing = datetime.fromisoformat(row["renew_ts"])
                if existing.tzinfo is None:
                    existing = existing.replace(tzinfo=timezone.utc)
                base = existing if existing > now else now
            except ValueError:
                base = now
        else:
            base = now
        new_renew = (base + timedelta(days=add_days)).strftime("%Y-%m-%dT%H:%M:%S")
        now_str   = now.strftime("%Y-%m-%dT%H:%M:%S")
        conn.execute("""
            INSERT INTO subscriptions
                (user_id, tier, status, current_period_start, renew_ts, updated_at)
            VALUES (?, ?, 'active', ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                tier       = excluded.tier,
                status     = 'active',
                renew_ts   = excluded.renew_ts,
                updated_at = excluded.updated_at
        """, (user_id, tier, now_str, new_renew, now_str))
        conn.commit()
    finally:
        conn.close()
    return get_subscription(user_id)


# ── Referrals ─────────────────────────────────────────────────────────────────

def _gen_code() -> str:
    suffix = "".join(secrets.choice(_CODE_CHARS) for _ in range(6))
    return f"SBF_{suffix}"


def get_or_create_referral_code(user_id: str = "default") -> dict:
    """Возвращает существующий или создаёт новый реферальный код."""
    ensure_schema()
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM referrals WHERE user_id = ? AND invited_user_id IS NULL LIMIT 1",
            (user_id,)
        ).fetchone()
        if row:
            return dict(row)
        for _ in range(10):
            code = _gen_code()
            dup = conn.execute(
                "SELECT 1 FROM referrals WHERE code = ?", (code,)
            ).fetchone()
            if not dup:
                break
        conn.execute(
            "INSERT INTO referrals (user_id, code) VALUES (?,?)", (user_id, code)
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM referrals WHERE user_id = ? AND invited_user_id IS NULL LIMIT 1",
            (user_id,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def use_referral_code(code: str, new_user_id: str = "default") -> dict:
    """§10.2 Применяет код: Win-Win +7 дней PRO обоим."""
    ensure_schema()
    clean = code.upper().strip()
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM referrals WHERE code = ? AND invited_user_id IS NULL",
            (clean,)
        ).fetchone()
        if not row:
            return {"error": "Код недействителен или уже использован"}
        if row["user_id"] == new_user_id:
            return {"error": "Нельзя использовать собственный реферальный код"}
        referral_id = row["id"]
        referrer_id = row["user_id"]
        conn.execute(
            "UPDATE referrals SET invited_user_id = ? WHERE id = ?",
            (new_user_id, referral_id)
        )
        conn.commit()
    finally:
        conn.close()
    return process_referral_bonus(referrer_id, new_user_id, referral_id)


def process_referral_bonus(referrer_id: str, referee_id: str,
                           referral_record_id: int) -> dict:
    """§10.2 ACID-эквивалент: 7 дней PRO обоим + статус applied."""
    BONUS_DAYS = 7
    upsert_subscription(referrer_id, tier="pro", add_days=BONUS_DAYS)
    upsert_subscription(referee_id,  tier="pro", add_days=BONUS_DAYS)
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE referrals SET bonus_status = 'applied' WHERE id = ?",
            (referral_record_id,)
        )
        conn.commit()
    finally:
        conn.close()
    return {"success": True, "days_added": BONUS_DAYS}


def list_referrals(user_id: str = "default") -> list[dict]:
    ensure_schema()
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM referrals WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Broker links ──────────────────────────────────────────────────────────────

def add_broker_link(user_id: str = "default",
                    broker: str = "", account_number: str = "") -> dict:
    """§10.3 Добавляет привязку брокерского счёта (status = pending_verification)."""
    if broker not in VALID_BROKERS:
        return {"error": f"broker must be one of: {list(VALID_BROKERS)}"}
    account_number = account_number.strip()
    if not account_number:
        return {"error": "account_number обязателен"}
    ensure_schema()
    conn = _get_conn()
    try:
        try:
            conn.execute(
                """INSERT INTO broker_links (user_id, broker, account_number)
                   VALUES (?,?,?)""",
                (user_id, broker, account_number)
            )
            conn.commit()
        except sqlite3.IntegrityError as e:
            # 🔴 IntegrityError — не синоним дубликата. Нарушение CHECK
            # (брокер не из списка) прилетает тем же исключением, и
            # пользователь, впервые привязывающий счёт XM, получал ответ
            # «Эта связка уже существует» — сообщение, по которому ни он, ни
            # поддержка не догадаются, что дело в схеме базы. Ровно та же
            # ошибка уже случалась в journal_db.add_trade.
            текст = str(e)
            if "UNIQUE" in текст.upper():
                return {"error": "Эта связка уже существует"}
            if "CHECK" in текст.upper():
                log.error("broker_links: схема не принимает брокера %r — "
                          "CHECK в базе разошёлся с VALID_BROKERS (%s)", broker, текст)
                return {"error": "Этот брокер пока не принимается — мы уже знаем об этом"}
            raise
        row = conn.execute(
            "SELECT * FROM broker_links WHERE user_id=? AND broker=? AND account_number=?",
            (user_id, broker, account_number)
        ).fetchone()
        return dict(row) if row else {"error": "insert failed"}
    finally:
        conn.close()


def list_broker_links(user_id: str = "default") -> list[dict]:
    ensure_schema()
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM broker_links WHERE user_id = ? ORDER BY id",
            (user_id,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["label"]   = BROKER_LABELS.get(d["broker"], d["broker"])
            d["ib_link"] = BROKER_IB_LINKS.get(d["broker"], "")
            result.append(d)
        return result
    finally:
        conn.close()


def delete_broker_link(link_id: int, user_id: str = "default") -> bool:
    conn = _get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM broker_links WHERE id = ? AND user_id = ?",
            (link_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_broker_ib_links() -> dict:
    """§10.3 Возвращает IB deep-links для всех партнёров."""
    return {
        broker: {
            "label":   BROKER_LABELS[broker],
            "ib_link": BROKER_IB_LINKS[broker],
        }
        for broker in VALID_BROKERS
    }


# ── GDPR: Data export (§10.4) ─────────────────────────────────────────────────

def export_user_data(user_id: str = "default") -> dict:
    """Агрегированный полный JSON-дамп — право на переносимость данных."""
    ensure_schema()
    conn = _get_conn()
    try:
        sub_row = conn.execute(
            "SELECT tier, status, renew_ts FROM subscriptions WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        subscription = dict(sub_row) if sub_row else None

        trades: list[dict] = []
        try:
            for t in conn.execute(
                "SELECT * FROM trades WHERE user_id = ?", (user_id,)
            ).fetchall():
                td = dict(t)
                meta = conn.execute(
                    "SELECT setup_tag, emo_open, emo_close, note FROM journal_meta WHERE trade_id=?",
                    (t["id"],)
                ).fetchone()
                td["meta"] = dict(meta) if meta else None
                trades.append(td)
        except Exception:
            pass

        achievements: list[str] = []
        try:
            achievements = [
                r["achievement_id"]
                for r in conn.execute(
                    "SELECT achievement_id FROM user_achievements WHERE user_id=?",
                    (user_id,)
                ).fetchall()
            ]
        except Exception:
            pass

        goals: list[dict] = []
        try:
            goals = [
                dict(r) for r in conn.execute(
                    "SELECT kind, target_value, current_value, status, label FROM goals WHERE user_id=?",
                    (user_id,)
                ).fetchall()
            ]
        except Exception:
            pass

        referrals: list[dict] = []
        try:
            referrals = [
                {"code": r["code"], "bonus_status": r["bonus_status"],
                 "used": r["invited_user_id"] is not None}
                for r in conn.execute(
                    "SELECT * FROM referrals WHERE user_id=?", (user_id,)
                ).fetchall()
            ]
        except Exception:
            pass

        return {
            "export_ts":    datetime.now(timezone.utc).isoformat(),
            "user_id":      user_id,
            "subscription": subscription,
            "trades":       trades,
            "achievements": achievements,
            "goals":        goals,
            "referrals":    referrals,
        }
    finally:
        conn.close()


# ── GDPR: Account deletion (§10.4) ───────────────────────────────────────────

def request_account_deletion(user_id: str = "default") -> dict:
    """Soft-delete: ставит задачу жёсткого удаления через 30 дней."""
    ensure_schema()
    scheduled = (
        datetime.now(timezone.utc) + timedelta(days=30)
    ).strftime("%Y-%m-%dT%H:%M:%S")
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO account_deletion_requests
               (user_id, scheduled_hard_delete_at) VALUES (?,?)""",
            (user_id, scheduled)
        )
        conn.commit()
    finally:
        conn.close()
    return {"scheduled": scheduled, "grace_days": 30}


def cancel_deletion_request(user_id: str = "default") -> bool:
    conn = _get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM account_deletion_requests WHERE user_id = ?", (user_id,)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_deletion_status(user_id: str = "default") -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM account_deletion_requests WHERE user_id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ── Account overview ──────────────────────────────────────────────────────────

def get_account_overview(user_id: str = "default") -> dict:
    """Все данные аккаунт-хаба одним вызовом для загрузки UI."""
    ensure_schema()
    referral_record = get_or_create_referral_code(user_id)
    used = [r for r in list_referrals(user_id) if r.get("invited_user_id")]
    deletion = get_deletion_status(user_id)
    return {
        "subscription":    get_subscription(user_id),
        "referral": {
            "code":        referral_record["code"],
            "used_count":  len(used),
            "invites":     used[:20],
        },
        "broker_links":    list_broker_links(user_id),
        "ib_partners":     get_broker_ib_links(),
        "deletion_pending": deletion is not None,
        "deletion_info":   deletion,
    }
