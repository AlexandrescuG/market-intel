"""core/focus_db.py — Focus Engine: слой персистентности (bot.db).

Разделено от core/focus.py намеренно: там чистая арифметика/гистерезис без
БД (тестируется синтетическими данными), здесь — всё, что трогает SQLite.
Общий модуль для focus_batch_job.py, focus_live.py и serve.py (API), чтобы
схема/сиды создавались и читались в одном месте, не дублировались по job'ам.

Таблицы -- в bot.db (там же, где day_thermo/econ_events/price_bars уже
живут, см. day_thermo_job.py), НЕ в market_intel's собственных data/*.db --
это system-wide инструментальное состояние, а не signals/journal-специфика.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from core.focus import (DEFAULT_UNIVERSE, MIN_SANE_SHARE, NO_LIVE_FEED, FocusState,
                        anomaly, running_tr, sane_share)
from core.sessions import us_dst_active
from core import journal_brief
from core.journal_symbols import to_chart_symbol

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS instrument (
  symbol TEXT PRIMARY KEY, name TEXT NOT NULL, asset_class TEXT NOT NULL,
  quote_kind TEXT NOT NULL, decimals INTEGER DEFAULT 2, live_capable INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS atr_cache (
  symbol TEXT, date TEXT, n INTEGER, atr REAL, prev_close REAL,
  PRIMARY KEY (symbol, date)
);
CREATE TABLE IF NOT EXISTS instrument_live (
  symbol TEXT PRIMARY KEY, ts INTEGER,
  day_open REAL, day_high REAL, day_low REAL, last REAL, session_state TEXT
);
CREATE TABLE IF NOT EXISTS session_hours (
  asset_class TEXT PRIMARY KEY, tz TEXT, open_min INTEGER, close_min INTEGER,
  days_mask INTEGER
);
CREATE TABLE IF NOT EXISTS focus_state (
  scope_key TEXT PRIMARY KEY, symbol TEXT, anomaly REAL, decided_at INTEGER, source TEXT
);
"""

# (symbol, name, asset_class, quote_kind, decimals, live_capable)
_INSTRUMENT_SEED = [
    ("GOLD",   "Gold (XAU/USD)",   "metal",     "usd",    1, 1),
    ("SILVER", "Silver (XAG/USD)", "metal",     "usd",    2, 1),
    ("BTC",    "Bitcoin",          "crypto",    "usd",    1, 1),
    ("ETH",    "Ethereum",         "crypto",    "usd",    1, 1),
    ("SOL",    "Solana",           "crypto",    "usd",    2, 1),
    ("EURUSD", "EUR/USD",          "fx",        "usd",    4, 1),
    ("GBPUSD", "GBP/USD",          "fx",        "usd",    4, 1),
    ("SPX",    "S&P 500",          "index",     "points", 1, 1),
    ("NASDAQ", "Nasdaq 100",       "index",     "points", 1, 1),
    ("DJI",    "Dow Jones",        "index",     "points", 1, 1),
    ("WTI",    "WTI Crude Oil",    "commodity", "usd",    2, 1),
    ("NG",     "Natural Gas",      "commodity", "usd",    3, 1),
    ("DXY",    "US Dollar Index",  "fx",        "points", 2, 1),
    ("USDJPY", "USD/JPY",          "fx",        "usd",    3, 0),
    ("USDRUB", "USD/RUB",          "fx",        "usd",    2, 0),
]
# USDKZT выведен из вселенной 14.09.2026 (см. причину в core/focus.py), но
# остаётся в NO_LIVE_FEED: это справочник свойств инструмента, а не список
# показываемого, и запись «у тенге нет живого фида» от вывода из витрины не
# перестала быть правдой.
assert {r[0] for r in _INSTRUMENT_SEED} == set(DEFAULT_UNIVERSE)
assert {r[0] for r in _INSTRUMENT_SEED if r[5] == 0} <= NO_LIVE_FEED

# (asset_class, tz, open_min, close_min, days_mask) -- часы в СТАНДАРТНОМ
# (зимнем, не-DST) времени для index; DST-сдвиг применяется в рантайме
# (см. _apply_dst ниже) через core.sessions.us_dst_active -- в буквальной
# схеме спеки нет отдельной колонки под DST-правило, поэтому храним
# canonical off-DST границы и сдвигаем на чтении, а не второй колонкой.
# days_mask: бит i = день недели i (Python .weekday(): Mon=0..Sun=6).
_MON_FRI = 0b0011111   # биты 0..4
_ALL_WEEK = 0b1111111  # биты 0..6
_SESSION_HOURS_SEED = [
    ("crypto",    "UTC", 0, 1440, _ALL_WEEK),
    # FX/металлы/энергоносители -- почти 24/5, упрощено до "весь Пн-Пт" (не
    # моделируем закрытие в пятницу вечером/открытие в воскресенье вечером
    # с точностью до минуты -- см. план, "не критично для ранжирования").
    ("fx",        "UTC", 0, 1440, _MON_FRI),
    ("metal",     "UTC", 0, 1440, _MON_FRI),
    ("commodity", "UTC", 0, 1440, _MON_FRI),
    # US RTH 9:30-16:00 ET в СТАНДАРТНОМ (EST, зима) времени = 14:30-21:00 UTC.
    ("index",     "America/New_York", 14 * 60 + 30, 21 * 60, _MON_FRI),
]


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(_BOT_DB), timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=10000")
    con.row_factory = sqlite3.Row
    return con


def ensure_schema(con: sqlite3.Connection | None = None) -> None:
    """Идемпотентно: создать таблицы + засеять instrument/session_hours если
    пусты. Вызывается в начале run() обоих джобов (день_thermo_job.py стиль)."""
    own = con is None
    if own:
        con = _connect()
    try:
        con.executescript(_SCHEMA)
        if not con.execute("SELECT 1 FROM instrument LIMIT 1").fetchone():
            con.executemany(
                "INSERT INTO instrument(symbol,name,asset_class,quote_kind,decimals,live_capable) "
                "VALUES (?,?,?,?,?,?)",
                _INSTRUMENT_SEED,
            )
        if not con.execute("SELECT 1 FROM session_hours LIMIT 1").fetchone():
            con.executemany(
                "INSERT INTO session_hours(asset_class,tz,open_min,close_min,days_mask) VALUES (?,?,?,?,?)",
                _SESSION_HOURS_SEED,
            )
        con.commit()
    finally:
        if own:
            con.close()


def _apply_dst(asset_class: str, open_min: int, close_min: int, now_utc: datetime) -> tuple[int, int]:
    """index (US RTH) сдвигается на -60 мин (раньше по UTC) во время DST --
    9:30-16:00 ET это 14:30-21:00 UTC зимой, 13:30-20:00 UTC летом."""
    if asset_class == "index" and us_dst_active(now_utc.date()):
        return open_min - 60, close_min - 60
    return open_min, close_min


def compute_session_state(asset_class: str, now_utc: datetime) -> str:
    """'open'|'closed' -- §5. Читает session_hours (сиды гарантированы
    ensure_schema()); часовая/дневная маска, без внешних библиотек."""
    con = _connect()
    try:
        row = con.execute(
            "SELECT open_min, close_min, days_mask FROM session_hours WHERE asset_class=?",
            (asset_class,),
        ).fetchone()
    finally:
        con.close()
    if not row:
        return "open"  # неизвестный asset_class -- не блокировать ранжирование
    open_min, close_min = _apply_dst(asset_class, row["open_min"], row["close_min"], now_utc)
    if not (row["days_mask"] & (1 << now_utc.weekday())):
        return "closed"
    minute_of_day = now_utc.hour * 60 + now_utc.minute
    return "open" if open_min <= minute_of_day < close_min else "closed"


def load_instrument(symbol: str) -> sqlite3.Row | None:
    con = _connect()
    try:
        return con.execute("SELECT * FROM instrument WHERE symbol=?", (symbol,)).fetchone()
    finally:
        con.close()


def all_instruments(live_capable_only: bool = False) -> list[sqlite3.Row]:
    con = _connect()
    try:
        q = "SELECT * FROM instrument"
        if live_capable_only:
            q += " WHERE live_capable=1"
        return con.execute(q).fetchall()
    finally:
        con.close()


def save_atr_cache(symbol: str, trading_date: str, n: int, atr: float | None, prev_close: float | None) -> None:
    con = _connect()
    try:
        con.execute(
            "INSERT OR REPLACE INTO atr_cache(symbol,date,n,atr,prev_close) VALUES (?,?,?,?,?)",
            (symbol, trading_date, n, atr, prev_close),
        )
        con.commit()
    finally:
        con.close()


def load_atr_today(symbol: str, trading_date: str) -> sqlite3.Row | None:
    con = _connect()
    try:
        return con.execute(
            "SELECT * FROM atr_cache WHERE symbol=? AND date=?", (symbol, trading_date)
        ).fetchone()
    finally:
        con.close()


def save_instrument_live(symbol: str, ts: int, day_open: float | None, day_high: float,
                          day_low: float, last: float, session_state: str) -> None:
    con = _connect()
    try:
        con.execute(
            "INSERT OR REPLACE INTO instrument_live(symbol,ts,day_open,day_high,day_low,last,session_state) "
            "VALUES (?,?,?,?,?,?,?)",
            (symbol, ts, day_open, day_high, day_low, last, session_state),
        )
        con.commit()
    finally:
        con.close()


def load_instrument_live(symbol: str) -> sqlite3.Row | None:
    con = _connect()
    try:
        return con.execute("SELECT * FROM instrument_live WHERE symbol=?", (symbol,)).fetchone()
    finally:
        con.close()


def load_focus_state(scope_key: str) -> FocusState | None:
    con = _connect()
    try:
        row = con.execute("SELECT * FROM focus_state WHERE scope_key=?", (scope_key,)).fetchone()
    finally:
        con.close()
    if not row:
        return None
    return FocusState(row["scope_key"], row["symbol"], row["anomaly"], row["decided_at"], row["source"])


def save_focus_state(state: FocusState) -> None:
    con = _connect()
    try:
        con.execute(
            "INSERT OR REPLACE INTO focus_state(scope_key,symbol,anomaly,decided_at,source) VALUES (?,?,?,?,?)",
            (state.scope_key, state.symbol, state.anomaly, state.decided_at, state.source),
        )
        con.commit()
    finally:
        con.close()


def today_str(now_utc: datetime | None = None) -> str:
    return (now_utc or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


_негодные: dict[str, float] = {}      # символ → доля целых баров, для отчёта


def _ряд_годен(con, symbol: str, today: str, дней: int = 120) -> bool:
    """Достаточно ли целых баров в ряду, чтобы ему верить.

    Смотрим последние ~120 дневных баров: более старая история на отбор
    сегодняшнего фокуса не влияет, а гонять весь ряд каждый цикл незачем.
    Если таблицы/баров нет — не мешаем работать: отсутствие данных это не
    порча данных, и такой инструмент отсеется выше по ATR.
    """
    try:
        rows = con.execute(
            "SELECT o, h, l, c FROM price_bars WHERE symbol=? AND tf='1d' "
            "ORDER BY ts DESC LIMIT ?", (symbol, дней)).fetchall()
    except sqlite3.Error:
        return True
    if len(rows) < 20:
        return True
    доля = sane_share([{"o": r["o"], "h": r["h"], "l": r["l"], "c": r["c"]} for r in rows])
    if доля < MIN_SANE_SHARE:
        _негодные[symbol] = доля
        return False
    _негодные.pop(symbol, None)
    return True


def rejected_series() -> dict[str, float]:
    """{символ: доля целых баров} — кого отсеяли по порче ряда в этом прогоне.

    🔴 Отсев обязан быть видимым. Молчаливый фильтр по качеству данных — это
    способ годами не замечать, что половина вселенной инструментов
    развалилась: витрина просто показывает то, что осталось.
    """
    return dict(_негодные)


def build_candidates(symbols: list[str], today: str) -> list[tuple[str, float | None]]:
    """§10: "live = load_live(w.symbol); atr = load_atr_today(w.symbol); if
    not live or live.session_state != 'open': continue; if atr is None:
    continue; runningTR = ...; cands.append((w.symbol, runningTR/atr.atr))".
    Общая сборка кандидатов для select_focus() -- используется и batch
    (scope='default', current=None), и live (каждый scope) джобами, чтобы
    фильтрация session_state/ATR не дублировалась в двух местах."""
    con = _connect()
    try:
        out = []
        for symbol in symbols:
            live = con.execute(
                "SELECT * FROM instrument_live WHERE symbol=?", (symbol,)
            ).fetchone()
            if not live or live["session_state"] != "open":
                continue
            atr_row = con.execute(
                "SELECT * FROM atr_cache WHERE symbol=? AND date=?", (symbol, today)
            ).fetchone()
            if atr_row is None or atr_row["atr"] is None:
                continue
            # 🔴 Инструмент с гнилым рядом в отбор не допускается.
            #
            # Фокус ранжирует по runningTR/ATR — по размаху относительно
            # нормы. Значит любая порча, раздувающая размах, выигрывает
            # автоматически: отбор «самого аномального» молча превращается
            # в отбор «самого испорченного». 14.09.2026 так и было: 12 из
            # 19 подборов — USDKZT, у которого 59% дневных баров имеют
            # закрытие ВНЕ диапазона [low, high].
            #
            # Проверка стоит здесь, а не в select_focus(): та функция
            # намеренно без обращения к БД, а судить о годности ряда можно
            # только по самому ряду.
            if not _ряд_годен(con, symbol, today):
                continue
            tr = running_tr(live["day_high"], live["day_low"], atr_row["prev_close"])
            out.append((symbol, anomaly(tr, atr_row["atr"])))
        return out
    finally:
        con.close()


def active_user_scopes() -> list[str]:
    """Пользователи (не 'default') с непустым ватчлистом и БЕЗ пина
    (запиненным select_focus() не нужен -- пин читается напрямую в API).
    Общее для focus_live.py (каждый тик) и focus_batch_job.py (раз в день,
    чтобы персональные scope тоже получали source="batch" -> LLM-разбор,
    не только 'default' -- см. серию находок про "куцую" карточку у
    залогиненных пользователей с собственным watchlist/пином)."""
    return [uid for uid in journal_brief.list_watchlist_user_ids(exclude_default=True)
            if not journal_brief.get_pinned(uid)]


def scope_symbols(user_id: str | None) -> list[str]:
    if user_id is None:
        return DEFAULT_UNIVERSE
    raw = journal_brief.get_watchlist(user_id)
    if not raw:
        return DEFAULT_UNIVERSE
    mapped = []
    for s in raw:
        chart_sym = to_chart_symbol(s) or (s if s in DEFAULT_UNIVERSE else None)
        if chart_sym:
            mapped.append(chart_sym)
    return mapped or DEFAULT_UNIVERSE
