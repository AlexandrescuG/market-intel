#!/usr/bin/env python3
"""
sentiment_job.py — SBF_Charts_Layer3_Spec, Фаза 3 (сентимент толпы vs цена).

Источники: НИ ОДИН из трёх заявленных в спеке (StockTwits bull/bear-метки,
Reddit, Telegram-алерты) сейчас реально не работает — проверено перед
реализацией (см. память/vault): StockTwits закрыт Cloudflare-челленджем
(HTTP 403 на каждый запрос), Reddit отключён ещё раньше («заблокировали
скрапинг», core/config.py), Telegram как источник ДАННЫХ не существовал
вовсе (core/telegram.py — только исходящие уведомления). По согласованию с
пользователем источники: `twitter` (уже собирается) + `telegram` (новый
sbfeconomics_pull.py — канал "SBF Экономика, Геополитика, Деньги", реальный
дополнительный поток, отдельно одобрен пользователем).

Разметка bull/bear — core/sentiment_lexicon.py (словарь RU+EN, без ML, как
требует спека). Символ определяется тем же regex-словарём, что
news_burst_job.py (_SYMBOL_PATTERNS) — НЕ по cashtags: там коллизия
$GOLD=Barrick Gold Corp (см. day_thermo_job.py Фазы 1), тот же риск был бы и
здесь для GOLD.

Джоб (раз в час; --backfill-hours позволяет один раз проставить историю по
уже накопленным в signals сообщениям — данные уже лежат в БД с подлинными
метками времени, ждать реального времени не нужно): для каждого символа из
STARTER_SYMBOLS считает по часам bull/bear/total, публикует час только если
у символа за 24ч, оканчивающиеся в конце этого часа, накопилось
>= MIN_DAILY_LABELLED размеченных упоминаний (дневной гейт спеки) И у самого
часа total >= MIN_HOUR_TOTAL (часовой гейт спеки — иначе разрыв линии).

Использование:
  python3 sentiment_job.py [--backfill-hours 168] [--verbose]
"""
import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core.config import DB_PATH as _SIGNALS_DB  # noqa: E402
from core.sentiment_lexicon import classify_text  # noqa: E402
from news_burst_job import _SYMBOL_PATTERNS  # noqa: E402

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

# "US500" из текста спеки — это chart-символ SPX в этом проекте (см.
# web/data/ohlc_SPX_D1.json) — маппинг задокументирован явно, не угадан молча.
STARTER_SYMBOLS = ["BTC", "ETH", "GOLD", "SPX", "EURUSD"]

MIN_DAILY_LABELLED = 10   # спека: "≥10 размеченных упоминаний/сутки"
MIN_HOUR_TOTAL = 5        # спека: "часы с total < 5 не публикуются"


def _msg_ts(source: str, raw_json: str, first_seen: str) -> float:
    """Истинная метка времени сообщения. Twitter не пишет raw.published (см.
    collectors/twitter.py) — first_seen там достаточно точен (коллектор
    гоняется каждые ~15-20 мин, first_seen ставится при первом же скрейпе
    свежего твита). Telegram (sbfeconomics_pull.py) пишет raw.published —
    подлинную дату Telegram-сообщения; last_seen/first_seen там всегда
    "момент бэкафилла" (все ~1200 сообщений получили last_seen ОДНИМ днём при
    первом прогоне), использовать для бакетинга по часам нельзя."""
    if source == "telegram":
        try:
            pub = json.loads(raw_json or "{}").get("published")
            if pub:
                return float(pub)
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
    try:
        return datetime.fromisoformat(first_seen).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _load_labelled(con_signals):
    """[(symbol, ts, label)] по ВСЕМ twitter+telegram сигналам. Без SQL-фильтра
    по last_seen — для telegram он не отражает истинную дату сообщения (см.
    _msg_ts), поэтому любая SQL-фильтрация по last_seen была бы неверна для
    бэкафилла; датасет небольшой (twitter+telegram — десятки тысяч строк),
    фильтрация по времени делается в Python на истинных метках."""
    rows = con_signals.execute(
        "SELECT source, title, text, raw, first_seen FROM signals WHERE source IN ('twitter','telegram')"
    ).fetchall()
    out = []
    for source, title, text, raw_json, first_seen in rows:
        ts = _msg_ts(source, raw_json, first_seen)
        if not ts:
            continue
        blob = f"{title or ''}\n{text or ''}"
        for symbol in STARTER_SYMBOLS:
            if _SYMBOL_PATTERNS[symbol].search(blob):
                label = classify_text(blob)
                if label:
                    out.append((symbol, ts, label))
    return out


def run(backfill_hours: int = 1, verbose: bool = False) -> int:
    con_bot = sqlite3.connect(str(_BOT_DB))
    con_bot.executescript("""
        CREATE TABLE IF NOT EXISTS sentiment_hourly(
          symbol TEXT, ts_hour INT, bull INT, bear INT, total INT, score REAL,
          PRIMARY KEY(symbol, ts_hour));
    """)
    con_bot.commit()
    con_signals = sqlite3.connect(str(_SIGNALS_DB))

    all_labelled = _load_labelled(con_signals)
    con_signals.close()
    if verbose:
        print(f"загружено {len(all_labelled)} размеченных (symbol,ts,label) упоминаний")

    by_symbol = {}
    for s, ts, label in all_labelled:
        by_symbol.setdefault(s, []).append((ts, label))

    now_hour = int(time.time()) // 3600 * 3600
    written = 0
    for i in range(backfill_hours, 0, -1):
        hour_start = now_hour - i * 3600
        hour_end = hour_start + 3600
        day_start = hour_end - 86400
        for symbol in STARTER_SYMBOLS:
            items = by_symbol.get(symbol, [])
            daily = [(ts, lb) for ts, lb in items if day_start <= ts < hour_end]
            if len(daily) < MIN_DAILY_LABELLED:
                continue
            bull = sum(1 for ts, lb in daily if hour_start <= ts < hour_end and lb == "bull")
            bear = sum(1 for ts, lb in daily if hour_start <= ts < hour_end and lb == "bear")
            total = bull + bear
            if total < MIN_HOUR_TOTAL:
                continue
            score = round((bull - bear) / total, 4)
            con_bot.execute(
                "INSERT OR REPLACE INTO sentiment_hourly(symbol,ts_hour,bull,bear,total,score) VALUES(?,?,?,?,?,?)",
                (symbol, hour_start, bull, bear, total, score),
            )
            written += 1
            if verbose:
                dt = datetime.fromtimestamp(hour_start, timezone.utc).isoformat()
                print(f"  {symbol} @{dt}: bull={bull} bear={bear} total={total} score={score}")
        con_bot.commit()

    con_bot.close()
    if verbose:
        print(f"готово: {written} часов записано")
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill-hours", type=int, default=1,
                     help="сколько последних часов (пере)считать; 168 = 7 дней")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    run(backfill_hours=args.backfill_hours, verbose=args.verbose)
