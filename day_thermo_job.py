#!/usr/bin/env python3
"""
day_thermo_job.py — SBF_Charts_Layer3_Spec, Фаза 1 («Термометр дня»).

Офлайн-джоб (раз в 5 мин, см. sbf-day-thermo.timer — та же частота, что и
sbf-publish.timer, который обновляет ohlc_{symbol}_D1.json): для каждого
инструмента с D1-данными пишет снапшот 4 метрик (перцентиль диапазона дня,
новостной фон, ближайшее событие календаря, DVOL для крипты / зона внимания
Layer2 для остальных). Полный пересчёт с нуля каждый прогон (DELETE+INSERT),
как остальные джобы Layer1/2.

Использование:
  python3 day_thermo_job.py [--verbose]
"""
import argparse
import glob
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parent))
from core.config import DB_PATH as _SIGNALS_DB  # noqa: E402

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")
_WEB_DATA = Path(__file__).parent / "web" / "data"

RANGE_WINDOW = 60           # дневных диапазонов для перцентиля волатильности
DVOL_WINDOW_DAYS = 90
DVOL_CURRENCIES = {"BTC", "ETH"}     # SOL: у Deribit нет DVOL-индекса для SOL
CRYPTO_SYMBOLS = {"BTC", "ETH", "SOL"}

# symbol -> категория в pulse_scores (Фаза 4 Layer1), ТОЛЬКО где символ график
# и cashtag-категория совпадают по смыслу. "GOLD" сознательно НЕ включён —
# в pulse_scores 'GOLD'/'stocks' это акция Barrick Gold Corp (коллизия тикеров
# с товаром XAU/USD этого графика), а не новости о золоте. Использовать было
# бы прямой смысловой ошибкой в метрике.
_PULSE_CATEGORY = {
    "BTC": "crypto", "ETH": "crypto", "SOL": "crypto",
    "SPX": "indices", "NASDAQ": "indices", "DJI": "indices",
}

# Fallback-источник новостного фона для символов без валидной pulse_scores
# записи (FX/commodities) — та же regex-разметка новостей, что news_burst_job
# использует для всплесков, но здесь считаем непрерывный ratio (не только в
# момент всплеска: news_bursts пишет строки лишь когда всплеск уже случился).
_NEWS_TAG_BASELINE_WINDOW = 7 * 86400
_NEWS_TAG_SYMBOLS = {
    "GOLD", "SILVER", "WTI", "NG", "EURUSD", "GBPUSD", "USDJPY",
}


def _candles_from_cache(symbol: str):
    """Дневки из data/candle_cache.db, если файла-проекции нет.

    🔴 Термометр считался только по тем инструментам, у которых на диске лежит
    ohlc_{symbol}_D1.json, — а такие файлы публикуются только для реестра. На
    витрине 780 инструментов, снапшотов было 27: на остальных панель под
    графиком («диапазон дня», «новостной фон», «ближайшее событие») просто не
    появлялась. Кэш свечей знает 788 символов — берём оттуда.
    """
    import sqlite3 as _sq
    db = str(Path(__file__).resolve().parent / "data" / "candle_cache.db")
    try:
        con = _sq.connect(f"file:{db}?mode=ro", uri=True, timeout=20)
        con.execute("PRAGMA busy_timeout=20000")
        try:
            row = con.execute(
                "SELECT payload FROM candles WHERE symbol=? AND tf='D1'", (symbol,)).fetchone()
        finally:
            con.close()
    except Exception:
        return None
    if not row:
        return None
    try:
        raw = json.loads(row[0])
    except Exception:
        return None
    out = []
    for c in raw:
        try:
            out.append({"ts": int(c["time"]), "h": float(c["high"]), "l": float(c["low"])})
        except (KeyError, TypeError, ValueError):
            continue
    if not out:
        return None
    out.sort(key=lambda b: b["ts"])
    try:
        last_price = float(raw[-1]["close"])
    except (KeyError, IndexError, TypeError, ValueError):
        last_price = None
    return {"candles": out, "last": last_price}


def _all_thermo_symbols() -> list:
    """Реестр (файлы-проекции) плюс всё, по чему есть дневки в кэше свечей."""
    import sqlite3 as _sq
    reg = sorted({Path(f).stem.replace("ohlc_", "").replace("_D1", "")
                  for f in glob.glob(str(_WEB_DATA / "ohlc_*_D1.json"))})
    db = str(Path(__file__).resolve().parent / "data" / "candle_cache.db")
    try:
        con = _sq.connect(f"file:{db}?mode=ro", uri=True, timeout=20)
        con.execute("PRAGMA busy_timeout=20000")
        try:
            cached = sorted({s for (s,) in con.execute(
                "SELECT DISTINCT symbol FROM candles WHERE tf='D1'")})
        finally:
            con.close()
    except Exception:
        # Кэш недоступен — считаем по реестру, как считали раньше. Пустой
        # список стёр бы термометр у всех.
        return reg
    seen = set(reg)
    return reg + [s for s in cached if s not in seen]


def _load_d1(symbol: str):
    f = _WEB_DATA / f"ohlc_{symbol}_D1.json"
    if not f.exists():
        return _candles_from_cache(symbol)
    try:
        data = json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    out = []
    for c in data.get("candles") or []:
        t = c.get("time")
        try:
            ts = int(datetime.strptime(t, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()) \
                if isinstance(t, str) else int(t)
            out.append({"ts": ts, "h": float(c["high"]), "l": float(c["low"])})
        except (ValueError, TypeError, KeyError):
            continue
    out.sort(key=lambda b: b["ts"])
    last_price = data.get("last")
    try:
        last_price = float(last_price) if last_price is not None else None
    except (ValueError, TypeError):
        last_price = None
    return {"candles": out, "last": last_price}


def _range_percentile(candles, window=RANGE_WINDOW):
    """Перцентиль диапазона (high-low) последней свечи против последних
    `window` дневных диапазонов (включая саму последнюю). Определение простое
    и вручную проверяемое: доля диапазонов окна <= сегодняшнего, в процентах."""
    if len(candles) < 2:
        return None
    win = candles[-window:]
    ranges = [c["h"] - c["l"] for c in win]
    today = ranges[-1]
    pctl = 100.0 * sum(1 for r in ranges if r <= today) / len(ranges)
    return round(pctl, 1)


def _range_series(candles, window=RANGE_WINDOW):
    """[(ts, range)] последних `window` дневных диапазонов — для мини-гистограммы
    на тапе по чипу «волатильность» (/api/chart/thermo-hist)."""
    win = candles[-window:]
    return [(c["ts"], round(c["h"] - c["l"], 6)) for c in win]


def _news_ratio_pulse(con_signals, symbol: str):
    cat = _PULSE_CATEGORY.get(symbol)
    if not cat:
        return None
    row = con_signals.execute(
        "SELECT score FROM pulse_scores WHERE symbol=? AND category=? ORDER BY ts DESC LIMIT 1",
        (symbol, cat),
    ).fetchone()
    return round(row[0], 2) if row and row[0] is not None else None


def _news_ratio_tags(con_signals, symbol: str, now: float):
    """Тот же count_1h/avg_baseline, что news_burst_job.detect_bursts() считает
    только в момент всплеска — здесь нужен ratio непрерывно, поэтому считаем
    напрямую по news_instrument_tags, не читая news_bursts (пустая большую
    часть времени)."""
    rows = con_signals.execute(
        """SELECT s.raw, s.first_seen FROM news_instrument_tags t
           JOIN signals s ON s.uid = t.news_uid
           WHERE t.symbol = ? AND s.last_seen >= ?""",
        (symbol, datetime.fromtimestamp(now - _NEWS_TAG_BASELINE_WINDOW, timezone.utc).isoformat()),
    ).fetchall()
    ts_list = []
    for raw, first_seen in rows:
        try:
            pub = json.loads(raw or "{}").get("published")
            ts_list.append(float(pub) if pub else datetime.fromisoformat(first_seen).timestamp())
        except (ValueError, TypeError, json.JSONDecodeError):
            ts_list.append(now)
    count_1h = sum(1 for t in ts_list if now - 3600 <= t <= now)
    count_7d = sum(1 for t in ts_list if now - _NEWS_TAG_BASELINE_WINDOW <= t <= now)
    baseline = count_7d / (_NEWS_TAG_BASELINE_WINDOW / 3600)
    if baseline <= 0:
        return None
    return round(count_1h / baseline, 2)


def _news_ratio(con_signals, symbol: str, now: float):
    r = _news_ratio_pulse(con_signals, symbol)
    if r is not None:
        return r
    if symbol in _NEWS_TAG_SYMBOLS:
        return _news_ratio_tags(con_signals, symbol, now)
    return None


def _nearest_event(con_bot, symbol: str, now: int):
    """Ближайшее будущее событие weight=2 (строго — намеренно уже, чем
    weight>=1 у /api/chart/events, см. спеку: "с weight=2 для символа"),
    importance medium+. Большинство некрипто/не-FX-мажоров (GOLD, WTI, индексы,
    BTC/ETH/SOL) сейчас не имеют weight=2 записей в event_instrument_map вовсе
    (см. Layer1 Фаза2/Layer2 память) — для них метрика почти всегда покажет
    «календарь спокоен», это ожидаемо честное поведение при текущем покрытии
    маппинга, а не баг этого джоба."""
    row = con_bot.execute(
        """SELECT e.id, e.scheduled_ts FROM econ_events e
           JOIN event_instrument_map m ON m.country = e.country
           WHERE m.symbol = ? AND m.weight = 2
             AND e.impact IN ('medium','high')
             AND e.scheduled_ts > ?
           ORDER BY e.scheduled_ts ASC LIMIT 1""",
        (symbol, now),
    ).fetchone()
    return (row[0], row[1]) if row else (None, None)


def _nearest_zone(con_bot, symbol: str, last_price):
    if last_price is None:
        return None, None, None
    rows = con_bot.execute(
        "SELECT price_low, price_high FROM confluence_zones WHERE symbol=?", (symbol,)
    ).fetchall()
    best = None
    for lo, hi in rows:
        dist = 0.0 if lo <= last_price <= hi else min(abs(last_price - lo), abs(last_price - hi))
        if best is None or dist < best[2]:
            best = (lo, hi, dist)
    return best if best else (None, None, None)


_dvol_series_cache: dict[str, list | None] = {}


def _dvol_series(currency: str, verbose=False):
    """90-дневная дневная серия DVOL (Deribit, публичный API без ключа), как
    [(ts, close), ...]. Только BTC/ETH — у Deribit нет DVOL-индекса для SOL
    (проверено эмпирически: get_volatility_index_data для SOL возвращает
    пустой data[]). Вынесено отдельно от _dvol_percentile, т.к. живой хендлер
    /api/chart/thermo-hist (тап по чипу DVOL) отдаёт всю серию для мини-гистограммы,
    а не только перцентиль."""
    if currency in _dvol_series_cache:
        return _dvol_series_cache[currency]
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - DVOL_WINDOW_DAYS * 86400 * 1000
    url = (
        "https://www.deribit.com/api/v2/public/get_volatility_index_data"
        f"?currency={currency}&start_timestamp={start_ms}&end_timestamp={now_ms}&resolution=86400"
    )
    try:
        with urlopen(Request(url, headers={"User-Agent": "sbf-market-intel/1.0"}), timeout=15) as r:
            payload = json.loads(r.read().decode("utf-8"))
        rows = payload.get("result", {}).get("data") or []
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as e:
        if verbose:
            print(f"  DVOL {currency}: fetch error {e}")
        _dvol_series_cache[currency] = None
        return None
    if len(rows) < 5:
        _dvol_series_cache[currency] = None
        return None
    series = [(int(row[0] // 1000), row[4]) for row in rows]  # [ts, open, high, low, close]
    _dvol_series_cache[currency] = series
    return series


def _dvol_percentile(currency: str, verbose=False):
    series = _dvol_series(currency, verbose)
    if not series:
        return None
    closes = [c for _, c in series]
    today = closes[-1]
    return round(100.0 * sum(1 for c in closes if c <= today) / len(closes), 1)


def compute_symbol(symbol: str, con_bot, con_signals, now: int, verbose=False):
    d1 = _load_d1(symbol)
    if not d1 or not d1["candles"]:
        return None
    range_pctl = _range_percentile(d1["candles"])
    news_ratio = _news_ratio(con_signals, symbol, now)
    next_event_id, next_event_ts = _nearest_event(con_bot, symbol, now)

    dvol_pctl = None
    zone_low = zone_high = dist_points = None
    if symbol in CRYPTO_SYMBOLS and symbol in DVOL_CURRENCIES:
        dvol_pctl = _dvol_percentile(symbol, verbose)
    if dvol_pctl is None:
        # некрипто, либо крипто без DVOL-покрытия (SOL) — зона внимания Layer2
        zone_low, zone_high, dist_points = _nearest_zone(con_bot, symbol, d1["last"])

    if verbose:
        print(f"  {symbol}: range_pctl={range_pctl} news_ratio={news_ratio} "
              f"next_event_ts={next_event_ts} dvol_pctl={dvol_pctl} "
              f"zone=({zone_low},{zone_high}) dist={dist_points}")

    return {
        "symbol": symbol, "ts": now, "range_pctl": range_pctl, "news_ratio": news_ratio,
        "next_event_id": next_event_id, "next_event_ts": next_event_ts,
        "dvol_pctl": dvol_pctl, "nearest_zone_low": zone_low, "nearest_zone_high": zone_high,
        "dist_points": round(dist_points, 4) if dist_points is not None else None,
    }


def run(verbose: bool = False) -> int:
    con_bot = sqlite3.connect(str(_BOT_DB), timeout=10)
    con_bot.execute("PRAGMA journal_mode=WAL")
    con_bot.execute("PRAGMA busy_timeout=10000")
    con_bot.executescript("""
        CREATE TABLE IF NOT EXISTS day_thermo(
          symbol TEXT PRIMARY KEY, ts INT,
          range_pctl REAL, news_ratio REAL,
          next_event_id TEXT, next_event_ts INT,
          dvol_pctl REAL,
          nearest_zone_low REAL, nearest_zone_high REAL, dist_points REAL);
    """)
    con_bot.commit()
    con_signals = sqlite3.connect(str(_SIGNALS_DB))

    now = int(time.time())
    symbols = _all_thermo_symbols()

    written = 0
    for symbol in symbols:
        snap = compute_symbol(symbol, con_bot, con_signals, now, verbose)
        if not snap:
            continue
        con_bot.execute(
            """INSERT OR REPLACE INTO day_thermo
               (symbol, ts, range_pctl, news_ratio, next_event_id, next_event_ts,
                dvol_pctl, nearest_zone_low, nearest_zone_high, dist_points)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (snap["symbol"], snap["ts"], snap["range_pctl"], snap["news_ratio"],
             snap["next_event_id"], snap["next_event_ts"], snap["dvol_pctl"],
             snap["nearest_zone_low"], snap["nearest_zone_high"], snap["dist_points"]),
        )
        written += 1

    con_bot.commit()
    con_bot.close()
    con_signals.close()
    if verbose:
        print(f"готово: {written} снапшотов по {len(symbols)} символам")
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    run(verbose=args.verbose)
