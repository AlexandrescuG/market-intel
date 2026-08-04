"""
journal_csv.py — Парсер MT4/MT5 CSV и HTML экспорта истории.
Возвращает список dict-сделок для add_trade().
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Iterator


def _norm_float(s: str) -> float | None:
    s = str(s).strip().replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _norm_ts(s: str) -> str | None:
    s = str(s).strip()
    fmts = [
        "%Y.%m.%d %H:%M:%S",
        "%Y.%m.%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
    return None


def _row_to_trade(row: dict) -> dict | None:
    """
    Нормализует один dict-ряд CSV к trade-dict.
    Поддерживает разные варианты заголовков MT4/MT5.
    """
    # Алиасы заголовков (lowercase)
    aliases = {
        "symbol":      ["symbol", "instrument", "pair", "ticker"],
        "dir":         ["type", "direction", "side", "order_type", "action"],
        "size":        ["volume", "size", "lots", "quantity", "lot"],
        "open_ts":     ["open_time", "opentime", "open time", "time open", "entry_time", "entrydate"],
        "close_ts":    ["close_time", "closetime", "close time", "time close", "exit_time", "exitdate"],
        "entry_price": ["open_price", "openprice", "open price", "price open", "entry", "entry_price"],
        "exit_price":  ["close_price", "closeprice", "close price", "price close", "exit", "exit_price"],
        "pnl":         ["profit", "pnl", "net_profit", "net profit", "pl", "p/l"],
        "fees":        ["commission", "comm", "fees", "fee", "swap"],
        "stop_loss":   ["s/l", "sl", "stop_loss", "stop loss", "stoploss"],
    }

    # Нормализуем ключи ряда
    row_lc = {k.lower().strip(): v for k, v in row.items()}

    def pick(field: str) -> str | None:
        for alias in aliases[field]:
            if alias in row_lc:
                return str(row_lc[alias]).strip()
        return None

    symbol    = pick("symbol")
    dir_raw   = (pick("dir") or "").lower()
    size_s    = pick("size")
    open_s    = pick("open_ts")
    close_s   = pick("close_ts")
    entry_s   = pick("entry_price")
    exit_s    = pick("exit_price")
    pnl_s     = pick("pnl")
    fees_s    = pick("fees")
    sl_s      = pick("stop_loss")

    if not symbol or not dir_raw or not open_s or not close_s:
        return None

    # Нормализация direction
    direction = None
    if "buy" in dir_raw or dir_raw in ("long", "1", "bl", "b"):
        direction = "buy"
    elif "sell" in dir_raw or dir_raw in ("short", "-1", "sl", "s"):
        direction = "sell"
    if not direction:
        return None

    open_ts  = _norm_ts(open_s)
    close_ts = _norm_ts(close_s)
    if not open_ts or not close_ts:
        return None

    entry = _norm_float(entry_s)
    exit_ = _norm_float(exit_s)
    size  = _norm_float(size_s)
    pnl   = _norm_float(pnl_s)
    if None in (entry, exit_, size, pnl):
        return None

    trade = {
        "symbol":      symbol.upper(),
        "dir":         direction,
        "entry_price": entry,
        "exit_price":  exit_,
        "size":        size,
        "open_ts":     open_ts,
        "close_ts":    close_ts,
        "pnl":         pnl,
        "fees":        abs(_norm_float(fees_s) or 0.0),
        "source":      "file_import",
    }
    sl = _norm_float(sl_s)
    if sl and sl > 0:
        trade["stop_loss"] = sl
    return trade


# ── HTML парсер ──────────────────────────────────────────────────────────────

class _MT5HtmlParser(HTMLParser):
    """Парсит HTML-экспорт MT5 (таблица с историей сделок)."""

    def __init__(self):
        super().__init__()
        self._in_table  = False
        self._in_row    = False
        self._in_cell   = False
        self._headers:  list[str] = []
        self._current:  list[str] = []
        self._rows:     list[list[str]] = []
        self._got_hdr   = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._in_table = True
        elif tag in ("tr",) and self._in_table:
            self._in_row   = True
            self._current  = []
        elif tag in ("td", "th") and self._in_row:
            self._in_cell  = True

    def handle_endtag(self, tag):
        if tag == "table":
            self._in_table = False
        elif tag == "tr":
            if self._in_row:
                if not self._got_hdr:
                    self._headers  = self._current[:]
                    self._got_hdr  = True
                else:
                    if any(c.strip() for c in self._current):
                        self._rows.append(self._current[:])
            self._in_row  = False
            self._current = []
        elif tag in ("td", "th"):
            self._in_cell = False

    def handle_data(self, data):
        if self._in_cell:
            if self._current:
                self._current[-1] += data
            else:
                self._current.append(data)

    def handle_starttag_ex(self, tag, attrs):
        if tag in ("td", "th"):
            self._current.append("")

    def get_dicts(self) -> list[dict]:
        result = []
        for row in self._rows:
            d = {}
            for i, h in enumerate(self._headers):
                d[h] = row[i] if i < len(row) else ""
            result.append(d)
        return result


def parse_html(content: str) -> list[dict]:
    parser = _MT5HtmlParser()
    # Для каждой ячейки нужно добавлять пустую строку при открытии td/th
    # Дописываем немного иначе — через простой split
    trades = []
    # Упрощённый подход: вытаскиваем строки <tr>...</tr> и ячейки <td>...</td>
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", content, re.DOTALL | re.IGNORECASE)
    if not rows:
        return []
    headers_raw = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", rows[0], re.DOTALL | re.IGNORECASE)
    headers = [re.sub(r"<[^>]+>", "", h).strip().lower() for h in headers_raw]
    for row in rows[1:]:
        cells_raw = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL | re.IGNORECASE)
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells_raw]
        if not any(cells):
            continue
        d = dict(zip(headers, cells))
        trade = _row_to_trade(d)
        if trade:
            trades.append(trade)
    return trades


# ── CSV парсер ────────────────────────────────────────────────────────────────

def parse_csv(content: str) -> list[dict]:
    """
    Парсит CSV-строку с любым разделителем (авто-детект: ; или ,).
    """
    # Определяем разделитель
    first_line = content.split("\n")[0]
    delimiter  = ";" if first_line.count(";") > first_line.count(",") else ","

    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    trades = []
    for row in reader:
        trade = _row_to_trade(dict(row))
        if trade:
            trades.append(trade)
    return trades


def parse_auto(content: str) -> list[dict]:
    """Авто-определение формата: HTML или CSV."""
    stripped = content.lstrip()
    if stripped.startswith("<"):
        return parse_html(content)
    return parse_csv(content)
