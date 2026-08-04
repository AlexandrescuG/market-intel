"""publish.py — мост backend→фронт. Превращает БД + рынок + технику в статический
JSON, который читает дашборд на lp.sbfconsult.com.

Полностью детерминированно, без LLM. Гоняется по расписанию (каждые 5-10 мин).
Сайт ничего не вычисляет — только отдаёт эти артефакты.

Пишет в web/data/:
  market.json     — состояние рынка + Crypto F&G
  technical.json  — TC-подобные карточки по watchlist
  signals.json    — топ-сигналы по измерениям
  buzz.json       — тепловая карта тикеров (для пузырей)
  report.json     — мета последнего утреннего отчёта + markdown
  meta.json       — когда что обновлялось (для индикаторов свежести на сайте)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from core import db
from core.config import BASE_DIR, REPORTS_DIR

log = logging.getLogger("publish")

WEB_DATA = BASE_DIR / "web" / "data"
WEB_DATA.mkdir(parents=True, exist_ok=True)

_BOT_DB = Path("/mnt/sbfdata/sbf-platform/SBFAcademy_bot/bot.db")

# Фиксированный список тикеров для технических карточек (строго этот порядок)
TECH_BASE = [
    "GC=F", "SI=F",
    "BTC-USD", "ETH-USD", "SOL-USD",
    "EURUSD=X", "GBPUSD=X",
    "^GSPC", "^IXIC", "^DJI",
    "CL=F", "NG=F",
]

# Читабельные имена для отображения на сайте
TICKER_NAMES = {
    "GC=F": "GOLD",       "SI=F": "SILVER",
    "BTC-USD": "BTCUSD",  "ETH-USD": "ETHUSD",  "SOL-USD": "SOLUSD",
    "EURUSD=X": "EURUSD", "GBPUSD=X": "GBPUSD",
    "^GSPC": "S&P 500",   "^IXIC": "Nasdaq",    "^DJI": "Dow Jones",
    "CL=F": "Нефть WTI",  "NG=F": "Природный газ",
    "^VIX": "VIX",        "DX-Y.NYB": "DXY",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(name: str, payload: dict) -> None:
    (WEB_DATA / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("wrote %s", name)


def publish_market() -> None:
    from core.market import snapshot, crypto_fear_greed, DASHBOARD
    names = {
        "^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^DJI": "Dow Jones", "^VIX": "VIX",
        "GC=F": "GOLD", "SI=F": "SILVER", "CL=F": "Нефть WTI", "NG=F": "Природный газ",
        "BTC-USD": "BTCUSD", "ETH-USD": "ETHUSD", "SOL-USD": "SOLUSD",
        "EURUSD=X": "EURUSD", "GBPUSD=X": "GBPUSD",
        "DX-Y.NYB": "DXY",
    }
    snap = snapshot(DASHBOARD)
    items = [{"name": names.get(t, t), "ticker": t, **snap.get(t, {})}
             for t in DASHBOARD if snap.get(t, {}).get("price") is not None]
    _write("market.json", {"updated": _now(), "items": items,
                           "fear_greed": crypto_fear_greed()})


def publish_technical() -> None:
    from core.technical import analyze
    cards = []
    for t in TECH_BASE:
        a = analyze(t)
        if a:
            a["name"] = TICKER_NAMES.get(t, t)  # добавляем читабельное имя
            cards.append(a)
    _write("technical.json", {"updated": _now(), "cards": cards})


def publish_signals() -> None:
    # P0-2 §2.2 шаги 2-4: маркер достоверности + фильтр (без тикера — не
    # показывать, капс/BREAKING — понизить, политическое — отсечь) + связка
    # с брифом. Правила берут кандидатов с запасом (лимит ×4 к отображаемому),
    # т.к. часть будет отфильтрована — иначе после фильтра карточек может
    # остаться меньше 12 даже когда сырых сигналов достаточно.
    from core.feed_filter import apply_feed_rules
    DISPLAY_LIMIT = 12
    # SPEC_site_fixes_2026-07-29 §6 п.1: квота, не ранжирование -- пока
    # importance для RSS ниже вовлечённости твитов, ранжирование одно эту
    # задачу не решает. Не применяется к "Соцсети" (crowd) -- та вкладка
    # сознательно осталась чисто социальной (см. §7).
    PRESS_QUOTA = 4
    out = {}
    for dim in ("economy", "geopolitics"):
        candidates = [_sig(s) for s in db.top_by_dimension(24, dim, DISPLAY_LIMIT * 4)]
        # geopolitics по данным структурно без тикеров (см. feed_filter.py) --
        # там штамп "нет тикера" убил бы вкладку целиком, требование ослаблено
        # сознательно, политический фильтр остаётся в силе.
        out[dim] = apply_feed_rules(candidates, DISPLAY_LIMIT, require_cashtag=(dim != "geopolitics"),
                                     press_quota=PRESS_QUOTA)
    crowd_candidates = [_sig(s) for s in db.top_by_crowd(24, DISPLAY_LIMIT * 4)]
    out["crowd"] = apply_feed_rules(crowd_candidates, DISPLAY_LIMIT)
    _write("signals.json", {"updated": _now(), **out})


def _sig(s: dict) -> dict:
    # SPEC_site_fixes_2026-07-29 §6 п.4: для Google-News-статей s["url"] -- это
    # редирект через news.google.com, не первоисточник, поэтому домен из URL
    # был бы неверным ("news.google.com"). rss.py уже резолвит настоящий домен
    # издания (entry.source.href) и кладёт в raw -- используем его, если есть.
    try:
        raw = json.loads(s.get("raw") or "{}")
    except (json.JSONDecodeError, TypeError):
        raw = {}
    return {
        "source": s["source"], "author": s["author"],
        "outlet": s.get("topic_hint") or "",
        "domain": raw.get("domain") or "",
        "text": (s["title"] or s["text"])[:280], "url": s["url"],
        "importance": s["importance"], "econ": s["econ_relevance"],
        "crowd": s["crowd_intensity"], "engagement": s["engagement"],
        "cashtags": json.loads(s["cashtags"] or "[]"),
    }


def publish_buzz() -> None:
    heat = db.cashtag_heatmap(24, limit=40)
    _write("buzz.json", {"updated": _now(),
                         "tickers": [{"tag": t, "mentions": c, "importance": imp}
                                     for t, c, imp in heat]})


def publish_report() -> None:
    reports = sorted(REPORTS_DIR.glob("report_*.md"))
    if not reports:
        _write("report.json", {"updated": None, "markdown": "", "date": None})
        return
    latest = reports[-1]
    _write("report.json", {
        "updated": _now(),
        "date": latest.stem.replace("report_", ""),
        "markdown": latest.read_text(encoding="utf-8"),
    })


def publish_stories() -> None:
    from core.stories import active_stories, attach_market, rebuild_stories
    rebuild_stories(hours=48)
    stories = [attach_market(s) for s in active_stories(limit=12)]
    _write("stories.json", {"updated": _now(), "stories": stories})


def publish_regime() -> None:
    from core.regime import detect_regime
    _write("regime.json", detect_regime())


def publish_verification() -> None:
    from core.verification import scorecard, recent_observations, resolve_due
    resolve_due()
    _write("verification.json", {
        "updated": _now(),
        "scorecard": scorecard(),
        "recent": recent_observations(limit=15),
    })


def publish_calendar() -> None:
    from collectors.calendar import upcoming, resolve_past_events
    resolve_past_events()
    _write("calendar.json", {"updated": _now(), "upcoming": upcoming(hours=72)})


def publish_macro() -> None:
    from core.fred import macro_snapshot
    _write("macro.json", macro_snapshot())


def publish_divergence() -> None:
    from core.divergence import sentiment_price_divergence, changes_since
    _write("divergence.json", {
        "updated": _now(),
        "divergences": sentiment_price_divergence(),
        "changes": changes_since(),
    })


def publish_anomalies() -> None:
    from core.anomaly import anomalies, update_baselines
    update_baselines()
    _write("anomalies.json", {"updated": _now(), "anomalies": anomalies()})


def publish_charts() -> None:
    """OHLC + уровни для интерактивных Lightweight Charts.
    Таймфреймы: M30 / H1 / H4 (ресемпл) / D1 / W1 с глубокой историей."""
    import pandas as pd
    import yfinance as yf
    from core.technical import analyze

    WATCH = {
        "GOLD": "GC=F", "SILVER": "SI=F",
        "BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD",
        "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X",
        "SPX": "^GSPC", "NASDAQ": "^IXIC", "DJI": "^DJI",
        "WTI": "CL=F", "NG": "NG=F",
        "DXY": "DX-Y.NYB",  # Focus Engine DEFAULT_UNIVERSE (core/focus.py) -- уже
                            # в core.market.DASHBOARD/quotes.json, не хватало
                            # только дневного OHLC для ATR.
    }
    # (period, interval) — глубина истории под прокрутку назад
    NATIVE = {
        "M30": ("60d",  "30m"),
        "H1":  ("730d", "60m"),
        "D1":  ("5y",   "1d"),
        "W1":  ("max",  "1wk"),
    }

    def rows_from(df, intraday, overrides=None):
        candles, vol = [], []
        for ts, r in df.iterrows():
            t = int(ts.timestamp()) if intraday else ts.strftime("%Y-%m-%d")
            o, h, l, c = float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"])
            if overrides is not None:
                ov = overrides.get(ts.date())
                if ov is not None:
                    o, h, l, c = ov
            up = c >= o
            candles.append({"time": t,
                             "open":  round(o, 4), "high": round(h, 4),
                             "low":   round(l, 4), "close": round(c, 4)})
            vol.append({"time": t, "value": int(r["Volume"] or 0),
                        "color": "rgba(30,142,90,.5)" if up else "rgba(192,57,43,.5)"})
        return candles, vol

    for label, ticker in WATCH.items():
        a = analyze(ticker)
        if not a:
            continue
        p = a["pivots"]
        levels = [
            ("R2", p["R2"], "#c0392b"), ("R1", p["R1"], "#c0392b"),
            ("PP", p["PP"], "#C9A227"),
            ("S1", p["S1"], "#1e8e5a"), ("S2", p["S2"], "#1e8e5a"),
        ]
        nearest = min(levels, key=lambda L: abs(L[1] - a["price"]))
        meta = {
            "ticker": ticker, "label": label,
            "last": a["price"], "rsi": a["rsi"],
            "bias": a["bias"], "patterns": a["patterns"],
            "levels": [{"name": n, "price": round(v, 4), "color": c}
                       for n, v, c in levels],
            "nearest": {"name": nearest[0], "price": round(nearest[1], 4),
                        "dist_pct": round(
                            (a["price"] - nearest[1]) / a["price"] * 100, 2)},
        }
        h1_df = None
        for tf, (period, interval) in NATIVE.items():
            try:
                df = yf.Ticker(ticker).history(period=period, interval=interval)
                if df is None or df.empty:
                    continue
                if tf == "H1":
                    h1_df = df
                overrides = None
                if tf == "D1" and ticker.endswith("=X") and h1_df is not None and not h1_df.empty:
                    # Yahoo's нативный дневной OHLC для FX (=X) вырожден: Open
                    # почти всегда ≈ Close ТОГО ЖЕ дня (тело свечи ~0, только
                    # фитиль -- каждый день выглядит доджи), и есть разрывы на
                    # границах дней (вчерашний Close != сегодняшний Open) --
                    # проверено вручную сравнением с непрерывным H1-рядом.
                    # H1-ресемпл (уже используется для H4 ниже) даёт здоровые,
                    # непрерывные дневные бары. Подменяем только там, где есть
                    # H1-покрытие (~2 года, period H1 = 730d) -- за пределами
                    # этого окна оставляем родной (пусть менее надёжный) D1,
                    # чтобы не резать глубину истории для дальнего скролла.
                    resampled = h1_df.resample("1D").agg(
                        {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
                    ).dropna()
                    overrides = {ts.date(): (float(r.Open), float(r.High), float(r.Low), float(r.Close))
                                 for ts, r in resampled.iterrows()}
                candles, vol = rows_from(df, intraday=interval in ("30m", "60m"), overrides=overrides)
                _write(f"ohlc_{label}_{tf}.json",
                       {**meta, "interval": tf, "candles": candles, "volume": vol})
            except Exception as e:
                log.debug("chart %s %s: %s", label, tf, e)
        # H4 — ресемпл из H1
        if h1_df is not None and not h1_df.empty:
            try:
                h4 = h1_df.resample("4h").agg(
                    {"Open": "first", "High": "max",
                     "Low": "min", "Close": "last", "Volume": "sum"}
                ).dropna()
                candles, vol = rows_from(h4, intraday=True)
                _write(f"ohlc_{label}_H4.json",
                       {**meta, "interval": "H4", "candles": candles, "volume": vol})
            except Exception as e:
                log.debug("chart %s H4: %s", label, e)


def publish_quotes() -> None:
    """Быстрые котировки для live-обновления графика и строки (каждые 15 с).
    Пишет web/data/quotes.json: {"quotes": {"GC=F": {"price": ..., "change_pct": ...}, ...}}
    Использует прямые HTTP запросы к Yahoo Finance v8 — обходит кеш yfinance."""
    import requests
    from concurrent.futures import ThreadPoolExecutor
    from core.market import DASHBOARD

    syms = list(dict.fromkeys(
        DASHBOARD + ["GC=F", "SI=F", "ETH-USD", "SOL-USD",
                     "EURUSD=X", "GBPUSD=X", "CL=F", "NG=F"]
    ))
    _HDR = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://finance.yahoo.com",
    }

    def _fetch(sym):
        try:
            r = requests.get(
                f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}",
                params={"range": "2d", "interval": "1d"},
                headers=_HDR,
                timeout=6,
            )
            if not r.ok:
                return sym, None
            meta = r.json()["chart"]["result"][0]["meta"]
            price = float(meta["regularMarketPrice"])
            prev = meta.get("chartPreviousClose")
            chg = round((price / prev - 1) * 100, 2) if prev else None
            return sym, {"price": round(price, 4), "change_pct": chg}
        except Exception:
            return sym, None

    out = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for sym, val in ex.map(_fetch, syms):
            if val is not None:
                out[sym] = val

    _write("quotes.json", {"updated": _now(), "quotes": out})


def publish_health() -> None:
    from core import db as _db
    beats = _db.get_heartbeats()
    _write("health.json", {"updated": _now(), "components": beats})


def publish_charts_mt5() -> None:
    """OHLC-файлы для MT5-символов (USDRUB, USDKZT, USDJPY) из bot.db."""
    import sqlite3
    import pandas as pd
    from datetime import datetime, timezone as tz
    from core.technical import pivots as calc_pivots, _rsi

    MT5_SYMS = ["USDRUB", "USDKZT", "USDJPY"]
    TF_MAP = {
        "M30": ("30m", True),
        "H1":  ("1h",  True),
        "H4":  ("4h",  True),
        "D1":  ("1d",  False),
        "W1":  ("1w",  False),
    }

    con = sqlite3.connect(str(_BOT_DB))
    try:
        for sym in MT5_SYMS:
            d1 = con.execute(
                "SELECT ts,o,h,l,c FROM price_bars WHERE symbol=? AND tf='1d' ORDER BY ts ASC",
                (sym,)).fetchall()
            if not d1:
                continue

            df = pd.DataFrame(d1, columns=["ts", "Open", "High", "Low", "Close"]).astype(
                {"Open": float, "High": float, "Low": float, "Close": float})
            price = float(df["Close"].iloc[-1])

            pv = calc_pivots(
                float(df["High"].iloc[-2]), float(df["Low"].iloc[-2]), float(df["Close"].iloc[-2])
            ) if len(df) >= 2 else calc_pivots(
                float(df["High"].max()), float(df["Low"].min()), price)

            rsi_val = round(_rsi(df["Close"]), 1)
            ma20 = float(df["Close"].rolling(20).mean().iloc[-1])
            ma50 = float(df["Close"].rolling(50).mean().iloc[-1]) if len(df) >= 50 else ma20
            mom  = price - float(df["Close"].iloc[-11]) if len(df) > 11 else 0.0
            bull = sum([price > pv["PP"], ma20 > ma50, mom > 0, rsi_val > 50])
            bias = ("техническая картина бычья" if bull >= 3
                    else "техническая картина медвежья" if bull <= 1
                    else "смешанная / нейтральная")

            levels = [
                ("R2", pv["R2"], "#c0392b"), ("R1", pv["R1"], "#c0392b"),
                ("PP", pv["PP"], "#C9A227"),
                ("S1", pv["S1"], "#1e8e5a"), ("S2", pv["S2"], "#1e8e5a"),
            ]
            nearest = min(levels, key=lambda L: abs(L[1] - price))
            meta = {
                "ticker": sym, "label": sym,
                "last": round(price, 4), "rsi": rsi_val, "bias": bias, "patterns": [],
                "levels": [{"name": n, "price": round(v, 4), "color": c} for n, v, c in levels],
                "nearest": {"name": nearest[0], "price": round(nearest[1], 4),
                            "dist_pct": round((price - nearest[1]) / price * 100, 2)},
            }

            for web_tf, (mt5_tf, intraday) in TF_MAP.items():
                rows = con.execute(
                    "SELECT ts,o,h,l,c,v FROM price_bars WHERE symbol=? AND tf=? ORDER BY ts ASC",
                    (sym, mt5_tf)).fetchall()
                if not rows:
                    continue
                candles, volume = [], []
                for ts, o, h, l, c, v in rows:
                    o, h, l, c = float(o), float(h), float(l), float(c)
                    t = int(ts) if intraday else datetime.fromtimestamp(
                        int(ts), tz=tz.utc).strftime("%Y-%m-%d")
                    up = c >= o
                    candles.append({"time": t, "open": round(o, 4), "high": round(h, 4),
                                    "low": round(l, 4), "close": round(c, 4)})
                    volume.append({"time": t, "value": int(v or 0),
                                   "color": "rgba(30,142,90,.5)" if up else "rgba(192,57,43,.5)"})
                _write(f"ohlc_{sym}_{web_tf}.json",
                       {**meta, "interval": web_tf, "candles": candles, "volume": volume})
    finally:
        con.close()


def publish_all() -> None:
    db.init_db()

    # Быстрые (рынок, сигналы)
    fast_fns = (publish_market, publish_technical, publish_signals,
                publish_buzz, publish_report)
    # Медленнее / зависят от истории
    # publish_calendar снят из пайплайна: читает мёртвую таблицу `calendar` в
    # signals.db (её пишет только collect_calendar(), которого никто не вызывает) —
    # реальный календарь теперь в econ_events, отдаётся через /api/calendar/events
    # и build_brief_v2.py. Витрину calendar.json не читал ни один фронтенд-код.
    slow_fns = (publish_stories, publish_regime, publish_verification,
                publish_macro, publish_divergence,
                publish_anomalies, publish_health, publish_charts, publish_charts_mt5)

    layers = []
    for fn in fast_fns + slow_fns:
        try:
            fn()
            layers.append(fn.__name__.replace("publish_", ""))
        except Exception as e:
            log.error("%s failed: %s", fn.__name__, e)

    db.heartbeat("publish", ok=True)
    _write("meta.json", {"updated": _now(), "layers": layers})


if __name__ == "__main__":
    from core.logging_setup import setup
    setup("publish")
    publish_all()
    print("published →", WEB_DATA)
