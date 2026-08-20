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

# кэштег → тикер yfinance. Не в реестре вообще (нет price_bars/symbols.json
# записи ни на одну) -- формула, а не таблица данных, оставлена как есть.
_CRYPTO = {"BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "BNB", "AVAX", "LINK", "DOT", "MATIC", "LTC"}

# базовый дашборд — всегда считаем реакцию по этим инструментам.
# СПЕКА_графики_и_починка_календаря.md §2: выведено из symbols.json
# ("quote": true), не захардкожено -- те же 14 тикеров, что были, проверено
# на равенство перед переключением.
# WP1.1 SPEC_alpha_engine_implementation.md: были ещё _INDEX/_ALIAS —
# независимые хардкод-копии части тех же Yahoo-тикеров (SPX/NDX/DJI/VIX/RUT,
# DXY/GOLD/XAU/OIL/WTI/BRENT/GAS/SILVER), убраны в пользу resolve()+
# alias_for() -- по пути починены 2 реальных дыры реестра, из-за которых
# resolve() раньше не мог их заменить: RUT и BRENT не имели поля "yahoo"
# вообще, GAS не был записан как алиас NG нигде.
from core.symbols_registry import quote_dashboard, resolve as _resolve_symbol, alias_for as _alias_for
DASHBOARD = quote_dashboard()

_cache: dict[str, tuple[float, dict]] = {}
_TTL = 600  # сек


def to_ticker(tag: str) -> str:
    t = tag.upper().lstrip("$")
    canonical = _resolve_symbol(t)
    if canonical:
        y = _alias_for(canonical, "yahoo")
        if y:
            return y
    # 🔴 Была здесь без фоллбека в реестр: for FX она возвращала тег как есть
    # ("USDCAD" -> "USDCAD"), а Yahoo ждёт "USDCAD=X". Пока пары были только
    # в _ALIAS выше, это не всплывало -- 12 новых пар (06.08) уже ловили баг.
    if t in _CRYPTO:
        return f"{t}-USD"
    return t  # обычная акция как есть


def snapshot(tickers: list[str]) -> dict[str, dict]:
    """{ticker: {price, change_pct, prev}} по дневным барам. Кэш на _TTL.

    🔴 20.08.2026: инструменты, что есть у брокера, берутся у НЕГО, а не у
    Yahoo. Через эту функцию идут market.json, утренний бриф, режим рынка,
    дивергенции и проверка прогнозов — то есть почти всё, что говорит о
    цене словами. Пока она ходила в yfinance, сайт произносил про золото
    два разных числа: график 4 487 (спот брокера), а всё остальное 4 545
    (фьючерс GC=F). См. core/mt5_quotes.py — там же, почему это нельзя
    было закрыть подменой тикера.

    Отказ моста не роняет функцию и не маскируется: те тикеры, что он не
    дал, честно уходят в ветку Yahoo ниже, о чём пишется предупреждение.
    """
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

    if fresh:
        try:
            from core import mt5_quotes
            broker = mt5_quotes.snapshot(set(fresh))
        except Exception as e:
            broker = {}
            log.warning("snapshot: мост MT5 недоступен (%s) — цены от Yahoo; "
                        "по золоту это фьючерс против спота на графике", e)
        for t, data in broker.items():
            _cache[t] = (now, data)
            out[t] = data
        missed = [t for t in fresh if t not in broker]
        if broker and missed:
            log.debug("snapshot: у брокера нет %s — остаются на Yahoo", missed)
        fresh = missed

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


def _registry_labels() -> dict[str, str]:
    """yahoo-тикер -> человеческое имя из symbols.json (ru)."""
    try:
        from core.symbols_registry import _load
        out = {}
        for _k, v in _load().items():
            y = v.get("yahoo") if isinstance(v, dict) else None
            if y:
                out[y] = v.get("ru") or v.get("en") or _k
        return out
    except Exception:
        return {}


def market_state_block(extra_tags: list[str] | None = None) -> str:
    """Готовый markdown-блок для брифа: дашборд + крипто F&G + тикеры из брифа."""
    lines = ["## 📉 РЕАЛЬНОЕ СОСТОЯНИЕ РЫНКА (yfinance, d/d)"]
    snap = snapshot(DASHBOARD)
    # DASHBOARD собирается из реестра (symbols.json, quote=true), а подписи
    # жили тут отдельным словарём — и обращение шло по names[tk] без запаса.
    # 20.08 это чуть не уронило бриф: смена тикера Nasdaq на ^NDX (реестр
    # называл инструмент «Nasdaq 100», а тянул ^IXIC — Composite, другой
    # индекс) дала бы KeyError на первом же прогоне. Подпись по .get с
    # фолбэком на сам тикер: неизвестный инструмент должен появиться в брифе
    # своим именем, а не обрушить весь блок.
    # Подписи берём из того же реестра, что и сам список тикеров, иначе это
    # два источника правды: локальный словарь покрывал 7 тикеров из 14, и
    # остальные (SI=F, NG=F, ^DJI, ETH-USD…) выводились бы сырыми кодами.
    names = _registry_labels()
    # Ширина колонки — по самому длинному ИМЕЮЩЕМУСЯ имени, а не константа 9:
    # с русскими подписями «Природный газ» и «Индекс доллара» фиксированная
    # ширина ломала выравнивание всей таблицы.
    shown = [tk for tk in DASHBOARD if snap.get(tk, {}).get("price") is not None]
    w = max((len(names.get(tk, tk)) for tk in shown), default=9)
    for tk in shown:
        d = snap[tk]
        lines.append(f"  {names.get(tk, tk):<{w}} {d['price']:>12,.2f}  {d['change_pct']:+.2f}%")
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
