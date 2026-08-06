#!/usr/bin/env python3
"""
calendar_pull.py — Forexfactory → econ_events

Два режима (вызываются из serve.py поллера):
  pull_forward()  — thisweek + nextweek + lastweek (раз в несколько часов)
  pull_capture()  — только thisweek, ищем новые actuals (раз в 2 мин в окне события)
  has_upcoming_event(n)  — есть ли high-событие в ±n мин?

ETag / If-None-Match — не гоняем трафик без нужды.
UPSERT без DELETE — история не трогается.
Новый actual → append в econ_event_history.
"""

import sqlite3, json, time, sys, re, argparse, hashlib
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core.event_types import normalize_event_type

_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

_FEEDS = {
    "lastweek":  "https://nfs.faireconomy.media/ff_calendar_lastweek.json",
    "thisweek":  "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "nextweek":  "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
    "thismonth": "https://nfs.faireconomy.media/ff_calendar_thismonth.json",
    "nextmonth": "https://nfs.faireconomy.media/ff_calendar_nextmonth.json",
}

_TV_URL = "https://economic-calendar.tradingview.com/events"
_TV_COUNTRIES = "US,EU,GB,JP,AU,CA,CH,NZ,CN,ZA,AE,KZ"
_TV_IMP = {1: "high", 0: "medium", -1: "low"}

_UA    = {"User-Agent": "Mozilla/5.0 (compatible; SBFBot/1.0)", "Accept": "application/json"}
_UA_TV = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
    "Origin":     "https://www.tradingview.com",
    "Referer":    "https://www.tradingview.com/economic-calendar/",
}

# currency → country ISO (FF field "country" is actually the currency code)
_CUR = {
    "USD":"US","EUR":"EU","GBP":"GB","JPY":"JP","AUD":"AU",
    "CAD":"CA","CHF":"CH","CNY":"CN","NZD":"NZ","SEK":"SE",
    "NOK":"NO","SGD":"SG","KRW":"KR","ZAR":"ZA","MXN":"MX",
    "BRL":"BR","RUB":"RU","TRY":"TR","AED":"AE","KZT":"KZ",
}
_IMP = {"High":"high","Medium":"medium","Low":"low","Non-Economic":"low","Holiday":"low"}

# ETag cache (in-process, survives loop iterations)
_etags: dict[str, str] = {}
# Cooldown после 429 (per-URL, in-process) — без него pull_capture() в цикле
# каждые 2 мин продолжает долбить уже забаненный URL и никогда не восстанавливается
_blocked_until: dict[str, float] = {}
_RATE_LIMIT_COOLDOWN = 15 * 60


# ── HTTP ────────────────────────────────────────────────────────────────────

def _fetch_tv(from_dt: datetime, to_dt: datetime) -> list[dict]:
    """TradingView economic calendar — бесплатно, без ключа, месяц+."""
    from urllib.parse import urlencode
    params = urlencode({
        "from":      from_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to":        to_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "countries": _TV_COUNTRIES,
    })
    url = f"{_TV_URL}?{params}"
    try:
        with urlopen(Request(url, headers=_UA_TV), timeout=20) as r:
            data = json.loads(r.read())
            return data.get("result", []) if isinstance(data, dict) else []
    except Exception as e:
        print(f"  TV fetch: {e}", file=sys.stderr)
        return []

def _fetch(url: str) -> list[dict] | None:
    """Returns list on success, None on 304 (Not Modified), [] on error."""
    blocked = _blocked_until.get(url)
    if blocked and time.time() < blocked:
        return []
    hdrs = dict(_UA)
    if url in _etags:
        hdrs["If-None-Match"] = _etags[url]
    try:
        with urlopen(Request(url, headers=hdrs), timeout=20) as r:
            etag = r.headers.get("ETag")
            if etag:
                _etags[url] = etag
            return json.loads(r.read())
    except HTTPError as e:
        if e.code == 304:
            return None
        if e.code == 429:
            try:
                retry_after = int(e.headers.get("Retry-After", _RATE_LIMIT_COOLDOWN))
            except (TypeError, ValueError):
                retry_after = _RATE_LIMIT_COOLDOWN
            _blocked_until[url] = time.time() + max(retry_after, 60)
            print(f"  HTTP 429: {url} — пауза {max(retry_after, 60)} сек (Retry-After)", file=sys.stderr)
            return []
        if e.code != 404:
            print(f"  HTTP {e.code}: {url}", file=sys.stderr)
        return []
    except URLError as e:
        print(f"  URLError {url}: {e.reason}", file=sys.stderr)
        return []


# ── Нормализация ────────────────────────────────────────────────────────────

def _parse_ts(date_str: str) -> int | None:
    try:
        return int(datetime.fromisoformat(date_str).astimezone(timezone.utc).timestamp())
    except (ValueError, TypeError):
        return None


def _split_indicator_period(title: str, scheduled_ts: int) -> tuple[str, str]:
    """'CPI (June)' → ('CPI','June');  'NFP' → ('NFP','2026-07')"""
    m = re.match(r'^(.+?)\s*\(([^)]+)\)\s*$', title.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    dt = datetime.fromtimestamp(scheduled_ts, tz=timezone.utc)
    return title.strip(), dt.strftime("%Y-%m")


def _event_key(country: str, indicator: str) -> str:
    # ВАЖНО: без period. period меняется на каждый релиз повторяющегося
    # индикатора ("2026-07" -> "2026-08" и т.п.) -- если включить его сюда,
    # у ОДНОГО И ТОГО ЖЕ индикатора (напр. еженедельный ADP) каждый релиз
    # получает СВОЙ уникальный ключ, econ_event_history группируется по
    # event_key -- то есть история никогда не накапливается через несколько
    # релизов, только текущий период. Ключ должен идентифицировать индикатор,
    # не конкретный релиз (для этого уже есть отдельный id/ts).
    return hashlib.sha256(f"{country}|{indicator}".encode()).hexdigest()[:20]


def _row_id(ts_utc: str, country: str, title: str) -> str:
    """Стабильный PK строки (дата+страна+название)."""
    return hashlib.md5(f"{ts_utc[:10]}{country}{title}".encode()).hexdigest()[:16]


def _normalize_tv(raw: dict) -> dict | None:
    """Нормализует запись TradingView-формата."""
    title    = (raw.get("title") or "").strip()
    country  = (raw.get("country") or "").upper()
    if not title or not country:
        return None
    date_str = raw.get("date", "")
    if not date_str:
        return None
    # TV даёт UTC без суффикса: "2026-07-06T14:00:00" или "2026-07-06T14:00"
    try:
        if len(date_str) == 16:
            date_str += ":00"
        scheduled_ts = int(datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc).timestamp())
    except (ValueError, TypeError):
        return None

    indicator = (raw.get("indicator") or title).strip()
    period    = (raw.get("period") or "").strip()
    if not period:
        dt = datetime.fromtimestamp(scheduled_ts, tz=timezone.utc)
        period = dt.strftime("%Y-%m")

    ts_utc  = datetime.fromtimestamp(scheduled_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    imp_raw = raw.get("importance", -1)
    # TV returns None/blank for future actuals; coerce empty strings
    actual   = raw.get("actual")   or None
    forecast = raw.get("forecast") or None
    previous = raw.get("previous") or None

    return {
        "id":           _row_id(ts_utc, country, title),
        "event_key":    _event_key(country, indicator),
        "ts_utc":       ts_utc,
        "scheduled_ts": scheduled_ts,
        "country":      country,
        "title":        title,
        "indicator":    indicator,
        "period":       period,
        "impact":       _TV_IMP.get(imp_raw, "low"),
        "actual":       actual,
        "forecast":     forecast,
        "previous":     previous,
        "revised":      None,
        "unit":         raw.get("unit") or None,
        "source":       "tradingview",
        "yahoo_url":    "https://finance.yahoo.com/calendar/economic" if country == "US" else None,
    }

def _normalize(raw: dict) -> dict | None:
    title    = (raw.get("title") or "").strip()
    currency = (raw.get("country") or "").upper()
    if not title:
        return None
    scheduled_ts = _parse_ts(raw.get("date", ""))
    if not scheduled_ts:
        return None

    country   = _CUR.get(currency, currency[:2] if len(currency) >= 2 else "??")
    ts_utc    = datetime.fromtimestamp(scheduled_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    indicator, period = _split_indicator_period(title, scheduled_ts)

    return {
        "id":           _row_id(ts_utc, country, title),
        "event_key":    _event_key(country, indicator),
        "ts_utc":       ts_utc,
        "scheduled_ts": scheduled_ts,
        "country":      country,
        "title":        title,
        "indicator":    indicator,
        "period":       period,
        "impact":       _IMP.get(raw.get("impact", ""), "low"),
        "actual":       raw.get("actual") or None,
        "forecast":     raw.get("forecast") or None,
        "previous":     raw.get("previous") or None,
        "revised":      raw.get("revised") or None,
        "unit":         None,
        "source":       "forexfactory",
        "yahoo_url":    "https://finance.yahoo.com/calendar/economic" if country == "US" else None,
    }


# ── Schema ──────────────────────────────────────────────────────────────────

def _migrate(con: sqlite3.Connection) -> None:
    """Добавляет новые столбцы к существующей таблице (идемпотентно)."""
    new_cols = [
        ("event_key",    "TEXT"),
        ("scheduled_ts", "INTEGER"),
        ("indicator",    "TEXT"),
        ("period",       "TEXT"),
        ("revised",      "TEXT"),
        ("unit",         "TEXT"),
        ("first_seen",   "INTEGER"),
        ("updated_ts",   "INTEGER"),
        ("is_primary",   "INTEGER"),  # СПЕКА_графики_и_починка_календаря.md §3 — см. recompute_primary_flags()
    ]
    existing = {row[1] for row in con.execute("PRAGMA table_info(econ_events)")}
    for col, typ in new_cols:
        if col not in existing:
            con.execute(f"ALTER TABLE econ_events ADD COLUMN {col} {typ}")

    con.executescript("""
        CREATE TABLE IF NOT EXISTS econ_events (
            id TEXT PRIMARY KEY, ts_utc TEXT, country TEXT, title TEXT, impact TEXT,
            actual TEXT, forecast TEXT, previous TEXT, source TEXT, yahoo_url TEXT,
            cheatsheet_id TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_ee_sched ON econ_events(scheduled_ts);
        CREATE INDEX IF NOT EXISTS idx_ee_key   ON econ_events(event_key);
        CREATE TABLE IF NOT EXISTS econ_event_history (
            event_key TEXT NOT NULL, ts INTEGER NOT NULL,
            actual TEXT, forecast TEXT, previous TEXT, unit TEXT,
            PRIMARY KEY(event_key, ts)
        );
    """)

    # Заполнить scheduled_ts из ts_utc для существующих строк (один раз)
    con.execute("""
        UPDATE econ_events
        SET scheduled_ts = CAST(strftime('%s', REPLACE(ts_utc,'Z','')) AS INTEGER)
        WHERE scheduled_ts IS NULL AND ts_utc IS NOT NULL
    """)

    # Заполнить event_key / indicator / period для существующих строк
    rows = con.execute(
        "SELECT id, country, title, scheduled_ts FROM econ_events WHERE event_key IS NULL"
    ).fetchall()
    for eid, country, title, sched_ts in rows:
        if not title or not sched_ts:
            continue
        indicator, period = _split_indicator_period(title, sched_ts)
        ek = _event_key(country or "??", indicator)
        con.execute(
            "UPDATE econ_events SET event_key=?, indicator=?, period=? WHERE id=?",
            (ek, indicator, period, eid)
        )

    _migrate_stable_event_keys(con)


def _migrate_stable_event_keys(con: sqlite3.Connection) -> None:
    """event_key раньше включал period -- см. комментарий в _event_key(). Из-за
    этого econ_event_history (группируется по event_key) никогда не накапливала
    историю через несколько релизов одного повторяющегося индикатора: каждый
    новый период писал под новым ключом, а фронтенд к тому же считал event_key
    ПО-СВОЕМУ (client-side slug), не совпадавшим с этим хешем вообще -- история
    была недостижима нулём способов. Пересчитываем ключ на стабильный
    (country+indicator, без period) для всех строк и переносим уже
    накопленную историю со старых ключей на новые. Идемпотентно: после первого
    прогона event_key уже везде совпадает с новой формулой, дальше no-op."""
    rows = con.execute(
        "SELECT DISTINCT event_key, country, indicator FROM econ_events "
        "WHERE event_key IS NOT NULL AND indicator IS NOT NULL"
    ).fetchall()
    for old_key, country, indicator in rows:
        new_key = _event_key(country or "??", indicator)
        if new_key == old_key:
            continue
        con.execute("UPDATE econ_events SET event_key=? WHERE event_key=?", (new_key, old_key))
        con.execute(
            "INSERT OR IGNORE INTO econ_event_history(event_key, ts, actual, forecast, previous, unit) "
            "SELECT ?, ts, actual, forecast, previous, unit FROM econ_event_history WHERE event_key=?",
            (new_key, old_key),
        )
        con.execute("DELETE FROM econ_event_history WHERE event_key=?", (old_key,))
    con.commit()


# ── Дедупликация между источниками (СПЕКА_графики_и_починка_календаря.md §3) ─
# Приоритет источника при коллизии — тот же порядок, что уже использует
# event_reactions_job.py (_SOURCE_PRIORITY) для схлопывания при подсчёте
# статистики; здесь та же логика материализуется в саму таблицу, чтобы
# calendar.html (который просто листает econ_events без своей агрегации)
# тоже не показывал одно и то же событие 2-3 раза.
_SOURCE_PRIORITY = {"curated_official": 0, "forexfactory": 1, "tradingview": 2, "recognia_via_avatrade": 3}


def recompute_primary_flags(con: sqlite3.Connection | None = None, verbose: bool = False) -> int:
    """Группирует по (страна, время, НОРМАЛИЗОВАННЫЙ индикатор) — не по
    event_key (тот всё ещё считается из сырого текста через _event_key, а
    группировка для дедупликации намеренно использует более грубую
    normalize_event_type, которая уже умеет узнавать "Initial Jobless Claims"
    и "Unemployment Claims" как один и тот же релиз). У самой приоритетной
    по источнику строки в группе — is_primary=1, у остальных — 0. Строки НЕ
    удаляются и НЕ схлопываются в одну — расхождение прогнозов между
    источниками само по себе интересный факт (§3, §7 спеки)."""
    own_con = con is None
    if own_con:
        con = sqlite3.connect(str(_DB))
    rows = con.execute(
        "SELECT id, country, scheduled_ts, indicator, title, source FROM econ_events "
        "WHERE scheduled_ts IS NOT NULL"
    ).fetchall()
    groups: dict[tuple, list[tuple[str, str]]] = {}
    for eid, country, ts, indicator, title, source in rows:
        etype = normalize_event_type(indicator or title or "")
        groups.setdefault((country, ts, etype), []).append((eid, source))

    updates: list[tuple[int, str]] = []
    dup_groups = 0
    for key, items in groups.items():
        if len(items) > 1:
            dup_groups += 1
            items = sorted(items, key=lambda x: _SOURCE_PRIORITY.get(x[1], 9))
        primary_id = items[0][0]
        for eid, _src in items:
            updates.append((1 if eid == primary_id else 0, eid))

    con.executemany("UPDATE econ_events SET is_primary=? WHERE id=?", updates)
    con.commit()
    if verbose:
        print(f"  is_primary: {len(groups)} групп, из них с дублями между источниками: {dup_groups}")
    if own_con:
        con.close()
    return dup_groups


# ── UPSERT + history ────────────────────────────────────────────────────────

def _upsert(con: sqlite3.Connection, ev: dict) -> bool:
    """
    Insert new event or update mutable fields only (никогда не NULL-ует имеющееся).
    Возвращает True если actual только что появился → нужен append в history.
    """
    now_ts = int(time.time())
    row = con.execute(
        "SELECT actual FROM econ_events WHERE id=?", (ev["id"],)
    ).fetchone()

    if row is None:
        con.execute("""
            INSERT INTO econ_events
              (id, event_key, ts_utc, scheduled_ts, country, title, indicator, period,
               impact, actual, forecast, previous, revised, unit, source, yahoo_url,
               first_seen, updated_ts)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            ev["id"], ev["event_key"], ev["ts_utc"], ev["scheduled_ts"],
            ev["country"], ev["title"], ev["indicator"], ev["period"],
            ev["impact"], ev["actual"], ev["forecast"], ev["previous"],
            ev["revised"], ev["unit"], ev["source"], ev["yahoo_url"],
            now_ts, now_ts,
        ))
        if ev["actual"]:
            _history_append(con, ev, now_ts)
            return True
        return False

    old_actual = row[0]
    con.execute("""
        UPDATE econ_events SET
            forecast     = COALESCE(?, forecast),
            actual       = COALESCE(?, actual),
            previous     = COALESCE(?, previous),
            revised      = COALESCE(?, revised),
            event_key    = COALESCE(?, event_key),
            indicator    = COALESCE(?, indicator),
            period       = COALESCE(?, period),
            scheduled_ts = COALESCE(?, scheduled_ts),
            updated_ts   = ?
        WHERE id=?
    """, (
        ev["forecast"], ev["actual"], ev["previous"], ev["revised"],
        ev["event_key"], ev["indicator"], ev["period"], ev["scheduled_ts"],
        now_ts, ev["id"],
    ))

    # Факт появился впервые
    if ev["actual"] and not old_actual:
        _history_append(con, ev, now_ts)
        return True
    return False


def _history_append(con: sqlite3.Connection, ev: dict, ts: int) -> None:
    try:
        con.execute("""
            INSERT OR IGNORE INTO econ_event_history
              (event_key, ts, actual, forecast, previous, unit)
            VALUES (?,?,?,?,?,?)
        """, (ev["event_key"], ts, ev["actual"], ev["forecast"], ev["previous"], ev["unit"]))
    except sqlite3.Error as e:
        print(f"  history: {e}", file=sys.stderr)


# ── Публичный API ───────────────────────────────────────────────────────────

def pull_forward(verbose: bool = True) -> int:
    """
    FF thisweek/nextweek/lastweek/thismonth/nextmonth  (актуальные факты, ~2 нед)
    + TradingView следующие 35 дней                     (полный forward-горизонт)
    + TradingView последние 7 дней                       (бэкфилл actual, см. ниже)

    Бэкфилл нужен, потому что FF-путь захвата фактов (pull_capture(), только
    thisweek) на практике почти всегда упирается в HTTP 429 от nfs.faireconomy.media
    (агрессивный rate-limit, Retry-After ~5 мин) — без этого TV-бэкфилла actual
    вообще ни разу не попадал в econ_events (проверено: 601 прошедших событий,
    0 с actual). economic-calendar.tradingview.com при этом не лимитирует нас
    и честно отдаёт actual для прошедших дат — этим и пользуемся.
    """
    # ── Forexfactory ──────────────────────────────────────────────────────────
    all_ff: list[dict] = []
    for name, url in _FEEDS.items():
        data = _fetch(url)
        if data is None:
            if verbose:
                print(f"  FF {name}: 304 (без изменений)")
            continue
        if data:
            if verbose:
                print(f"  FF {name}: {len(data)} событий")
            all_ff.extend(data)
        else:
            if verbose:
                print(f"  FF {name}: нет / 404")
        time.sleep(0.3)

    # ── TradingView: следующие 35 дней + последние 7 (бэкфилл actual) ──────
    now      = datetime.now(timezone.utc)
    tv_to    = now + timedelta(days=35)
    tv_from  = now - timedelta(days=7)
    if verbose:
        print(f"  TV {now.strftime('%Y-%m-%d')} → {tv_to.strftime('%Y-%m-%d')} ...", end=" ", flush=True)
    tv_raw = _fetch_tv(now, tv_to)
    if verbose:
        print(f"{len(tv_raw)} событий")
        print(f"  TV backfill {tv_from.strftime('%Y-%m-%d')} → {now.strftime('%Y-%m-%d')} ...", end=" ", flush=True)
    tv_back_raw = _fetch_tv(tv_from, now)
    if verbose:
        print(f"{len(tv_back_raw)} событий")
    tv_raw = tv_raw + tv_back_raw

    con = sqlite3.connect(str(_DB))
    _migrate(con)
    captured = 0

    for raw in all_ff:
        ev = _normalize(raw)
        if ev is None:
            continue
        try:
            if _upsert(con, ev):
                captured += 1
        except sqlite3.Error as e:
            print(f"  DB FF upsert: {e}", file=sys.stderr)

    for raw in tv_raw:
        ev = _normalize_tv(raw)
        if ev is None:
            continue
        try:
            if _upsert(con, ev):  # TV не переписывает FF-факты (COALESCE)
                captured += 1
        except sqlite3.Error as e:
            print(f"  DB TV upsert: {e}", file=sys.stderr)

    con.commit()
    recompute_primary_flags(con, verbose=verbose)  # §3 — дедуп между источниками, каждый forward-цикл
    con.close()
    if verbose:
        total = len(all_ff) + len(tv_raw)
        print(f"  → FF {len(all_ff)} + TV {len(tv_raw)} событий, новых фактов: {captured}")
    return captured


def pull_capture(verbose: bool = False) -> int:
    """Только thisweek — ищем новые actuals. Вызывать каждые 2 мин в окне события."""
    data = _fetch(_FEEDS["thisweek"])
    if not data:
        return 0

    con = sqlite3.connect(str(_DB))
    _migrate(con)
    captured = 0
    for raw in data:
        ev = _normalize(raw)
        if ev is None or not ev["actual"]:
            continue
        try:
            if _upsert(con, ev):
                captured += 1
                if verbose:
                    print(f"  ФАКТ: {ev['country']} {ev['title']} = {ev['actual']}")
        except sqlite3.Error as e:
            print(f"  DB capture: {e}", file=sys.stderr)
    con.commit()
    con.close()
    return captured


def has_upcoming_event(within_minutes: int = 35) -> bool:
    """Есть ли high-событие без факта в окне ±within_minutes?
    Раньше проверялось high+medium — их вместе так много (Fed-спичи и т.п.,
    ~57% всех 30-минутных окон за сутки), что 2-минутный capture-луп работал
    почти непрерывно и забивал ff_calendar_thisweek.json до HTTP 429
    (см. _blocked_until в _fetch). high-only даёт ~20% окон — заметно реже."""
    now = int(time.time())
    w   = within_minutes * 60
    try:
        con = sqlite3.connect(str(_DB))
        row = con.execute("""
            SELECT 1 FROM econ_events
            WHERE impact = 'high'
              AND actual IS NULL
              AND scheduled_ts BETWEEN ? AND ?
            LIMIT 1
        """, (now - w, now + w)).fetchone()
        con.close()
        return row is not None
    except Exception:
        return False


def pull(days: int = 14) -> int:
    """Backward-compat wrapper для serve.py."""
    return pull_forward(verbose=True)


def backfill_tv(days: int = 200, chunk_days: int = 25, verbose: bool = True) -> int:
    """Разовый глубокий бэкфилл actual из TradingView для истории Фазы 2
    (обычный pull_forward() тянет только последние 7 дней назад — этого мало
    для месячных индикаторов вроде NFP/CPI, нужно 6-12 публикаций).
    TradingView режет ответ на 2000 записей — на широком окне это тихо
    обрезает данные, поэтому бьём на чанки по chunk_days."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    con = sqlite3.connect(str(_DB))
    _migrate(con)
    captured = 0
    cur = start
    while cur < now:
        chunk_to = min(cur + timedelta(days=chunk_days), now)
        raw = _fetch_tv(cur, chunk_to)
        if verbose:
            print(f"  TV {cur.strftime('%Y-%m-%d')} → {chunk_to.strftime('%Y-%m-%d')}: {len(raw)} событий"
                  + (" ⚠️ похоже обрезано лимитом 2000" if len(raw) >= 2000 else ""))
        for r in raw:
            ev = _normalize_tv(r)
            if ev is None:
                continue
            try:
                if _upsert(con, ev):
                    captured += 1
            except sqlite3.Error as e:
                print(f"  DB TV backfill upsert: {e}", file=sys.stderr)
        con.commit()
        cur = chunk_to
        time.sleep(0.3)
    con.close()
    if verbose:
        print(f"  → бэкфилл: новых фактов {captured}")
    return captured


# ── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Forexfactory/TradingView → econ_events")
    ap.add_argument("--mode", choices=["forward", "capture"], default="forward")
    ap.add_argument("--backfill-days", type=int, default=None,
                     help="Разовый глубокий бэкфилл actual из TradingView на N дней назад")
    args = ap.parse_args()

    if args.backfill_days:
        print(f"Backfill TV ({args.backfill_days}д)...")
        backfill_tv(days=args.backfill_days)
    elif args.mode == "forward":
        print("Forward (расписание вперёд)...")
        pull_forward(verbose=True)
    elif args.mode == "capture":
        print("Capture (новые факты)...")
        n = pull_capture(verbose=True)
        print(f"Захвачено: {n}")
