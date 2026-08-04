"""
journal_auth.py — Регистрация, онбординг-опросник, персонализация (§1–§5 спека).

Таблицы:
  users               — аккаунты (email, Имя, ДР, страна, согласия)
  sessions            — токены входа (localStorage на клиенте)
  onboarding_answers  — сырые ответы (key→value, аудит)
  user_prefs          — производные настройки (уровень, пресет, таймфрейм)

Мост аккаунтов с SBFAcademy_bot (2026-07-14): SBFAcademy (email/Google/Telegram,
JWT) — канонический источник identity для ВСЕГО SBF, по решению пользователя.
Свежий логин/регистрация на lp.sbfconsult.com теперь сначала бьётся туда;
локальные таблицы этого файла (onboarding_answers/user_prefs/trades/...) остаются
на месте и адресуются локальным TEXT-id — просто теперь этот id находится через
sbfacademy_user_id, а не через собственный пароль. См. validate_session/register/login.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

log = logging.getLogger("journal_auth")

_DB = Path(__file__).parent.parent / "data" / "journal.db"

# ── Мост к SBFAcademy_bot (канонический источник identity) ────────────────────
_SBF_BOT_DB   = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
_SBF_ENV_FILE = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/.env")
_SBF_API_BASE = "http://127.0.0.1:8000"  # loopback — тот же хост, без Cloudflare


def _load_sbf_jwt_secret() -> str | None:
    """Читает JWT_SECRET из .env SBFAcademy_bot напрямую — секрет не дублируем
    во второй конфиг, но если файл когда-нибудь исчезнет/будет нечитаем, это
    ДОЛЖНО громко упасть в лог, а не тихо ронять все SBFAcademy-токены на lp."""
    try:
        for line in _SBF_ENV_FILE.read_text("utf-8").splitlines():
            line = line.strip()
            if line.startswith("JWT_SECRET="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception as e:
        log.error("Не удалось прочитать JWT_SECRET из %s: %s", _SBF_ENV_FILE, e)
        return None
    log.error("JWT_SECRET не найден в %s", _SBF_ENV_FILE)
    return None


_SBF_JWT_SECRET = _load_sbf_jwt_secret()

# ── Rate limiting (in-process) ─────────────────────────────────────────────────
_auth_failures: dict[str, list[float]] = {}  # "(ip,email)" → [timestamps]
_reg_ips: dict[str, list[float]] = {}         # ip → [timestamps]


def _rate_check_login(ip: str, email: str) -> bool:
    """True = разрешить, False = заблокировать (10 неудач за 15 мин)."""
    key = f"{ip}|{email}"
    now = time.time()
    window = 900  # 15 min
    times = [t for t in _auth_failures.get(key, []) if now - t < window]
    _auth_failures[key] = times
    return len(times) < 10


def _record_login_failure(ip: str, email: str) -> None:
    key = f"{ip}|{email}"
    _auth_failures.setdefault(key, []).append(time.time())


def _clear_login_failures(ip: str, email: str) -> None:
    _auth_failures.pop(f"{ip}|{email}", None)


def _rate_check_register(ip: str) -> bool:
    """True = разрешить, False = заблокировать (5 регистраций с IP за час)."""
    now = time.time()
    times = [t for t in _reg_ips.get(ip, []) if now - t < 3600]
    _reg_ips[ip] = times
    return len(times) < 5


def _record_register(ip: str) -> None:
    _reg_ips.setdefault(ip, []).append(time.time())

# ── Маппинг рынков → стартовые символы ватчлиста ──────────────────────────────
_MARKET_SYMBOLS: dict[str, list[str]] = {
    "forex":       ["EURUSD", "GBPUSD", "USDJPY"],
    "crypto":      ["BTCUSD", "ETHUSD"],
    "commodities": ["XAUUSD"],
    "indices":     ["SPX500", "NAS100"],
    "stocks":      ["AAPL", "TSLA"],
}

# Маппинг пресет ← риск-ответы (Q10, Q11)
_RISK_TO_PRESET: dict[str, str] = {
    "close_all":  "conservative",
    "average_in": "scalper",
    "wait_plan":  "conservative",
    "dont_know":  "conservative",
}

# Маппинг стиля → таймфрейм
_STYLE_TO_TF: dict[str, str] = {
    "scalping":  "M5",
    "intraday":  "H1",
    "swing":     "H4",
    "longterm":  "D1",
    "unknown":   "H1",
}

# Минимальный возраст по умолчанию
_MIN_AGE = 18


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_schema() -> None:
    conn = _get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id                   TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
        email                TEXT NOT NULL UNIQUE COLLATE NOCASE,
        password_hash        TEXT NOT NULL,
        password_salt        TEXT NOT NULL,
        first_name           TEXT NOT NULL DEFAULT '',
        last_name            TEXT NOT NULL DEFAULT '',
        phone                TEXT,
        dob                  TEXT,
        country              TEXT NOT NULL DEFAULT '',
        lang                 TEXT NOT NULL DEFAULT 'ru',
        age_18_confirmed     INTEGER NOT NULL DEFAULT 0,
        age_verified         INTEGER NOT NULL DEFAULT 0,
        consent_data         INTEGER NOT NULL DEFAULT 0,
        consent_disclaimer   INTEGER NOT NULL DEFAULT 0,
        consent_marketing    INTEGER NOT NULL DEFAULT 0,
        onboarding_done      INTEGER NOT NULL DEFAULT 0,
        created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
        deleted_at           TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

    CREATE TABLE IF NOT EXISTS sessions (
        token      TEXT PRIMARY KEY,
        user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
        expires_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

    CREATE TABLE IF NOT EXISTS onboarding_answers (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        qkey       TEXT NOT NULL,
        value      TEXT NOT NULL,
        saved_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
        UNIQUE(user_id, qkey)
    );
    CREATE INDEX IF NOT EXISTS idx_ob_user ON onboarding_answers(user_id);

    CREATE TABLE IF NOT EXISTS user_prefs (
        user_id        TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        level          TEXT NOT NULL DEFAULT 'beginner',
        disc_preset    TEXT NOT NULL DEFAULT 'conservative',
        default_tf     TEXT NOT NULL DEFAULT 'H1',
        watchlist_markets TEXT NOT NULL DEFAULT '[]',
        goal           TEXT NOT NULL DEFAULT 'learn',
        chapter_start  INTEGER NOT NULL DEFAULT 1,
        updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
    );

    CREATE TABLE IF NOT EXISTS entitlements (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     TEXT NOT NULL,
        tier        TEXT NOT NULL DEFAULT 'pro',
        source      TEXT NOT NULL,
        granted_ts  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
        expires_ts  TEXT NOT NULL,
        UNIQUE(user_id, source)
    );
    CREATE INDEX IF NOT EXISTS idx_ent_user ON entitlements(user_id);
    """)
    # Добавляем новые колонки в существующие БД (ALTER игнорирует ошибку если уже есть)
    for ddl in [
        "ALTER TABLE users ADD COLUMN phone TEXT",
        "ALTER TABLE users ADD COLUMN age_18_confirmed INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE user_prefs ADD COLUMN tz TEXT NOT NULL DEFAULT 'UTC'",
        "ALTER TABLE user_prefs ADD COLUMN broker_tz_offset INTEGER",
        "ALTER TABLE user_prefs ADD COLUMN prestige_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN sbfacademy_user_id INTEGER",
        # SBF_Charts_Layer4_Spec, Фаза 1.4/1.2.3: тогглы слоёв графика (зеркало
        # localStorage для входа с нового устройства) и последний просмотренный
        # инструмент (приоритет над первым из ватчлиста при открытии графика).
        "ALTER TABLE user_prefs ADD COLUMN chart_layers TEXT NOT NULL DEFAULT '{}'",
        "ALTER TABLE user_prefs ADD COLUMN last_symbol TEXT",
        # SPEC_morning_brief_v2.md блок 6 ("Твоё окно"): JSON {"start_h","end_h",
        # "archetype"} -- глава 5 курса (MyWindowBlock) уже считает это на клиенте,
        # но никогда не сохраняла -- отдельная колонка (не chart_layers), чтобы
        # /api/journal/brief мог читать одно поле без парсинга чужого блока.
        "ALTER TABLE user_prefs ADD COLUMN trading_window TEXT",
    ]:
        try:
            conn.execute(ddl)
            conn.commit()
        except Exception:
            pass
    # Partial unique index — допускает много NULL (аккаунты ещё не связанные
    # с SBFAcademy), но не даёт создать ДВЕ локальные записи под одним и тем
    # же sbfacademy_user_id (защита от гонки при первом одновременном визите).
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_sbf_uid "
            "ON users(sbfacademy_user_id) WHERE sbfacademy_user_id IS NOT NULL"
        )
        conn.commit()
    except Exception as e:
        log.error("Не удалось создать idx_users_sbf_uid: %s", e)
    conn.close()


# ── Утилиты ────────────────────────────────────────────────────────────────────

def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 260_000
    ).hex()


def _calculate_age(dob_str: str) -> int:
    """Вычисляет полных лет из ISO-даты 'YYYY-MM-DD'."""
    try:
        dob = date.fromisoformat(dob_str)
    except (ValueError, TypeError):
        return 0
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


# ── Мост к SBFAcademy_bot (канонический источник identity) ────────────────────

def _sbfacademy_call(path: str, **json_body) -> dict | None:
    """POST к SBFAcademy_bot по loopback (тот же хост, без Cloudflare). None
    при любой сетевой ошибке — вызывающий код обязан аккуратно откатиться на
    локальное поведение (fail-open), а не 500ить lp из-за соседнего сервиса."""
    try:
        r = httpx.post(_SBF_API_BASE + path, json=json_body, timeout=5.0)
    except Exception as e:
        log.error("SBFAcademy недоступен (%s): %s", path, e)
        return None
    try:
        body = r.json()
    except Exception:
        body = {}
    body["_status"] = r.status_code
    return body


def _decode_sbfacademy_jwt(token: str) -> int | None:
    """SBFAcademy-токен (JWT, HS256) → user_id, или None если это не он /
    подпись не сошлась / секрет недоступен. token.count('.')==2 — дешёвый
    и точный пре-фильтр: opaque-токены этого файла (secrets.token_urlsafe)
    никогда не содержат точку, JWT всегда содержит ровно две."""
    if not _SBF_JWT_SECRET or token.count(".") != 2:
        return None
    import jwt
    try:
        payload = jwt.decode(token, _SBF_JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "access":
        return None
    try:
        return int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        return None


def _lookup_sbfacademy_user(sbf_uid: int) -> dict | None:
    """Read-only чтение email/full_name напрямую из bot.db — тот же хост/диск,
    без лишнего HTTP-хопа. Fail-open (None) при блокировке файла, а не 500."""
    try:
        con = sqlite3.connect(f"file:{_SBF_BOT_DB}?mode=ro", uri=True, timeout=3)
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT email, full_name FROM users WHERE user_id=?", (sbf_uid,)
        ).fetchone()
        con.close()
        return dict(row) if row else None
    except sqlite3.OperationalError as e:
        log.error("Не удалось прочитать bot.db (user_id=%s): %s", sbf_uid, e)
        return None


def _find_or_create_shadow(sbf_uid: int, email: str | None, full_name: str | None) -> str:
    """SBFAcademy user_id → локальный (journal.db) TEXT id, заводя "теневую"
    запись при первом визите этой identity. Матчинг по email — то, что тихо
    восстанавливает уже существующие журнал-аккаунты при их следующем входе,
    без ручной миграции. Telegram-only identity (email=None) получает
    плейсхолдер-email — реальный email здесь никогда никому не показывается,
    это чисто внутренний ключ ради NOT NULL UNIQUE на users.email."""
    email_norm = (email or "").strip().lower() or None
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id FROM users WHERE sbfacademy_user_id=?", (sbf_uid,)
        ).fetchone()
        if row:
            return row["id"]

        if email_norm:
            row = conn.execute(
                "SELECT id FROM users WHERE email=?", (email_norm,)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE users SET sbfacademy_user_id=? WHERE id=?",
                    (sbf_uid, row["id"]),
                )
                conn.commit()
                return row["id"]

        new_id = secrets.token_hex(8)
        shadow_email = email_norm or f"tg{sbf_uid}@sbfacademy.local"
        name = (full_name or "").strip()
        first_name, _, last_name = name.partition(" ")
        try:
            conn.execute(
                """INSERT INTO users
                   (id, email, password_hash, password_salt, first_name, last_name,
                    sbfacademy_user_id, age_18_confirmed, age_verified,
                    consent_data, consent_disclaimer)
                   VALUES (?,?,?,?,?,?,?,1,1,1,1)""",
                (new_id, shadow_email, "", "", first_name, last_name, sbf_uid),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            # Гонка: параллельный запрос для той же identity/email уже создал
            # строку между нашим SELECT и INSERT — перечитываем ниже вместо падения.
            conn.rollback()

        row = conn.execute(
            "SELECT id FROM users WHERE sbfacademy_user_id=? OR email=?",
            (sbf_uid, shadow_email),
        ).fetchone()
        found_id = row["id"] if row else new_id
        conn.execute("INSERT OR IGNORE INTO user_prefs (user_id) VALUES (?)", (found_id,))
        conn.commit()
        return found_id
    finally:
        conn.close()


# ── Регистрация ────────────────────────────────────────────────────────────────

def register(
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    phone: str = "",
    lang: str = "ru",
    age_18_confirmed: bool = False,
    consent_data: bool = False,
    consent_disclaimer: bool = False,
    consent_marketing: bool = False,
) -> dict:
    """§1: Лёгкая регистрация — без ДР и страны; 18+ через чекбокс.

    С 2026-07-14: канонический аккаунт создаётся/резолвится на стороне
    SBFAcademy_bot (единый источник identity для lp.sbfconsult.com и Telegram
    Mini App — см. заголовок файла). Эта функция по-прежнему держит
    регуляторный гейт (согласия/18+) и хранит lp-специфичные поля
    (phone/lang), которых у SBFAcademy нет и не будет.
    """
    ensure_schema()
    email = email.strip().lower()
    if not email or "@" not in email:
        return {"error": "Некорректный email"}
    if not password or len(password) < 8:
        # 8, не 6 — таково правило SBFAcademy (канонический аккаунт создаётся
        # там); держим оба правила синхронными, чтобы не ловить 422 ниже.
        return {"error": "Пароль должен быть не менее 8 символов"}
    if not consent_data:
        return {"error": "Необходимо согласие на обработку данных"}
    if not consent_disclaimer:
        return {"error": "Прочитай и подтверди дисклеймер"}
    if not age_18_confirmed:
        return {"error": "age_gate",
                "message": "Трейдинг-функционал доступен только с 18 лет."}

    sbf = _sbfacademy_call("/api/auth/register", email=email, password=password)
    if sbf is None:
        # SBFAcademy временно недоступен — не блокируем регистрацию на lp,
        # заводим локальный аккаунт как раньше; свяжется сам при следующем login().
        return _register_local_only(
            email, password, first_name, last_name, phone, lang,
            age_18_confirmed, consent_data, consent_disclaimer, consent_marketing,
        )
    if sbf.get("_status") == 409:
        # Этот email уже существует на SBFAcademy (например, человек раньше
        # зарегистрировался там же через Telegram Mini App) — логинимся вместо
        # повторной регистрации, чтобы попасть в ТОТ ЖЕ аккаунт, а не создать новый.
        sbf = _sbfacademy_call("/api/auth/login", email=email, password=password)
        if sbf is None or sbf.get("_status") != 200:
            return {"error": "Этот email уже используется в аккаунте SBF Academy "
                              "с другим паролем — войдите через него или "
                              "используйте «Забыли пароль»"}
    elif sbf.get("_status") != 200:
        return {"error": "Не удалось зарегистрироваться, попробуйте ещё раз"}

    access_token = sbf.get("access_token")
    sbf_uid = _decode_sbfacademy_jwt(access_token) if access_token else None
    if sbf_uid is None:
        return {"error": "Внутренняя ошибка регистрации, попробуйте ещё раз"}
    user_id = _find_or_create_shadow(sbf_uid, email, f"{first_name} {last_name}".strip())

    conn = _get_conn()
    try:
        conn.execute(
            """UPDATE users SET phone=?, lang=?, age_18_confirmed=?, age_verified=?,
                   consent_data=?, consent_disclaimer=?, consent_marketing=?,
                   first_name=?, last_name=?
               WHERE id=?""",
            (phone.strip() or None, lang, int(age_18_confirmed), int(age_18_confirmed),
             int(consent_data), int(consent_disclaimer), int(consent_marketing),
             first_name.strip(), last_name.strip(), user_id),
        )
        conn.execute("INSERT OR IGNORE INTO user_prefs (user_id) VALUES (?)", (user_id,))
        conn.commit()
    finally:
        conn.close()

    return {"ok": True, "user_id": user_id, "token": access_token,
            "refresh_token": sbf.get("refresh_token"), "first_name": first_name.strip()}


def _register_local_only(
    email: str, password: str, first_name: str, last_name: str, phone: str, lang: str,
    age_18_confirmed: bool, consent_data: bool, consent_disclaimer: bool,
    consent_marketing: bool,
) -> dict:
    """Fallback когда SBFAcademy временно недоступен — прежнее (pre-2026-07-14)
    чисто локальное поведение 1:1. Аккаунт свяжется с канонической identity
    лениво, при первом успешном login() после того, как SBFAcademy снова жив."""
    salt = secrets.token_hex(16)
    pw_hash = _hash_password(password, salt)
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO users
               (email, password_hash, password_salt, first_name, last_name,
                phone, lang, age_18_confirmed, age_verified,
                consent_data, consent_disclaimer, consent_marketing)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (email, pw_hash, salt, first_name.strip(), last_name.strip(),
             phone.strip() or None, lang,
             int(age_18_confirmed), int(age_18_confirmed),
             int(consent_data), int(consent_disclaimer), int(consent_marketing))
        )
        conn.commit()
        row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        user_id = row["id"]
        conn.execute(
            "INSERT OR IGNORE INTO user_prefs (user_id) VALUES (?)", (user_id,)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return {"error": "Email уже зарегистрирован"}
    finally:
        conn.close()

    token = _create_session(user_id)
    return {"ok": True, "user_id": user_id, "token": token,
            "first_name": first_name.strip()}


# ── Аутентификация ─────────────────────────────────────────────────────────────

def login(email: str, password: str, client_ip: str = "") -> dict:
    """С 2026-07-14: пробуем SBFAcademy первым (канонический аккаунт). Если он
    отклоняет/недоступен, падаем на прежнюю локальную PBKDF2-проверку — это
    единственный путь для 3 аккаунтов, заведённых до моста, и он же лениво
    мигрирует их на SBFAcademy тем же паролем, раз мы только что убедились,
    что человек его знает."""
    ensure_schema()
    email = email.strip().lower()
    if client_ip and not _rate_check_login(client_ip, email):
        return {"error": "rate_limit", "retry_after": 900}

    sbf = _sbfacademy_call("/api/auth/login", email=email, password=password)
    if sbf is not None and sbf.get("_status") == 200:
        if client_ip:
            _clear_login_failures(client_ip, email)
        sbf_uid = _decode_sbfacademy_jwt(sbf.get("access_token") or "")
        if sbf_uid is not None:
            user_id = _find_or_create_shadow(sbf_uid, email, None)
            urow = _get_conn()
            try:
                u = urow.execute(
                    "SELECT first_name, onboarding_done FROM users WHERE id=?", (user_id,)
                ).fetchone()
            finally:
                urow.close()
            return {
                "ok": True, "user_id": user_id, "token": sbf["access_token"],
                "refresh_token": sbf.get("refresh_token"),
                "first_name": u["first_name"] if u else "",
                "onboarding_done": bool(u["onboarding_done"]) if u else False,
            }

    # SBFAcademy отклонил или недоступен — legacy-проверка (поведение как раньше)
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE email=? AND deleted_at IS NULL", (email,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        if client_ip:
            _record_login_failure(client_ip, email)
        return {"error": "Неверный email или пароль"}
    pw_hash = _hash_password(password, row["password_salt"])
    if not secrets.compare_digest(pw_hash, row["password_hash"]):
        if client_ip:
            _record_login_failure(client_ip, email)
        return {"error": "Неверный email или пароль"}
    if client_ip:
        _clear_login_failures(client_ip, email)

    # Пароль верный локально — лениво заводим/связываем канонический аккаунт
    # тем же паролем, раз человек только что доказал, что его знает.
    migrate = _sbfacademy_call("/api/auth/register", email=email, password=password)
    if migrate is not None and migrate.get("_status") == 200:
        sbf_uid = _decode_sbfacademy_jwt(migrate.get("access_token") or "")
        if sbf_uid is not None:
            conn2 = _get_conn()
            try:
                conn2.execute(
                    "UPDATE users SET sbfacademy_user_id=? WHERE id=?",
                    (sbf_uid, row["id"]),
                )
                conn2.commit()
            finally:
                conn2.close()
            return {
                "ok": True, "user_id": row["id"], "token": migrate["access_token"],
                "refresh_token": migrate.get("refresh_token"),
                "first_name": row["first_name"],
                "onboarding_done": bool(row["onboarding_done"]),
            }
    # Не удалось лениво мигрировать (пароль <8 симв. не проходит правило
    # SBFAcademy, или SBFAcademy временно недоступен) — пускаем по старому
    # локальному токену, помечаем, что нужно сменить пароль при случае.
    token = _create_session(row["id"])
    return {
        "ok": True, "user_id": row["id"], "token": token,
        "first_name": row["first_name"],
        "onboarding_done": bool(row["onboarding_done"]),
        "password_upgrade_required": len(password) < 8,
    }


def _create_session(user_id: str, days: int = 30) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    conn = _get_conn()
    try:
        # Чистим старые сессии
        conn.execute(
            "DELETE FROM sessions WHERE user_id=? AND expires_at < strftime('%Y-%m-%dT%H:%M:%S','now')",
            (user_id,)
        )
        conn.execute(
            "INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,?)",
            (token, user_id, expires)
        )
        conn.commit()
    finally:
        conn.close()
    return token


def validate_session(token: str) -> str | None:
    """Возвращает user_id если токен валиден, иначе None.

    Токен либо "свой" opaque (secrets.token_urlsafe, без точек) — ищем в
    sessions как раньше, либо JWT от SBFAcademy (2026-07-14+, канонический
    источник identity) — тогда резолвим через identity-мост вместо локальной
    таблицы sessions."""
    if not token:
        return None
    if token.count(".") == 2:
        sbf_uid = _decode_sbfacademy_jwt(token)
        if sbf_uid is not None:
            info = _lookup_sbfacademy_user(sbf_uid)
            if info is not None:
                return _find_or_create_shadow(sbf_uid, info.get("email"), info.get("full_name"))
            # bot.db временно недоступен/заблокирован — не рубим сессию просто
            # так; падаем на локальную проверку ниже (скорее всего не найдёт
            # ничего для JWT-строки, но это безопаснее, чем 500).
    conn = _get_conn()
    try:
        row = conn.execute(
            """SELECT user_id FROM sessions
               WHERE token=?
               AND expires_at > strftime('%Y-%m-%dT%H:%M:%S','now')""",
            (token,)
        ).fetchone()
        return row["user_id"] if row else None
    finally:
        conn.close()


def logout(token: str) -> bool:
    conn = _get_conn()
    try:
        cur = conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ── Профиль пользователя ───────────────────────────────────────────────────────

def get_user(user_id: str) -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            """SELECT id, email, first_name, last_name, dob, country, lang,
                      age_verified, consent_marketing, onboarding_done, created_at
               FROM users WHERE id=? AND deleted_at IS NULL""",
            (user_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        prefs = conn.execute(
            "SELECT * FROM user_prefs WHERE user_id=?", (user_id,)
        ).fetchone()
        d["prefs"] = dict(prefs) if prefs else {}
        return d
    finally:
        conn.close()


# ── Онбординг-опросник ─────────────────────────────────────────────────────────

# Ключи core-блоков A–C опросника (нужны для награды PRO)
_CORE_SURVEY_KEYS: frozenset[str] = frozenset({
    "level", "years", "instruments", "knows_leverage", "uses_sl",  # A
    "goal", "style", "time", "markets",                             # B
    "drawdown_reaction", "risk_per_trade",                          # C
})


def grant_survey_pro(user_id: str = "default") -> dict:
    """Выдаёт 30 дней PRO за полное прохождение опросника (идемпотентно)."""
    ensure_schema()
    conn = _get_conn()
    try:
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=30)
        conn.execute(
            """INSERT OR IGNORE INTO entitlements
               (user_id, tier, source, granted_ts, expires_ts)
               VALUES (?,?,?,?,?)""",
            (user_id, "pro", "survey",
             now.strftime("%Y-%m-%dT%H:%M:%S"),
             expires.strftime("%Y-%m-%dT%H:%M:%S"))
        )
        conn.commit()
        row = conn.execute(
            "SELECT expires_ts FROM entitlements WHERE user_id=? AND source='survey'",
            (user_id,)
        ).fetchone()
        return {"ok": True, "expires_ts": row["expires_ts"] if row else None}
    finally:
        conn.close()


def get_survey_status(user_id: str = "default") -> dict:
    """Проверяет, пройден ли опросник A–C и выдан ли PRO."""
    ensure_schema()
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT qkey FROM onboarding_answers WHERE user_id=?", (user_id,)
        ).fetchall()
        answered = {r["qkey"] for r in rows}
        done = _CORE_SURVEY_KEYS.issubset(answered)
        ent = conn.execute(
            "SELECT expires_ts FROM entitlements WHERE user_id=? AND source='survey'",
            (user_id,)
        ).fetchone()
        return {
            "done": done,
            "pro_until": ent["expires_ts"] if ent else None,
            "answered_count": len(answered),
            "core_total": len(_CORE_SURVEY_KEYS),
        }
    finally:
        conn.close()


def save_onboarding_answers(user_id: str, answers: dict) -> dict:
    """Сохраняет ответы и применяет персонализацию; выдаёт PRO если A–C пройдены."""
    ensure_schema()
    conn = _get_conn()
    try:
        for qkey, value in answers.items():
            v = json.dumps(value, ensure_ascii=False) if isinstance(value, list) else str(value)
            conn.execute(
                """INSERT INTO onboarding_answers (user_id, qkey, value) VALUES (?,?,?)
                   ON CONFLICT(user_id, qkey) DO UPDATE SET value=excluded.value,
                   saved_at=strftime('%Y-%m-%dT%H:%M:%S','now')""",
                (user_id, qkey, v)
            )
        conn.execute(
            "UPDATE users SET onboarding_done=1 WHERE id=?", (user_id,)
        )
        conn.commit()
        # Проверяем, набраны ли все core-ключи после этого сохранения
        answered = {r["qkey"] for r in conn.execute(
            "SELECT qkey FROM onboarding_answers WHERE user_id=?", (user_id,)
        ).fetchall()}
    finally:
        conn.close()

    result = apply_personalization(user_id, answers)
    if _CORE_SURVEY_KEYS.issubset(answered):
        pro = grant_survey_pro(user_id)
        result["pro_granted"] = True
        result["pro_until"] = pro.get("expires_ts")
    else:
        result["pro_granted"] = False
        result["pro_until"] = None
    return result


def apply_personalization(user_id: str, answers: dict) -> dict:
    """
    §4: Маппинг ответов → user_prefs, watchlist, дисциплина-пресет.
    Возвращает результат — что было настроено.
    """
    # ── Уровень и глава старта ───────────────────────────────────────────────
    level_map = {"beginner": 1, "intermediate": 2, "advanced": 3}
    raw_level = answers.get("level", "beginner")
    level = raw_level if raw_level in level_map else "beginner"
    years_map = {"none": 1, "lt1": 3, "1to3": 6, "gt3": 10}
    chapter_start = years_map.get(answers.get("years", "none"), 1)

    # ── Пресет дисциплины ────────────────────────────────────────────────────
    has_sl = answers.get("uses_sl", "no")
    knows_leverage = answers.get("knows_leverage", "no")
    drawdown_reaction = answers.get("drawdown_reaction", "dont_know")
    risk_per_trade = answers.get("risk_per_trade", "lt1pct")

    if has_sl in ("always",) and risk_per_trade == "lt1pct":
        disc_preset = "conservative"
    elif has_sl == "never" or knows_leverage == "no":
        disc_preset = "conservative"
    elif drawdown_reaction == "average_in" or risk_per_trade == "gt2pct":
        disc_preset = "scalper"
    else:
        disc_preset = _RISK_TO_PRESET.get(drawdown_reaction, "conservative")

    # ── Таймфрейм ────────────────────────────────────────────────────────────
    default_tf = _STYLE_TO_TF.get(answers.get("style", "unknown"), "H1")

    # ── Ватчлист (рынки) ─────────────────────────────────────────────────────
    raw_markets = answers.get("markets", [])
    if isinstance(raw_markets, str):
        try:
            raw_markets = json.loads(raw_markets)
        except Exception:
            raw_markets = [raw_markets]
    watchlist_markets = raw_markets if isinstance(raw_markets, list) else []

    # ── Цель ─────────────────────────────────────────────────────────────────
    goal = answers.get("goal", "learn")

    # ── Язык ─────────────────────────────────────────────────────────────────
    lang = answers.get("lang", "ru")
    if lang in ("ru", "en"):
        conn_lang = _get_conn()
        try:
            conn_lang.execute("UPDATE users SET lang=? WHERE id=?", (lang, user_id))
            conn_lang.commit()
        finally:
            conn_lang.close()

    # ── Сохраняем user_prefs ─────────────────────────────────────────────────
    markets_json = json.dumps(watchlist_markets, ensure_ascii=False)
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO user_prefs
               (user_id, level, disc_preset, default_tf, watchlist_markets, goal, chapter_start)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                   level=excluded.level, disc_preset=excluded.disc_preset,
                   default_tf=excluded.default_tf,
                   watchlist_markets=excluded.watchlist_markets,
                   goal=excluded.goal, chapter_start=excluded.chapter_start,
                   updated_at=strftime('%Y-%m-%dT%H:%M:%S','now')""",
            (user_id, level, disc_preset, default_tf, markets_json, goal, chapter_start)
        )
        conn.commit()
    finally:
        conn.close()

    # ── Применяем дисциплину и ватчлист ──────────────────────────────────────
    applied_watchlist = []
    try:
        from . import journal_discipline, journal_brief
        journal_discipline._apply_preset(user_id, disc_preset)
        for market in watchlist_markets:
            for sym in _MARKET_SYMBOLS.get(market, []):
                if journal_brief.add_to_watchlist(sym, user_id):
                    applied_watchlist.append(sym)
    except Exception:
        pass

    return {
        "ok": True,
        "level": level,
        "disc_preset": disc_preset,
        "default_tf": default_tf,
        "goal": goal,
        "chapter_start": chapter_start,
        "watchlist_added": applied_watchlist,
    }


# ── «Твой путь» ────────────────────────────────────────────────────────────────

_GOAL_TEXTS = {
    "learn":    ("📚 Обучение с нуля",    "Начни с Главы 1 — Основы психологии трейдинга"),
    "improve":  ("📈 Улучшить результаты","Начни с Дисциплины и Зеркала поведения"),
    "passive":  ("💰 Пассивный доход",    "Изучи риск-менеджмент перед любыми счётами"),
    "coaching": ("🤝 Сопровождение",      "Привяжи брокерский счёт и начни вести дневник"),
}

_LEVEL_ADVICE = {
    "beginner":     "Твой фокус — главы 1–3 и ежедневный чек-лист перед входом в рынок.",
    "intermediate": "Твой фокус — Зеркало поведения и настройка дисциплины под свой стиль.",
    "advanced":     "Твой фокус — углублённая аналитика и цели на сезон.",
}

_PRESET_ADVICE = {
    "conservative": "Пресет 'Консервативный' активирован — строгий контроль стопов и риска.",
    "scalper":      "Пресет 'Скальпер' активирован — акцент на скорости входа и ментальном стопе.",
    "investor":     "Пресет 'Инвестор' активирован — долгосрочный горизонт, меньше трейдов.",
}


def get_my_path(user_id: str) -> dict:
    """§4 итоговый экран «Твой путь»."""
    conn = _get_conn()
    try:
        prefs = conn.execute(
            "SELECT * FROM user_prefs WHERE user_id=?", (user_id,)
        ).fetchone()
        user = conn.execute(
            "SELECT first_name, lang FROM users WHERE id=?", (user_id,)
        ).fetchone()
    finally:
        conn.close()

    if not prefs:
        return {"error": "Персонализация не найдена"}

    p = dict(prefs)
    goal_key = p.get("goal", "learn")
    goal_title, goal_subtitle = _GOAL_TEXTS.get(goal_key, _GOAL_TEXTS["learn"])

    markets = []
    try:
        markets = json.loads(p.get("watchlist_markets") or "[]")
    except Exception:
        pass

    return {
        "first_name":    (user["first_name"] if user else ""),
        "goal_title":    goal_title,
        "goal_subtitle": goal_subtitle,
        "level_advice":  _LEVEL_ADVICE.get(p["level"], ""),
        "preset_advice": _PRESET_ADVICE.get(p["disc_preset"], ""),
        "chapter_start": p["chapter_start"],
        "default_tf":    p["default_tf"],
        "markets":       markets,
        "disc_preset":   p["disc_preset"],
        "steps": [
            f"Открой Обучение → Глава {p['chapter_start']}",
            "Внеси первую сделку в Дневник",
            "Пройди утренний Чек-лист перед входом",
        ],
    }


def update_tz(user_id: str, tz: str) -> dict:
    """Обновить IANA-таймзону пользователя."""
    if not tz or len(tz) > 60:
        return {"error": "invalid tz"}
    conn = _get_conn()
    conn.execute(
        "UPDATE user_prefs SET tz=?, updated_at=strftime('%Y-%m-%dT%H:%M:%S','now') WHERE user_id=?",
        (tz, user_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


def update_broker_tz(user_id: str, offset_minutes: int) -> dict:
    """Обновить смещение времени брокера (от UTC, в минутах)."""
    if not isinstance(offset_minutes, int) or not (-720 <= offset_minutes <= 840):
        return {"error": "invalid offset"}
    conn = _get_conn()
    conn.execute(
        "UPDATE user_prefs SET broker_tz_offset=?, updated_at=strftime('%Y-%m-%dT%H:%M:%S','now') WHERE user_id=?",
        (offset_minutes, user_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


def update_chart_prefs(user_id: str, layers: dict | None = None, last_symbol: str | None = None) -> dict:
    """SBF_Charts_Layer4_Spec, Фаза 1.4/1.2.3 (+ 1.2.2 использует то же поле
    для тумблера «Мои инструменты» календаря — тот же per-user JSON-блок мелких
    UI-настроек, не только графика, несмотря на имя колонки chart_layers):
    зеркало тогглов слоёв + последний просмотренный инструмент, один UPDATE.

    `layers` — ЧАСТИЧНОЕ обновление (merge в существующий JSON), не замена
    целиком: несколько независимых вызывающих (chart.html, calendar.html)
    пишут в одну и ту же колонку разными ключами, полная перезапись одного
    затирала бы ключи, записанные другим."""
    import json as _json
    conn = _get_conn()
    sets, args = [], []
    if layers is not None:
        row = conn.execute("SELECT chart_layers FROM user_prefs WHERE user_id=?", (user_id,)).fetchone()
        try:
            merged = _json.loads(row[0]) if row and row[0] else {}
        except (ValueError, TypeError):
            merged = {}
        merged.update(layers)
        sets.append("chart_layers=?")
        args.append(_json.dumps(merged, ensure_ascii=False))
    if last_symbol is not None:
        sets.append("last_symbol=?")
        args.append(last_symbol)
    if not sets:
        conn.close()
        return {"error": "nothing to update"}
    sets.append("updated_at=strftime('%Y-%m-%dT%H:%M:%S','now')")
    args.append(user_id)
    conn.execute(f"UPDATE user_prefs SET {', '.join(sets)} WHERE user_id=?", args)
    conn.commit()
    conn.close()
    return {"ok": True}


_ARCHETYPES = {"morning", "evening", "night"}


def update_trading_window(user_id: str, start_h: int, end_h: int, archetype: str | None = None) -> dict:
    """SPEC_morning_brief_v2.md блок 6 -- сохранить выбранное торговое окно
    (глава 5 курса, MyWindowBlock, раньше только setSaved(true) локально).
    Как update_tz/update_broker_tz — валидация диапазона, один UPDATE."""
    import json as _json
    if not isinstance(start_h, int) or not isinstance(end_h, int):
        return {"error": "invalid hours"}
    if not (0 <= start_h < 24) or not (0 <= end_h <= 24):
        return {"error": "invalid hours"}
    if archetype is not None and archetype not in _ARCHETYPES:
        return {"error": "invalid archetype"}
    payload = {"start_h": start_h, "end_h": end_h, "archetype": archetype}
    conn = _get_conn()
    conn.execute(
        "UPDATE user_prefs SET trading_window=?, updated_at=strftime('%Y-%m-%dT%H:%M:%S','now') WHERE user_id=?",
        (_json.dumps(payload, ensure_ascii=False), user_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


def get_trading_window(user_id: str) -> dict | None:
    import json as _json
    conn = _get_conn()
    row = conn.execute("SELECT trading_window FROM user_prefs WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if not row or not row[0]:
        return None
    try:
        return _json.loads(row[0])
    except (ValueError, TypeError):
        return None


def prestige(user_id: str) -> dict:
    """Престиж: уровень→1, XP→0, prestige_count+1. Доступен только на уровне 8."""
    from . import journal_gamification
    xp = journal_gamification.get_xp_total(user_id)
    lvl = journal_gamification.calc_level(xp)
    if lvl.get("level", 1) < 8:
        return {"error": "Престиж доступен только на уровне 8"}
    conn = _get_conn()
    # Обнуляем XP через добавление отрицательного XP
    conn.execute(
        """INSERT INTO xp_events(user_id, kind, amount, level, ref_id)
           VALUES(?, 'prestige_reset', ?, 1, NULL)""",
        (user_id, -xp),
    )
    conn.execute(
        """UPDATE user_prefs SET prestige_count = prestige_count + 1,
               updated_at=strftime('%Y-%m-%dT%H:%M:%S','now')
           WHERE user_id=?""",
        (user_id,),
    )
    conn.commit()
    row = conn.execute("SELECT prestige_count FROM user_prefs WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    cnt = row["prestige_count"] if row else 1
    return {"ok": True, "prestige_count": cnt}


ensure_schema()
