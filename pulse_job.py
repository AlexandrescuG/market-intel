#!/usr/bin/env python3
"""
pulse_job.py — SBF_Charts_Layer1_Spec, Фаза 4 («Пульс Рынка»).

Офлайн-джоб (раз в 15 мин, см. sbf-pulse.timer): единый скоринг обсуждаемости
для трёх вкладок (Крипта/Акции/Индексы) поверх уже собранных данных —
ApeWisdom нигде не подключён (проверено в Фазе 1), поэтому источник —
signals.cashtags (twitter+stocktwits+rss) + news_instrument_tags (Фаза 3,
только для индексов — своя RSS-подсчётная колонка, как и просит спека).

pulse(symbol) = mentions_1h / max(avg_mentions_1h_7d, 0.5)

Использование:
  python3 pulse_job.py [--verbose]
"""
import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core.config import DB_PATH

# Классификация тикеров по вкладкам. ApeWisdom не подключён (см. память
# project_sbf_charts_layer1) — картировано вручную: crypto-аллоулист +
# index-аллоулист (индексы и ETF-трекеры индексов), всё остальное — Акции
# по умолчанию (ловит любой реальный cashtag типа AAPL/NVDA без исчерпывающего
# списка акций).
CRYPTO_TICKERS = {
    "BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "BNB", "LTC", "LINK", "MATIC",
    "POL", "AVAX", "DOT", "SHIB", "TRX", "UNI", "ATOM", "NEAR", "ARB", "OP",
    "APT", "SUI", "PEPE", "WIF", "BONK", "TON", "ICP", "FIL", "ETC", "XLM",
    "HBAR", "VET", "ALGO", "AAVE", "MKR", "INJ", "RUNE", "SEI", "TIA", "PYTH", "JUP",
}
INDEX_TICKERS = {
    "SPX", "US500", "NDX", "NASDAQ", "QQQ", "DJI", "DOW", "US30", "VIX",
    "DAX", "FTSE", "NIKKEI", "RUT", "IWM", "DIA", "SPY", "DXY",
}
# news_instrument_tags (Фаза 3) использует символы chart.html — только
# индексные символы релевантны вкладке "Индексы" (FX/commodity-символы Фазы 3
# сюда не попадают, .get() просто вернёт None и они будут пропущены).
_NEWS_TAG_TO_TICKER = {"SPX": "SPX", "NASDAQ": "NASDAQ", "DJI": "DJI", "VIX": "VIX", "DXY": "DXY"}

MIN_BASELINE = 0.5
BURST_LOOKBACK_HOURS = 1
BASELINE_DAYS = 7
HISTORY_KEEP_DAYS = 2  # для 24ч спарклайна с запасом


def _classify(ticker: str) -> str:
    if ticker in CRYPTO_TICKERS:
        return "crypto"
    if ticker in INDEX_TICKERS:
        return "indices"
    return "stocks"


def _cashtag_counts(con, since_iso: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in con.execute("SELECT cashtags FROM signals WHERE last_seen >= ?", (since_iso,)):
        for t in json.loads(row[0] or "[]"):
            counts[t] = counts.get(t, 0) + 1
    return counts


def _news_tag_counts(con, since_ts: float) -> dict[str, int]:
    """Только для индексов — доп. счётчик из RSS-тегов Фазы 3 (news_instrument_tags)."""
    counts: dict[str, int] = {}
    try:
        rows = con.execute(
            "SELECT t.symbol, s.raw, s.first_seen FROM news_instrument_tags t "
            "JOIN signals s ON s.uid = t.news_uid"
        ).fetchall()
    except sqlite3.OperationalError:
        return counts  # таблица Фазы 3 ещё не создана
    for symbol, raw, first_seen in rows:
        ticker = _NEWS_TAG_TO_TICKER.get(symbol)
        if not ticker:
            continue
        try:
            ts = float(json.loads(raw or "{}").get("published") or 0)
        except (ValueError, TypeError):
            ts = 0
        if not ts:
            try:
                ts = datetime.fromisoformat(first_seen).timestamp()
            except (ValueError, TypeError):
                continue
        if ts >= since_ts:
            counts[ticker] = counts.get(ticker, 0) + 1
    return counts


def run(verbose: bool = False) -> int:
    con = sqlite3.connect(str(DB_PATH), timeout=10)
    con.execute("PRAGMA busy_timeout=10000")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS pulse_scores(
            symbol TEXT NOT NULL, category TEXT NOT NULL, ts INT NOT NULL,
            mentions INT, baseline REAL, score REAL,
            PRIMARY KEY(symbol, category, ts)
        );
    """)
    con.commit()

    now = time.time()
    now_iso = datetime.fromtimestamp(now, timezone.utc).isoformat()
    h1_iso = datetime.fromtimestamp(now - BURST_LOOKBACK_HOURS * 3600, timezone.utc).isoformat()
    d7_iso = datetime.fromtimestamp(now - BASELINE_DAYS * 86400, timezone.utc).isoformat()

    mentions_1h = _cashtag_counts(con, h1_iso)
    mentions_7d = _cashtag_counts(con, d7_iso)
    news_1h = _news_tag_counts(con, now - BURST_LOOKBACK_HOURS * 3600)
    news_7d = _news_tag_counts(con, now - BASELINE_DAYS * 86400)

    all_tickers = set(mentions_7d) | set(news_7d)
    written = 0
    for ticker in all_tickers:
        category = _classify(ticker)
        m1h = mentions_1h.get(ticker, 0) + news_1h.get(ticker, 0)
        m7d = mentions_7d.get(ticker, 0) + news_7d.get(ticker, 0)
        baseline = max(m7d / (BASELINE_DAYS * 24), MIN_BASELINE)
        score = m1h / baseline
        con.execute(
            "INSERT OR REPLACE INTO pulse_scores(symbol, category, ts, mentions, baseline, score) VALUES(?,?,?,?,?,?)",
            (ticker, category, int(now), m1h, baseline, score),
        )
        written += 1
        if verbose and score >= 1.5:
            print(f"  {category}/{ticker}: mentions={m1h} baseline={baseline:.2f} score={score:.2f}")

    # чистка старой истории — не нужна глубже 24ч+запас для спарклайна
    cutoff = int(now - HISTORY_KEEP_DAYS * 86400)
    con.execute("DELETE FROM pulse_scores WHERE ts < ?", (cutoff,))
    con.commit()
    con.close()
    if verbose:
        print(f"готово: {written} (symbol,category) пар записано")
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    run(verbose=args.verbose)
