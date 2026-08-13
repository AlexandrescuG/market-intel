"""core/factor_store.py — WP1.3 SPEC_alpha_engine_implementation.md, L1.

Любой фактор -> (symbol, tf, ts, factor_key, value, asof_ts). До этого слоя
факторные таблицы (sr_levels, pattern_stats, hourly_vol_profile, ...) не
хранили момент, когда значение стало ИЗВЕСТНО -- только момент, к которому
оно относится. Без asof_ts бэктест по истории завышен и это необнаружимо
(см. §1.6 спеки, прецедент — lookahead в double_top/bottom).

Три жёсткие правила (не смягчать без явного решения Георгия):
  1. asof_ts ОБЯЗАТЕЛЕН, никогда не подставляется равным ts по умолчанию.
     Для цены — закрытие бара (обычно = ts); для COT — +3 дня; для новости —
     first_seen; для макро — момент релиза. Решение о том, чем asof_ts равен,
     принимает писатель явно на каждый вызов, а не эта библиотека молча.
  2. Ревизии не перезаписываются — put() всегда добавляет rev = max(rev)+1,
     старые строки остаются. snapshot(as_of=T) берёт последнюю ревизию среди
     тех, у кого asof_ts<=T — это и есть защита от lookahead.
  3. Символ "_GLOBAL" (см. GLOBAL_SYMBOL) — для факторов без инструмента
     (VIX, DXY, индекс макросюрпризов), чтобы не плодить дубли по всем 31.

symbol здесь — ИМЯ В ПРОСТРАНСТВЕ price_bars (XAUUSD, не GOLD) -- так же,
как сам price_bars, factor_values физически хранит цены/факторы. Канонические
(реестровые) имена — забота вызывающего кода и core.symbols_registry, не этого
модуля (см. WP1.1).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from core import db_migrations as _migrations

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

GLOBAL_SYMBOL = "_GLOBAL"

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS factor_registry (
      factor_key TEXT PRIMARY KEY, family TEXT, description TEXT, unit TEXT,
      tf_native TEXT, publish_lag INTEGER, source_job TEXT,
      status TEXT DEFAULT 'experimental', retired_ts INTEGER, retired_reason TEXT,
      history INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS factor_values (
      symbol TEXT, tf TEXT, ts INTEGER, factor_key TEXT, value REAL,
      asof_ts INTEGER NOT NULL, rev INTEGER DEFAULT 0,
      PRIMARY KEY (symbol, tf, ts, factor_key, rev)
    );
    CREATE INDEX IF NOT EXISTS idx_fv_asof ON factor_values(factor_key, asof_ts);
"""


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(_BOT_DB))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=10000")
    con.executescript(_SCHEMA)
    _migrations.apply_all(con)  # factor_registry.history (WP2, §4 ревью 12.08) — таблица
    # могла быть создана ДО появления этой колонки в _SCHEMA выше (CREATE TABLE IF NOT
    # EXISTS не трогает уже существующую таблицу).
    return con


def register_factor(factor_key: str, family: str, description: str = "", unit: str = "",
                     tf_native: str | None = None, publish_lag: int = 0,
                     source_job: str = "", status: str = "experimental",
                     history: bool = True) -> None:
    """Идемпотентная регистрация/обновление метаданных фактора в factor_registry.
    Не обязательна перед put() (таблицы независимы, без FK), но без записи
    здесь фактор не виден в каталоге -- вызывать при первом переупаковывании
    семейства (WP1.5), не при каждой записи значения.

    history=False — 🔴 ревью §4 (12.08): для 6 "снэпшот"-семейств
    (levels/pattern/vol/event-reaction/sentiment/news, категория B в
    docstring `factor_repack_job.py`) каждая запись пишется с
    asof_ts=момент repack-прогона, а не с честным моментом по бару —
    исходные таблицы (sr_levels, pattern_stats, ...) не хранят историю
    задним числом, так что per-ts исторических ревизий у этих факторов
    физически нет, только "как это выглядит сейчас". history=False
    помечает это в реестре, чтобы бэктест не мог молча принять снэпшот
    за честный временной ряд (см. `snapshot_for_backtest`)."""
    con = _connect()
    try:
        con.execute(
            """INSERT INTO factor_registry (factor_key, family, description, unit,
                                             tf_native, publish_lag, source_job, status, history)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(factor_key) DO UPDATE SET
                 family=excluded.family, description=excluded.description,
                 unit=excluded.unit, tf_native=excluded.tf_native,
                 publish_lag=excluded.publish_lag, source_job=excluded.source_job,
                 history=excluded.history""",
            (factor_key, family, description, unit, tf_native, publish_lag, source_job, status,
             1 if history else 0),
        )
        con.commit()
    finally:
        con.close()


def factor_keys_without_history(con: sqlite3.Connection | None = None) -> set[str]:
    """{factor_key} тех факторов, у кого history=0 в реестре — снэпшот-семейства
    WP1.5 категории B (см. `register_factor`). Нужен вызывающему коду
    бэктеста, чтобы явно решить, допускать их или нет (см.
    `snapshot_for_backtest`)."""
    owns_con = con is None
    con = con or _connect()
    try:
        rows = con.execute("SELECT factor_key FROM factor_registry WHERE history=0").fetchall()
        return {r[0] for r in rows}
    finally:
        if owns_con:
            con.close()


def _next_rev(con: sqlite3.Connection, symbol: str, tf: str, ts: int, factor_key: str) -> int:
    row = con.execute(
        "SELECT MAX(rev) FROM factor_values WHERE symbol=? AND tf=? AND ts=? AND factor_key=?",
        (symbol, tf, ts, factor_key),
    ).fetchone()
    return (row[0] + 1) if row and row[0] is not None else 0


def put(symbol: str, tf: str, ts: int, factor_key: str, value: float, asof_ts: int) -> int:
    """Пишет НОВУЮ ревизию, возвращает её номер. asof_ts обязателен и не
    подставляется — см. правило 1 в докстринге модуля."""
    if asof_ts is None:
        raise ValueError(
            f"asof_ts обязателен для {factor_key} ({symbol} {tf} @{ts}) — "
            "передай явно (для цены обычно = ts закрытия бара, для новости — first_seen)"
        )
    con = _connect()
    try:
        rev = _next_rev(con, symbol, tf, ts, factor_key)
        con.execute(
            "INSERT INTO factor_values (symbol, tf, ts, factor_key, value, asof_ts, rev) "
            "VALUES (?,?,?,?,?,?,?)",
            (symbol, tf, ts, factor_key, value, asof_ts, rev),
        )
        con.commit()
        return rev
    finally:
        con.close()


def put_many(rows) -> int:
    """Батч-версия put() — один коннект на всю переупаковку семейства
    (WP1.5 пишет сотни тысяч строк, put() поштучно был бы дорог по I/O).
    rows: iterable словарей с ключами symbol,tf,ts,factor_key,value,asof_ts."""
    con = _connect()
    try:
        n = 0
        for r in rows:
            if r.get("asof_ts") is None:
                raise ValueError(f"asof_ts обязателен: {r}")
            rev = _next_rev(con, r["symbol"], r["tf"], r["ts"], r["factor_key"])
            con.execute(
                "INSERT INTO factor_values (symbol, tf, ts, factor_key, value, asof_ts, rev) "
                "VALUES (?,?,?,?,?,?,?)",
                (r["symbol"], r["tf"], r["ts"], r["factor_key"], r["value"], r["asof_ts"], rev),
            )
            n += 1
        con.commit()
        return n
    finally:
        con.close()


def snapshot(symbol: str, tf: str, ts: int, as_of: int | None = None) -> dict[str, float]:
    """{factor_key: value} на баре (symbol,tf,ts) — последняя ревизия каждого
    фактора. as_of=None — без ограничения по asof_ts (берёт самую свежую
    ревизию как есть, для live-использования). as_of=T — правило 2: НЕ
    возвращает ни одного значения с asof_ts>T (защита от lookahead в
    бэктесте, тестируется на подложенных данных в Acceptance WP1)."""
    con = _connect()
    try:
        if as_of is None:
            rows = con.execute(
                "SELECT factor_key, value, MAX(rev) FROM factor_values "
                "WHERE symbol=? AND tf=? AND ts=? GROUP BY factor_key",
                (symbol, tf, ts),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT factor_key, value, MAX(rev) FROM factor_values "
                "WHERE symbol=? AND tf=? AND ts=? AND asof_ts<=? GROUP BY factor_key",
                (symbol, tf, ts, as_of),
            ).fetchall()
        return {fk: v for fk, v, _ in rows}
    finally:
        con.close()


def snapshot_for_backtest(symbol: str, tf: str, ts: int, as_of: int) -> dict[str, float]:
    """🔴 Guard, ревью §4 (12.08): обёртка над `snapshot()` для БЭКТЕСТА
    (историческое окно, НЕ live) — `as_of` обязателен (в отличие от
    `snapshot()`, где None разрешён для live-использования: здесь его
    отсутствие означало бы честную ошибку вызывающего кода, не смягчаем).

    Дополнительно ВСЕГДА выкидывает из результата любые factor_key с
    history=0 в реестре (снэпшот-семейства WP1.5 категории B) — даже
    формально пройдя asof_ts<=as_of, их единственная запись физически
    отражает "как это выглядело в момент repack-прогона", а не честную
    историю на баре ts (см. `register_factor`). Тихая фильтрация, не
    исключение — бэктест на 20+ факторах не должен падать из-за одного
    снэпшот-семейства; вызывающий код видит недостачу по составу ключей
    в возвращённом dict, не по краху."""
    no_history = factor_keys_without_history()
    values = snapshot(symbol, tf, ts, as_of=as_of)
    return {fk: v for fk, v in values.items() if fk not in no_history}
