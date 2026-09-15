"""
journal_db.py — SQLite-хранилище дневника сделок.

Таблицы:
  trades           — история сделок (дедупликация по import_hash)
  investor_accounts — MT5-аккаунты с зашифрованным инвест-паролем
"""
from __future__ import annotations

import hashlib
import sqlite3
import os
from pathlib import Path
from typing import Any

# Путь к базе можно увести в сторону переменной SBF_JOURNAL_DB.
# Нужно для стенда: платные главы 6-15 не посмотреть без PRO, а
# выдавать себе право в боевой базе — значит пачкать прод. Со
# стендом права выдаются в КОПИИ, прод не трогаем вовсе.
_DB = Path(os.getenv("SBF_JOURNAL_DB")
          or Path(__file__).parent.parent / "data" / "journal.db")


# ── Инициализация схемы ───────────────────────────────────────────────────────
def _get_conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_schema() -> None:
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      TEXT    NOT NULL DEFAULT 'default',
            symbol       TEXT    NOT NULL,
            dir          TEXT    NOT NULL CHECK(dir IN ('buy','sell')),
            entry_price  REAL    NOT NULL,
            exit_price   REAL    NOT NULL,
            size         REAL    NOT NULL,
            open_ts      TEXT    NOT NULL,
            close_ts     TEXT    NOT NULL,
            pnl          REAL    NOT NULL,
            pnl_r        REAL    NOT NULL DEFAULT 0.0,
            fees         REAL    NOT NULL DEFAULT 0.0,
            stop_loss    REAL,
            source       TEXT    NOT NULL
                CHECK(source IN ('mt5','ocr','manual','file_import')),
            import_hash  TEXT    NOT NULL,
            note         TEXT,
            setup_tag    TEXT,
            emo_open     TEXT,
            emo_close    TEXT,
            followed_plan INTEGER DEFAULT NULL,
            created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
            UNIQUE(user_id, import_hash)
        );

        CREATE INDEX IF NOT EXISTS idx_trades_user_ts
            ON trades(user_id, close_ts);

        CREATE TABLE IF NOT EXISTS investor_accounts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       TEXT NOT NULL DEFAULT 'default',
            broker        TEXT NOT NULL,
            account_no    TEXT NOT NULL,
            server        TEXT NOT NULL,
            encrypted_pass TEXT NOT NULL,
            iv            TEXT NOT NULL,
            last_sync     TEXT,
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(user_id, account_no, server)
        );
    """)
    conn.commit()
    conn.close()


# ── Hash дедупликации (spec §1.4) ─────────────────────────────────────────────
def calc_import_hash(
    symbol: str,
    direction: str,
    size: float,
    open_ts: str,
    entry_price: float,
) -> str:
    """SHA-256(symbol|dir|size|open_ts|entry_price)"""
    raw = f"{symbol}|{direction}|{size}|{open_ts}|{entry_price}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ── R-мультипликатор (spec §1.5) ──────────────────────────────────────────────
def calc_pnl_r(
    pnl: float,
    entry_price: float,
    exit_price: float,
    stop_loss: float | None,
    avg_risk_money: float | None = None,
) -> float:
    """
    pnl_r = |exit - entry| / |entry - SL| * sign(pnl)

    Лот и контрактный мультипликатор сокращаются — формула работает
    для акций, форекс и фьючерсов без дополнительных коэффициентов.
    Fallback: pnl / avg_risk_money (если SL не задан).
    """
    if stop_loss is not None and stop_loss > 0:
        risk_pts = abs(entry_price - stop_loss)
        if risk_pts > 0:
            profit_pts = abs(exit_price - entry_price)
            sign = 1 if pnl >= 0 else -1
            return round(sign * profit_pts / risk_pts, 2)
    if avg_risk_money and avg_risk_money > 0:
        return round(pnl / avg_risk_money, 2)
    return 0.0


# ── Equity curve (spec §1.5) ──────────────────────────────────────────────────
def equity_curve(user_id: str = "default") -> list[dict]:
    """Кумулятивная сумма pnl_r по close_ts."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT close_ts, pnl_r, pnl FROM trades "
        "WHERE user_id=? ORDER BY close_ts ASC",
        (user_id,),
    ).fetchall()
    conn.close()
    cumulative = 0.0
    result = []
    for r in rows:
        cumulative += r["pnl_r"]
        result.append({
            "ts":    r["close_ts"],
            "eq_r":  round(cumulative, 2),
            "pnl_r": r["pnl_r"],
            "pnl":   r["pnl"],
        })
    return result


# ── CRUD ──────────────────────────────────────────────────────────────────────
def add_trade(t: dict, user_id: str = "default") -> dict:
    """
    Вставляет сделку. При дубликате (ON CONFLICT DO NOTHING) возвращает {duplicate: True}.
    """
    import_hash = calc_import_hash(
        t["symbol"], t["dir"], t["size"], t["open_ts"], t["entry_price"]
    )
    pnl_r = calc_pnl_r(
        t["pnl"],
        t["entry_price"],
        t["exit_price"],
        t.get("stop_loss"),
    )
    conn = _get_conn()
    try:
        # 🔴 СНАЧАЛА СПРАШИВАЕМ, ЕСТЬ ЛИ ТАКАЯ СДЕЛКА, И ТОЛЬКО ПОТОМ ВСТАВЛЯЕМ.
        #
        # Раньше вставка шла через INSERT OR IGNORE, а дубликат определялся по
        # `lastrowid == 0`. Беда в том, что OR IGNORE глотает ЛЮБОЕ нарушение
        # ограничения, не только повтор: неверное направление сделки, источник
        # не из списка, отсутствующее обязательное поле — всё это давало ровно
        # тот же признак, и наружу уходило «дубликат».
        #
        # Цена такой подмены: человек видит «эта сделка уже импортирована» и
        # ищет её в пустом журнале. Я сам на этом потерял час — послал в пробе
        # dir="long" вместо "buy", получил «duplicate: true» на пустой таблице
        # и успел решить, что сломана запись сделок. Ответ, который врёт про
        # причину, дороже ответа, которого нет.
        уже = conn.execute(
            "SELECT id FROM trades WHERE user_id=? AND import_hash=?",
            (user_id, import_hash),
        ).fetchone()
        if уже:
            return {"duplicate": True, "import_hash": import_hash,
                    "id": уже[0]}
        cur = conn.execute(
            """INSERT INTO trades
               (user_id, symbol, dir, entry_price, exit_price, size,
                open_ts, close_ts, pnl, pnl_r, fees, stop_loss,
                source, import_hash, note)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                user_id, t["symbol"], t["dir"],
                t["entry_price"], t["exit_price"], t["size"],
                t["open_ts"], t["close_ts"],
                t["pnl"], pnl_r,
                t.get("fees", 0.0), t.get("stop_loss"),
                t["source"], import_hash, t.get("note", ""),
            ),
        )
        conn.commit()
        return {"id": cur.lastrowid, "import_hash": import_hash, "pnl_r": pnl_r}
    except sqlite3.IntegrityError as e:
        # Сюда попадают именно нарушения ограничений, и теперь они называют
        # себя своим именем. Гонка (две одинаковые сделки разом) тоже сюда:
        # проверка выше её пропустит, а UNIQUE — нет; отличаем по тексту.
        текст = str(e)
        if "UNIQUE" in текст.upper():
            return {"duplicate": True, "import_hash": import_hash}
        raise ValueError(f"сделка не принята: {текст}") from e
    finally:
        conn.close()


def list_trades(
    user_id: str = "default",
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        """SELECT t.*,
               CASE WHEN jm.trade_id IS NOT NULL THEN 1 ELSE 0 END AS has_meta
           FROM trades t
           LEFT JOIN journal_meta jm ON t.id = jm.trade_id
           WHERE t.user_id=?
           ORDER BY t.close_ts DESC LIMIT ? OFFSET ?""",
        (user_id, limit, offset),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_trade(trade_id: int, user_id: str = "default") -> dict | None:
    """SBF_Charts_Layer4_Spec, Фаза 2: одна сделка, со scoping по user_id —
    та же изоляция, что list_trades/delete_trade (чужая сделка недоступна
    даже по прямому id, WHERE user_id=? в запросе, не постфильтром)."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM trades WHERE id=? AND user_id=?", (trade_id, user_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_trades_for_chart(
    user_id: str, symbols: list[str], from_iso: str, to_iso: str, limit: int = 500
) -> list[dict]:
    """SBF_Charts_Layer4_Spec, Фаза 2: сделки пользователя по алиасам символа
    графика (см. core/journal_symbols.py) в диапазоне дат — окно open_ts/
    close_ts должно ПЕРЕСЕКАТЬ [from_iso,to_iso], не просто close_ts внутри
    (иначе сделка, открытая до начала видимого окна графика, но закрытая
    внутри него, потерялась бы на левом краю)."""
    if not symbols:
        return []
    conn = _get_conn()
    placeholders = ",".join("?" * len(symbols))
    rows = conn.execute(
        f"""SELECT * FROM trades
            WHERE user_id=? AND symbol IN ({placeholders})
              AND open_ts <= ? AND close_ts >= ?
            ORDER BY open_ts DESC LIMIT ?""",
        (user_id, *symbols, to_iso, from_iso, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_trades(user_id: str = "default") -> int:
    conn = _get_conn()
    n = conn.execute(
        "SELECT COUNT(*) FROM trades WHERE user_id=?", (user_id,)
    ).fetchone()[0]
    conn.close()
    return n


def delete_trade(trade_id: int, user_id: str = "default") -> bool:
    conn = _get_conn()
    cur = conn.execute(
        "DELETE FROM trades WHERE id=? AND user_id=?", (trade_id, user_id)
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def get_stats(user_id: str = "default") -> dict:
    """Win rate, средний R, серия и т.д."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT pnl, pnl_r FROM trades WHERE user_id=? ORDER BY close_ts",
        (user_id,),
    ).fetchall()
    conn.close()
    if not rows:
        return {"total": 0, "wins": 0, "losses": 0, "winrate": 0,
                "avg_r": 0, "total_pnl": 0, "total_pnl_r": 0}
    wins   = sum(1 for r in rows if r["pnl"] > 0)
    losses = sum(1 for r in rows if r["pnl"] < 0)
    total  = len(rows)
    return {
        "total":     total,
        "wins":      wins,
        "losses":    losses,
        "winrate":   round(wins / total * 100, 1) if total else 0,
        "avg_r":     round(sum(r["pnl_r"] for r in rows) / total, 2),
        "total_pnl": round(sum(r["pnl"]   for r in rows), 2),
        "total_pnl_r": round(sum(r["pnl_r"] for r in rows), 2),
    }


# ── Investor accounts ─────────────────────────────────────────────────────────
def save_investor_account(
    broker: str,
    account_no: str,
    server: str,
    encrypted_pass: str,
    iv: str,
    user_id: str = "default",
) -> int:
    conn = _get_conn()
    cur = conn.execute(
        """INSERT OR REPLACE INTO investor_accounts
           (user_id, broker, account_no, server, encrypted_pass, iv)
           VALUES (?,?,?,?,?,?)""",
        (user_id, broker, account_no, server, encrypted_pass, iv),
    )
    conn.commit()
    conn.close()
    return cur.lastrowid


def list_investor_accounts(user_id: str = "default") -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, broker, account_no, server, last_sync, created_at "
        "FROM investor_accounts WHERE user_id=? ORDER BY id",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


ensure_schema()
