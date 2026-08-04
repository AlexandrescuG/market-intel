"""
journal_import.py — Парсер и импортёр MT4/MT5/CSV для SBF Journal.

Поддерживаемые форматы:
  - MT5 HTML Report (ReportHistory-*.html)  — таблица Positions/Deals
  - MT4 HTML Statement (Statement.htm)      — таблица с Ticket/Open Time/...
  - CSV (авто-разделитель ,/; кодировки utf-8/utf-16/cp1251)

Дедупликация: SHA-256(symbol|dir|size|open_ts|entry_price)[:16] уже в journal_db.
"""
from __future__ import annotations

import csv
import hashlib
import html.parser
import io
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .journal_db import _get_conn as _db_conn, calc_import_hash, add_trade

_DB = Path(__file__).parent.parent / "data" / "journal.db"

_SKIP_TYPES = frozenset({"balance", "credit", "deposit", "withdrawal", "bonus", "correction"})
_BUY_SYMS   = frozenset({"buy", "long"})
_SELL_SYMS  = frozenset({"sell", "short"})


def ensure_schema() -> None:
    conn = _db_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS import_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT NOT NULL DEFAULT 'default',
            filename    TEXT NOT NULL,
            format      TEXT NOT NULL,
            parsed      INTEGER NOT NULL DEFAULT 0,
            imported    INTEGER NOT NULL DEFAULT 0,
            duplicates  INTEGER NOT NULL DEFAULT 0,
            skipped     INTEGER NOT NULL DEFAULT 0,
            ts          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
        );
    """)
    conn.commit()
    conn.close()


def _normalize_symbol(s: str) -> str:
    """Убираем суффиксы брокера (.m, _ecn, .pro и т.д.) если базовый символ ≥4 симв."""
    s = s.strip().upper()
    cleaned = re.sub(r"[._-][a-z]+$", "", s, flags=re.IGNORECASE)
    return cleaned if len(cleaned) >= 4 else s


def _parse_datetime_mt(s: str, tz_offset_min: int = 0) -> str:
    """Парсит MT4/MT5 время (YYYY.MM.DD HH:MM:SS или YYYY-MM-DD HH:MM:SS) → UTC ISO."""
    s = s.strip().replace(".", "-")
    fmts = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"]
    dt = None
    for fmt in fmts:
        try:
            dt = datetime.strptime(s, fmt)
            break
        except ValueError:
            continue
    if dt is None:
        raise ValueError(f"Неизвестный формат даты: {s!r}")
    # Вычесть смещение брокера чтобы получить UTC
    dt_utc = dt - timedelta(minutes=tz_offset_min)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%S")


# ── HTML парсер (общий для MT4 и MT5) ────────────────────────────────────────

class _TableParser(html.parser.HTMLParser):
    """Извлекает все таблицы из HTML как список списков строк."""

    def __init__(self):
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._cur_table: list[list[str]] | None = None
        self._cur_row: list[str] | None = None
        self._cur_cell: str = ""
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._cur_table = []
        elif tag in ("tr",) and self._cur_table is not None:
            self._cur_row = []
        elif tag in ("td", "th") and self._cur_row is not None:
            self._cur_cell = ""
            self._in_cell = True

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._in_cell:
            self._cur_row.append(self._cur_cell.strip())
            self._in_cell = False
            self._cur_cell = ""
        elif tag == "tr" and self._cur_row is not None and self._cur_table is not None:
            self._cur_table.append(self._cur_row)
            self._cur_row = None
        elif tag == "table" and self._cur_table is not None:
            self.tables.append(self._cur_table)
            self._cur_table = None

    def handle_data(self, data):
        if self._in_cell:
            self._cur_cell += data


def _parse_mt5_html(content: str, tz_offset_min: int = 0) -> list[dict]:
    """Парсить MT5 HTML Report. Возвращает список сырых сделок."""
    p = _TableParser()
    p.feed(content)

    trades = []
    for table in p.tables:
        if len(table) < 2:
            continue
        header = [c.strip().lower() for c in table[0]]
        # Ищем таблицу с ключевыми колонками MT5
        col_map: dict[str, int] = {}
        for i, h in enumerate(header):
            if "ticket" in h or "position" in h:
                col_map.setdefault("ticket", i)
            if "open time" in h or "time" in h and i < 4:
                col_map.setdefault("open_time", i)
            if "type" in h:
                col_map.setdefault("type", i)
            if "volume" in h or "size" in h or "lots" in h:
                col_map.setdefault("volume", i)
            if "symbol" in h or "item" in h:
                col_map.setdefault("symbol", i)
            if "price" in h and "open" in h:
                col_map.setdefault("open_price", i)
            elif "price" in h and i not in col_map.values():
                col_map.setdefault("open_price", i)
            if "s / l" in h or "s/l" in h or "stop" in h:
                col_map.setdefault("sl", i)
            if "t / p" in h or "t/p" in h or "take" in h:
                col_map.setdefault("tp", i)
            if "close time" in h:
                col_map.setdefault("close_time", i)
            if "close price" in h:
                col_map.setdefault("close_price", i)
            if "profit" in h and "point" not in h:
                col_map.setdefault("profit", i)

        needed = {"open_time", "type", "volume", "symbol", "open_price"}
        if not needed.issubset(col_map):
            # Попытаться по позиции для типичного MT5 (Ticket,Open,Type,Volume,Symbol,Price,S/L,T/P,Close,Price,Profit)
            if len(header) >= 9:
                col_map = {
                    "ticket": 0, "open_time": 1, "type": 2, "volume": 3,
                    "symbol": 4, "open_price": 5, "sl": 6, "tp": 7,
                    "close_time": 8, "close_price": 9, "profit": 10 if len(header) > 10 else 9,
                }
            else:
                continue

        for row in table[1:]:
            if len(row) <= max(col_map.values()):
                continue
            def g(k, default=""):
                idx = col_map.get(k)
                return row[idx].strip() if idx is not None and idx < len(row) else default

            trade_type = g("type").lower()
            if any(skip in trade_type for skip in _SKIP_TYPES):
                continue
            if trade_type not in _BUY_SYMS and trade_type not in _SELL_SYMS:
                continue

            symbol_raw = g("symbol")
            if not symbol_raw:
                continue

            try:
                open_ts  = _parse_datetime_mt(g("open_time"), tz_offset_min)
                close_ts = _parse_datetime_mt(g("close_time"), tz_offset_min) if g("close_time") else open_ts
                op  = float(g("open_price").replace(",", ".") or "0")
                cp  = float(g("close_price").replace(",", ".") or "0") if g("close_price") else op
                vol = float(g("volume").replace(",", ".") or "0")
                pnl = float(g("profit").replace(",", ".").replace(" ", "") or "0")
                sl_raw = g("sl")
                sl = float(sl_raw.replace(",", ".")) if sl_raw and sl_raw not in ("0", "0.00", "") else None
            except (ValueError, TypeError):
                continue

            if vol <= 0 or op <= 0:
                continue

            trades.append({
                "symbol":      _normalize_symbol(symbol_raw),
                "dir":         "buy" if trade_type in _BUY_SYMS else "sell",
                "open_ts":     open_ts,
                "close_ts":    close_ts,
                "entry_price": op,
                "exit_price":  cp,
                "volume":      vol,
                "stop_loss":   sl,
                "pnl":         pnl,
            })
    return trades


def _parse_mt4_html(content: str, tz_offset_min: int = 0) -> list[dict]:
    """Парсить MT4 Statement.htm — аналогично MT5 но с другими заголовками."""
    # MT4 формат: Ticket, Open Time, Type, Size, Item, Open Price, S/L, T/P, Close Time, Close Price, Profit
    p = _TableParser()
    p.feed(content)

    trades = []
    for table in p.tables:
        if len(table) < 2:
            continue
        header = [c.strip().lower() for c in table[0]]
        if "ticket" not in " ".join(header) and "open time" not in " ".join(header):
            continue

        col_map = {
            "ticket": None, "open_time": None, "type": None, "size": None,
            "item": None, "open_price": None, "sl": None, "tp": None,
            "close_time": None, "close_price": None, "profit": None,
        }
        for i, h in enumerate(header):
            if h in ("ticket", "#"):
                col_map["ticket"] = i
            elif "open time" in h:
                col_map["open_time"] = i
            elif h == "type":
                col_map["type"] = i
            elif h in ("size", "volume", "lots"):
                col_map["size"] = i
            elif h in ("item", "symbol"):
                col_map["item"] = i
            elif h == "open price" or (h == "price" and col_map["open_price"] is None):
                col_map["open_price"] = i
            elif "s / l" in h or h == "s/l":
                col_map["sl"] = i
            elif "t / p" in h or h == "t/p":
                col_map["tp"] = i
            elif "close time" in h:
                col_map["close_time"] = i
            elif "close price" in h:
                col_map["close_price"] = i
            elif "profit" in h:
                col_map["profit"] = i

        # Фоллбэк по позиции (стандартный MT4)
        if col_map["open_time"] is None and len(header) >= 10:
            cols = list(col_map.keys())
            for idx, key in enumerate(cols):
                col_map[key] = idx

        for row in table[1:]:
            def g(k, default=""):
                idx = col_map.get(k)
                return row[idx].strip() if idx is not None and idx < len(row) else default

            trade_type = g("type").lower()
            if any(skip in trade_type for skip in _SKIP_TYPES):
                continue
            symbol_raw = g("item")
            if not symbol_raw or trade_type not in _BUY_SYMS and trade_type not in _SELL_SYMS:
                continue
            try:
                open_ts  = _parse_datetime_mt(g("open_time"), tz_offset_min)
                close_ts = _parse_datetime_mt(g("close_time"), tz_offset_min) if g("close_time") else open_ts
                op  = float(g("open_price").replace(",", ".") or "0")
                cp  = float(g("close_price").replace(",", ".") or "0") if g("close_price") else op
                vol = float(g("size").replace(",", ".") or "0")
                pnl = float(g("profit").replace(",", ".").replace(" ", "") or "0")
                sl_raw = g("sl")
                sl = float(sl_raw.replace(",", ".")) if sl_raw and sl_raw not in ("0", "0.00", "") else None
            except (ValueError, TypeError):
                continue
            if vol <= 0 or op <= 0:
                continue
            trades.append({
                "symbol":      _normalize_symbol(symbol_raw),
                "dir":         "buy" if trade_type in _BUY_SYMS else "sell",
                "open_ts":     open_ts,
                "close_ts":    close_ts,
                "entry_price": op,
                "exit_price":  cp,
                "volume":      vol,
                "stop_loss":   sl,
                "pnl":         pnl,
            })
    return trades


def _parse_csv_bytes(content_bytes: bytes, tz_offset_min: int = 0) -> list[dict]:
    """Парсить CSV (авто-определение разделителя и кодировки)."""
    for enc in ("utf-8-sig", "utf-16", "cp1251"):
        try:
            text = content_bytes.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            text = None
    if text is None:
        text = content_bytes.decode("latin-1")

    # Определить разделитель
    first_line = text.splitlines()[0] if text else ""
    delimiter = ";" if first_line.count(";") >= first_line.count(",") else ","

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return []

    # Нормализовать заголовки
    fieldnames = {k.strip().lower().replace(" ", "_"): k for k in (rows[0].keys() if rows else [])}

    def find_col(*candidates):
        for c in candidates:
            for norm, orig in fieldnames.items():
                if c in norm:
                    return orig
        return None

    col_symbol = find_col("symbol", "item", "instrument")
    col_type   = find_col("type", "direction", "side")
    col_open_t = find_col("open_time", "open time", "entry_time", "opentime")
    col_close_t = find_col("close_time", "close time", "exit_time", "closetime")
    col_size   = find_col("volume", "size", "lots")
    col_op     = find_col("open_price", "entry_price", "open price")
    col_cp     = find_col("close_price", "exit_price", "close price")
    col_sl     = find_col("s/l", "stop_loss", "sl")
    col_pnl    = find_col("profit", "pnl")

    trades = []
    for row in rows:
        def g(col, default=""):
            return row[col].strip() if col and col in row else default

        trade_type = g(col_type).lower()
        if not trade_type or any(skip in trade_type for skip in _SKIP_TYPES):
            continue
        if trade_type not in _BUY_SYMS and trade_type not in _SELL_SYMS:
            continue
        symbol_raw = g(col_symbol)
        if not symbol_raw:
            continue
        try:
            open_ts  = _parse_datetime_mt(g(col_open_t), tz_offset_min)
            close_ts = _parse_datetime_mt(g(col_close_t), tz_offset_min) if g(col_close_t) else open_ts
            op  = float(g(col_op).replace(",", ".") or "0")
            cp  = float(g(col_cp).replace(",", ".") or "0") if g(col_cp) else op
            vol = float(g(col_size).replace(",", ".") or "0")
            pnl = float(g(col_pnl).replace(",", ".").replace(" ", "") or "0") if col_pnl else 0.0
            sl_raw = g(col_sl) if col_sl else ""
            sl = float(sl_raw.replace(",", ".")) if sl_raw and sl_raw not in ("0", "0.00", "") else None
        except (ValueError, TypeError):
            continue
        if vol <= 0:
            continue
        trades.append({
            "symbol":      _normalize_symbol(symbol_raw),
            "dir":         "buy" if trade_type in _BUY_SYMS else "sell",
            "open_ts":     open_ts,
            "close_ts":    close_ts,
            "entry_price": op,
            "exit_price":  cp,
            "volume":      vol,
            "stop_loss":   sl,
            "pnl":         pnl,
        })
    return trades


def detect_format(filename: str, content: bytes) -> str:
    """Определить формат файла."""
    fname = filename.lower()
    if fname.endswith((".htm", ".html")):
        snippet = content[:2000].lower()
        if b"reporthistory" in snippet or b"positions" in snippet:
            return "mt5_html"
        if b"statement" in snippet or b"open time" in snippet:
            return "mt4_html"
        return "mt5_html"  # попробуем mt5 по умолчанию
    if fname.endswith(".csv") or fname.endswith(".txt"):
        return "csv"
    # Heuristic
    if content[:3] in (b"\xff\xfe", b"\xfe\xff") or content[:4] == b"\xff\xfe\x00\x00":
        return "csv"
    snippet = content[:500].lower()
    if b"<html" in snippet or b"<!doctype" in snippet:
        return "mt4_html"
    return "csv"


def parse_file(filename: str, content_bytes: bytes, broker_tz_offset: int = 0) -> tuple[list[dict], list[str]]:
    """Распарсить файл. Возвращает (trade_rows, errors)."""
    fmt = detect_format(filename, content_bytes)
    errors: list[str] = []
    try:
        if fmt == "mt5_html":
            text = content_bytes.decode("utf-8", errors="replace")
            rows = _parse_mt5_html(text, broker_tz_offset)
        elif fmt == "mt4_html":
            text = content_bytes.decode("utf-8", errors="replace")
            rows = _parse_mt4_html(text, broker_tz_offset)
        else:
            rows = _parse_csv_bytes(content_bytes, broker_tz_offset)
    except Exception as e:
        return [], [f"Ошибка парсинга: {e}"]
    return rows, errors


def import_trades(
    rows: list[dict],
    user_id: str = "default",
    filename: str = "",
    fmt: str = "file_import",
) -> dict:
    """Импортировать подготовленные строки в БД. Возвращает статистику."""
    ensure_schema()
    parsed = len(rows)
    imported = 0
    duplicates = 0
    errors: list[str] = []

    for t in rows:
        try:
            result = add_trade({
                "symbol":      t["symbol"],
                "dir":         t["dir"],
                "entry_price": t["entry_price"],
                "exit_price":  t["exit_price"],
                "size":        t["volume"],
                "open_ts":     t["open_ts"],
                "close_ts":    t["close_ts"],
                "pnl":         t["pnl"],
                "fees":        0.0,
                "stop_loss":   t.get("stop_loss"),
                "source":      "file_import",
                "note":        "",
            }, user_id=user_id)
            if result.get("duplicate"):
                duplicates += 1
            else:
                imported += 1
        except Exception as e:
            errors.append(str(e))

    # Лог
    conn = _db_conn()
    conn.execute(
        "INSERT INTO import_log(user_id,filename,format,parsed,imported,duplicates,skipped) VALUES(?,?,?,?,?,?,?)",
        (user_id, filename[:255], fmt, parsed, imported, duplicates, len(errors)),
    )
    conn.commit()
    conn.close()

    # XP за импорт — cap 100 XP
    if imported > 0:
        try:
            from . import journal_gamification
            xp = min(imported * 10, 100)
            journal_gamification.award_xp("import_batch", xp, user_id=user_id)
        except Exception:
            pass

    return {
        "parsed":     parsed,
        "imported":   imported,
        "duplicates": duplicates,
        "skipped":    len(errors),
        "errors":     errors[:5],
        "fmt":        fmt,
    }


def get_import_history(user_id: str = "default") -> list[dict]:
    ensure_schema()
    conn = _db_conn()
    rows = conn.execute(
        "SELECT * FROM import_log WHERE user_id=? ORDER BY ts DESC LIMIT 10",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


ensure_schema()
