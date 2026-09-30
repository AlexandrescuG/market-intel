"""core/candle_cache.py — свечи на диске, чтобы не ходить в мост MT5 на каждый показ.

ЗАЧЕМ. Из 842 инструментов каталога статические ohlc_*.json есть только у 31.
Остальные 811 при каждом открытии графика шли синхронным вызовом в терминал MT5
прямо во время HTTP-запроса. Замер 31.08.2026:

  • щадящий темп (1 запрос / 2 с) — 18 из 20 отдают свечи, но холодный
    инструмент отвечает 1.5-3.4 с;
  • 60 запросов подряд — 3 из 60. Мост перестаёт отвечать целиком, и в это
    окно не работают даже золото и евродоллар. Через пару минут само проходит.

Тот же отказ уже записан в ops/units.txt как причина выключить спарклайны
(«обход 842 символов ронял сайт через синхронный мост», 25.08).

ЧТО ДЕЛАЕТ. Прослойка между обработчиком и мостом: свечи, однажды взятые у
брокера, ложатся в SQLite и дальше отдаются с диска за миллисекунды. В мост
идём только когда копия устарела.

ДВА РЕШЕНИЯ, КОТОРЫЕ ВАЖНО НЕ ПЕРЕПУТАТЬ:

1. Отдельный файл БД, не bot.db. В bot.db пишет пул сборщиков, и «database is
   locked» там уже ломал метрику риска (см. память проекта). Ставить чтение
   веб-страницы в очередь к тем же блокировкам — заводить новый источник тех же
   отказов. Здесь свой файл и WAL: читатели не блокируют писателя.

2. Устаревшая копия лучше пустого графика, но НЕ выдаётся за свежую. Когда мост
   молчит, отдаём что есть и помечаем stale=True; обработчик считает delay_sec
   от последней свечи, а страница показывает бейдж «данные от …». Пустое белое
   поле без единого слова — то, что пользователь читает как «сайт сломан», хотя
   данные есть.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time

log = logging.getLogger("candle_cache")

_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "candle_cache.db")
_local = threading.local()
_init_lock = threading.Lock()
_initialised = False

# Насколько копия считается свежей. Привязано к таймфрейму: минутный бар живёт
# минуту, часовой — час, и держать часовую свечу 20 секунд смысла нет, а вреда
# (поход в мост) много. Потолок 10 минут — чтобы даже дневной график не отставал
# от рынка заметно для глаза.
_FRESH_SEC = {"M1": 20, "M5": 60, "M15": 150, "M30": 300,
              "H1": 600, "H4": 600, "D1": 600, "W1": 600}
_FRESH_DEFAULT = 300

# Дольше этого копию не отдаём даже как устаревшую: показывать позавчерашний
# ряд под видом графика хуже, чем честно сказать, что данных нет.
_MAX_STALE_SEC = 3 * 86400


def fresh_sec(tf: str) -> int:
    return _FRESH_SEC.get(tf, _FRESH_DEFAULT)


def _conn() -> sqlite3.Connection:
    global _initialised
    c = getattr(_local, "conn", None)
    if c is not None:
        return c
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    c = sqlite3.connect(_DB_PATH, timeout=5)
    # WAL: читатели страницы не встают в очередь за писателем.
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    with _init_lock:
        if not _initialised:
            c.execute("""CREATE TABLE IF NOT EXISTS candles (
                            symbol      TEXT NOT NULL,
                            tf          TEXT NOT NULL,
                            payload     TEXT NOT NULL,
                            updated_ts  INTEGER NOT NULL,
                            last_bar_ts INTEGER NOT NULL,
                            PRIMARY KEY (symbol, tf))""")
            c.commit()
            _initialised = True
    _local.conn = c
    return c


def get(symbol: str, tf: str) -> tuple[list | None, bool]:
    """(свечи, устарела ли). (None, False) — копии нет вовсе.

    Устаревшая копия возвращается сознательно: вызывающий сам решит, сходить ли
    в мост, и сможет отдать её, если мост молчит.
    """
    try:
        row = _conn().execute(
            "SELECT payload, updated_ts FROM candles WHERE symbol=? AND tf=?",
            (symbol, tf)).fetchone()
    except Exception as e:
        log.warning("candle_cache чтение %s %s: %s", symbol, tf, e)
        return None, False
    if not row:
        return None, False
    payload, updated = row
    age = time.time() - updated
    if age > _MAX_STALE_SEC:
        return None, False
    try:
        return json.loads(payload), age > fresh_sec(tf)
    except Exception:
        return None, False


def put(symbol: str, tf: str, candles: list) -> None:
    if not candles:
        return
    try:
        _conn().execute(
            "INSERT INTO candles (symbol, tf, payload, updated_ts, last_bar_ts) "
            "VALUES (?,?,?,?,?) ON CONFLICT(symbol, tf) DO UPDATE SET "
            "payload=excluded.payload, updated_ts=excluded.updated_ts, "
            "last_bar_ts=excluded.last_bar_ts",
            (symbol, tf, json.dumps(candles, separators=(",", ":")),
             int(time.time()), int(candles[-1]["time"])))
        _conn().commit()
    except Exception as e:
        log.warning("candle_cache запись %s %s: %s", symbol, tf, e)


def drop(symbol: str, tf: str) -> None:
    """Убрать копию — например, когда выяснилось, что фид символа мёртв."""
    try:
        _conn().execute("DELETE FROM candles WHERE symbol=? AND tf=?", (symbol, tf))
        _conn().commit()
    except Exception:
        pass


def stats() -> dict:
    try:
        c = _conn()
        total = c.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
        syms = c.execute("SELECT COUNT(DISTINCT symbol) FROM candles").fetchone()[0]
        fresh = c.execute("SELECT COUNT(*) FROM candles WHERE updated_ts > ?",
                          (int(time.time()) - 600,)).fetchone()[0]
        size = os.path.getsize(_DB_PATH) if os.path.exists(_DB_PATH) else 0
        return {"rows": total, "symbols": syms, "fresh_10min": fresh,
                "db_bytes": size}
    except Exception as e:
        return {"error": str(e)}
