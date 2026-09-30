"""WP9 — FRED (официальная макроэкономика).

Требует FRED_API_KEY в .env (бесплатный: fred.stlouisfed.org/docs/api/).
Без ключа — возвращает пустые данные с предупреждением.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

log = logging.getLogger("fred")

_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Ключевые ряды
KEY_SERIES = {
    "CPIAUCSL":  "CPI (All Urban)",
    "UNRATE":    "Unemployment Rate",
    "DFF":       "Fed Funds Rate",
    "T10Y2Y":    "10y-2y Spread",
    "T10YIE":    "10y Breakeven Inflation",
    "DCOILWTICO": "WTI Oil Price",
    "DTWEXBGS":  "Trade-Weighted USD",
}


def _api_key() -> str | None:
    return os.getenv("FRED_API_KEY")


def series(code: str, n: int = 12) -> list[dict]:
    """Вернуть последние n наблюдений для FRED-ряда.

    Returns: [{"date": "YYYY-MM-DD", "value": float}, ...]
    """
    key = _api_key()
    if not key:
        log.warning("FRED_API_KEY не задан — данные FRED недоступны")
        return []

    try:
        resp = httpx.get(
            _BASE,
            params={"series_id": code, "api_key": key, "file_type": "json",
                    "sort_order": "desc", "limit": n},
            timeout=10,
        )
        resp.raise_for_status()
        obs = resp.json().get("observations", [])
        result = []
        for o in obs:
            try:
                result.append({"date": o["date"], "value": float(o["value"])})
            except (ValueError, KeyError):
                pass
        return list(reversed(result))
    except Exception as e:
        log.error("FRED %s: %s", code, e)
        return []


# Ряды, у которых пересмотров больше лимита FRED (2000 винтажей): дату
# публикации приходится оценивать. Все они ежедневные, задержка ~1 день.
DAILY_PUBLISH_LAG_DAYS = {"T10Y2Y": 1, "T10YIE": 1, "DFF": 1, "DCOILWTICO": 4}


def _vintage_count(text: str) -> int:
    m = re.search(r"There are (\d+) vintage dates", text or "")
    return int(m.group(1)) if m else -1


def series_full(code: str) -> list[dict]:
    """Весь ряд с ДАТАМИ ПУБЛИКАЦИИ, а не только последние n наблюдений.

    🔴 Зачем отдельно от series(): та просит limit=12, отчего в factor_values
    лежало по 11 точек на показатель — фундаментальные факторы физически не
    могли участвовать ни в бэктесте, ни в базовых ставках.

    Главное здесь — `realtime_start`. FRED публикует статистику СИЛЬНО позже
    периода, который она описывает: CPI за 2026-07-01 стал известен только
    2026-08-12, задержка 42 дня. Брать значение по дате наблюдения — прямой
    lookahead, причём крупный: месяц с лишним знания будущего.

    Returns: [{"date": период, "published": дата публикации, "value": float}]
    Первая вертикаль (не пересмотры): realtime_start самой ранней версии.
    Для рядов старше 1994 г. FRED отдаёт realtime_start=1994-02-17 — тогда он
    начал вести реальное время; на нашей истории (бары с 2018) это не мешает.
    """
    key = _api_key()
    if not key:
        log.warning("FRED_API_KEY не задан — данные FRED недоступны")
        return []
    def _get(params):
        # httpx пишет полный URL в лог на уровне INFO — вместе с api_key.
        # Ключ не должен попадать ни в journald, ни в файлы логов.
        hx = logging.getLogger("httpx")
        prev = hx.level
        hx.setLevel(logging.WARNING)
        try:
            return httpx.get(_BASE, params={**params, "api_key": key,
                                            "file_type": "json"}, timeout=60)
        finally:
            hx.setLevel(prev)

    base = {"series_id": code, "sort_order": "asc"}
    fallback_lag = None
    try:
        resp = _get({**base, "realtime_start": "1776-07-04", "realtime_end": "9999-12-31"})
        if resp.status_code == 400 and "vintage dates" in resp.text:
            # У ежедневных рядов (T10Y2Y, T10YIE) пересмотров больше, чем
            # лимит FRED в 2000 винтажей. Тогда берём ряд без реального
            # времени, а дату публикации оцениваем типичной задержкой.
            # Это ХУЖЕ точного realtime_start и помечено как оценка —
            # но для рядов с задержкой в 1 день ошибка мала, а альтернатива
            # (выкинуть ряд совсем) хуже.
            fallback_lag = DAILY_PUBLISH_LAG_DAYS.get(code, 1)
            log.warning("%s: %d винтажей > лимита FRED, дата публикации "
                        "оценивается как date+%d дн", code,
                        _vintage_count(resp.text), fallback_lag)
            resp = _get(base)
        resp.raise_for_status()
    except Exception as e:
        log.error("FRED %s (full): %s", code, e)
        return []

    # Одна дата наблюдения может встречаться несколько раз — это ПЕРЕСМОТРЫ.
    # Берём первую опубликованную версию: именно её видел бы наблюдатель в
    # тот момент. Пересмотренное значение — знание будущего.
    first: dict[str, dict] = {}
    for o in resp.json().get("observations", []):
        try:
            date, value = o["date"], float(o["value"])
        except (ValueError, KeyError):
            continue                       # "." — нет данных за период
        published = o.get("realtime_start")
        if fallback_lag is not None:
            published = (datetime.strptime(date, "%Y-%m-%d")
                         + timedelta(days=fallback_lag)).strftime("%Y-%m-%d")
        if not published:
            continue
        if date not in first or published < first[date]["published"]:
            first[date] = {"date": date, "published": published, "value": value,
                           "published_estimated": fallback_lag is not None}
    return [first[d] for d in sorted(first)]


def macro_snapshot() -> dict:
    """Последние значения ключевых рядов."""
    out = {}
    for code, label in KEY_SERIES.items():
        data = series(code, n=2)
        if data:
            latest = data[-1]
            prev = data[-2] if len(data) >= 2 else None
            delta = None
            if prev:
                try:
                    delta = round(latest["value"] - prev["value"], 3)
                except Exception:
                    pass
            out[code] = {
                "label": label,
                "value": latest["value"],
                "date": latest["date"],
                "delta": delta,
            }
    out["_updated"] = datetime.now(timezone.utc).isoformat()
    return out
