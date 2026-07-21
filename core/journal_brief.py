"""
journal_brief.py — Персональный утренний бриф «Твой день» (Part 5).

Таблицы (journal.db):
  watchlist             — список наблюдения пользователя
  morning_briefs_cache  — кэш сгенерированных брифов (один в день)

Источники данных (bot.db):
  price_bars            — OHLCV свечи для расчёта волатильности и ATR14
  econ_events           — экономический календарь
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DB     = Path(__file__).parent.parent / "data" / "journal.db"
_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

# ── Соответствие: валюта → код страны в econ_events ──────────────────────────
_CURRENCY_TO_COUNTRY: dict[str, str] = {
    "USD": "US", "EUR": "EU", "GBP": "GB", "JPY": "JP",
    "AUD": "AU", "NZD": "NZ", "CAD": "CA", "CHF": "CH",
    "CNY": "CN", "RUB": "RU", "ZAR": "ZA", "KZT": "KZ",
}


def _get_conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _get_bot_conn() -> sqlite3.Connection | None:
    if not _BOT_DB.exists():
        return None
    conn = sqlite3.connect(str(_BOT_DB), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema() -> None:
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS watchlist (
            user_id    TEXT NOT NULL DEFAULT 'default',
            symbol     TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, symbol)
        );

        CREATE INDEX IF NOT EXISTS idx_watchlist_symbol ON watchlist(symbol);

        CREATE TABLE IF NOT EXISTS morning_briefs_cache (
            user_id      TEXT NOT NULL DEFAULT 'default',
            brief_date   TEXT NOT NULL,
            payload      TEXT NOT NULL,
            generated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, brief_date)
        );
    """)
    # Focus Engine (SPEC_focus_engine.md, §6): один пин на пользователя,
    # переиспользуем эту таблицу вместо отдельной user_watchlist из спеки --
    # watchlist(user_id,symbol) уже существует, PUT/POST/DELETE и редактор
    # уже вокруг неё; ALTER, не отдельная таблица.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(watchlist)")}
    if "pinned" not in cols:
        conn.execute("ALTER TABLE watchlist ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
    conn.commit()
    conn.close()


# ── Watchlist CRUD ────────────────────────────────────────────────────────────
def get_watchlist(user_id: str = "default") -> list[str]:
    conn = _get_conn()
    rows = conn.execute(
        # rowid как вторичный ключ сортировки — created_at имеет точность до
        # секунды (datetime('now')), при массовой замене (set_watchlist) все
        # строки могут получить одинаковую метку; rowid сохраняет порядок
        # вставки надёжно (Layer4 Фаза 1.3 — редактор с drag-порядком).
        "SELECT symbol FROM watchlist WHERE user_id=? ORDER BY created_at, rowid",
        (user_id,),
    ).fetchall()
    conn.close()
    return [r["symbol"] for r in rows]


def add_to_watchlist(symbol: str, user_id: str = "default") -> bool:
    sym = symbol.upper().strip()
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist (user_id, symbol) VALUES (?,?)",
            (user_id, sym),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def remove_from_watchlist(symbol: str, user_id: str = "default") -> bool:
    conn = _get_conn()
    cur = conn.execute(
        "DELETE FROM watchlist WHERE user_id=? AND symbol=?",
        (user_id, symbol.upper()),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def set_watchlist(symbols: list[str], user_id: str = "default") -> list[str]:
    """SBF_Charts_Layer4_Spec, Фаза 1.3: полная замена ватчлиста одним вызовом
    (редактор — чипы+drag, не инкрементальные add/remove). Порядок сохраняется
    через порядок INSERT (таблица не имеет отдельной колонки позиции —
    created_at монотонно растёт внутри одного вызова, этого достаточно для
    ORDER BY created_at в get_watchlist()). Дедуп регистронезависимо; лимит на
    10 проверяет вызывающая сторона (API) — это чистый CRUD-примитив."""
    conn = _get_conn()
    seen = set()
    ordered = []
    for s in symbols:
        su = s.upper().strip()
        if su and su not in seen:
            seen.add(su)
            ordered.append(su)
    conn.execute("DELETE FROM watchlist WHERE user_id=?", (user_id,))
    for su in ordered:
        conn.execute("INSERT INTO watchlist (user_id, symbol) VALUES (?,?)", (user_id, su))
    conn.commit()
    conn.close()
    return ordered


def get_available_symbols() -> list[str]:
    """Возвращает символы, для которых есть дневные бары в bot.db."""
    bc = _get_bot_conn()
    if bc is None:
        return []
    try:
        rows = bc.execute(
            "SELECT DISTINCT symbol FROM price_bars WHERE tf='1d' ORDER BY symbol"
        ).fetchall()
        return [r["symbol"] for r in rows]
    except Exception:
        return []
    finally:
        bc.close()


# ── Символ → страны (для фильтрации событий) ─────────────────────────────────
def _symbol_to_countries(symbol: str) -> set[str]:
    """
    Маппинг торгового символа → коды стран для фильтрации econ_events.
    Реализует кросс-зависимости спецификации §5.2:
      XAUUSD → USD-события (US)
      UKOIL  → USD-события (US)
    """
    s = symbol.upper().strip()

    # Специальные кросс-зависимости (спецификация §5.2)
    if s in ("XAUUSD", "GOLD", "XAU"):
        return {"US"}
    if s in ("UKOIL", "BRENTOIL", "WTI", "USOIL", "OIL"):
        return {"US"}

    # Форексные пары: извлечь базовую и котировочную валюту
    if len(s) == 6 and s.isalpha():
        base  = s[:3]
        quote = s[3:]
        countries: set[str] = set()
        for ccy in (base, quote):
            c = _CURRENCY_TO_COUNTRY.get(ccy)
            if c:
                countries.add(c)
        return countries

    # Индексы и прочие активы: US по умолчанию
    if any(k in s for k in ("SPX", "SP500", "NAS", "DOW", "US30", "US500")):
        return {"US"}

    # Прямое совпадение с кодом страны
    if s in _CURRENCY_TO_COUNTRY.values():
        return {s}

    return {"US"}


# ── Волатильность (вчерашняя сессия) ─────────────────────────────────────────
def _get_yesterday_moves(symbols: list[str]) -> list[dict]:
    """
    Выбирает самую свежую дневную свечу из price_bars для каждого символа.
    Вычисляет % изменения цены и уровень волатильности (§5.3).

    volatility_state:
      extreme — (high - low) > ATR14 × 1.5
      high    — (high - low) > ATR14
      normal  — иначе
    """
    if not symbols:
        return []

    bc = _get_bot_conn()
    if bc is None:
        return []

    result = []
    try:
        for sym in symbols:
            # Берём 15 последних дней: первый — «вчера», 2-15 — для ATR14
            rows = bc.execute(
                "SELECT ts, o, h, l, c FROM price_bars "
                "WHERE symbol=? AND tf='1d' ORDER BY ts DESC LIMIT 15",
                (sym,),
            ).fetchall()

            if not rows:
                continue

            yesterday = rows[0]
            o, h, l, c = yesterday["o"], yesterday["h"], yesterday["l"], yesterday["c"]

            # ATR14 из предшествующих свечей
            prev_rows = rows[1:]
            if prev_rows:
                atr14 = sum(r["h"] - r["l"] for r in prev_rows) / len(prev_rows)
            else:
                atr14 = h - l

            price_change_pct = round((c - o) / o * 100, 2) if o else 0.0
            day_range = h - l

            if atr14 > 0:
                if day_range > atr14 * 1.5:
                    vol_state = "extreme"
                elif day_range > atr14:
                    vol_state = "high"
                else:
                    vol_state = "normal"
            else:
                vol_state = "normal"

            bar_date = datetime.fromtimestamp(
                yesterday["ts"], tz=timezone.utc
            ).strftime("%Y-%m-%d")

            result.append({
                "symbol":               sym,
                "price_change_percent": price_change_pct,
                "volatility_state":     vol_state,
                "close":                round(c, 5),
                "bar_date":             bar_date,
            })
    finally:
        bc.close()

    return result


# ── Макроэкономический календарь (сегодня) ────────────────────────────────────
def _get_today_calendar(symbols: list[str]) -> list[dict]:
    """
    Выбирает события экономического календаря на сегодня,
    фильтруя по странам, связанным с символами из watchlist.
    Без торговых рекомендаций — только факты (§5.5).
    """
    if not symbols:
        return []

    bc = _get_bot_conn()
    if bc is None:
        return []

    # Собираем все релевантные страны
    relevant_countries: set[str] = set()
    for sym in symbols:
        relevant_countries |= _symbol_to_countries(sym)

    if not relevant_countries:
        return []

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ts_start = int(
        datetime.strptime(today, "%Y-%m-%d")
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )
    ts_end = ts_start + 86400

    placeholders = ",".join("?" * len(relevant_countries))
    try:
        rows = bc.execute(
            f"""SELECT id, ts_utc, country, title, impact, event_key,
                       scheduled_ts, actual, forecast, previous, unit
                FROM econ_events
                WHERE country IN ({placeholders})
                  AND (
                    (scheduled_ts IS NOT NULL AND scheduled_ts >= ? AND scheduled_ts < ?)
                    OR (scheduled_ts IS NULL AND ts_utc LIKE ?)
                  )
                ORDER BY COALESCE(scheduled_ts, 0) ASC""",
            (*sorted(relevant_countries), ts_start, ts_end, f"{today}%"),
        ).fetchall()

        return [
            {
                "id":           r["id"],
                "ts_utc":       r["ts_utc"],
                "scheduled_ts": r["scheduled_ts"],
                "country":      r["country"],
                "title":        r["title"],
                "impact":       r["impact"],
                "event_key":    r["event_key"],
                "actual":       r["actual"],
                "forecast":     r["forecast"],
                "previous":     r["previous"],
                "unit":         r["unit"],
            }
            for r in rows
        ]
    except Exception:
        return []
    finally:
        bc.close()


# ── Генерация и кэширование брифа ─────────────────────────────────────────────
def _get_yesterday_you(user_id: str = "default") -> dict | None:
    """SBF_Charts_Layer4_Spec, Фаза 4, блок 3 «Вчерашний ты»: последняя
    заметка/дебриф из журнала одной строкой — уже в БД, без новых расчётов.
    Спека называет и «заметку», и «дебриф» через «/» — берём более СВЕЖЕЕ из
    двух реально существующих источников (последняя заметка сделки vs
    последний тильт-дебриф), а не только один жёстко; недельная рефлексия
    (journal_review.get_prev_reflection) — запасной вариант пореже, только
    если нет ни того, ни другого за последние 7 дней (иначе "вчерашний ты"
    может показать нерелевантную рефлексию месячной давности)."""
    from core import journal_db, journal_cooldown, journal_review

    candidates = []
    try:
        trades = journal_db.list_trades(user_id=user_id, limit=20)
        for tr in trades:
            if tr.get("note") and tr["note"].strip():
                candidates.append({"kind": "trade_note", "ts": tr.get("close_ts"), "text": tr["note"].strip()})
                break
    except Exception:
        pass
    try:
        debriefs = journal_cooldown.get_debriefs(user_id=user_id, limit=1)
        # tilt_debriefs хранит 3 отдельных ответа (q1/q2/q3), не единое поле
        # text — берём q1 (первый вопрос, «что произошло») как одну строку.
        if debriefs and debriefs[0].get("q1"):
            candidates.append({"kind": "tilt_debrief", "ts": debriefs[0].get("ts"), "text": debriefs[0]["q1"].strip()})
    except Exception:
        pass

    candidates = [c for c in candidates if c.get("ts")]
    if candidates:
        candidates.sort(key=lambda c: c["ts"], reverse=True)
        best = candidates[0]
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        if best["ts"] >= cutoff:
            return best

    try:
        reflection = journal_review.get_prev_reflection(user_id)
        if reflection and reflection.strip():
            return {"kind": "weekly_reflection", "ts": None, "text": reflection.strip()}
    except Exception:
        pass
    return None


def _get_open_items(user_id: str = "default") -> dict:
    """SBF_Charts_Layer4_Spec, Фаза 4, блок 4 «Незакрытые пункты» — условные,
    отсутствие любого не оставляет дыру (спека): активный cooldown,
    доступное weekly review (ещё не заполненное на эту неделю), недавний
    незадебрифленный тильт-триггер отдельно не проверяем — get_debriefs()
    уже показывает историю, если пользователь их пишет по своей инициативе
    через существующий флоу journal_tilt, здесь дублировать нечего."""
    from core import journal_cooldown, journal_review

    items = {}
    try:
        cd = journal_cooldown.get_active_cooldown(user_id)
        if cd:
            items["cooldown"] = {"started_ts": cd.get("started_ts"), "reason": cd.get("reason")}
    except Exception:
        pass
    try:
        if journal_review.is_review_open() and not journal_review.get_this_week_review(user_id):
            items["weekly_review_available"] = True
    except Exception:
        pass
    return items


def generate_brief(user_id: str = "default") -> dict:
    """
    Собирает персональный бриф по спецификации §5.2.
    Фильтрация: только данные по символам из watchlist пользователя.
    """
    today  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    symbols = get_watchlist(user_id)

    payload = {
        "date":                   today,
        "watchlist":              symbols,
        "yesterday_retrospective": _get_yesterday_moves(symbols),
        "today_macro_calendar":   _get_today_calendar(symbols),
        "yesterday_you":          _get_yesterday_you(user_id),
        "open_items":             _get_open_items(user_id),
    }

    # Кэшировать результат
    conn = _get_conn()
    conn.execute(
        """INSERT INTO morning_briefs_cache (user_id, brief_date, payload, generated_at)
           VALUES (?,?,?,datetime('now'))
           ON CONFLICT(user_id, brief_date) DO UPDATE SET
               payload=excluded.payload,
               generated_at=excluded.generated_at""",
        (user_id, today, json.dumps(payload, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()

    return payload


def get_brief(user_id: str = "default") -> dict:
    """
    Возвращает бриф на сегодня. Использует кэш если он свежий.
    Повторные вызовы в течение дня не перегружают БД (§5.1).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn  = _get_conn()
    row   = conn.execute(
        "SELECT payload FROM morning_briefs_cache WHERE user_id=? AND brief_date=?",
        (user_id, today),
    ).fetchone()
    conn.close()

    if row:
        try:
            return json.loads(row["payload"])
        except Exception:
            pass

    return generate_brief(user_id)


def invalidate_cache(user_id: str = "default") -> None:
    """Сбросить кэш брифа (нужно при изменении watchlist)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn  = _get_conn()
    conn.execute(
        "DELETE FROM morning_briefs_cache WHERE user_id=? AND brief_date=?",
        (user_id, today),
    )
    conn.commit()
    conn.close()


ensure_schema()
