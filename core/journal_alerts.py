"""
journal_alerts.py — Пуш-алерты в приложении (Part 4).

Таблицы:
  push_subscriptions   — устройства/браузеры пользователя
  alert_rules          — настраиваемые рыночные правила
  alert_notifications  — очередь сгенерированных уведомлений (in-app + Web Push)
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore[assignment]

_DB = Path(__file__).parent.parent / "data" / "journal.db"

ALERT_KINDS = (
    "price_cross",
    "rsi_extreme",
    "economic_event",
    "weekly_range",
    "behavioral_streak",
    "behavioral_journal",
    "behavioral_tilt",
    "morning_brief",
)

PUSH_PLATFORMS = ("web_push", "fcm", "apns")

# Обходят тихие часы (§4.2)
CRITICAL_KINDS: frozenset[str] = frozenset({"behavioral_tilt"})

# Anti-flood: cooldown для рыночных алертов (§4.4)
MARKET_COOLDOWN_MINUTES = 15

# ── Детерминированные шаблоны payload (§4.3) ─────────────────────────────────
_TEMPLATES: dict[str, dict] = {
    "price_cross": {
        "title": "Цена достигнута",
        "body": "{symbol} пересёк уровень {target} {direction_label}.",
    },
    "rsi_extreme": {
        "title": "Экстремум RSI",
        "body": "{symbol} на таймфрейме {tf} вошёл в зону {condition_label} ({level}).",
    },
    "economic_event": {
        "title": "Макрособытие",
        "body": "Через {minutes_before} мин. — {event_name}. Проверьте открытые позиции.",
    },
    "weekly_range": {
        "title": "Недельный экстремум",
        "body": "{symbol} достиг недельного {extreme_label} ({level}).",
    },
    "behavioral_streak": {
        "title": "Сохраните ваш прогресс",
        "body": "Ваш {current_streak}-дневный стрик дисциплины под угрозой. Заполните дневник сегодня.",
    },
    "behavioral_journal": {
        "title": "Аномальная сделка",
        "body": "Зафиксировано сильное отклонение ({pnl_r}R). Опишите ваши эмоции, пока свежа память.",
    },
    "behavioral_tilt": {
        "title": "Внимание: снизьте темп",
        "body": "Индикаторы фиксируют признаки серийного тильта. Рекомендуется закрыть терминал.",
    },
    "morning_brief": {
        "title": "Утренний бриф готов",
        "body": "Персональный анализ рынка на сегодня доступен во вкладке «Брифинг».",
    },
}


# ── Подключение ───────────────────────────────────────────────────────────────
def _get_conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_schema() -> None:
    conn = _get_conn()
    kinds_sql = ",".join(f"'{k}'" for k in ALERT_KINDS)
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   TEXT NOT NULL DEFAULT 'default',
            platform  TEXT NOT NULL CHECK(platform IN ('web_push','fcm','apns')),
            token     TEXT NOT NULL,
            quiet_hours_start TEXT,
            quiet_hours_end   TEXT,
            timezone  TEXT NOT NULL DEFAULT 'UTC',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(user_id, token)
        );

        CREATE INDEX IF NOT EXISTS idx_push_subscriptions_user
            ON push_subscriptions(user_id);

        CREATE TABLE IF NOT EXISTS alert_rules (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       TEXT NOT NULL DEFAULT 'default',
            symbol        TEXT NOT NULL,
            kind          TEXT NOT NULL CHECK(kind IN ({kinds_sql})),
            param         TEXT NOT NULL DEFAULT '{{}}',
            is_active     INTEGER NOT NULL DEFAULT 1,
            cooldown_until TEXT,
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_alert_rules_active
            ON alert_rules(symbol, kind, is_active, user_id);

        CREATE TABLE IF NOT EXISTS alert_notifications (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    TEXT NOT NULL DEFAULT 'default',
            rule_id    INTEGER,
            kind       TEXT NOT NULL,
            title      TEXT NOT NULL,
            body       TEXT NOT NULL,
            is_critical INTEGER NOT NULL DEFAULT 0,
            delivered  INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_alert_notif_pending
            ON alert_notifications(user_id, delivered);
    """)
    conn.commit()
    conn.close()


# ── Тихие часы (§4.2) ─────────────────────────────────────────────────────────
def should_deliver_now(subscription: dict, is_critical: bool = False) -> bool:
    """
    Алгоритм диспетчеризации по спецификации §4.2.
    Критические алерты игнорируют тихие часы.
    """
    if is_critical:
        return True
    qh_start = subscription.get("quiet_hours_start")
    qh_end   = subscription.get("quiet_hours_end")
    if not qh_start or not qh_end:
        return True

    tz_name = subscription.get("timezone") or "UTC"
    try:
        if ZoneInfo is not None:
            tz = ZoneInfo(tz_name)
            user_dt = datetime.now(tz)
        else:
            user_dt = datetime.utcnow()
    except Exception:
        user_dt = datetime.utcnow()

    current = user_dt.strftime("%H:%M:%S")
    start   = qh_start  # e.g. '22:00:00'
    end     = qh_end    # e.g. '08:00:00'

    if start <= end:
        # Тихие часы в пределах одного дня
        return current < start or current > end
    else:
        # Тихие часы переходят через полночь (e.g. 22:00–08:00)
        return current < start and current > end


# ── Генерация payload (§4.3) ──────────────────────────────────────────────────
def generate_payload(kind: str, symbol: str, param: dict) -> dict:
    """
    Детерминированная генерация payload по шаблону.
    Без торговых рекомендаций — только фактическая информация (§4.4).
    """
    tpl = _TEMPLATES.get(kind)
    if not tpl:
        return {"title": kind, "body": json.dumps(param), "is_critical": False}

    ctx: dict = {"symbol": symbol, **param}
    ctx["direction_label"] = {"up": "вверх", "down": "вниз"}.get(
        str(ctx.get("direction", "")), str(ctx.get("direction", ""))
    )
    ctx["condition_label"] = {
        "overbought": "перекупленности",
        "oversold":   "перепроданности",
    }.get(str(ctx.get("condition", "")), str(ctx.get("condition", "")))
    ctx["extreme_label"] = {"high": "максимума", "low": "минимума"}.get(
        str(ctx.get("extreme", "")), str(ctx.get("extreme", ""))
    )
    ctx.setdefault("event_name", "событие")

    # pnl_r: форматировать как ±X.XR
    if "pnl_r" in ctx:
        pnl_r = float(ctx["pnl_r"])
        ctx["pnl_r"] = f"{pnl_r:+.1f}"

    try:
        body = tpl["body"].format(**ctx)
    except (KeyError, ValueError):
        body = tpl["body"]

    return {
        "title":       tpl["title"],
        "body":        body,
        "is_critical": kind in CRITICAL_KINDS,
    }


# ── Push-подписки ─────────────────────────────────────────────────────────────
def save_subscription(
    platform: str,
    token: str,
    quiet_hours_start: str | None = None,
    quiet_hours_end: str | None = None,
    timezone: str = "UTC",
    user_id: str = "default",
) -> int:
    if platform not in PUSH_PLATFORMS:
        raise ValueError(f"platform must be one of {PUSH_PLATFORMS}")
    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO push_subscriptions
               (user_id, platform, token, quiet_hours_start, quiet_hours_end, timezone)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(user_id, token) DO UPDATE SET
               platform=excluded.platform,
               quiet_hours_start=excluded.quiet_hours_start,
               quiet_hours_end=excluded.quiet_hours_end,
               timezone=excluded.timezone""",
        (user_id, platform, token, quiet_hours_start, quiet_hours_end, timezone),
    )
    conn.commit()
    conn.close()
    return cur.lastrowid


def list_subscriptions(user_id: str = "default") -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, platform, quiet_hours_start, quiet_hours_end, timezone, created_at "
        "FROM push_subscriptions WHERE user_id=? ORDER BY id",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_subscription(sub_id: int, user_id: str = "default") -> bool:
    conn = _get_conn()
    cur = conn.execute(
        "DELETE FROM push_subscriptions WHERE id=? AND user_id=?", (sub_id, user_id)
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# ── Правила алертов ───────────────────────────────────────────────────────────
def add_rule(
    symbol: str,
    kind: str,
    param: dict,
    user_id: str = "default",
) -> dict:
    if kind not in ALERT_KINDS:
        raise ValueError(f"kind must be one of {ALERT_KINDS}")
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO alert_rules (user_id, symbol, kind, param) VALUES (?,?,?,?)",
        (user_id, symbol.upper(), kind, json.dumps(param, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()
    return {"id": cur.lastrowid, "symbol": symbol.upper(), "kind": kind, "param": param}


def list_rules(user_id: str = "default") -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, symbol, kind, param, is_active, cooldown_until, created_at "
        "FROM alert_rules WHERE user_id=? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["param"] = json.loads(d["param"])
        except Exception:
            d["param"] = {}
        d["is_active"] = bool(d["is_active"])
        result.append(d)
    return result


def delete_rule(rule_id: int, user_id: str = "default") -> bool:
    conn = _get_conn()
    cur = conn.execute(
        "DELETE FROM alert_rules WHERE id=? AND user_id=?", (rule_id, user_id)
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def toggle_rule(rule_id: int, is_active: bool, user_id: str = "default") -> bool:
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE alert_rules SET is_active=? WHERE id=? AND user_id=?",
        (1 if is_active else 0, rule_id, user_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def _set_cooldown(rule_id: int, minutes: int = MARKET_COOLDOWN_MINUTES) -> None:
    until = (datetime.utcnow() + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S")
    conn = _get_conn()
    conn.execute("UPDATE alert_rules SET cooldown_until=? WHERE id=?", (until, rule_id))
    conn.commit()
    conn.close()


def _is_on_cooldown(rule: dict) -> bool:
    until = rule.get("cooldown_until")
    if not until:
        return False
    try:
        return datetime.utcnow() < datetime.fromisoformat(until)
    except ValueError:
        return False


# ── Очередь уведомлений ───────────────────────────────────────────────────────
def queue_notification(
    kind: str,
    title: str,
    body: str,
    is_critical: bool = False,
    rule_id: int | None = None,
    user_id: str = "default",
) -> int:
    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO alert_notifications
               (user_id, rule_id, kind, title, body, is_critical)
           VALUES (?,?,?,?,?,?)""",
        (user_id, rule_id, kind, title, body, 1 if is_critical else 0),
    )
    conn.commit()
    conn.close()
    return cur.lastrowid


def get_pending_notifications(user_id: str = "default") -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        """SELECT id, rule_id, kind, title, body, is_critical, created_at
           FROM alert_notifications
           WHERE user_id=? AND delivered=0
           ORDER BY created_at DESC LIMIT 50""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [
        {**dict(r), "is_critical": bool(r["is_critical"])}
        for r in rows
    ]


def mark_delivered(notif_ids: list[int], user_id: str = "default") -> int:
    if not notif_ids:
        return 0
    placeholders = ",".join("?" * len(notif_ids))
    conn = _get_conn()
    cur = conn.execute(
        f"UPDATE alert_notifications SET delivered=1 "
        f"WHERE id IN ({placeholders}) AND user_id=?",
        (*notif_ids, user_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount


# ── Проверка рыночных правил (§4.1) ──────────────────────────────────────────
def check_market_rules(
    user_id: str = "default",
    current_prices: dict | None = None,
) -> list[dict]:
    """
    Проверяет price_cross, rsi_extreme, weekly_range против current_prices.

    current_prices: {
        "XAUUSD": {
            "price": 2350.5,
            "rsi": {"H1": 76.2, "D1": 68.0},
            "weekly_high": 2380.0,
            "weekly_low":  2290.0
        }
    }
    Возвращает список созданных уведомлений.
    """
    if not current_prices:
        return []

    conn = _get_conn()
    now_str = datetime.utcnow().isoformat()
    rules = conn.execute(
        """SELECT id, symbol, kind, param, cooldown_until
           FROM alert_rules
           WHERE user_id=? AND is_active=1 AND kind IN ('price_cross','rsi_extreme','weekly_range')""",
        (user_id,),
    ).fetchall()
    conn.close()

    fired = []
    for rule in rules:
        rule_d = dict(rule)
        if _is_on_cooldown(rule_d):
            continue

        sym = rule_d["symbol"]
        price_data = current_prices.get(sym)
        if not price_data:
            continue

        try:
            param = json.loads(rule_d["param"])
        except Exception:
            param = {}

        triggered = False
        kind = rule_d["kind"]

        if kind == "price_cross":
            target    = float(param.get("target", 0))
            direction = param.get("direction", "up")
            price     = float(price_data.get("price", 0))
            if direction == "up"   and price >= target:
                triggered = True
            elif direction == "down" and price <= target:
                triggered = True

        elif kind == "rsi_extreme":
            tf    = param.get("tf", "H1")
            level = float(param.get("level", 70))
            cond  = param.get("condition", "overbought")
            rsi   = float((price_data.get("rsi") or {}).get(tf, 50))
            if cond == "overbought" and rsi >= level:
                triggered = True
            elif cond == "oversold" and rsi <= level:
                triggered = True

        elif kind == "weekly_range":
            extreme = param.get("extreme", "high")
            price   = float(price_data.get("price", 0))
            if extreme == "high":
                level = float(price_data.get("weekly_high", 0))
                if level > 0 and price >= level:
                    triggered = True
            else:
                level = float(price_data.get("weekly_low", 0))
                if level > 0 and price <= level:
                    param["level"] = level
                if level > 0 and price <= level:
                    triggered = True

        if not triggered:
            continue

        param["symbol"] = sym
        payload = generate_payload(kind, sym, param)
        notif_id = queue_notification(
            kind=kind,
            title=payload["title"],
            body=payload["body"],
            is_critical=payload["is_critical"],
            rule_id=rule_d["id"],
            user_id=user_id,
        )
        # Anti-flood cooldown (§4.4)
        _set_cooldown(rule_d["id"], MARKET_COOLDOWN_MINUTES)
        fired.append({"notif_id": notif_id, "kind": kind, "symbol": sym})

    return fired


# ── Поведенческие алерты (§4.3) ──────────────────────────────────────────────
def check_behavioral_alerts(user_id: str = "default") -> list[dict]:
    """
    Генерирует поведенческие алерты на основе текущего состояния дневника.
    Anti-flood: дедупликация по kind — не чаще раза в 6 часов.
    """
    from . import journal_meta, journal_discipline  # lazy import

    fired: list[dict] = []

    def _already_sent(kind: str, hours: int = 6) -> bool:
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        conn = _get_conn()
        n = conn.execute(
            "SELECT COUNT(*) FROM alert_notifications "
            "WHERE user_id=? AND kind=? AND created_at > ?",
            (user_id, kind, cutoff),
        ).fetchone()[0]
        conn.close()
        return n > 0

    # 1. behavioral_tilt — дисциплинарный пробой
    if not _already_sent("behavioral_tilt", hours=3):
        bk = journal_discipline.check_breakout(user_id=user_id)
        if bk.get("detected"):
            payload = generate_payload("behavioral_tilt", "", {"reason": "disciplinary_breakout"})
            notif_id = queue_notification(
                kind="behavioral_tilt",
                title=payload["title"],
                body=payload["body"],
                is_critical=True,
                user_id=user_id,
            )
            fired.append({"notif_id": notif_id, "kind": "behavioral_tilt"})

    # 2. behavioral_journal — аномальная сделка в очереди
    if not _already_sent("behavioral_journal", hours=6):
        behavioral = journal_meta.get_behavioral_data(user_id=user_id)
        queue = behavioral.get("queue_trades") or []
        if queue:
            top = queue[0]
            pnl_r = float(top.get("pnl_r") or 0)
            if abs(pnl_r) >= 2.0:
                payload = generate_payload(
                    "behavioral_journal",
                    top.get("symbol", ""),
                    {"pnl_r": pnl_r, "trade_id": top.get("id")},
                )
                notif_id = queue_notification(
                    kind="behavioral_journal",
                    title=payload["title"],
                    body=payload["body"],
                    is_critical=False,
                    user_id=user_id,
                )
                fired.append({"notif_id": notif_id, "kind": "behavioral_journal"})

    # 3. behavioral_streak — активный стрик, дневник не заполнен сегодня
    if not _already_sent("behavioral_streak", hours=20):
        streaks = journal_discipline.get_all_streaks(user_id=user_id)
        max_streak = max(streaks.values()) if streaks else 0
        if max_streak >= 3:
            today = datetime.utcnow().strftime("%Y-%m-%d")
            conn = _get_conn()
            has_today = conn.execute(
                """SELECT COUNT(*) FROM journal_meta jm
                   JOIN trades t ON t.id = jm.trade_id
                   WHERE t.user_id=? AND date(jm.updated_at)=?""",
                (user_id, today),
            ).fetchone()[0]
            conn.close()
            if not has_today:
                payload = generate_payload(
                    "behavioral_streak", "", {"current_streak": max_streak}
                )
                notif_id = queue_notification(
                    kind="behavioral_streak",
                    title=payload["title"],
                    body=payload["body"],
                    is_critical=False,
                    user_id=user_id,
                )
                fired.append({"notif_id": notif_id, "kind": "behavioral_streak"})

    # 4. setup_review — просроченные сетапы ждут пересмотра
    if not _already_sent("setup_review", hours=20):
        from . import journal_setups  # lazy import
        overdue = journal_setups.get_overdue_reviews(user_id=user_id)
        for setup in overdue[:3]:  # не более 3 уведомлений за раз
            title = "Время пересмотреть тезис"
            body  = (
                f"Наступил срок валидации вашей графической идеи "
                f"по {setup['symbol']} ({setup['timeframe']}). "
                f"Проверьте, отработал ли паттерн."
            )
            notif_id = queue_notification(
                kind="setup_review",
                title=title,
                body=body,
                is_critical=False,
                user_id=user_id,
            )
            fired.append({"notif_id": notif_id, "kind": "setup_review", "setup_id": setup["id"]})
    # 5. morning_brief — бриф готов (только утром 05:00–10:00 UTC)
    current_hour = datetime.utcnow().hour
    if 5 <= current_hour < 10 and not _already_sent("morning_brief", hours=20):
        from . import journal_brief  # lazy import
        wl = journal_brief.get_watchlist(user_id=user_id)
        if wl:
            # Кэшируем бриф если ещё нет
            journal_brief.get_brief(user_id=user_id)
            payload = generate_payload("morning_brief", "", {})
            notif_id = queue_notification(
                kind="morning_brief",
                title=payload["title"],
                body=payload["body"],
                is_critical=False,
                user_id=user_id,
            )
            fired.append({"notif_id": notif_id, "kind": "morning_brief"})

    return fired


ensure_schema()

# ── Web Push delivery (§0.3 VAPID) ───────────────────────────────────────────

_VAPID_KEYS_PATH = Path(__file__).parent.parent / "data" / "vapid_keys.json"
_vapid_cache: dict | None = None

_log = logging.getLogger(__name__)


def get_vapid_public_key() -> str:
    """Возвращает applicationServerKey для регистрации PushManager в браузере."""
    global _vapid_cache
    if _vapid_cache is None and _VAPID_KEYS_PATH.exists():
        _vapid_cache = json.loads(_VAPID_KEYS_PATH.read_text())
    return (_vapid_cache or {}).get("application_server_key", "")


def _in_quiet_hours(sub: dict) -> bool:
    qs = sub.get("quiet_hours_start")
    qe = sub.get("quiet_hours_end")
    if not qs or not qe:
        return False
    try:
        tz_name = sub.get("timezone", "UTC")
        if ZoneInfo:
            now = datetime.now(ZoneInfo(tz_name))
        else:
            now = datetime.utcnow()
        cur = now.hour * 60 + now.minute
        def hm(s: str) -> int:
            h, m = s.split(":")
            return int(h) * 60 + int(m)
        start, end = hm(qs), hm(qe)
        return (start <= cur < end) if start <= end else (cur >= start or cur < end)
    except Exception:
        return False


def send_web_push(subscription_info: dict, title: str, body: str,
                  icon: str = "/favicon.ico") -> bool:
    """Отправляет одно Web Push через pywebpush + VAPID. Возвращает True при успехе."""
    global _vapid_cache
    if _vapid_cache is None:
        if not _VAPID_KEYS_PATH.exists():
            _log.warning("VAPID keys not found at %s", _VAPID_KEYS_PATH)
            return False
        _vapid_cache = json.loads(_VAPID_KEYS_PATH.read_text())
    try:
        from pywebpush import webpush
        webpush(
            subscription_info=subscription_info,
            data=json.dumps({"title": title, "body": body, "icon": icon}),
            vapid_private_key=_vapid_cache["private_pem"],
            vapid_claims={"sub": f"mailto:{_vapid_cache.get('mailto','sbf@sbf.com')}"},
        )
        return True
    except Exception as exc:
        _log.error("Web Push failed: %s", exc)
        return False


def deliver_pending_notifications(user_id: str = "default") -> dict:
    """
    Берёт необработанные уведомления из очереди и отправляет Web Push
    на все web_push-подписки пользователя (с учётом тихих часов).
    """
    conn = _get_conn()
    subs = [dict(r) for r in conn.execute(
        "SELECT * FROM push_subscriptions WHERE user_id=? AND platform='web_push'",
        (user_id,)
    ).fetchall()]
    notifs = [dict(r) for r in conn.execute(
        """SELECT id, title, body FROM alert_notifications
           WHERE user_id=? AND delivered=0 ORDER BY created_at LIMIT 10""",
        (user_id,)
    ).fetchall()]
    conn.close()

    if not subs or not notifs:
        return {"sent": 0, "failed": 0, "skipped_quiet_hours": 0}

    sent = failed = quiet = 0
    delivered_ids: list[int] = []

    for sub in subs:
        if _in_quiet_hours(sub):
            quiet += len(notifs)
            continue
        try:
            sub_info = json.loads(sub["token"])
        except (json.JSONDecodeError, TypeError):
            continue
        for n in notifs:
            if send_web_push(sub_info, n["title"], n["body"]):
                sent += 1
                if n["id"] not in delivered_ids:
                    delivered_ids.append(n["id"])
            else:
                failed += 1

    if delivered_ids:
        mark_delivered(delivered_ids, user_id)
    return {"sent": sent, "failed": failed, "skipped_quiet_hours": quiet}


def register_web_push_subscription(
    subscription_json: dict,
    user_id: str = "default",
    quiet_hours_start: str | None = None,
    quiet_hours_end: str | None = None,
    timezone: str = "UTC",
) -> dict:
    """Сохраняет PushSubscription.toJSON() из браузера после pushManager.subscribe()."""
    token = json.dumps(subscription_json, separators=(",", ":"))
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO push_subscriptions
                   (user_id, platform, token, quiet_hours_start, quiet_hours_end, timezone)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(user_id, token) DO UPDATE SET
                   quiet_hours_start = excluded.quiet_hours_start,
                   quiet_hours_end   = excluded.quiet_hours_end,
                   timezone          = excluded.timezone""",
            (user_id, "web_push", token, quiet_hours_start, quiet_hours_end, timezone)
        )
        conn.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()
