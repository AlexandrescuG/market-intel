"""Слой состояния рынка и верификации (yfinance + Crypto Fear&Greed).

Зачем: отделить «что сказали инфлюенсеры» от «как реально двинулся рынок».
Кормит бриф фактами: цена, дневное движение, реакция вокруг события.

  snapshot(tickers)          → текущая цена + d/d по списку инструментов
  reaction_around(t, when)   → движение инструмента вокруг момента события
  crypto_fear_greed()        → индекс настроения крипты (0..100)
  enrich_cashtags(tags)      → market-state блок по тикерам из брифа

Замечания по free-tier: yfinance неофициальный, иногда ломается/лимитит —
кэшируем на короткое время. Биржевые тикеры мапятся из кэштегов.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from datetime import datetime, timezone

log = logging.getLogger("market")

# кэштег → тикер yfinance
_CRYPTO = {"BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "BNB", "AVAX", "LINK", "DOT", "MATIC", "LTC"}
_INDEX = {"SPX": "^GSPC", "NDX": "^IXIC", "DJI": "^DJI", "VIX": "^VIX", "RUT": "^RUT"}
_ALIAS = {"DXY": "DX-Y.NYB", "GOLD": "GC=F", "XAU": "GC=F", "OIL": "CL=F",
          "WTI": "CL=F", "BRENT": "BZ=F", "GAS": "NG=F", "SILVER": "SI=F"}

# базовый дашборд — всегда считаем реакцию по этим инструментам
DASHBOARD = [
    "^GSPC", "^IXIC", "^DJI", "^VIX",
    "GC=F", "SI=F", "CL=F", "NG=F",
    "BTC-USD", "ETH-USD", "SOL-USD",
    "EURUSD=X", "GBPUSD=X",
    "DX-Y.NYB",
]

_cache: dict[str, tuple[float, dict]] = {}
_TTL = 600  # сек


def to_ticker(tag: str) -> str:
    t = tag.upper().lstrip("$")
    if t in _INDEX:
        return _INDEX[t]
    if t in _ALIAS:
        return _ALIAS[t]
    if t in _CRYPTO:
        return f"{t}-USD"
    return t  # обычная акция как есть


def snapshot(tickers: list[str]) -> dict[str, dict]:
    """{ticker: {price, change_pct, prev}} по дневным барам. Кэш на _TTL."""
    import yfinance as yf
    out: dict[str, dict] = {}
    fresh = []
    now = time.time()
    for t in tickers:
        c = _cache.get(t)
        if c and now - c[0] < _TTL:
            out[t] = c[1]
        else:
            fresh.append(t)
    for t in fresh:
        try:
            h = yf.Ticker(t).history(period="6d", interval="1d")
            h = h.dropna(subset=["Close"])
            if len(h) >= 2:
                last = float(h["Close"].iloc[-1]); prev = float(h["Close"].iloc[-2])
                # round(x, 2) схлопывал форекс-пары (EURUSD ~1.14) в 2 знака —
                # для них нужен 4-й (пипс), как и на графике (chart.html fmtPrice)
                prec = 4 if abs(last) < 10 else 2
                data = {"price": round(last, prec), "prev": round(prev, prec),
                        "change_pct": round((last / prev - 1) * 100, 2)}
            else:
                data = {"price": None, "prev": None, "change_pct": None}
        except Exception as e:
            log.debug("snapshot %s: %s", t, e)
            data = {"price": None, "prev": None, "change_pct": None, "error": str(e)[:60]}
        _cache[t] = (now, data)
        out[t] = data
    return out


def reaction_around(ticker: str, when: datetime, window_min: int = 120) -> dict | None:
    """Движение инструмента в окне ±window_min вокруг момента события (интрадей).

    Полезно для «как рынок отреагировал на X». Работает для ликвидных тикеров,
    т.к. yfinance даёт интрадей только за последние ~60 дней.
    """
    import yfinance as yf
    try:
        h = yf.Ticker(ticker).history(period="5d", interval="5m")
        if h.empty:
            return None
        h.index = h.index.tz_convert("UTC")
        when = when.astimezone(timezone.utc)
        before = h[h.index <= when]
        after = h[h.index > when]
        if before.empty or after.empty:
            return None
        p0 = float(before["Close"].iloc[-1])
        p1 = float(after["Close"].iloc[min(len(after) - 1, window_min // 5)])
        return {"t0_price": round(p0, 2), "t1_price": round(p1, 2),
                "move_pct": round((p1 / p0 - 1) * 100, 2),
                "window_min": window_min}
    except Exception as e:
        log.debug("reaction %s: %s", ticker, e)
        return None


def crypto_fear_greed() -> dict | None:
    try:
        r = urllib.request.urlopen("https://api.alternative.me/fng/?limit=1", timeout=10)
        d = json.loads(r.read())["data"][0]
        return {"value": int(d["value"]), "label": d["value_classification"]}
    except Exception as e:
        log.debug("fng: %s", e)
        return None


def enrich_cashtags(tags: list[str], limit: int = 12) -> list[dict]:
    """[{tag, ticker, price, change_pct}] — реальное состояние по тикерам из брифа."""
    uniq = list(dict.fromkeys(t.upper() for t in tags))[:limit]
    tickers = {t: to_ticker(t) for t in uniq}
    snap = snapshot(list(set(tickers.values())))
    return [{"tag": t, "ticker": tk, **snap.get(tk, {})} for t, tk in tickers.items()]


def market_state_block(extra_tags: list[str] | None = None) -> str:
    """Готовый markdown-блок для брифа: дашборд + крипто F&G + тикеры из брифа."""
    lines = ["## 📉 РЕАЛЬНОЕ СОСТОЯНИЕ РЫНКА (yfinance, d/d)"]
    snap = snapshot(DASHBOARD)
    names = {"^GSPC": "S&P 500", "^IXIC": "Nasdaq", "DX-Y.NYB": "DXY",
             "GC=F": "Gold", "CL=F": "WTI", "BTC-USD": "BTC", "^VIX": "VIX"}
    for tk in DASHBOARD:
        d = snap.get(tk, {})
        if d.get("price") is not None:
            lines.append(f"  {names[tk]:9} {d['price']:>10,.2f}  {d['change_pct']:+.2f}%")
    fng = crypto_fear_greed()
    if fng:
        lines.append(f"  Crypto F&G: {fng['value']} ({fng['label']})")
    if extra_tags:
        enr = enrich_cashtags(extra_tags)
        rows = [f"  ${e['tag']:6} {e.get('price', '—')}  "
                f"{e.get('change_pct', 0):+.2f}%" for e in enr
                if e.get("price") is not None]
        if rows:
            lines.append("\n  Тикеры из брифа:")
            lines += rows
    lines.append("\n  ⚠️ Цифры из yfinance — приоритет над ценами из соцсетей.")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    from core.logging_setup import setup
    setup("market")
    print(market_state_block(extra_tags=["BTC", "SPY", "NVDA", "OIL", "DXY"]))
