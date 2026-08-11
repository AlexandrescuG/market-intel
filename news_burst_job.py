#!/usr/bin/env python3
"""
news_burst_job.py — SBF_Charts_Layer1_Spec, Фаза 3 («Новостные кластеры»).

Офлайн-джоб (раз в 15 мин, см. sbf-news-burst.timer):
1. Тегирует непомеченные RSS-сигналы из signals.db по словарю ключевых слов
   на инструмент (та же символьная система, что event_instrument_map в Фазе 1).
2. Детектирует всплески: count новостей за последний час vs средний count/час
   за 7 дней. Всплеск = count >= max(5, 3*baseline).

Использование:
  python3 news_burst_job.py [--verbose]
"""
import argparse
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core.config import DB_PATH

# Словарь ключевых слов на символ (RU+EN, регистронезависимо). Прогоняется по
# title+text уже econ-relevance-отфильтрованных RSS-сигналов (signals.source=
# 'rss') — поэтому широкие слова вроде "нефть"/"euro" реже дают шум, чем на
# сыром интернет-тексте. Символьное пространство — то же, что в event_instrument_map
# (Фаза 1): GOLD/SILVER/BTC/ETH/SOL/SPX/NASDAQ/DJI/VIX/WTI/NG/EURUSD/GBPUSD/USDJPY/DXY.
_SYMBOL_PATTERNS = {
    "GOLD":   re.compile(r"\bgold\b|золот|\bxau\b", re.I),
    "SILVER": re.compile(r"\bsilver\b|серебр|\bxag\b", re.I),
    "BTC":    re.compile(r"\bbitcoin\b|биткои|биткойн|\bbtc\b", re.I),
    "ETH":    re.compile(r"\bethereum\b|эфириум|\beth\b", re.I),
    "SOL":    re.compile(r"\bsolana\b", re.I),
    "SPX":    re.compile(r"s&p\s*500|\bs&p\b|\bspx\b|standard\s*&\s*poor", re.I),
    "NASDAQ": re.compile(r"\bnasdaq\b|\bnas100\b", re.I),
    "DJI":    re.compile(r"dow\s+jones|\bdow\s*30\b|\bus30\b", re.I),
    "VIX":    re.compile(r"\bvix\b|volatility index|индекс волатильности", re.I),
    "WTI":    re.compile(r"\bwti\b|crude oil|нефт[ьи]", re.I),
    "NG":     re.compile(r"natural gas|природн\w*\s*газ|henry hub", re.I),
    "EURUSD": re.compile(r"eur\s*/\s*usd|\beurusd\b|евро.{0,15}доллар", re.I),
    "GBPUSD": re.compile(r"gbp\s*/\s*usd|\bgbpusd\b|\bcable\b|фунт.{0,15}доллар", re.I),
    "USDJPY": re.compile(r"usd\s*/\s*jpy|\busdjpy\b|доллар.{0,15}йен", re.I),
    "DXY":    re.compile(r"\bdxy\b|dollar index|индекс доллара", re.I),
}

TAG_WINDOW_DAYS = 8      # тегируем немного шире окна всплеска (7д) с запасом
BURST_WINDOW = 3600      # 1 час
BASELINE_WINDOW = 7 * 86400
MIN_COUNT = 5
BASELINE_MULT = 3
OPEN_GRACE = 3600        # "час без превышения — конец всплеска" (см. spec)


def _published_ts(row) -> float:
    try:
        raw = json.loads(row["raw"] or "{}")
        if raw.get("published"):
            return float(raw["published"])
    except (ValueError, TypeError, json.JSONDecodeError):
        pass
    # fallback: first_seen ISO
    try:
        return datetime.fromisoformat(row["first_seen"]).timestamp()
    except (ValueError, TypeError):
        return time.time()


def tag_recent(con, verbose=False) -> int:
    cutoff = time.time() - TAG_WINDOW_DAYS * 86400
    rows = con.execute(
        "SELECT uid, title, text FROM signals WHERE source='rss' AND last_seen >= ?",
        (datetime.fromtimestamp(cutoff, timezone.utc).isoformat(),),
    ).fetchall()
    tagged = 0
    for uid, title, text in rows:
        blob = f"{title}\n{text}"
        for symbol, pat in _SYMBOL_PATTERNS.items():
            if pat.search(blob):
                cur = con.execute(
                    "INSERT OR IGNORE INTO news_instrument_tags(news_uid, symbol) VALUES(?,?)",
                    (uid, symbol),
                )
                if cur.rowcount:
                    tagged += 1
    con.commit()
    if verbose:
        print(f"тегировано новых (uid,symbol) пар: {tagged} (просканировано {len(rows)} новостей)")
    return tagged


def detect_bursts(con, verbose=False) -> int:
    now = time.time()
    symbols = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM news_instrument_tags").fetchall()]
    opened_or_extended = 0

    for symbol in symbols:
        rows = con.execute(
            """SELECT s.raw, s.first_seen FROM news_instrument_tags t
               JOIN signals s ON s.uid = t.news_uid
               WHERE t.symbol = ? AND s.last_seen >= ?""",
            (symbol, datetime.fromtimestamp(now - BASELINE_WINDOW, timezone.utc).isoformat()),
        ).fetchall()
        ts_list = [_published_ts({"raw": r[0], "first_seen": r[1]}) for r in rows]
        count_1h = sum(1 for t in ts_list if now - BURST_WINDOW <= t <= now)
        count_7d = sum(1 for t in ts_list if now - BASELINE_WINDOW <= t <= now)
        avg_baseline = count_7d / (BASELINE_WINDOW / 3600)  # среднее в час

        is_burst = count_1h >= max(MIN_COUNT, BASELINE_MULT * avg_baseline)

        last = con.execute(
            "SELECT start_ts, end_ts, count FROM news_bursts WHERE symbol=? ORDER BY start_ts DESC LIMIT 1",
            (symbol,),
        ).fetchone()

        if is_burst:
            if last and (now - last[1]) <= OPEN_GRACE:
                con.execute(
                    "UPDATE news_bursts SET end_ts=?, count=?, avg_baseline=? WHERE symbol=? AND start_ts=?",
                    (int(now), count_1h, avg_baseline, symbol, last[0]),
                )
            else:
                con.execute(
                    "INSERT INTO news_bursts(symbol, start_ts, end_ts, count, avg_baseline) VALUES(?,?,?,?,?)",
                    (symbol, int(now), int(now), count_1h, avg_baseline),
                )
            opened_or_extended += 1
            if verbose:
                print(f"  {symbol}: всплеск count={count_1h} baseline={avg_baseline:.2f}")

    con.commit()
    return opened_or_extended


def run(verbose: bool = False) -> None:
    con = sqlite3.connect(str(DB_PATH), timeout=10)
    con.execute("PRAGMA busy_timeout=10000")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE IF NOT EXISTS news_instrument_tags(
            news_uid TEXT NOT NULL, symbol TEXT NOT NULL,
            PRIMARY KEY(news_uid, symbol)
        );
        CREATE TABLE IF NOT EXISTS news_bursts(
            symbol TEXT NOT NULL, start_ts INT NOT NULL, end_ts INT NOT NULL,
            count INT, avg_baseline REAL,
            PRIMARY KEY(symbol, start_ts)
        );
    """)
    con.commit()

    tag_recent(con, verbose)
    n = detect_bursts(con, verbose)
    con.close()
    if verbose:
        print(f"готово: {n} символов во всплеске сейчас")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    run(verbose=args.verbose)
